"""Register of C9–C12 capabilities (content/companions/c9_c12.yaml) + the checks `forge accept C9..C12` runs on it."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import yaml

from forge.i18n import catalogue, t
from forge.paths import find_repo_root
from forge.stubs import StubError

REGISTER = Path("content") / "companions" / "c9_c12.yaml"
PL_KOTLIN = Path("companions") / "pocketloom" / "fabriccore" / "src" / "main" / "kotlin" / "fabric" / "core"
PL_STRINGS = Path("companions") / "pocketloom" / "app" / "src" / "main" / "res" / "values" / "strings.xml"
MODULES = {"C9": "forge.mirrorweave", "C10": "forge.lensforge", "C11": "forge.depth", "C12": "forge.realityloom"}


def load(root: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load(((root or find_repo_root()) / REGISTER).read_text(encoding="utf-8"))


def features(ms: str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    return [f for f in load(root)["features"] if ms is None or f["milestone"] == ms]


def descriptor(ms: str, root: Path | None = None) -> dict[str, Any]:
    """Public, machine-readable statement of what a milestone does and does not do (served at GET /mirror/info)."""
    reg = load(root)
    rows = []
    for f in features(ms, root):
        row = {"id": f["id"], "status": f["status"], "spec": f["spec"]}
        if f["status"] == "stub":
            row["reason"] = t(f["reason_key"], root, codec="h264")
        rows.append(row)
    return {"milestone": ms, "title": reg["milestones"][ms]["title"], "features": rows,
            "deferred": [d["id"] for d in reg.get("deferred", [])]}


def _resolve(path: str) -> Any:
    mod, attr = path.split(":")
    obj = importlib.import_module(mod)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def android_key(key: str) -> str:
    return key.replace(".", "_")


def check(root: Path | None = None, ms: str | None = None) -> dict[str, Any]:
    """Static + dynamic consistency of the register with code, ladder, locales, Android strings and Kotlin."""
    from forge import groundweave

    root = root or find_repo_root()
    reg = load(root)
    ladder = groundweave.load_ladder(root)["ops"]
    loc = catalogue(root)
    strings = (root / PL_STRINGS).read_text(encoding="utf-8")
    kt = "\n".join(p.read_text(encoding="utf-8") for p in sorted((root / PL_KOTLIN).glob("*.kt")))
    problems: list[str] = []
    seen: set[str] = set()
    stub_results: dict[str, Any] = {}
    real_ids, stub_ids = [], []
    for f in reg["features"]:
        if ms and f["milestone"] != ms:
            continue
        fid = f["id"]
        if fid in seen:
            problems.append(f"{fid}: duplicate id")
        seen.add(fid)
        if f["milestone"] not in MODULES:
            problems.append(f"{fid}: bad milestone")
        if f["status"] not in ("real", "stub"):
            problems.append(f"{fid}: status must be real|stub")
            continue
        try:
            _resolve(f["entry"])
        except Exception as e:  # noqa: BLE001
            problems.append(f"{fid}: entry {f['entry']} does not resolve ({type(e).__name__})")
        if f.get("ladder_op") and f["ladder_op"] not in ladder:
            problems.append(f"{fid}: ladder_op {f['ladder_op']} not in ladder.yaml")
        if f.get("kotlin") and not re.search(rf"\b(class|object|interface)\s+{re.escape(f['kotlin'])}\b", kt):
            problems.append(f"{fid}: Kotlin symbol {f['kotlin']} not found in FabricCore")
        if f["status"] == "stub":
            stub_ids.append(fid)
            key = f.get("reason_key")
            if not key or key not in loc:
                problems.append(f"{fid}: reason_key {key!r} missing from locales/en.json")
            if f.get("kotlin") and key and f'name="{android_key(key)}"' not in strings:
                problems.append(f"{fid}: Android string {android_key(key)} missing from strings.xml")
            probe = getattr(importlib.import_module(MODULES[f["milestone"]]), "STUB_PROBES", {}).get(fid)
            if probe is None:
                problems.append(f"{fid}: no STUB_PROBES entry in {MODULES[f['milestone']]}")
            else:
                try:
                    out = probe()
                    problems.append(f"{fid}: stub returned {out!r} instead of refusing")
                except StubError as e:
                    msg = str(e)
                    ok = (msg.startswith(f"[STUB {fid} {f['milestone']}]") and e.key == key and t(key, root, codec="h264") in msg)
                    stub_results[fid] = {"refused": True, "message": msg}
                    if not ok:
                        problems.append(f"{fid}: refusal label/key mismatch: {msg!r}")
                except Exception as e:  # noqa: BLE001
                    problems.append(f"{fid}: stub raised {type(e).__name__}, not StubError")
        else:
            real_ids.append(fid)
    return {"ok": not problems, "problems": problems, "real": real_ids, "stubs": stub_ids,
            "stub_refusals": stub_results, "deferred": [d["id"] for d in reg.get("deferred", [])]}
