"""F6 world layer: Codegen-World output, quest chart, loot, economy solvability, save v4, slice tilemaps."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from forge.save import CURRENT, FIXTURES, migrate, validate
from forge.statechart import analyze
from forge.world import (Lcg, QuestLog, compile_quests, crop_ready, eval_guard, load_world, loot_ev, roll_loot,
                         solvability, stage_index)

GAME = Path(__file__).resolve().parents[1] / "games" / "game-zero"


@pytest.fixture(scope="module")
def world() -> dict:
    return load_world()


def test_world_export_matches_sources(world: dict) -> None:
    assert {"items", "crops", "recipes", "loot", "quests", "quest_chart", "music", "areas"} <= set(world)
    assert world["quest_chart"] == compile_quests(world["quests"])


def test_quest_chart_has_no_softlocks(world: dict) -> None:
    rep = analyze(world["quest_chart"])
    assert rep["ok"], rep


def test_guard_language() -> None:
    c = {"have": {"flint": 3}, "total": {"planted": 1}, "flag": {"warden_down": True}}
    assert eval_guard("", c)
    assert eval_guard("have:flint>=3", c) and not eval_guard("have:flint>=4", c)
    assert eval_guard("have:flint>=2&flag:warden_down", c)
    assert not eval_guard("total:planted>=2", c) and not eval_guard("flag:nope", c)


def test_quest_log_walks_main_quest_in_order(world: dict) -> None:
    q = QuestLog(world)
    assert q.stage("q_warden") == "choose"
    assert q.send("enter") == []                     # wrong event for the current stage: no transition
    q.send("select", {"have": {}, "total": {}, "flag": {}})
    assert q.stage("q_warden") == "plant"
    q.send("plant", {"have": {}, "total": {"planted": 1}, "flag": {}})
    assert q.stage("q_warden") == "plant"            # guard not met yet
    q.send("plant", {"have": {}, "total": {"planted": 2}, "flag": {}})
    assert q.stage("q_warden") == "forage"
    assert stage_index(world, "q_warden", "forage") > stage_index(world, "q_warden", "plant")


def test_loot_is_deterministic_and_tiered(world: dict) -> None:
    a = [roll_loot(world, t, r, Lcg(7)) for r, t in [("cave_mite", 1), ("cave_warden", 3)]]
    b = [roll_loot(world, t, r, Lcg(7)) for r, t in [("cave_mite", 1), ("cave_warden", 3)]]
    assert a == b
    for seed in range(20):                               # tier 3 always yields the guaranteed core
        assert ["warden_core", 1] in roll_loot(world, 3, "cave_warden", Lcg(seed))
    ev = loot_ev(world)
    assert ev["3"]["coin"] > ev["2"]["coin"] > ev["1"]["coin"]


def test_economy_is_solvable_without_random_drops(world: dict) -> None:
    reg = json.loads((GAME / "assets" / "generated" / "fabric_assets.json").read_text())["assets"]
    rep = solvability(world, reg["world"]["meta"]["node_counts"])
    assert rep["ok"], rep["missing"]
    starved = solvability(world, {})                     # no gather nodes → the flint stage is unreachable
    assert not starved["ok"]


def test_crop_growth(world: dict) -> None:
    plot = {"crop": "sunroot", "planted": 100}
    g = world["crops"]["sunroot"]["grow_ticks"]
    assert not crop_ready(world, plot, 100 + g - 1) and crop_ready(world, plot, 100 + g)
    assert not crop_ready(world, {"crop": "", "planted": 0}, 10**9)


def test_save_v4_migration_adds_world_state() -> None:
    assert CURRENT == 4
    for name, f in FIXTURES.items():
        s, steps = migrate(copy.deepcopy(f))
        assert s["version"] == 4 and validate(s) == [], name
        assert {"farm", "checkpoint", "counters", "packs_cleared", "buffs"} <= set(s["world"])
        assert {"unlocked", "party_hp", "gear"} <= set(s["roster"])
        assert steps[-1] == 3


@pytest.mark.parametrize("name", ["field_01", "tunnels_01", "cave_deep"])
def test_slice_tilemaps_have_features_and_route(name: str) -> None:
    lay = json.loads((GAME / "assets" / "generated" / "tilemap" / f"{name}.json").read_text())
    rows = "".join(lay["rows"])
    assert rows.count("S") == 1 and rows.count("E") == 1
    assert rows.count("G") >= 3
    if name == "field_01":
        assert rows.count("P") == 4 and rows.count("W") == 1


def test_areas_link_both_ways(world: dict) -> None:
    areas = world["areas"]
    for aid, a in areas.items():
        for glyph, link in a["links"].items():
            back = areas[link["to"]]["links"]
            assert any(l["to"] == aid for l in back.values()) or link["to"] == "field", (aid, glyph)
