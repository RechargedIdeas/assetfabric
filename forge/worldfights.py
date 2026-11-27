"""World-fight Monte Carlo: wipe-rate and clear-time bands (P7, 0.7.15, INFERENCE C-98).

The F5 balance runner proves the Cave Warden in isolation (G-BAL-01). P7 extends it to every *world* fight of the
vertical slice: the slice records, for each fight, the state it started from (party levels + pet, item/buff bonuses,
HP carried from earlier fights, which packs were pulled, the tilemap — ``slice.gd::_fight_context``). This module
replays each recorded fight in the headless balance worker (``--scene=balance``, inline ``encounter_def`` + per-job
``patch``/``start_hp``) over many seeds and checks the bands in ``content/tune/worldfights.yaml``:

* wipe rate per fight class (trash / elite / boss) inside ``[min, max]`` for every selection,
* median engaged clear time (first landed hit → victory) inside ``[min, max]`` and p90 under a cap,
* whole-slice P(≥ 1 wipe) per selection under ``slice_wipe_any_max``,
* no soft-locks or timeouts.

Deterministic (fixed seed list, common random numbers across selections), CPU only, no LLM in the tick.
"""

from __future__ import annotations

import math
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from forge.balance import _godot, _run_shard, game_data, wilson
from forge.paths import find_repo_root

CONFIG_REL = "content/tune/worldfights.yaml"


def load_config(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    return yaml.safe_load((root / CONFIG_REL).read_text(encoding="utf-8"))


def _areas(world: dict[str, Any]) -> dict[str, Any]:
    a = world["areas"]
    return a if isinstance(a, dict) else {x["id"]: x for x in a}


def fight_units(fights: list[dict[str, Any]], world: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn one slice run's ``fights`` (with ``ctx``) into replayable units.

    World fights → their pulled packs. The lair records two fights (adds, then the Warden); the boss unit replays the
    whole ``boss_warden`` encounter from the state the party entered the lair with. A fight whose context is missing
    (older runs) is skipped."""
    areas = _areas(world)
    out: list[dict[str, Any]] = []
    boss_done = False
    for f in fights:
        ctx = f.get("ctx")
        if not ctx:
            continue
        base = {"party": ctx["party"], "bonus": ctx.get("bonus", {}), "start_hp": ctx.get("hp", {}), "tilemap": ctx["tilemap"]}
        if ctx.get("encounter"):
            if boss_done:
                continue
            boss_done = True
            out.append(base | {"key": f"{f['area']}.boss", "area": f["area"], "encounter": ctx["encounter"], "packs": []})
            continue
        packs = sorted(p for p in ctx.get("packs", []) if p >= 0)
        if not packs:
            continue
        defs = areas[f["area"]].get("packs", [])
        hostiles = [{"ref": u["ref"], "count": int(u.get("count", 1)), "spawn": int(defs[p]["spawn"])}
                    for p in packs for u in defs[p]["units"]]
        out.append(base | {"key": f"{f['area']}." + "+".join(f"p{p}" for p in packs), "area": f["area"], "packs": packs,
                           "hostiles": hostiles})
    return out


def classify(unit: dict[str, Any], data: dict[str, Any], cfg: dict[str, Any]) -> str:
    if unit.get("encounter"):
        return "boss"
    t2 = sum(int(h["count"]) for h in unit.get("hostiles", []) if int(data["enemies"][h["ref"]]["tier"]) >= 2)
    return "elite" if t2 >= int(cfg.get("elite_min_tier2", 2)) else "trash"


def build_shards(units_by_sel: dict[str, list[dict[str, Any]]], seeds: dict[str, int], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """One worker spec per encounter kind (world packs / boss); jobs carry the per-fight patch and carried HP."""
    world_jobs: list[dict[str, Any]] = []
    boss_jobs: list[dict[str, Any]] = []
    sb = int(cfg["seed_base"])
    for sel, units in sorted(units_by_sel.items()):
        for u in units:
            for i in range(int(seeds["boss" if u.get("encounter") else "world"])):
                job = {"id": f"{sel}|{u['key']}", "seed": sb + i, "party": u["party"], "start_hp": u["start_hp"],
                       "patch": {"bonus": u["bonus"], "tilemap": u["tilemap"], "tick_limit": int(cfg["tick_limit"])}}
                if u.get("encounter"):
                    boss_jobs.append(job)
                else:
                    job["patch"]["hostiles"] = u["hostiles"]
                    world_jobs.append(job)
    common = {"variance": float(cfg["variance"]), "crit": float(cfg["crit"])}
    specs = []
    if world_jobs:
        specs.append(common | {"encounter_def": {"id": "world_pack", "tilemap": "tunnels_01", "hostiles": [], "ai": "bt"},
                               "jobs": world_jobs})
    if boss_jobs:
        specs.append(common | {"encounter": "boss_warden", "jobs": boss_jobs})
    return specs


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))
    return s[k]


def aggregate(rows: list[dict[str, Any]], classes: dict[str, str], cfg: dict[str, Any]) -> dict[str, Any]:
    hz = float(cfg.get("tick_hz", 60))
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r)
    cells: dict[str, Any] = {}
    for jid, rs in sorted(by.items()):
        sel, key = jid.split("|")
        wins = [r for r in rs if r["outcome"] == "victory"]
        wipes = sum(r["outcome"] == "defeat" for r in rs)
        bad = sum(r["outcome"] in ("softlock", "timeout") for r in rs)
        clear = [(r["ticks"] - max(0, int(r.get("engage_tick", 0)))) / hz for r in wins]
        downs = sum(any("_" not in str(d[0]) for d in r.get("deaths", [])) for r in rs)   # ≥ 1 fighter downed (pets excluded)
        cells[jid] = {"selection": sel, "fight": key, "class": classes[key][0], "packs": classes[key][1], "n": len(rs), "wipes": wipes,
                      "down_rate": round(downs / len(rs), 4),
                      "wipe_rate": round(wipes / len(rs), 4), "wipe_ci95": wilson(wipes, len(rs)), "stalls": bad,
                      "clear_median_s": round(_pct(clear, 0.5), 2), "clear_p90_s": round(_pct(clear, 0.9), 2),
                      "party_hp_end": round(sum(r.get("party_hp_ratio", 0) for r in wins) / max(1, len(wins)), 3)}
    fights: dict[str, Any] = {}
    for c in cells.values():
        f = fights.setdefault(c["fight"], {"class": c["class"], "n": 0, "wipes": 0, "selections": 0, "down_rate_max": 0.0,
                                           "wipe_rate_range": [1.0, 0.0], "clear_median_range_s": [1e9, 0.0], "clear_p90_max_s": 0.0})
        f["n"] += c["n"]
        f["wipes"] += c["wipes"]
        f["selections"] += 1
        f["wipe_rate_range"] = [min(f["wipe_rate_range"][0], c["wipe_rate"]), max(f["wipe_rate_range"][1], c["wipe_rate"])]
        f["clear_median_range_s"] = [min(f["clear_median_range_s"][0], c["clear_median_s"]), max(f["clear_median_range_s"][1], c["clear_median_s"])]
        f["clear_p90_max_s"] = max(f["clear_p90_max_s"], c["clear_p90_s"])
        f["down_rate_max"] = max(f["down_rate_max"], c["down_rate"])
    for f in fights.values():
        f["wipe_rate"] = round(f["wipes"] / max(1, f["n"]), 4)
    per_sel: dict[str, Any] = {}
    for c in cells.values():
        s = per_sel.setdefault(c["selection"], {"p_no_wipe": 1.0, "fights": 0})
        s["p_no_wipe"] *= (1.0 - c["wipe_rate"])
        s["fights"] += 1
    for s in per_sel.values():
        s["p_any_wipe"] = round(1.0 - s.pop("p_no_wipe"), 4)
    by_class: dict[str, Any] = {}
    for c in cells.values():
        k = by_class.setdefault(c["class"], {"cells": 0, "fights": set(), "wipe_rate_range": [1.0, 0.0],
                                             "clear_median_range_s": [1e9, 0.0], "clear_p90_max_s": 0.0, "n": 0, "wipes": 0})
        k["cells"] += 1
        k["fights"].add(c["fight"])
        k["n"] += c["n"]
        k["wipes"] += c["wipes"]
        k["wipe_rate_range"] = [min(k["wipe_rate_range"][0], c["wipe_rate"]), max(k["wipe_rate_range"][1], c["wipe_rate"])]
        k["clear_median_range_s"] = [min(k["clear_median_range_s"][0], c["clear_median_s"]), max(k["clear_median_range_s"][1], c["clear_median_s"])]
        k["clear_p90_max_s"] = max(k["clear_p90_max_s"], c["clear_p90_s"])
    for k in by_class.values():
        k["fights"] = len(k["fights"])
        k["wipe_rate"] = round(k["wipes"] / max(1, k["n"]), 4)
    return {"cells": cells, "fights": fights, "classes": by_class, "selections": per_sel,
            "encounters": len(rows), "stalls": sum(c["stalls"] for c in cells.values())}


def verdict(agg: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    bands = cfg["bands"]
    out_of_band = []
    for jid, c in agg["cells"].items():
        b = bands[c["class"]]
        lo, hi = b["wipe_rate"]
        if not lo <= c["wipe_rate"] <= hi:
            out_of_band.append(f"{jid} wipe {c['wipe_rate']:.3f} ∉ [{lo}, {hi}]")
        clo, chi = b["clear_s"]
        k = int(c.get("packs", 1))              # bands are per pack; a pull of k packs may take k × the upper bound
        if not clo <= c["clear_median_s"] <= chi * k:
            out_of_band.append(f"{jid} clear median {c['clear_median_s']} s ∉ [{clo}, {chi * k}]")
        if c["clear_p90_s"] > float(b["clear_p90_max_s"]) * k:
            out_of_band.append(f"{jid} clear p90 {c['clear_p90_s']} s > {float(b['clear_p90_max_s']) * k}")
    slice_bad = [f"{s} P(any wipe) {v['p_any_wipe']} > {cfg['slice_wipe_any_max']}"
                 for s, v in agg["selections"].items() if v["p_any_wipe"] > float(cfg["slice_wipe_any_max"])]
    checks = {"every_cell_in_band": not out_of_band, "slice_wipe_any_ok": not slice_bad, "no_stalls": agg["stalls"] == 0,
              "has_boss": "boss" in agg["classes"], "has_world_fights": any(k in agg["classes"] for k in ("trash", "elite"))}
    return {"ok": all(checks.values()), "checks": checks, "out_of_band": (out_of_band + slice_bad)[:40],
            "out_of_band_count": len(out_of_band) + len(slice_bad)}


def run(units_by_sel: dict[str, list[dict[str, Any]]], seeds: dict[str, int], root: Path | None = None, workers: int = 0) -> dict[str, Any]:
    root = root or find_repo_root()
    cfg = load_config(root)
    data = game_data(root)
    classes = {u["key"]: (classify(u, data, cfg), max(1, len(u.get("packs", [])))) for us in units_by_sel.values() for u in us}
    specs = build_shards(units_by_sel, seeds, cfg)
    workers = max(1, workers or os.cpu_count() or 1)
    argv = _godot(root)
    t0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="fabric-worldfights-") as tmp, ThreadPoolExecutor(workers) as ex:
        futs = []
        k = 0
        for spec in specs:
            jobs = spec["jobs"]
            for w in range(workers):
                part = jobs[w::workers]
                if part:
                    futs.append(ex.submit(_run_shard, argv, spec | {"jobs": part}, Path(tmp), k))
                    k += 1
        for f in futs:
            rs, err = f.result()
            rows += rs
            if err:
                errors.append(err)
    agg = aggregate(rows, classes, cfg)
    agg.update({"wall_s": round(time.perf_counter() - t0, 2), "workers": workers, "errors": errors, "seeds": seeds,
                "seed_base": cfg["seed_base"], "bands": cfg["bands"], "slice_wipe_any_max": cfg["slice_wipe_any_max"]})
    agg["verdict"] = verdict(agg, cfg)
    if errors:
        agg["verdict"]["ok"] = False
    return agg


def summary(agg: dict[str, Any]) -> dict[str, Any]:
    """Compact record for results/F6.json (cells are kept only when out of band)."""
    v = agg.get("verdict", {})
    return {k: agg.get(k) for k in ("encounters", "seeds", "seed_base", "wall_s", "workers", "stalls", "bands",
                                    "slice_wipe_any_max", "classes", "fights", "selections", "errors")} | {"verdict": v}
