"""LiveOps readiness (F9) — ASSETFABRIC_SPEC §12 "LiveOps readiness: remote config / feature flags (launch content
deferred)", §13 F9 "LiveOps foundation — readiness only"; GAME_SPEC §5 "Live seasonal content (remote config readiness
OK)", §8 "Remote config hooks for balance knobs". Readiness only: nothing here talks to a network or a live service.

Pieces (mirrored by the game's ``games/game-zero/autoload/liveops.gd``):

* **Flag manifest** — ``content/liveops/flags.yaml``: kill switches (default on) and consent flags (default off, never
  settable by a bundle). Compiled by the ``liveops`` generator into ``assets/generated/liveops/liveops.json`` together
  with the balance-knob table, which *is* the F4 live-tune table (``content/tune/limits.yaml``).
* **Config bundle** — a signed JSON file: ``{"format": "gamezero-liveops-signed", "alg": "rsa-pkcs1v15-sha256",
  "key_id", "payload": "<canonical JSON>", "sig": "<base64>"}``. The signature covers the exact payload bytes, so the
  game verifies the same bytes forge signed (no re-canonicalisation). RSA PKCS#1 v1.5 / SHA-256 because Godot 4.3's
  ``Crypto.verify`` supports exactly that (``[INFERENCE F9-2]``).
* **Payload** — ``serial`` (strictly increasing — anti-replay / anti-downgrade), ``build_min``/``build_max``,
  ``flags`` (kill switches only), ``patches`` (numeric balance leaves inside the F4 ranges). Any other key is refused:
  bundles cannot carry content (seasonal content stays deferred).
* **Device state machine** (game side): ``inbox.json`` → verify → promote to ``active.json`` (old active kept as
  ``previous.json``) or move to ``rejected/``; ``active.json`` is re-verified every boot (tamper → safe defaults); a boot
  sentinel quarantines a bundle after ``MAX_BOOT_FAILS`` crashed boots and restores ``previous.json``.
* **Rollback** — serials never go backwards on a device, so an operator rollback is *roll-forward*: re-sign an
  earlier payload (or the empty defaults payload) under a new serial (``rollback_bundle``).
* **Diagnostics** — opt-in, local-only: the game writes a session record only with player consent; ``diag_export``
  scrubs PII (home paths, user/host names, e-mails, IPs, long tokens) into a local JSON file. Nothing is uploaded.
* **Readiness checklist** — ``readiness()`` (``forge liveops readiness``), user-gated items reported as such.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from forge.paths import find_repo_root

FLAGS_REL = "content/liveops/flags.yaml"
MANIFEST_REL = "games/game-zero/assets/generated/liveops/liveops.json"
RUNBOOK_REL = "docs/liveops-runbook.md"
SIGNED_FORMAT = "gamezero-liveops-signed"
PAYLOAD_FORMAT = "gamezero-liveops"
SCHEMA = 1
ALG = "rsa-pkcs1v15-sha256"
MAX_PAYLOAD_BYTES = 65536
MAX_PATCHES = 256
MAX_BOOT_FAILS = 2
PAYLOAD_KEYS = {"format", "schema", "serial", "channel", "build_min", "build_max", "issued", "flags", "patches", "notes"}
REQUIRED_KEYS = {"format", "schema", "serial", "build_min", "flags", "patches"}
CHANNELS = {"dev", "qa", "prod"}
KINDS = {"kill_switch", "consent"}
RUNBOOK_SECTIONS = ["Key ceremony", "Issue a bundle", "Verify", "Deliver", "Rollback", "Crash-loop quarantine",
                    "Kill switch", "Diagnostics", "Save compatibility", "Readiness checklist"]


# ----------------------------------------------------------------------------- manifest

def load_flags(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    return yaml.safe_load((root / FLAGS_REL).read_text(encoding="utf-8"))


def validate_flags(raw: dict[str, Any], locale: dict[str, str] | None = None) -> list[str]:
    errs: list[str] = []
    if raw.get("bundle_format") != PAYLOAD_FORMAT or raw.get("bundle_schema") != SCHEMA:
        errs.append("bundle_format/bundle_schema do not match forge.liveops")
    flags = raw.get("flags") or {}
    if not flags:
        errs.append("no flags")
    for name, f in flags.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            errs.append(f"{name}: flag ids are snake_case")
        if f.get("kind") not in KINDS:
            errs.append(f"{name}: kind must be one of {sorted(KINDS)}")
        if not isinstance(f.get("default"), bool):
            errs.append(f"{name}: default must be a bool")
        # safe offline defaults: features on (= 0.8.0 behaviour), consent off (privacy by default)
        if f.get("kind") == "kill_switch" and f.get("default") is not True:
            errs.append(f"{name}: a kill switch defaults to on (the shipped behaviour)")
        if f.get("kind") == "consent" and f.get("default") is not False:
            errs.append(f"{name}: a consent flag defaults to off")
        for k in ("label_key", "note_key"):
            key = str(f.get(k, ""))
            if not key.startswith("liveops.flag."):
                errs.append(f"{name}: {k} must be a locale key liveops.flag.*")
            elif locale is not None and key not in locale:
                errs.append(f"{name}: locale key {key} missing from en.json")
    return errs


def locale_en(root: Path) -> dict[str, str]:
    return json.loads((root / "games/game-zero/locale/en.json").read_text(encoding="utf-8"))


def tune_limits(root: Path) -> dict[str, list[float]]:
    rules = yaml.safe_load((root / "content/tune/limits.yaml").read_text(encoding="utf-8"))["rules"]
    return {k: [float(v[0]), float(v[1])] for k, v in sorted(rules.items())}


def game_manifest(root: Path) -> dict[str, Any]:
    """The table the game reads (generator output) — flags + knob ranges, sorted, no free text."""
    raw = load_flags(root)
    return {"schema_version": raw["schema_version"], "bundle_format": PAYLOAD_FORMAT, "bundle_schema": SCHEMA,
            "signed_format": SIGNED_FORMAT, "alg": ALG, "max_payload_bytes": MAX_PAYLOAD_BYTES, "max_patches": MAX_PATCHES,
            "max_boot_fails": MAX_BOOT_FAILS, "channels": sorted(CHANNELS),
            "flags": {n: {"kind": f["kind"], "default": f["default"], "label_key": f["label_key"], "note_key": f["note_key"]}
                      for n, f in sorted(raw["flags"].items())},
            "knobs": {k: v for k, v in tune_limits(root).items() if not k.startswith("sim.")}}


def defaults(root: Path) -> dict[str, bool]:
    return {n: f["default"] for n, f in load_flags(root)["flags"].items()}


# ----------------------------------------------------------------------------- versions

def version_tuple(v: str) -> tuple[int, int, int]:
    core = str(v).split("+", 1)[0].split("-", 1)[0]
    parts = [int(p) if p.isdigit() else 0 for p in core.split(".")[:3]]
    return tuple(parts + [0] * (3 - len(parts)))  # type: ignore[return-value]


def build_version(root: Path) -> str:
    m = re.search(r'config/version="([^"]+)"', (root / "games/game-zero/project.godot").read_text(encoding="utf-8"))
    return m.group(1) if m else "0.0.0"


# ----------------------------------------------------------------------------- keys

def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("forge liveops needs the `cryptography` package (pip install -e '.[liveops]')") from e
    return hashes, serialization, padding, rsa


def default_key_dir(root: Path) -> Path:
    return root / ".fabric" / "liveops"          # gitignored (/.fabric/liveops/)


def keygen(out_dir: Path, name: str = "dev") -> dict[str, str]:
    """RSA-2048 keypair. The private key is written 0600 and must never be committed (dev keys only — a production key
    comes from the Producer's key ceremony, docs/liveops-runbook.md)."""
    hashes, serialization, padding, rsa = _crypto()
    out_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = out_dir / f"{name}.key.pem"
    pub = out_dir / f"{name}.pub.pem"
    fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo))
    return {"private": str(priv), "public": str(pub), "key_id": key_id(pub.read_text(encoding="ascii"))}


def key_id(pub_pem: str) -> str:
    """sha256 of the DER (= the base64 body of the PEM), first 16 hex — computed identically by the game."""
    body = "".join(l.strip() for l in pub_pem.strip().splitlines() if l.strip() and not l.startswith("-----"))
    return hashlib.sha256(base64.b64decode(body)).hexdigest()[:16]


# ----------------------------------------------------------------------------- payload / bundle

def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_payload(payload: Any, manifest: dict[str, Any], game_data: dict[str, Any], version: str,
                     min_serial: int = 0) -> list[str]:
    """Same rules (same order of concern) as LiveOps.validate_payload in liveops.gd."""
    from forge.live import get_path, rule_for

    if not isinstance(payload, dict):
        return ["payload is not an object"]
    errs: list[str] = []
    extra = set(payload) - PAYLOAD_KEYS
    if extra:
        errs.append(f"unknown keys {sorted(extra)} (bundles carry flags + balance patches only)")
    missing = REQUIRED_KEYS - set(payload)
    if missing:
        errs.append(f"missing keys {sorted(missing)}")
        return errs
    if payload["format"] != PAYLOAD_FORMAT or payload["schema"] != SCHEMA:
        errs.append(f"format/schema {payload['format']}/{payload['schema']} not supported")
    serial = payload["serial"]
    if not isinstance(serial, int) or isinstance(serial, bool) or serial < 1:
        errs.append("serial must be an int >= 1")
    elif serial <= min_serial:
        errs.append(f"serial {serial} is not newer than {min_serial} (replay/downgrade)")
    if "channel" in payload and payload["channel"] not in CHANNELS:
        errs.append(f"channel {payload['channel']!r} unknown")
    v = version_tuple(version)
    if version_tuple(str(payload["build_min"])) > v:
        errs.append(f"build_min {payload['build_min']} > build {version}")
    if "build_max" in payload and version_tuple(str(payload["build_max"])) < v:
        errs.append(f"build_max {payload['build_max']} < build {version}")
    flags = payload["flags"]
    if not isinstance(flags, dict):
        errs.append("flags must be an object")
        flags = {}
    for n, val in flags.items():
        spec = manifest["flags"].get(n)
        if spec is None:
            errs.append(f"flag {n}: unknown")
        elif spec["kind"] == "consent":
            errs.append(f"flag {n}: consent is the player's decision, a bundle cannot set it")
        elif not isinstance(val, bool):
            errs.append(f"flag {n}: value must be a bool")
    patches = payload["patches"]
    if not isinstance(patches, list):
        errs.append("patches must be a list")
        patches = []
    if len(patches) > MAX_PATCHES:
        errs.append(f"{len(patches)} patches > {MAX_PATCHES}")
    limits = manifest["knobs"]
    for p in patches:
        path = str((p or {}).get("path", "")) if isinstance(p, dict) else ""
        val = p.get("value") if isinstance(p, dict) else None
        if not path:
            errs.append("patch.path missing")
            continue
        if path.startswith("sim."):
            errs.append(f"{path}: sim.* knobs are dev-only live tune, not remote config")
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val != val or val in (float("inf"), float("-inf")):
            errs.append(f"{path}: value must be a finite number")
            continue
        rng = rule_for(limits, path)
        if not rng:
            errs.append(f"{path}: not a balance knob")
            continue
        if not (rng[0] <= float(val) <= rng[1]):
            errs.append(f"{path}: {val} outside [{rng[0]:g}, {rng[1]:g}]")
            continue
        try:
            cur = get_path(game_data, path)
        except (KeyError, IndexError, ValueError):
            cur = None
        if isinstance(cur, bool) or not isinstance(cur, (int, float)):
            errs.append(f"{path}: no such numeric field")
    return errs


def make_payload(serial: int, flags: dict[str, bool] | None = None, patches: list[dict[str, Any]] | None = None,
                 build_min: str = "0.9.0", build_max: str | None = None, channel: str = "dev",
                 issued: str | None = None, notes: str = "") -> dict[str, Any]:
    p: dict[str, Any] = {"format": PAYLOAD_FORMAT, "schema": SCHEMA, "serial": int(serial), "channel": channel,
                         "build_min": build_min, "flags": dict(flags or {}), "patches": list(patches or []),
                         "issued": issued or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if build_max:
        p["build_max"] = build_max
    if notes:
        p["notes"] = notes
    return p


def sign(payload: dict[str, Any], private_pem: Path) -> dict[str, Any]:
    hashes, serialization, padding, rsa = _crypto()
    key = serialization.load_pem_private_key(private_pem.read_bytes(), password=None)
    body = canonical(payload)
    if len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload {len(body)} B > {MAX_PAYLOAD_BYTES} B")
    sig = key.sign(body.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"format": SIGNED_FORMAT, "alg": ALG, "key_id": key_id(pub.decode("ascii")), "payload": body,
            "sig": base64.b64encode(sig).decode("ascii")}


def verify_signature(bundle: Any, public_pem: Path) -> list[str]:
    hashes, serialization, padding, rsa = _crypto()
    from cryptography.exceptions import InvalidSignature

    if not isinstance(bundle, dict) or bundle.get("format") != SIGNED_FORMAT or bundle.get("alg") != ALG:
        return ["not a gamezero-liveops-signed bundle"]
    pem = public_pem.read_text(encoding="ascii")
    if bundle.get("key_id") != key_id(pem):
        return [f"key_id {bundle.get('key_id')} does not match the pinned key {key_id(pem)}"]
    body = str(bundle.get("payload", "")).encode("utf-8")
    if len(body) > MAX_PAYLOAD_BYTES:
        return ["payload too large"]
    try:
        serialization.load_pem_public_key(pem.encode("ascii")).verify(
            base64.b64decode(str(bundle.get("sig", "")), validate=True), body, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError):
        return ["signature invalid"]
    return []


def verify(bundle: Any, public_pem: Path, root: Path | None = None, min_serial: int = 0,
           version: str | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    errs = verify_signature(bundle, public_pem)
    payload: Any = None
    if not errs:
        try:
            payload = json.loads(bundle["payload"])
        except json.JSONDecodeError:
            errs = ["payload is not JSON"]
    if not errs:
        from forge.live import GAME_DATA_REL

        gd = json.loads((root / GAME_DATA_REL).read_text(encoding="utf-8"))
        errs = validate_payload(payload, game_manifest(root), gd, version or build_version(root), min_serial)
    return {"ok": not errs, "errors": errs, "serial": (payload or {}).get("serial") if isinstance(payload, dict) else None}


def write_bundle(bundle: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(bundle, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def install(bundle: dict[str, Any], liveops_dir: Path) -> Path:
    """Local delivery for dev/QA: drop the bundle into a device's LiveOps inbox (atomic). Production delivery rides
    inside a platform update/patch — never a game-initiated download ([INFERENCE F9-3])."""
    return write_bundle(bundle, liveops_dir / "inbox.json")


def rollback_bundle(previous: dict[str, Any] | None, new_serial: int, private_pem: Path, issued: str | None = None,
                    notes: str = "rollback") -> dict[str, Any]:
    """Roll-forward rollback: the content of `previous` (a signed bundle) or, with None, the empty defaults payload,
    re-issued under `new_serial` (devices never accept an older serial)."""
    if previous is None:
        old = make_payload(new_serial, issued=issued, notes=notes)
    else:
        old = json.loads(previous["payload"])
        old.update({"serial": int(new_serial), "notes": notes})
        old["issued"] = issued or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return sign(old, private_pem)


def device_status(liveops_dir: Path) -> dict[str, Any]:
    def rd(name: str) -> Any:
        p = liveops_dir / name
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except json.JSONDecodeError:
            return "corrupt"
    out: dict[str, Any] = {"dir": str(liveops_dir), "state": rd("state.json"), "boot_sentinel": rd("boot.json"),
                           "inbox": (liveops_dir / "inbox.json").exists(), "last_status": rd("status.json")}
    for name in ("active", "previous"):
        b = rd(f"{name}.json")
        out[name] = json.loads(b["payload"]).get("serial") if isinstance(b, dict) and "payload" in b else b
    out["rejected"] = sorted(p.name for p in (liveops_dir / "rejected").glob("*.json")) if (liveops_dir / "rejected").exists() else []
    out["quarantine"] = sorted(p.name for p in (liveops_dir / "quarantine").glob("*.json")) if (liveops_dir / "quarantine").exists() else []
    return out


# ----------------------------------------------------------------------------- diagnostics (opt-in, local)

DIAG_FORMAT = "gamezero-diag"
_SCRUB_RULES: list[tuple[str, str, str]] = [
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>"),
    ("home_path", r"(/home/|/Users/|[A-Za-z]:\\Users\\|/data/user/\d+/)[^/\\\s\"']+", r"\1<user>"),
    ("ipv4", r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>"),
    ("mac", r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", "<mac>"),
    ("ipv6", r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b", "<ip>"),
    ("token", r"\b[0-9a-fA-F]{32,}\b|\b[A-Za-z0-9+/_-]{40,}={0,2}", "<redacted>"),
]


def scrub(text: str, extra_words: list[str] | None = None) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for name, pat, rep in _SCRUB_RULES:
        text, n = re.subn(pat, rep, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    words = [w for w in (extra_words if extra_words is not None else _local_identity()) if w and len(w) >= 3]
    for w in sorted(set(words), key=len, reverse=True):
        text, n = re.subn(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", "<id>", text)
        if n:
            counts["identity"] = counts.get("identity", 0) + n
    return text, counts


def _local_identity() -> list[str]:
    out = []
    try:
        out.append(getpass.getuser())
    except Exception:  # pragma: no cover
        pass
    try:
        out.append(socket.gethostname())
    except Exception:  # pragma: no cover
        pass
    return out


def diag_export(files: list[Path], out: Path, consent: bool, extra_words: list[str] | None = None,
                created: str | None = None) -> dict[str, Any]:
    """Local, consent-gated, scrubbed diagnostics bundle. Never uploads (there is no endpoint — F9 is readiness)."""
    if not consent:
        raise PermissionError("diagnostics export needs the player's explicit consent (--consent)")
    entries, total = [], {}
    for f in files:
        raw = f.read_text(encoding="utf-8", errors="replace")
        clean, counts = scrub(raw, extra_words)
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
        entries.append({"name": scrub(f.name, extra_words)[0], "bytes": len(clean.encode("utf-8")),
                        "sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(), "text": clean})
    bundle = {"format": DIAG_FORMAT, "schema": 1, "consent": True, "uploaded": False,
              "created": created or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "scrub": {"rules": [r[0] for r in _SCRUB_RULES] + ["identity"], "redactions": total}, "files": entries}
    errs = validate_diag(bundle)
    if errs:
        raise ValueError(errs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return bundle


def validate_diag(bundle: dict[str, Any], root: Path | None = None) -> list[str]:
    import jsonschema

    root = root or find_repo_root()
    schema = json.loads((root / "forge/schemas/diag_bundle.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(bundle)]


# ----------------------------------------------------------------------------- readiness checklist

def _git_files(root: Path) -> list[str]:
    import subprocess

    p = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True)
    return p.stdout.splitlines() if p.returncode == 0 else []


LEGAL_PLACEHOLDER = "[PLACEHOLDER — LEGAL REVIEW REQUIRED]"


def readiness(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    items: list[dict[str, Any]] = []

    def item(iid: str, status: str, detail: Any) -> None:
        items.append({"id": iid, "status": status, "detail": detail})

    raw = load_flags(root)
    errs = validate_flags(raw, locale_en(root))
    item("flags_manifest_valid", "pass" if not errs else "fail", errs or f"{len(raw['flags'])} flags, locale keys present")
    gm = root / MANIFEST_REL
    in_sync = gm.exists() and json.loads(gm.read_text(encoding="utf-8")) == game_manifest(root)
    item("game_manifest_in_sync", "pass" if in_sync else "fail", MANIFEST_REL if in_sync else "run forge build")
    from forge.accept_f7 import net_scan

    ns = net_scan(root)
    item("no_network_api_in_game", "pass" if ns["ok"] else "fail", ns["network_api_uses"] or "0 uses")
    tracked = _git_files(root)
    marker = "-----BEGIN " + "PRIVATE KEY-----"
    keys = [f for f in tracked if f.endswith((".key.pem", ".pem", ".key")) or marker in _peek(root / f)]
    item("no_signing_key_in_repo", "pass" if not keys else "fail", keys or "no PEM / private key tracked")
    gi = (root / ".gitignore").read_text(encoding="utf-8")
    item("key_dir_gitignored", "pass" if "/.fabric/liveops/" in gi and "*.pem" in gi else "fail", "/.fabric/liveops/, *.pem")
    pub = root / "games/game-zero/data/liveops/pubkey.pem"
    item("production_public_key", "pass" if pub.exists() else "user_gated",
         "pinned" if pub.exists() else "Producer key ceremony pending — release builds ignore every bundle until then")
    rb = root / RUNBOOK_REL
    text = rb.read_text(encoding="utf-8") if rb.exists() else ""
    miss = [s for s in RUNBOOK_SECTIONS if f"## {s}" not in text]
    item("runbook", "pass" if rb.exists() and not miss else "fail", miss or RUNBOOK_REL)
    gd = (root / "games/game-zero/autoload/save.gd").read_text(encoding="utf-8")
    from forge import save as S

    item("save_forward_compat_guard", "pass" if "newer_than_build" in gd and hasattr(S, "classify") else "fail",
         "saves from a newer build are never overwritten (save.gd + forge/save.py)")
    d = defaults(root)
    consent = [n for n, f in raw["flags"].items() if f["kind"] == "consent"]
    item("privacy_defaults", "pass" if consent and not any(d[n] for n in consent) else "fail",
         {n: d[n] for n in consent})
    menu = root / "games/game-zero/ui/settings_menu.gd"
    mt = menu.read_text(encoding="utf-8") if menu.exists() else ""
    item("consent_toggle_in_settings", "pass" if "set_diagnostics_consent" in mt and "settings.diagnostics.notice" in mt
         else "fail", "Settings screen: diagnostics toggle (default off) + privacy notice (INFERENCES F9-12)")
    notice = locale_en(root).get("settings.diagnostics.notice", "")
    if not notice:
        item("privacy_text_legal_review", "fail", "locale key settings.diagnostics.notice missing")
    elif notice.startswith(LEGAL_PLACEHOLDER):
        item("privacy_text_legal_review", "user_gated", "privacy notice is a placeholder — legal review required (F9-8)")
    else:
        item("privacy_text_legal_review", "pass", "legal-reviewed text in place")
    item("live_service", "user_gated", "no endpoint, no delivery service, no launch — F9 is readiness only (spec §13)")
    failed = [i["id"] for i in items if i["status"] == "fail"]
    return {"ok": not failed, "failed": failed, "items": items,
            "user_gated": [i["id"] for i in items if i["status"] == "user_gated"]}


def _peek(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:4096] if p.is_file() and p.stat().st_size < 1 << 20 else ""
    except OSError:
        return ""
