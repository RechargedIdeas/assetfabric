"""Live channel — atomic hot reload + live tune between Forge and a running game (F4).

SPEC §6.3 "atomic reload": monotonic version ticket → stage/validate in isolation →
two-phase commit → health probe → rollback on failure. Split across processes:

Forge side (this module)
  1. **stage** — generate/derive content in a Sandbox (forge.sandbox), write staged files
     under `<live>/stage/<ticket>/`, validate every patch against `tune_limits`.
  2. **publish** — write `<live>/tickets/<n>.json` then advance `<live>/HEAD` (both via
     write-temp + os.replace, so a reader sees either the old or the new ticket, never half).
Game side (`games/game-zero/autoload/live.gd`)
  3. **prepare** — re-validate (limits + sha256 of staged files); reject → ack `rejected`.
  4. **commit** at a tick boundary — snapshot sim, apply patches/assets.
  5. **probe** — forward-simulate a clone; invariant failure → restore snapshot, ack `rolled_back`.
  6. **ack** — `<live>/acks/<n>.json` with status + state hashes; applied tickets are kept in
     the session WAL so a snapshot + WAL replays to the same state hash.

Tickets carry data patches (numeric leaves of game_data + `sim.*` params) and/or asset
overrides. Structural changes (new units, ability lists) are refused: run `forge build`.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from forge.paths import find_repo_root

GAME_DATA_REL = "games/game-zero/data/generated/game_data.json"


# ----------------------------------------------------------------------------- paths / limits

def _seg_match(pat: str, seg: str) -> bool:
    return pat == "*" or pat == seg


def path_matches(pattern: str, path: str) -> bool:
    p, q = pattern.split("."), path.split(".")
    return len(p) == len(q) and all(_seg_match(a, b) for a, b in zip(p, q))


def _walk(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{prefix}.{i}" if prefix else str(i))
    else:
        yield prefix, node


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def match_paths(data: dict[str, Any], pattern: str) -> list[str]:
    return [p for p, v in _walk(data) if _is_num(v) and path_matches(pattern, p)]


def rule_for(limits: dict[str, list[float]], path: str) -> list[float] | None:
    """Most specific matching rule (fewest wildcards)."""
    best = None
    for pat, rng in limits.items():
        if path_matches(pat, path):
            w = pat.count("*")
            if best is None or w < best[0]:
                best = (w, rng)
    return best[1] if best else None


def get_path(data: Any, path: str) -> Any:
    node = data
    for seg in path.split("."):
        if isinstance(node, list):
            node = node[int(seg)]
        elif isinstance(node, dict):
            node = node[seg]
        else:
            raise KeyError(path)
    return node


def validate_patch(game_data: dict[str, Any], patch: dict[str, Any]) -> str | None:
    """None if ok, else the reason. Mirrors LiveChannel._validate in live.gd."""
    path, value = patch.get("path"), patch.get("value")
    if not isinstance(path, str) or not path:
        return "patch.path missing"
    if not _is_num(value) or not math.isfinite(float(value)):
        return f"{path}: value must be a finite number"
    rng = rule_for(game_data.get("tune_limits", {}), path)
    if rng is None:
        return f"{path}: not live-tunable (structural → forge build)"
    if not (rng[0] <= float(value) <= rng[1]):
        return f"{path}: {value} outside [{rng[0]}, {rng[1]}]"
    if not path.startswith("sim."):
        try:
            cur = get_path(game_data, path)
        except (KeyError, IndexError, ValueError):
            return f"{path}: no such field"
        if not _is_num(cur):
            return f"{path}: not a numeric leaf"
    return None


def diff_numeric(old: dict[str, Any], new: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Numeric leaf changes old→new as patches, plus structural differences."""
    a, b = dict(_walk(old)), dict(_walk(new))
    structural = sorted(set(a) ^ set(b))
    patches = []
    for k in sorted(set(a) & set(b)):
        if a[k] == b[k] or k.startswith("tune_limits."):
            continue
        if _is_num(a[k]) and _is_num(b[k]):
            patches.append({"path": k, "value": b[k]})
        else:
            structural.append(k)
    return patches, structural


# ----------------------------------------------------------------------------- channel

def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def default_dir(root: Path | None = None) -> Path:
    return (root or find_repo_root()) / ".fabric" / "live" / "game-zero"


class LiveError(RuntimeError):
    pass


class LiveChannel:
    def __init__(self, live_dir: Path | None = None, root: Path | None = None) -> None:
        self.root = root or find_repo_root()
        self.dir = Path(live_dir) if live_dir else default_dir(self.root)
        for d in ("tickets", "stage", "acks"):
            (self.dir / d).mkdir(parents=True, exist_ok=True)

    # -- state -------------------------------------------------------------------------
    def head(self) -> int:
        p = self.dir / "HEAD"
        return int(json.loads(p.read_text())["ticket"]) if p.exists() else 0

    def base_data(self) -> dict[str, Any]:
        return json.loads((self.root / GAME_DATA_REL).read_text(encoding="utf-8"))

    def status(self) -> dict[str, Any]:
        p = self.dir / "status.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def ack(self, ticket: int) -> dict[str, Any] | None:
        p = self.dir / "acks" / f"{ticket}.json"
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except ValueError:
            return None   # mid-write on a non-atomic writer

    @contextmanager
    def _lock(self) -> Iterator[None]:
        with open(self.dir / "HEAD.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    # -- publish -----------------------------------------------------------------------
    def push(self, patches: list[dict[str, Any]] | None = None, assets: list[dict[str, Any]] | None = None,
             source: str = "forge live", control: str | None = None, validate: bool = True,
             fault: str | None = None, staged: dict[str, bytes] | None = None) -> int:
        patches = patches or []
        if validate:
            base = self.base_data()
            errs = [e for e in (validate_patch(base, p) for p in patches) if e]
            if errs:
                raise LiveError("; ".join(errs))
        with self._lock():
            n = self.head() + 1
            stage = self.dir / "stage" / str(n)
            asset_entries = []
            for a in assets or []:
                a = dict(a)
                if staged and a["file"] in staged:
                    data = staged[a["file"]]
                    _atomic_write(stage / a["file"], data)
                    a["path"] = str((stage / a["file"]).resolve())
                    a["sha256"] = hashlib.sha256(data).hexdigest()
                asset_entries.append(a)
            ticket = {"schema_version": "1.0", "ticket": n, "issued_at": datetime.now(timezone.utc).isoformat(),
                      "issued_unix": time.time(), "source": source, "patches": patches, "assets": asset_entries,
                      "control": control}
            if fault:
                ticket["fault"] = fault    # honoured only by games started with --allow-fault-injection
            _atomic_write(self.dir / "tickets" / f"{n}.json", (json.dumps(ticket, indent=1, sort_keys=True) + "\n").encode())
            _atomic_write(self.dir / "HEAD", json.dumps({"ticket": n}).encode())   # commit point
        return n

    def wait_ack(self, ticket: int, timeout: float = 10.0, poll: float = 0.02) -> dict[str, Any]:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            a = self.ack(ticket)
            if a:
                a["ack_latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
                return a
            time.sleep(poll)
        raise LiveError(f"no ack for ticket {ticket} within {timeout}s (is the game running with this --live-dir?)")

    def wait_status(self, timeout: float = 30.0) -> dict[str, Any]:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            s = self.status()
            if s.get("ready"):
                return s
            time.sleep(0.05)
        raise LiveError("game never reported ready on the live channel")

    # -- high-level pushes ---------------------------------------------------------------
    def push_sprite(self, brief_id: str, seed: int | None = None, tier: str = "auto") -> int:
        """Regenerate one sprite brief in a sandbox and hot-swap it into the running game."""
        from forge import sandbox
        from forge.pipeline import load_briefs

        briefs = {b["id"]: b for b in load_briefs(self.root)}
        if brief_id not in briefs:
            raise LiveError(f"unknown brief {brief_id}")
        b = dict(briefs[brief_id])
        if b["kind"] != "sprite":
            raise LiveError("live asset reload supports sprite briefs; other kinds need forge build")
        if seed is not None:
            b["seed"] = seed
        out = sandbox.generate(b, self.root, tier=tier)
        if not out.ok:
            raise LiveError("gates failed: " + ", ".join(g.gate for g in out.gates if not g.ok))
        staged = {a.name: a.data for a in out.artifacts}
        assets = [{"id": brief_id, "file": a.name} for a in out.artifacts if a.name.endswith(".png")]
        return self.push(assets=assets, staged=staged, source=f"forge live sprite {brief_id} seed={b.get('seed')} "
                         f"sandbox={out.meta['sandbox']['tier']}")

    def push_roster(self, tier: str = "auto") -> tuple[int | None, list[dict[str, Any]]]:
        """Re-run codegen on the edited roster in a sandbox; push numeric changes as patches."""
        from forge import sandbox
        from forge.pipeline import load_briefs

        brief = next(b for b in load_briefs(self.root) if b["kind"] == "codegen")
        out = sandbox.generate(brief, self.root, tier=tier)
        if not out.ok:
            raise LiveError("codegen gates failed: " + ", ".join(g.gate for g in out.gates if not g.ok))
        new = json.loads(next(a.data for a in out.artifacts if a.name == "game_data.json"))
        patches, structural = diff_numeric(self.base_data(), new)
        if structural:
            raise LiveError(f"structural roster change ({structural[:5]}…): run `forge build` instead")
        if not patches:
            return None, []
        return self.push(patches, source=f"forge live roster sandbox={out.meta['sandbox']['tier']}"), patches
