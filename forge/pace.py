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
        "crop_wait": 0.0,
        "explore_new_areas": first_visits * float(pace["first_visit_s"]),
        "interactions": sum(counts[k] * float(pace["interact_s"].get(k, 0)) for k in counts),
        "reading": read_s,
        "swap_overlays": len(s.get("swaps", [])) * float(pace["overlay_s"]),
    }
    comp["crop_wait"], slack = human_wait(s, comp, travel + combat, pace)
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
        "wait_slack_s": slack,
        "model": "content/tune/pace.yaml (INFERENCE C-92; not a playtest)",
    }


def human_wait(s: dict[str, Any], comp: dict[str, float], bot_active_ticks: int, pace: dict[str, Any]) -> tuple[float, float]:
    """Crop wait a human would actually sit through (seconds) and the slack that absorbed the rest.

    Crops grow in game time. A human is slower than the bot at everything between planting and the wait
    (factor f = human active seconds / bot active seconds), so part of each bot wait is already spent
    playing: human_wait = max(0, W - (f - 1) * active_between_plant_and_wait). Runs without
    ``wait_segments`` (pre-Q4 reports) fall back to the raw bot wait (conservative in the other direction).
    """
    segs = s.get("wait_segments")
    wf = float(pace["wait_factor"])
    if not segs:
        return round(int(s.get("wait_ticks") or 0) / TICK_HZ * wf, 1), 0.0
    human_active = sum(v for k, v in comp.items() if k not in ("select", "crop_wait"))
    f = human_active / max(1e-9, bot_active_ticks / TICK_HZ)
    total = slack = 0.0
    for i, g in enumerate(segs):
        start, ticks, planted = int(g["start"]), int(g["ticks"]), int(g.get("planted", -1))
        if planted < 0:
            total += ticks / TICK_HZ * wf
            continue
        waited_before = sum(int(h["ticks"]) for h in segs[:i] if int(h["start"]) >= planted)
        active = max(0, start - planted - waited_before) / TICK_HZ
        w = ticks / TICK_HZ * wf
        hw = max(0.0, w - max(0.0, f - 1.0) * active)
        slack += w - hw
        total += hw
    return round(total, 1), round(slack, 1)


def estimate_for(root: Path, s: dict[str, Any]) -> dict[str, Any]:
    locale = json.loads((root / "games/game-zero/locale/en.json").read_text(encoding="utf-8"))
    return estimate(s, load_pace(root), locale)
