"""`forge liveops …` — F9 LiveOps readiness: keys, signed config bundles, local install, roll-forward rollback,
device status, opt-in diagnostics export, readiness checklist. Local files only — nothing here opens a network
connection (there is no service: F9 is readiness only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from forge.paths import find_repo_root


def _echo(d: Any, ok: bool = True) -> None:
    click.echo(json.dumps(d, indent=2, sort_keys=True, default=str))
    if not ok:
        sys.exit(1)


def _value(s: str) -> float | int:
    f = float(s)
    return int(f) if f.is_integer() and "." not in s else f


@click.group("liveops")
def liveops_grp() -> None:
    """LiveOps readiness (F9): feature flags / kill switches + signed remote config for balance knobs. No live service."""


@liveops_grp.command("manifest")
def lo_manifest() -> None:
    """The flag manifest + remote-config knob table as the game reads it (content/liveops/flags.yaml + tune limits)."""
    from forge import liveops as L

    root = find_repo_root()
    errs = L.validate_flags(L.load_flags(root), L.locale_en(root))
    _echo({"errors": errs, "manifest": L.game_manifest(root)}, not errs)


@liveops_grp.command("keygen")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=None, help="Default .fabric/liveops (gitignored).")
@click.option("--name", default="dev")
def lo_keygen(out_dir: Path | None, name: str) -> None:
    """RSA-2048 signing keypair (dev/QA). The production key comes from the Producer key ceremony (runbook)."""
    from forge import liveops as L

    _echo(L.keygen(out_dir or L.default_key_dir(find_repo_root()), name))


@liveops_grp.command("bundle")
@click.option("--serial", type=int, required=True)
@click.option("--flag", "flags", multiple=True, help="name=on|off (kill switches only).")
@click.option("--set", "sets", multiple=True, help="knob.path=value (balance knobs = F4 tune limits, no sim.*).")
@click.option("--build-min", default=None)
@click.option("--build-max", default=None)
@click.option("--channel", type=click.Choice(["dev", "qa", "prod"]), default="dev")
@click.option("--notes", default="")
@click.option("--key", "key", type=click.Path(exists=True, path_type=Path), required=True, help="Private key PEM.")
@click.option("--out", type=click.Path(path_type=Path), required=True)
def lo_bundle(serial: int, flags: tuple[str, ...], sets: tuple[str, ...], build_min: str | None, build_max: str | None,
              channel: str, notes: str, key: Path, out: Path) -> None:
    """Validate (same rules as the game) and sign a config bundle."""
    from forge import liveops as L
    from forge.live import GAME_DATA_REL

    root = find_repo_root()
    fl = {}
    for f in flags:
        n, _, v = f.partition("=")
        fl[n] = v.lower() in ("on", "true", "1")
    patches = [{"path": p, "value": _value(v)} for p, _, v in (s.partition("=") for s in sets)]
    bm = build_min or ".".join(map(str, L.version_tuple(L.build_version(root))))
    payload = L.make_payload(serial, fl, patches, build_min=bm, build_max=build_max, channel=channel, notes=notes)
    errs = L.validate_payload(payload, L.game_manifest(root), json.loads((root / GAME_DATA_REL).read_text()), L.build_version(root))
    if errs:
        _echo({"ok": False, "errors": errs}, False)
    b = L.sign(payload, key)
    L.write_bundle(b, out)
    _echo({"ok": True, "out": str(out), "serial": serial, "key_id": b["key_id"], "bytes": len(b["payload"])})


@liveops_grp.command("verify")
@click.argument("bundle", type=click.Path(exists=True, path_type=Path))
@click.option("--pub", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--min-serial", type=int, default=0)
def lo_verify(bundle: Path, pub: Path, min_serial: int) -> None:
    """Signature + key id + payload rules + build range (the game's decision, computed by forge)."""
    from forge import liveops as L

    r = L.verify(json.loads(bundle.read_text(encoding="utf-8")), pub, min_serial=min_serial)
    _echo(r, r["ok"])


@liveops_grp.command("install")
@click.argument("bundle", type=click.Path(exists=True, path_type=Path))
@click.option("--dir", "lo_dir", type=click.Path(path_type=Path), required=True, help="Device LiveOps dir (dev/QA).")
def lo_install(bundle: Path, lo_dir: Path) -> None:
    """Dev/QA delivery: drop a bundle into a device's LiveOps inbox (local file copy; the game verifies at next boot)."""
    from forge import liveops as L

    _echo({"inbox": str(L.install(json.loads(bundle.read_text(encoding="utf-8")), lo_dir))})


@liveops_grp.command("rollback")
@click.option("--to", "to", required=True, help="A signed bundle file to restore, or `defaults`.")
@click.option("--serial", type=int, required=True, help="New serial (> every serial devices have seen).")
@click.option("--key", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
def lo_rollback(to: str, serial: int, key: Path, out: Path) -> None:
    """Roll-forward rollback: re-issue an earlier bundle's content (or the defaults) under a new serial."""
    from forge import liveops as L

    prev = None if to == "defaults" else json.loads(Path(to).read_text(encoding="utf-8"))
    b = L.rollback_bundle(prev, serial, key)
    L.write_bundle(b, out)
    _echo({"ok": True, "out": str(out), "serial": serial, "from": to})


@liveops_grp.command("status")
@click.option("--dir", "lo_dir", type=click.Path(path_type=Path), required=True)
def lo_status(lo_dir: Path) -> None:
    """A device's LiveOps state: active / previous / rejected / quarantined bundles, boot sentinel, last boot report."""
    from forge import liveops as L

    _echo(L.device_status(lo_dir))


@liveops_grp.command("diag-export")
@click.argument("files", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--consent", is_flag=True, help="The player has opted in (required).")
def lo_diag(files: tuple[Path, ...], out: Path, consent: bool) -> None:
    """Scrubbed, schema-validated local diagnostics bundle. Never uploads."""
    from forge import liveops as L

    try:
        b = L.diag_export(list(files), out, consent)
    except PermissionError as e:
        _echo({"ok": False, "error": str(e)}, False)
        return
    _echo({"ok": True, "out": str(out), "files": [f["name"] for f in b["files"]], "redactions": b["scrub"]["redactions"]})


@liveops_grp.command("readiness")
def lo_readiness() -> None:
    """LiveOps readiness checklist (fails on any `fail`; `user_gated` items are reported, not failures)."""
    from forge import liveops as L

    r = L.readiness(find_repo_root())
    _echo(r, r["ok"])
