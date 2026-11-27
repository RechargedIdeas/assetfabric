"""Economy design model + checks (Q5, quality gap P4 / D-005; ADR-0018, INFERENCE C-93).

`content/world/economy_design.yaml` holds the design decision: base values of raw goods, a craft markup and
targets. This module

* derives a coin-equivalent **value** for every item (base goods; seeds = shop price; crafted = Σ inputs ×
  markup) — Codegen-World writes it into world.json (``items[*].value``);
* checks the static targets (crop ROI, loot value per kill by tier, no dead materials) — Codegen-World gate
  ``economy_design``;
* replays a recorded vertical-slice run (kill sequence, stage ticks, quest XP) with many loot seeds
  (Python twin of world/loot.gd) to check the reliability targets and the XP pacing — `forge accept F6`.

Pure Python, CPU only, deterministic.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import yaml

DESIGN_REL = "content/world/economy_design.yaml"


def load_design(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / DESIGN_REL).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- values

def item_values(world: dict[str, Any], design: dict[str, Any]) -> dict[str, float]:
    base = {k: float(v) for k, v in design["base_value"].items()}
    val: dict[str, float] = {"coin": 1.0, **base}
    for k, price in world["shop"].items():
        val.setdefault(k, float(price))
    for k, it in world["items"].items():   # seeds the shop does not sell: worth their crop's share
        if it["kind"] == "seed" and k not in val:
            crop = world["crops"][it["crop"]]
            val[k] = round(base.get(crop["id"], 0.0) * int(crop["yield"]) / 2.0, 2)
    mk = float(design.get("craft_markup", 1.0))
    for _ in range(4):   # recipes may chain
        for r in world["recipes"].values():
            if all(i in val for i in r["in"]):
                v = sum(val[i] * q for i, q in r["in"].items()) * mk
                for o, q in r["out"].items():
                    val[o] = round(v / q, 2)
    return {k: val[k] for k in sorted(val)}


def loot_value_per_kill(world: dict[str, Any], values: dict[str, float], roster_enemies: dict[str, Any]) -> dict[str, float]:
    from forge.world import loot_ev

    ev = loot_ev(world)
    out: dict[str, float] = {}
    for tier, d in ev.items():
        v = sum(values.get(i, 0.0) * q for i, q in d.items())
        refs = [r for r, e in roster_enemies.items() if str(e.get("tier")) == tier]
        extras = []
        for r in refs:   # per-enemy extras, averaged over the tier's enemies
            t = world["loot"]["enemies"].get(r)
            if not t:
                extras.append(0.0)
                continue
            tot = sum(float(e["weight"]) for e in t["table"])
            extras.append(sum(values.get(e["item"], 0.0) * float(e["weight"]) / tot * (e["qty"][0] + e["qty"][1]) / 2
                              for e in t["table"] if e["item"] != "none"))
        out[tier] = round(v + (sum(extras) / len(extras) if extras else 0.0), 2)
    return out


def material_sinks(world: dict[str, Any]) -> dict[str, list[str]]:
    """Every material → what consumes it (recipe inputs, quest `have:` guards). Seeds are planted, crops eaten."""
    sinks: dict[str, list[str]] = {k: [] for k, it in world["items"].items() if it["kind"] == "material"}
    for r in world["recipes"].values():
        for i in r["in"]:
            if i in sinks:
                sinks[i].append(f"recipe:{r['id']}")
    for q in world["quests"]:
        for st in q["stages"]:
            for part in (st.get("guard") or "").split("&"):
                if part.startswith("have:"):
                    name = part[5:].partition(">=")[0]
                    if name in sinks:
                        sinks[name].append(f"quest:{q['id']}.{st['id']}")
    return sinks


def static_report(world: dict[str, Any], design: dict[str, Any], roster_enemies: dict[str, Any]) -> dict[str, Any]:
    t = design["targets"]
    values = item_values(world, design)
    missing_value = sorted(k for k in world["items"] if k not in values)
    lo, hi = (float(x) for x in t["crop_roi"])
    roi = {}
    for c in world["crops"].values():
        price = float(world["shop"].get(c["seed"], 0)) or values.get(c["seed"], 0.0)
        roi[c["id"]] = round(int(c["yield"]) * values.get(c["id"], 0.0) / price, 3) if price else None
    lvk = loot_value_per_kill(world, values, roster_enemies)
    sinks = material_sinks(world)
    checks = {
        "every_item_valued": not missing_value,
        "crop_roi_in_band": all(r is not None and lo <= r <= hi for r in roi.values()),
        "loot_value_per_kill_in_band": all(tier in lvk and float(b[0]) <= lvk[tier] <= float(b[1])
                                           for tier, b in t["loot_value_per_kill"].items()),
        "no_dead_materials": (not t.get("no_dead_materials")) or all(sinks.values()),
        "crafted_worth_more_than_inputs": all(
            values.get(o, 0) * q >= sum(values.get(i, 0) * n for i, n in r["in"].items()) - 1e-9
            for r in world["recipes"].values() for o, q in r["out"].items()),
    }
    return {"ok": all(checks.values()), "checks": checks, "values": values, "crop_roi": roi,
            "loot_value_per_kill": lvk, "sinks": sinks, "missing_value": missing_value}


# ----------------------------------------------------------------------------- slice replay (Monte Carlo)

def _level_for(xp: int, table: list[int]) -> int:
    lv = 1
    for i, v in enumerate(table):
        if xp >= int(v):
            lv = i + 1
    return lv


def xp_timeline(world: dict[str, Any], s: dict[str, Any]) -> list[tuple[int, int]]:
    """[(tick, cumulative xp)] of one base fighter: start level + kill XP (per_tier × tier) + quest XP rewards."""
    x = world["xp"]
    xp = int(x["level_at"][int(x.get("start_level", 1)) - 1])
    ev: list[tuple[int, int]] = [(int(d[3]), int(x["per_tier"]) * max(1, int(d[1]))) for d in s["loot"]["drops"]]
    stages = {f"{q['id']}.{st['id']}": int(st.get("reward", {}).get("xp", 0)) for q in world["quests"] for st in q["stages"]}
    ev += [(int(tk), stages.get(k, 0)) for k, tk in s.get("stage_ticks", {}).items() if stages.get(k, 0)]
    out = [(0, xp)]
    for tk, n in sorted(ev):
        xp += n
        out.append((tk, xp))
    return out


def level_at(world: dict[str, Any], tl: list[tuple[int, int]], tick: int) -> int:
    xp = max((v for tk, v in tl if tk <= tick), default=tl[0][1])
    return _level_for(xp, world["xp"]["level_at"])


def slice_report(world: dict[str, Any], design: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    from forge.world import Lcg, roll_loot

    t = design["targets"]
    st = s.get("stage_ticks", {})
    drops = s.get("loot", {}).get("drops", [])
    if not drops or len(drops[0]) < 4 or "q_warden.craft" not in st:
        return {"ok": False, "error": "slice report has no kill ticks / stages"}
    boss_prep = int(st.get("q_warden.second_harvest", st["q_warden.craft"]))   # boss prep starts here
    end = int(s.get("ticks", 0))
    edge = world["recipes"]["flint_edge"]["in"]
    charm = world["recipes"]["warden_charm"]["in"]
    n = int(t.get("mc_seeds", 1000))
    ok_edge = ok_charm = 0
    coin_end: list[int] = []
    # deterministic coin (start kit + quest coin rewards) − seeds bought (the bot's purchases, as played)
    det_coin = int(world["start_kit"].get("coin", 0)) + sum(
        int(stg.get("reward", {}).get("coin", 0)) for q in world["quests"] for stg in q["stages"] if f"{q['id']}.{stg['id']}" in st)
    spent = sum(int(world["shop"].get(b, 0)) for b in s.get("bought", [])) if s.get("bought") else 0
    for k in range(n):
        rng = Lcg(77_000 + k)
        bag: dict[str, int] = {}
        shard_at_prep = hide_end = 0
        for ref, tier, _, tick in drops:
            for item, q in roll_loot(world, int(tier), str(ref), rng):
                bag[item] = bag.get(item, 0) + int(q)
            if int(tick) <= boss_prep:
                shard_at_prep = bag.get("ember_shard", 0)
        hide_end = bag.get("brute_hide", 0)
        ok_edge += shard_at_prep >= int(edge.get("ember_shard", 0))
        ok_charm += hide_end >= int(charm.get("brute_hide", 0))
        coin_end.append(det_coin - spent + bag.get("coin", 0))
    tl = xp_timeline(world, s)
    boss_start = next((int(f["start"]) for f in s.get("fights", []) if f.get("boss")), None)
    levels = {}
    for key, band in t.get("level_at_stage", {}).items():
        tick = boss_start if key == "boss_start" else st.get(key)
        lv = level_at(world, tl, int(tick)) if tick is not None else None
        levels[key] = {"level": lv, "band": band, "ok": lv is not None and int(band[0]) <= lv <= int(band[1])}
    # twin parity: the level-ups this timeline predicts == the ones the game logged (leader)
    leader = (s.get("selection") or {}).get("leader")
    game_ups = [[lv, tk] for f, lv, tk in s.get("level_ups", []) if f == leader]
    twin_ups, prev = [], level_at(world, tl, 0)
    for tk, _ in tl:
        lv = level_at(world, tl, tk)
        if lv > prev:
            twin_ups.append([lv, tk])
            prev = lv
    p_edge, p_charm = ok_edge / n, ok_charm / n
    c50 = statistics.median(coin_end)
    cq = sorted(coin_end)
    checks = {
        "p_flint_edge_before_boss": p_edge >= float(t["p_flint_edge_before_boss"]),
        "p_warden_charm_by_end": p_charm >= float(t["p_warden_charm_by_end"]),
        "coin_end_p50_in_band": float(t["coin_end_p50"][0]) <= c50 <= float(t["coin_end_p50"][1]),
        "xp_pacing": all(v["ok"] for v in levels.values()),
        "xp_twin_matches_game": twin_ups == game_ups,
    }
    return {"ok": all(checks.values()), "checks": checks, "mc_seeds": n, "kills": len(drops),
            "p_flint_edge_before_boss": round(p_edge, 4), "p_warden_charm_by_end": round(p_charm, 4),
            "coin_end": {"p5": cq[int(0.05 * n)], "p50": c50, "p95": cq[int(0.95 * n) - 1]},
            "levels": levels, "level_ups": twin_ups, "xp_end": tl[-1][1], "end_tick": end}
