"""Human-pace estimate for the vertical slice (Q4; content/tune/pace.yaml, INFERENCE C-92).

Input: one QA-autopilot slice report (`FABRIC_RESULT.slice`). Output: an itemised estimate (seconds per
component + total minutes) of a first-time human playthrough of the same content. Bot game time is
reported unchanged next to it; the estimate is a model until a human GUI playtest exists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

PACE_REL = "content/tune/pace.yaml"
TICK_HZ = 60


def load_pace(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / PACE_REL).read_text(encoding="utf-8"))


def _words(text: str) -> int:
    return len([w for w in text.replace("—", " ").split() if w.strip()])


def estimate(s: dict[str, Any], pace: dict[str, Any], locale: dict[str, str]) -> dict[str, Any]:
    ticks = int(s.get("ticks") or 0)
    wait = int(s.get("wait_ticks") or 0)
    combat = sum(max(0, int(f.get("end", f.get("start", 0))) - int(f.get("start", 0))) for f in s.get("fights", []))
    travel = max(0, ticks - wait - combat)
    farming = s.get("farming", {})
    counts = {
        "plant": len(farming.get("planted", [])),
        "harvest": len(farming.get("harvested", [])),
        "gather": len(farming.get("gathered", [])),
        "craft": len(farming.get("crafted", [])),
        "buy": int(s.get("buys") or 0),
        "use": len(farming.get("salves", [])),
        "save": 1,
    }
    # objective text: every main/side stage the player is shown (stage_ticks keys = completed stages)
    read_s = 0.0
    shown = sorted(s.get("stage_ticks", {}))
    for key in shown:
        quest, _, stage = key.partition(".")
        text = locale.get(f"quest.{quest}.{stage}", "")
        read_s += max(float(pace["min_read_s"]), _words(text) / float(pace["reading_wpm"]) * 60.0)
    first_visits = len({a.get("area") for a in s.get("areas", [])})
    comp = {
        "select": float(pace["select_s"]),
        "travel": travel / TICK_HZ * float(pace["nav_factor"]),
        "combat": combat / TICK_HZ * float(pace["combat_factor"]),
        "crop_wait": wait / TICK_HZ * float(pace["wait_factor"]),
        "explore_new_areas": first_visits * float(pace["first_visit_s"]),
        "interactions": sum(counts[k] * float(pace["interact_s"].get(k, 0)) for k in counts),
        "reading": read_s,
        "swap_overlays": len(s.get("swaps", [])) * float(pace["overlay_s"]),
    }
    total = sum(comp.values()) / 60.0
    lo, hi = (float(x) for x in pace["target_min"])
    return {
        "human_estimate_min": round(total, 2),
        "within_target": lo <= total <= hi,
        "target_min": [lo, hi],
        "components_s": {k: round(v, 1) for k, v in comp.items()},
        "bot": {"game_min": round(ticks / TICK_HZ / 60.0, 2), "travel_s": round(travel / TICK_HZ, 1),
                "combat_s": round(combat / TICK_HZ, 1), "crop_wait_s": round(wait / TICK_HZ, 1),
                "first_visits": first_visits, "interactions": counts, "objectives_shown": len(shown)},
        "model": "content/tune/pace.yaml (INFERENCE C-92; not a playtest)",
    }


def estimate_for(root: Path, s: dict[str, Any]) -> dict[str, Any]:
    locale = json.loads((root / "games/game-zero/locale/en.json").read_text(encoding="utf-8"))
    return estimate(s, load_pace(root), locale)
