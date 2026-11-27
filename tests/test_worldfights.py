"""P7 (0.7.15): world-fight Monte Carlo — wipe-rate / clear-time bands (forge/worldfights.py, INFERENCE C-98)."""

from __future__ import annotations

from typing import Any

import pytest

from forge import worldfights as wf
from forge.balance import HOLDOUT_SEED_BASE, game_data
from forge.world import load_world
from tests.conftest import requires_godot

PARTY = [{"ref": f, "level": 3, **({"leader": True, "pets": ["ember_fox"]} if f == "kael" else {})}
         for f in ("bram", "kael", "nyra", "sola")]


def _fight(area: str, packs: list[int], **ctx: Any) -> dict[str, Any]:
    return {"area": area, "start": 0, "end": 100, "kills": 3,
            "ctx": {"tilemap": "x", "party": PARTY, "bonus": {}, "hp": {"kael": 50}, "packs": packs} | ctx}


def test_fight_units_expand_packs_and_dedupe_the_boss() -> None:
    w = load_world()
    fights = [_fight("tunnels", [1, 0]), _fight("warden_lair", [-1], encounter="boss_warden"),
              _fight("warden_lair", [-1], encounter="boss_warden"), _fight("field", [-1]), {"area": "field"}]
    u = wf.fight_units(fights, w)
    assert [x["key"] for x in u] == ["tunnels.p0+p1", "warden_lair.boss"]
    tun = {a["id"]: a for a in w["areas"]}["tunnels"] if isinstance(w["areas"], list) else w["areas"]["tunnels"]
    want = sum(int(x.get("count", 1)) for p in (0, 1) for x in tun["packs"][p]["units"])
    assert sum(h["count"] for h in u[0]["hostiles"]) == want
    assert u[0]["start_hp"] == {"kael": 50} and u[1]["encounter"] == "boss_warden"


def test_classify_by_tier2_count() -> None:
    data, cfg = game_data(wf.find_repo_root()), wf.load_config()
    assert wf.classify({"hostiles": [{"ref": "rock_brute", "count": 2}]}, data, cfg) == "elite"
    assert wf.classify({"hostiles": [{"ref": "rock_brute", "count": 1}, {"ref": "emberling", "count": 3}]}, data, cfg) == "trash"
    assert wf.classify({"encounter": "boss_warden"}, data, cfg) == "boss"


def _rows(jid: str, n: int, wipes: int, ticks: int) -> list[dict[str, Any]]:
    return [{"id": jid, "seed": i, "outcome": "defeat" if i < wipes else "victory", "ticks": ticks, "engage_tick": 30,
             "party_hp_ratio": 0.8, "deaths": []} for i in range(n)]


def test_verdict_bands() -> None:
    cfg = wf.load_config()
    classes = {"tunnels.p0": ("trash", 1), "tunnels.p1+p2": ("trash", 2), "warden_lair.boss": ("boss", 1)}
    ok = _rows("a+b|tunnels.p0", 40, 0, 30 + 150) + _rows("a+b|tunnels.p1+p2", 40, 0, 30 + 600) + _rows("a+b|warden_lair.boss", 40, 1, 30 + 600)
    agg = wf.aggregate(ok, classes, cfg)
    v = wf.verdict(agg, cfg)
    assert v["ok"], v                      # 10 s for a 2-pack pull is inside 2 × the 6 s trash ceiling
    assert agg["fights"]["warden_lair.boss"]["wipe_rate"] == 0.025
    bad = _rows("a+b|tunnels.p0", 40, 4, 30 + 30) + _rows("a+b|warden_lair.boss", 40, 0, 30 + 120)
    v = wf.verdict(wf.aggregate(bad, classes, cfg), cfg)
    assert not v["ok"]
    joined = " ".join(v["out_of_band"])
    assert "tunnels.p0 wipe" in joined and "tunnels.p0 clear median 0.5" in joined and "boss clear median 2.0" in joined
    stall = _rows("a+b|tunnels.p0", 10, 0, 180)
    stall[0]["outcome"] = "timeout"
    assert not wf.verdict(wf.aggregate(stall, classes, cfg), cfg)["checks"]["no_stalls"]


def test_config_is_sane() -> None:
    cfg = wf.load_config()
    for name, b in cfg["bands"].items():
        assert 0.0 <= b["wipe_rate"][0] <= b["wipe_rate"][1] <= 1.0, name
        assert 0.0 < b["clear_s"][0] < b["clear_s"][1] <= b["clear_p90_max_s"], name
    # C-93: the slice Warden is deliberately forgiving — capped, no wipe floor; the hard point stays G-BAL-01
    assert cfg["bands"]["boss"]["wipe_rate"][0] == 0.0
    # own seed range: not the G-BAL-01 seeds (1000…), the hold-out (20 000…) or the fits (50 000…)
    full = cfg["seeds"]["full"]
    lo, hi = int(cfg["seed_base"]), int(cfg["seed_base"]) + max(full.values())
    for other, n in ((1000, 1000), (HOLDOUT_SEED_BASE, 1000), (50_000, 20_000)):
        assert hi <= other or lo >= other + n


@requires_godot
def test_worker_replays_carried_state_and_gate_fires() -> None:
    """Healthy fight → in band; the same pack against a level-1 party on 1 HP must wipe and fail the gate."""
    w = load_world()
    fights = [_fight("ridge", [2], tilemap="ridge_01", hp={})]
    units = wf.fight_units(fights, w)
    good = wf.run({"kael+ember_fox": units}, {"world": 6, "boss": 0}, workers=2)
    assert not good["errors"] and good["encounters"] == 6
    assert good["fights"]["ridge.p2"]["class"] == "elite" and good["fights"]["ridge.p2"]["wipe_rate"] <= 0.06
    weak = [dict(u, party=[dict(m, level=1) for m in PARTY], start_hp={m["ref"]: 1 for m in PARTY}) for u in units]
    bad = wf.run({"kael+ember_fox": weak}, {"world": 6, "boss": 0}, workers=2)
    assert bad["fights"]["ridge.p2"]["wipe_rate"] > 0.06            # carried HP is applied: 0 wipes at full HP
    assert not bad["verdict"]["ok"]
