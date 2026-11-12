"""Game Zero save format + versioned migrations — Python twin of `autoload/save.gd` (F5).

Player State = three layers (GAME_SPEC §4.5): **profile** (settings, playtime, stats),
**roster** (leader, fighters with level/xp, pets owned/assigned), **world** (area, cleared
encounters, bosses, inventory, quests, flags). Versioned; every older version migrates
forward one step at a time; the canonical JSON (sorted keys, no spaces, integral floats as
ints) is checksummed with sha256 so Godot and Python agree byte-for-byte.

Version history ([INFERENCE] F5-4 — v1/v2 model the prototype formats we migrate from):
  v1  flat prototype: {version, leader, levels{id:int}, pets[], cleared[], playtime (s)}
  v2  layered: profile{playtime_ticks}, roster{leader, fighters{id:int}, pets{owned, assigned}}, world{area, cleared}
  v3  fighters{id:{level,xp}}, profile.settings + stats, world.bosses_defeated/inventory/quests/flags, checksum
  v4  (F6 vertical slice) roster.unlocked/party_hp/gear; world.farm/checkpoint/counters/seed/rng/tick/visits/
      depleted/packs_cleared/buffs — everything needed to resume the slice at a checkpoint [INFERENCE F6-6]
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

FORMAT = "gamezero-save"
CURRENT = 4
TICK_HZ = 60


def canon(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {str(k): canon(x) for k, x in v.items()}
    if isinstance(v, list):
        return [canon(x) for x in v]
    return v


def canonical_json(v: Any) -> str:
    return json.dumps(canon(v), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum(save: dict[str, Any]) -> str:
    body = {k: save[k] for k in ("profile", "roster", "world")}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _v1_to_v2(s: dict[str, Any]) -> dict[str, Any]:
    pets = list(s.get("pets", []))
    leader = s.get("leader", "")
    return {"format": FORMAT, "version": 2,
            "profile": {"playtime_ticks": int(round(float(s.get("playtime", 0)) * TICK_HZ))},
            "roster": {"leader": leader, "fighters": {k: int(v) for k, v in s.get("levels", {}).items()},
                       "pets": {"owned": pets, "assigned": {leader: pets[:1]} if leader and pets else {}}},
            "world": {"area": "", "cleared": list(s.get("cleared", []))}}


def _v2_to_v3(s: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(s)
    out["version"] = 3
    out["roster"]["fighters"] = {k: {"level": int(v), "xp": 0} for k, v in s["roster"]["fighters"].items()}
    out["profile"].setdefault("settings", {"palette_variant": "default", "input_remap": {}})
    out["profile"].setdefault("stats", {"encounters_won": len(s["world"].get("cleared", [])), "bosses_defeated": 0})
    w = out["world"]
    w.setdefault("bosses_defeated", [])
    w.setdefault("inventory", {})
    w.setdefault("quests", {})
    w.setdefault("flags", {})
    return out


V4_WORLD_DEFAULTS: dict[str, Any] = {"farm": {"plots": []}, "checkpoint": {"area": "", "arrive": ""}, "counters": {}, "seed": 0,
                                     "rng": 0, "tick": 0, "visits": {}, "depleted": {}, "packs_cleared": {}, "buffs": []}


def _v3_to_v4(s: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(s)
    out["version"] = 4
    r = out["roster"]
    r.setdefault("unlocked", [])
    r.setdefault("party_hp", {})
    r.setdefault("gear", {"shared": [], "unique": {}})
    for k, v in V4_WORLD_DEFAULTS.items():
        out["world"].setdefault(k, copy.deepcopy(v))
    return out


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4}


def migrate(save: dict[str, Any]) -> tuple[dict[str, Any], list[int]]:
    s = copy.deepcopy(save)
    v = int(s.get("version", 1))
    if v > CURRENT:
        raise ValueError(f"save version {v} is newer than this build ({CURRENT})")
    steps = []
    while v < CURRENT:
        s = MIGRATIONS[v](s)
        steps.append(v)
        v = int(s["version"])
    s["checksum"] = checksum(s)
    return canon(s), steps


def new_save(leader: str, fighters: dict[str, int], pets: list[str]) -> dict[str, Any]:
    s = {"format": FORMAT, "version": CURRENT,
         "profile": {"playtime_ticks": 0, "settings": {"palette_variant": "default", "input_remap": {}},
                     "stats": {"encounters_won": 0, "bosses_defeated": 0}},
         "roster": {"leader": leader, "fighters": {k: {"level": v, "xp": 0} for k, v in fighters.items()},
                    "pets": {"owned": list(pets), "assigned": {leader: list(pets[:1])}},
                    "unlocked": [], "party_hp": {}, "gear": {"shared": [], "unique": {}}},
         "world": {"area": "", "cleared": [], "bosses_defeated": [], "inventory": {}, "quests": {}, "flags": {},
                   **copy.deepcopy(V4_WORLD_DEFAULTS)}}
    s["checksum"] = checksum(s)
    return s


def validate(save: dict[str, Any]) -> list[str]:
    errs = []
    if save.get("format") != FORMAT:
        errs.append("format")
    if int(save.get("version", 0)) != CURRENT:
        errs.append(f"version {save.get('version')} != {CURRENT}")
    for layer in ("profile", "roster", "world"):
        if not isinstance(save.get(layer), dict):
            errs.append(f"missing layer {layer}")
    if not errs and save.get("checksum") != checksum(save):
        errs.append("checksum mismatch")
    return errs


FIXTURES: dict[str, dict[str, Any]] = {
    "v1": {"version": 1, "leader": "nyra", "levels": {"kael": 2, "nyra": 3, "bram": 1, "sola": 2},
           "pets": ["lumen_wisp", "ember_fox"], "cleared": ["sandbox", "first_combat"], "playtime": 754.5},
    "v2": {"format": FORMAT, "version": 2, "profile": {"playtime_ticks": 90210},
           "roster": {"leader": "bram", "fighters": {"kael": 3, "nyra": 3, "bram": 4, "sola": 3},
                      "pets": {"owned": ["stone_tortle"], "assigned": {"bram": ["stone_tortle"]}}},
           "world": {"area": "cave_02", "cleared": ["sandbox", "first_combat", "party_ai"]}},
    "v3": {"format": FORMAT, "version": 3,
           "profile": {"playtime_ticks": 1760, "settings": {"palette_variant": "default", "input_remap": {}},
                       "stats": {"encounters_won": 1, "bosses_defeated": 1}},
           "roster": {"leader": "kael", "fighters": {"kael": {"level": 3, "xp": 70}, "nyra": {"level": 3, "xp": 70}},
                      "pets": {"owned": ["ember_fox"], "assigned": {"kael": ["ember_fox"]}}},
           "world": {"area": "cave_boss", "cleared": ["boss_warden"], "bosses_defeated": ["cave_warden"],
                     "inventory": {}, "quests": {}, "flags": {}}},
}
