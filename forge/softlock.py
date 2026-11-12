"""Soft-lock detection (F5, GAME_SPEC §8 "soft-lock detection on scripted playthroughs").

Three layers:
1. **Static statecharts** — every chart in `data/statecharts/` through `forge.statechart.analyze`
   (unreachable / dead-end / trap / dangling states).
2. **Static encounters** — every encounter's tilemap is solvable and every hostile spawn region
   (incl. the boss room) is reachable from the party start; every roster ref exists.
3. **Runtime** — the balance worker flags `softlock` when nothing is hit or healed for
   `CombatSim.STALL_TICKS` while both sides live, and `timeout` at the tick limit. A probe run
   with every ability cooldown pushed to the live-tune maximum proves the detector fires.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from forge.paths import find_repo_root
from forge.statechart import analyze

GAME = Path("games/game-zero")


def _reach(rows: list[str], start: tuple[int, int]) -> set[tuple[int, int]]:
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= ny < len(rows) and 0 <= nx < len(rows[ny]) and rows[ny][nx] != "#" and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen


def static_report(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    game = root / GAME
    charts = {p.stem: analyze(json.loads(p.read_text())) for p in sorted((game / "data" / "statecharts").glob("*.json"))}
    data = json.loads((game / "data" / "generated" / "game_data.json").read_text())
    reg = json.loads((game / "assets" / "generated" / "fabric_assets.json").read_text())["assets"]
    encounters: dict[str, Any] = {}
    for p in sorted((game / "data" / "encounters").glob("*.json")):
        enc = json.loads(p.read_text())
        issues = []
        tm = enc.get("tilemap")
        layout = None
        if tm not in reg:
            issues.append(f"tilemap {tm} not in registry")
        else:
            res = reg[tm]["files"][f"{tm}.json"]["res"].replace("res://", "")
            layout = json.loads((game / res).read_text())
        for m in enc.get("party", []):
            if m["ref"] not in data["fighters"]:
                issues.append(f"party ref {m['ref']}")
            issues += [f"pet ref {pp}" for pp in m.get("pets", []) if pp not in data["pets"]]
        for h in enc.get("hostiles", []):
            if h["ref"] not in data["enemies"]:
                issues.append(f"hostile ref {h['ref']}")
        if layout:
            reach = _reach(layout["rows"], tuple(layout["start"]))
            if tuple(layout["exit"]) not in reach:
                issues.append("exit unreachable")
            for sp in layout.get("spawns", []):
                if tuple(sp) not in reach:
                    issues.append(f"spawn {sp} unreachable")
            if any(h.get("at") == "boss_room" for h in enc.get("hostiles", [])):
                br = layout.get("boss_room")
                if not br:
                    issues.append("boss_room requested but tilemap has none")
                elif tuple(br["center"]) not in reach:
                    issues.append("boss room unreachable")
        encounters[p.stem] = {"ok": not issues, "issues": issues}
    ok = all(c["ok"] for c in charts.values()) and all(e["ok"] for e in encounters.values())
    return {"ok": ok, "statecharts": {k: v["ok"] for k, v in charts.items()}, "chart_details": charts, "encounters": encounters}


def stall_probe_overrides(root: Path | None = None) -> list[dict[str, Any]]:
    """Designer mis-tune that must be caught: every cooldown at the live-tune maximum."""
    root = root or find_repo_root()
    data = json.loads((root / GAME / "data" / "generated" / "game_data.json").read_text())
    hi = data["tune_limits"]["abilities.*.cooldown"][1]
    return [{"path": f"abilities.{a}.cooldown", "value": int(hi)} for a in sorted(data["abilities"])]
