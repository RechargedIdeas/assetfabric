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


@pytest.mark.parametrize("name", ["field_01", "tunnels_01", "hollow_01", "cave_deep", "ridge_01"])
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


# --------------------------------------------------------------------- Q4 (0.7.12): slice length content + pace model

def test_q4_waves_and_open_world_chain(world: dict) -> None:
    areas = world["areas"]
    assert areas["warden_lair"]["links"]["E"]["to"] == "ridge" and areas["ridge"]["links"]["E"]["to"] == "field"
    assert areas["tunnels"]["links"]["E"]["to"] == "hollow" and areas["hollow"]["links"]["E"]["to"] == "cave_deep"
    waves = {f"{a}.{p['wave']}" for a, d in areas.items() for p in d.get("packs", []) if p.get("wave")}
    stages = {s["id"]: s for s in next(q for q in world["quests"] if q["id"] == "q_warden")["stages"]}
    assert stages["patrol"]["when"] == "cleared:hollow.patrol" and "hollow.patrol" in waves
    assert stages["open_world"]["when"] == "enter:ridge"
    order = list(stages)
    assert order.index("replant") < order.index("patrol") < order.index("second_harvest")


def test_q4_unknown_wave_is_a_cross_ref_error(root: Path) -> None:
    from forge.generators import world as gw

    raw = gw.load_world_sources(root)
    for q in raw["quests"]["quests"]:
        for st in q["stages"]:
            if st["id"] == "patrol":
                st["when"] = "cleared:hollow.nope"
    orig = gw.load_world_sources
    gw.load_world_sources = lambda *_a, **_k: raw
    try:
        out = gw.generate({"source": "content/world"}, type("C", (), {"root": root})())
    finally:
        gw.load_world_sources = orig
    cr = next(g for g in out.gates if g.gate == "cross_refs")
    assert not cr.ok and any("unknown wave hollow.nope" in m for m in cr.detail["missing"])


def _pace_report(segs):
    return {"ticks": 36000, "wait_ticks": sum(g["ticks"] for g in segs), "wait_segments": segs, "fights": [],
            "farming": {}, "stage_ticks": {}, "areas": [], "swaps": []}


def test_pace_human_wait_absorbs_slack_and_never_goes_negative(root: Path) -> None:
    from forge.pace import human_wait, load_pace

    pace = load_pace(root)
    comp = {"select": 45.0, "travel": 160.0, "combat": 0.0, "explore_new_areas": 0.0, "interactions": 0.0,
            "reading": 0.0, "swap_overlays": 0.0}
    # f = 160 s human / 100 s bot = 1.6; crop planted at 0, bot active 100 s (6000 ticks), then waits 30 s
    hw, slack = human_wait(_pace_report([{"start": 6000, "ticks": 1800, "planted": 0}]), comp, 6000, pace)
    assert hw == 0.0 and slack == 30.0                    # 0.6 × 100 s = 60 s of slack ≥ the 30 s wait
    hw, slack = human_wait(_pace_report([{"start": 600, "ticks": 3600, "planted": 0}]), comp, 6000, pace)
    assert hw == 54.0 and slack == 6.0                    # planted right before: only 0.6 × 10 s absorbed
    hw, _ = human_wait({"wait_ticks": 600}, comp, 6000, pace)   # pre-Q4 report: raw bot wait
    assert hw == 10.0


def test_pace_constants_are_the_documented_heuristics(root: Path) -> None:
    from forge.pace import load_pace

    p = load_pace(root)   # changing any of these needs a DECISIONS entry (pace.yaml header)
    assert (p["nav_factor"], p["combat_factor"], p["wait_factor"], p["first_visit_s"], p["select_s"]) == (1.6, 1.5, 1.0, 30, 45)
    assert p["target_min"] == [15.0, 20.0]


# --------------------------------------------------------------------- Q5 (0.7.13): economy design model (ADR-0018)

def test_q5_item_values_are_derived_and_exported(world: dict, root: Path) -> None:
    from forge.economy import item_values, load_design

    d = load_design(root)
    v = item_values(world, d)
    assert all(world["items"][k]["value"] == v[k] for k in world["items"])     # Codegen-World wrote them
    assert v["sunroot_seed"] == world["shop"]["sunroot_seed"]
    r = world["recipes"]["flint_edge"]["in"]
    assert v["flint_edge"] == round(sum(v[i] * q for i, q in r.items()) * d["craft_markup"], 2)
    assert not any("sell" in it for it in world["items"].values())             # placeholder sell prices removed


def test_q5_static_targets_hold_and_dead_drops_are_caught(world: dict, root: Path) -> None:
    import copy as _copy

    from forge.economy import load_design, static_report
    from forge.generators.codegen import load_roster

    enemies = {e["id"]: e for e in load_roster(root, "content/roster")["enemies"]["enemies"]}
    d = load_design(root)
    rep = static_report(world, d, enemies)
    assert rep["ok"], rep["checks"]
    w2 = _copy.deepcopy(world)
    w2["items"]["junk"] = {"id": "junk", "kind": "material"}
    d2 = _copy.deepcopy(d)
    d2["base_value"]["junk"] = 1
    bad = static_report(w2, d2, enemies)
    assert not bad["checks"]["no_dead_materials"] and bad["sinks"]["junk"] == []


def test_q5_xp_timeline_levels(world: dict) -> None:
    from forge.economy import level_at, xp_timeline

    s = {"loot": {"drops": [["emberling", 1, [], 100], ["rock_brute", 2, [], 200]]},
         "stage_ticks": {"q_warden.clear_cave": 300}}
    tl = xp_timeline(world, s)
    start = world["xp"]["level_at"][world["xp"]["start_level"] - 1]
    assert tl[0] == (0, start) and tl[-1][1] == start + 10 + 20 + 40
    assert level_at(world, tl, 0) == world["xp"]["start_level"]


def test_q5_holdout_is_out_of_sample() -> None:
    from forge.balance import AFFINITY_SPACE, HOLDOUT_LIMIT, HOLDOUT_SEED_BASE, HOLDOUT_SEEDS, BalanceConfig

    assert HOLDOUT_SEED_BASE >= 9000 and HOLDOUT_SEEDS >= 800 and HOLDOUT_LIMIT == 0.035
    gate = BalanceConfig()
    assert not (gate.seed_base <= HOLDOUT_SEED_BASE < gate.seed_base + gate.seeds)   # CRN gate seeds ≠ hold-out
    assert all(lo == 0.0 and hi == 3.0 for lo, hi in AFFINITY_SPACE.values())
