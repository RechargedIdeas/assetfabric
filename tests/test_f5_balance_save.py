"""F5: balance runner math, save format + migrations, soft-lock detection, boss content."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from forge import save
from forge.balance import BalanceConfig, aggregate, build_jobs, matchups, run, verdict, wilson
from forge.generators.tile import make_cave
from forge.softlock import _reach, stall_probe_overrides, static_report


@pytest.fixture
def data(root: Path) -> dict:
    return json.loads((root / "games/game-zero/data/generated/game_data.json").read_text())


# ----------------------------------------------------------------------------- content

def test_boss_is_tier3_with_descending_phases(data: dict) -> None:
    b = data["enemies"]["cave_warden"]
    assert b["tier"] == 3 and b["boss"] is True
    ats = [p["at"] for p in b["phases"]]
    assert ats[0] == 1.0 and ats == sorted(ats, reverse=True) and len(ats) == 3
    assert any("summon" in p for p in b["phases"]) and any("atk_mult" in p for p in b["phases"])
    for p in b["phases"]:
        assert all(a in data["abilities"] for a in p["abilities"])


def test_boss_room_is_carved_and_reachable() -> None:
    rows, info = make_cave({"width": 40, "height": 22, "density": 0.4, "min_path": 30, "boss_room": {"radius": 5}}, 51)
    cx, cy = info["boss_room"]["center"]
    assert rows[cy][cx] != "#"
    assert (cx, cy) in _reach(rows, tuple(info["start"]))


def test_caves_without_boss_room_are_unchanged() -> None:
    a = make_cave({"width": 40, "height": 22, "density": 0.42, "min_path": 30, "enemies": 3}, 23)
    assert "boss_room" not in a[1]


# ----------------------------------------------------------------------------- balance

def test_matchups_are_character_select_choices(data: dict) -> None:
    m = matchups(data)
    assert len(m) == 12 and len({f for f, _ in m}) == 4 and len({p for _, p in m}) == 3


def test_jobs_use_common_random_numbers(data: dict) -> None:
    jobs = build_jobs(BalanceConfig(seeds=5), data)
    assert len(jobs) == 60
    seeds = {}
    for j in jobs:
        seeds.setdefault(j["id"], []).append(j["seed"])
        assert sum(1 for m in j["party"] if m.get("leader")) == 1
        assert sum(len(m.get("pets", [])) for m in j["party"]) == 1
    assert len({tuple(v) for v in seeds.values()}) == 1


def test_aggregate_and_verdict() -> None:
    rows = []
    for mid, wins in (("a+x", 7), ("b+x", 8)):
        rows += [{"id": mid, "seed": i, "outcome": "victory" if i < wins else "defeat", "ticks": 100, "boss_phase": 3}
                 for i in range(10)]
    agg = aggregate(rows)
    assert agg["mean_win_rate"] == 0.75 and agg["max_deviation"] == 0.05 and agg["combo_deviation"] == 0.05
    assert agg["choice_deviation"] == 0.05          # leaders a/b are the only choices that differ
    assert agg["matchups"]["a+x"]["ci95"][0] < 0.7 < agg["matchups"]["a+x"]["ci95"][1]
    v = verdict(agg)
    assert not v["G-BAL-01"] and not v["checks"]["encounters_ge_1000"] and not v["checks"]["max_choice_deviation_lt_5pp"]
    assert v["soft"]["max_combo_deviation_lt_5pp"] is False       # point spread: reported since Q5
    assert v["checks"]["combo_ci_within_5pp"] is True             # 10 fights/cell: not significantly off


def test_verdict_per_pair_ci_check_catches_a_real_outlier() -> None:
    rows = []   # Q5 (C-94): 400 fights/cell, one cell 20 pp below the rest → its CI misses the ±5 pp band
    for mid, wins in (("a+x", 300), ("a+y", 300), ("b+x", 300), ("b+y", 220)):
        rows += [{"id": mid, "seed": i, "outcome": "victory" if i < wins else "defeat", "ticks": 100, "boss_phase": 3}
                 for i in range(400)]
    v = verdict(aggregate(rows))
    assert v["checks"]["combo_ci_within_5pp"] is False and not v["G-BAL-01"]


def test_wilson_interval() -> None:
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi and round(hi - lo, 2) == 0.19
    assert wilson(0, 0) == (0.0, 1.0)


def test_balance_overrides_obey_live_tune_limits(root: Path) -> None:
    with pytest.raises(ValueError):
        run(BalanceConfig(seeds=1, overrides=[{"path": "enemies.cave_warden.stats.hp", "value": 10 ** 6}]), root)


# ----------------------------------------------------------------------------- saves

def test_fixtures_migrate_to_current_and_validate() -> None:
    for name, fx in save.FIXTURES.items():
        s, steps = save.migrate(fx)
        assert s["version"] == save.CURRENT and save.validate(s) == [], name
        assert steps == list(range(int(fx["version"]), save.CURRENT))
    v1, _ = save.migrate(save.FIXTURES["v1"])
    assert v1["profile"]["playtime_ticks"] == round(754.5 * 60)
    assert v1["roster"]["fighters"]["nyra"] == {"level": 3, "xp": 0}
    assert v1["roster"]["pets"]["assigned"] == {"nyra": ["lumen_wisp"]}


def test_migration_is_idempotent_on_current() -> None:
    s, _ = save.migrate(save.FIXTURES["v2"])
    again, steps = save.migrate(s)
    assert steps == [] and again == s


def test_checksum_detects_tampering_and_ignores_float_formatting() -> None:
    s = save.new_save("kael", {"kael": 1, "nyra": 1}, ["ember_fox"])
    assert save.validate(s) == []
    t = copy.deepcopy(s)
    t["roster"]["fighters"]["kael"]["level"] = 99
    assert "checksum mismatch" in save.validate(t)
    f = copy.deepcopy(s)
    f["profile"]["playtime_ticks"] = 0.0          # JSON round-trips through Godot as floats
    assert save.validate(f) == []


def test_newer_versions_are_refused() -> None:
    with pytest.raises(ValueError):
        save.migrate({"version": save.CURRENT + 1})


# ----------------------------------------------------------------------------- soft-locks

def test_static_softlock_report_is_clean(root: Path) -> None:
    rep = static_report(root)
    assert rep["ok"], rep
    assert {"boss_warden", "party_ai", "live_tune"} <= set(rep["encounters"])


def test_reachability_flags_walled_off_cells() -> None:
    rows = ["#####", "#S#E#", "#####"]
    assert (3, 1) not in _reach(rows, (1, 1))


def test_stall_probe_overrides_are_valid(root: Path, data: dict) -> None:
    from forge.live import validate_patch

    ov = stall_probe_overrides(root)
    assert len(ov) == len(data["abilities"]) and all(validate_patch(data, p) is None for p in ov)
