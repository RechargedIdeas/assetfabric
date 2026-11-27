"""Monte Carlo balance runner + Bayesian tuning (F5, GAME_SPEC §6.2 G-BAL-01).

A *matchup* is a character-select choice: leader ∈ the 4 base fighters × starter pet ∈ the
3 starters (12 matchups, GAME_SPEC §6.1 step 1). The other three base fighters follow without
pets [INFERENCE F5-1]. Every matchup fights the same encounter (default: the F5 boss) with the
**same seed list** (common random numbers), so differences between matchups come from the
choice, not the dice. Each seed varies damage rolls (±variance) and hostile spawn cells.

G-BAL-01 (F6+): ≥ 1000 encounters, every character-select **combination** (leader × starter pet,
12 cells) within 5 pp of the mean, every **choice** marginal within 5 pp too, mean win-rate inside
the target band, zero soft-locks/timeouts [INFERENCE F5-2 band, F5-8 deviation level, updated in
F6]. F5 gated only the choice marginals (per-combination spread was 12.7 pp); F6 added
pet↔character affinity (GAME_SPEC §4.2) fitted on separate seeds, bringing the per-combination
spread under 5 pp on the gate seeds. Note the statistical floor: at 200 seeds/cell the per-cell
standard error is ≈ 3.2 pp, so the expected max |deviation| of 12 perfectly balanced cells is
≈ 5–6 pp on *fresh* seeds; the gate runs on a fixed seed list (CRN, deterministic) and the
fresh-seed hold-out is reported in docs/acceptance-tests/F6.md [INFERENCE F6-2].

Work is sharded over N headless Godot processes (`--scene=balance`), CPU only.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge.paths import find_repo_root

DEV_LIMIT = 0.05
TARGET_BAND = (0.55, 0.90)
TARGET_MEAN = 0.72
DEFAULT_ENCOUNTER = "boss_warden"
GAME_DATA_REL = "games/game-zero/data/generated/game_data.json"


@dataclass
class BalanceConfig:
    encounter: str = DEFAULT_ENCOUNTER
    seeds: int = 200                   # 200 × 12 matchups = 2400 encounters (≥ 1000; tighter CIs)
    seed_base: int = 1000
    variance: float = 0.20               # ± damage roll [INFERENCE F5-3]
    crit: float = 0.10                   # ×1.5 crit chance [INFERENCE F5-3]
    level: int = 3
    workers: int = 0                   # 0 → os.cpu_count()
    overrides: list[dict[str, Any]] = field(default_factory=list)


def game_data(root: Path) -> dict[str, Any]:
    return json.loads((root / GAME_DATA_REL).read_text(encoding="utf-8"))


def matchups(data: dict[str, Any]) -> list[tuple[str, str]]:
    fighters = sorted(k for k, v in data["fighters"].items() if v.get("base"))
    pets = sorted(k for k, v in data["pets"].items() if v.get("starter"))
    return [(f, p) for f in fighters for p in pets]


def _party(data: dict[str, Any], leader: str, pet: str, level: int) -> list[dict[str, Any]]:
    fighters = sorted(k for k, v in data["fighters"].items() if v.get("base"))
    return [{"ref": f, "level": level, **({"leader": True, "pets": [pet]} if f == leader else {})} for f in fighters]


def build_jobs(cfg: BalanceConfig, data: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = []
    for leader, pet in matchups(data):
        for i in range(cfg.seeds):
            jobs.append({"id": f"{leader}+{pet}", "seed": cfg.seed_base + i, "party": _party(data, leader, pet, cfg.level),
                         "overrides": cfg.overrides})
    return jobs


def _godot(root: Path) -> list[str]:
    from forge.manifest import load_manifest
    from forge.milestones import godot_binary

    gb = godot_binary(root)
    if not gb:
        raise FileNotFoundError("Godot binary not found (GODOT_BIN, PATH, or godot-bin/godot)")
    return [gb, "--headless", "--path", str(root / load_manifest(None, root).game.project_path)]


def _run_shard(argv: list[str], spec: dict[str, Any], tmp: Path, k: int) -> tuple[list[dict[str, Any]], str]:
    path = tmp / f"shard_{k}.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    proc = subprocess.run(argv + ["--", "--scene=balance", f"--jobs={path}", "--no-live"],
                          capture_output=True, text=True, timeout=3600)
    rows = [json.loads(line[len("BALANCE_RESULT "):]) for line in proc.stdout.splitlines() if line.startswith("BALANCE_RESULT ")]
    err = "" if proc.returncode == 0 and len(rows) == len(spec["jobs"]) else (proc.stderr[-800:] or f"rc={proc.returncode}")
    return rows, err


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r)
    per = {}
    for mid, rs in sorted(by.items()):
        wins = sum(r["outcome"] == "victory" for r in rs)
        per[mid] = {"n": len(rs), "wins": wins, "win_rate": round(wins / len(rs), 4), "ci95": wilson(wins, len(rs)),
                    "avg_ticks": round(sum(r["ticks"] for r in rs) / len(rs), 1),
                    "boss_phase3_rate": round(sum(r.get("boss_phase", 0) >= 3 for r in rs) / len(rs), 4)}
    rates = [m["win_rate"] for m in per.values()]
    mean = sum(rates) / len(rates) if rates else 0.0
    dev = max((abs(r - mean) for r in rates), default=1.0)
    marg: dict[str, dict[str, float]] = {"leader": {}, "pet": {}}
    for mid, m in per.items():
        f, p = mid.split("+")
        marg["leader"].setdefault(f, []).append(m["win_rate"])   # type: ignore[arg-type]
        marg["pet"].setdefault(p, []).append(m["win_rate"])      # type: ignore[arg-type]
    marg = {k: {kk: round(sum(v) / len(v), 4) for kk, v in d.items()} for k, d in marg.items()}
    choice_dev = max((abs(v - mean) for d in marg.values() for v in d.values()), default=1.0)
    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {"encounters": len(rows), "matchups": per, "mean_win_rate": round(mean, 4), "max_deviation": round(dev, 4),
            "choice_deviation": round(choice_dev, 4), "combo_deviation": round(dev, 4),
            "marginals": marg, "outcomes": outcomes, "softlocks": outcomes.get("softlock", 0) + outcomes.get("timeout", 0)}


def verdict(agg: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "encounters_ge_1000": agg["encounters"] >= 1000,
        "max_choice_deviation_lt_5pp": agg["choice_deviation"] < DEV_LIMIT,
        "max_combo_deviation_lt_5pp": agg["combo_deviation"] < DEV_LIMIT,     # F6: per-pair is gated
        "mean_in_target_band": TARGET_BAND[0] <= agg["mean_win_rate"] <= TARGET_BAND[1],
        "no_softlocks": agg["softlocks"] == 0,
    }
    soft: dict[str, bool] = {}     # F5 reported combo spread here; gated since F6
    return {"G-BAL-01": all(checks.values()), "checks": checks, "soft": soft, "dev_limit": DEV_LIMIT,
            "target_band": list(TARGET_BAND)}


def run(cfg: BalanceConfig, root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    data = game_data(root)
    from forge.live import validate_patch

    bad = [e for e in (validate_patch(data, p) for p in cfg.overrides) if e]
    if bad:   # balance knobs obey the same limits as live tuning
        raise ValueError("; ".join(bad))
    jobs = build_jobs(cfg, data)
    workers = max(1, cfg.workers or os.cpu_count() or 1)
    shards = [jobs[i::workers] for i in range(workers)]
    argv = _godot(root)
    t0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="fabric-balance-") as tmp, ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(_run_shard, argv, {"encounter": cfg.encounter, "variance": cfg.variance, "crit": cfg.crit, "jobs": s}, Path(tmp), k)
                for k, s in enumerate(shards) if s]
        for f in futs:
            rs, err = f.result()
            rows += rs
            if err:
                errors.append(err)
    agg = aggregate(rows)
    agg.update({"wall_s": round(time.perf_counter() - t0, 2), "workers": workers, "errors": errors,
                "config": {"encounter": cfg.encounter, "seeds": cfg.seeds, "seed_base": cfg.seed_base,
                           "variance": cfg.variance, "crit": cfg.crit, "level": cfg.level, "overrides": cfg.overrides},
                "verdict": verdict(agg)})
    return agg


# ----------------------------------------------------------------------------- Bayesian tuning

TUNE_SPACE = {   # knob path → (low, high); every path must be live-tunable (content/tune/limits.yaml)
    # boss (tier-scaled values = roster base × 3.2)
    "enemies.cave_warden.stats.hp": (255.0, 295.0),
    "enemies.cave_warden.stats.atk": (13.0, 15.0),
    # starter pets — after the F5 rally fix the leader choice is near-neutral; the pet choice is
    # what separates matchups (pet bonuses go to the leader + an ally share to the party)
    "pets.ember_fox.bonus.atk_pct": (0.10, 0.30),
    "pets.stone_tortle.bonus.def_flat": (1.0, 3.0),
    "pets.lumen_wisp.bonus.hp_pct": (0.10, 0.30),
}
# F6: per-pair knobs (pet↔character affinity, 12 cells). Each cell only depends on its own knob in
# the balance matrix (only the leader carries the starter pet), so `forge balance` fits are decoupled.
AFFINITY_SPACE = {f"pets.{p}.affinity.{f}": (0.0, 3.0) for p in ("ember_fox", "lumen_wisp", "stone_tortle")
                  for f in ("bram", "kael", "nyra", "sola")}


def objective(agg: dict[str, Any]) -> float:
    """Lower is better: spread across matchups + distance of the mean from the target."""
    return (agg["choice_deviation"] + 0.25 * agg["combo_deviation"] + 1.5 * abs(agg["mean_win_rate"] - TARGET_MEAN)
            + 0.05 * agg["softlocks"])


def tune(trials: int = 20, seeds: int = 24, root: Path | None = None, space: dict[str, tuple[float, float]] | None = None,
         sampler_seed: int = 7) -> dict[str, Any]:
    """Optuna TPE over TUNE_SPACE (CPU only). Returns the best overrides and the full study log.
    Use a *different* seed_base from the verification run so the result is not overfit to it."""
    try:
        import optuna
    except ImportError as exc:   # optional dependency (extra: tune)
        raise RuntimeError("optuna not installed: uv pip install -e '.[tune]'") from exc

    root = root or find_repo_root()
    space = space or TUNE_SPACE
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    log: list[dict[str, Any]] = []

    def f(trial: "optuna.Trial") -> float:
        ov = [{"path": k, "value": round(trial.suggest_float(k, lo, hi), 3)} for k, (lo, hi) in space.items()]
        agg = run(BalanceConfig(seeds=seeds, seed_base=50_000, overrides=ov), root)
        score = objective(agg)
        log.append({"trial": trial.number, "overrides": ov, "mean": agg["mean_win_rate"], "choice_dev": agg["choice_deviation"], "combo_dev": agg["combo_deviation"],
                    "softlocks": agg["softlocks"], "score": round(score, 4)})
        return score

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=sampler_seed))
    study.optimize(f, n_trials=trials)
    best = [{"path": k, "value": round(v, 3)} for k, v in study.best_params.items()]
    return {"best_overrides": best, "best_score": round(study.best_value, 4), "trials": log, "seeds_per_matchup": seeds,
            "sampler": f"TPE(seed={sampler_seed})", "optuna": optuna.__version__}


# ----------------------------------------------------------------------------- Q5: hold-out gate + per-cell study

HOLDOUT_SEED_BASE = 20_000    # never used for fitting (fits use 50_000+; the CRN gate uses 1000). 9000 was the first
                              # hold-out; it was spent calibrating three cells in 0.7.13, so the gate moved to fresh seeds [C-94]
HOLDOUT_SEEDS = 1000          # per cell: SE ≈ 1.4 pp, so a 3.5 pp spread limit is above the noise floor [C-94]
HOLDOUT_LIMIT = 0.035


def holdout(root: Path | None = None, seeds: int = HOLDOUT_SEEDS, seed_base: int = HOLDOUT_SEED_BASE) -> dict[str, Any]:
    """Out-of-sample per-pair spread: every leader × pet cell on seeds no fit has seen."""
    agg = run(BalanceConfig(seeds=seeds, seed_base=seed_base), root)
    agg["holdout"] = {"seed_base": seed_base, "seeds_per_cell": seeds, "limit": HOLDOUT_LIMIT,
                      "combo_deviation": agg["combo_deviation"], "ok": agg["combo_deviation"] <= HOLDOUT_LIMIT
                      and agg["softlocks"] == 0 and not agg["errors"]}
    return agg


def tune_affinity(trials: int = 30, seeds: int = 240, root: Path | None = None, sampler_seed: int = 11,
                  seed_base: int = 50_000, warm: dict[str, float] | None = None) -> dict[str, Any]:
    """Twelve independent Optuna TPE studies, one per leader × pet cell, sharing each balance run.

    In the balance matrix only the leader carries the starter pet, so cell (f, p) depends only on the knob
    ``pets.<p>.affinity.<f>`` — every run evaluates all 12 knobs at once and each study is told its own cell's
    loss |win_rate − TARGET_MEAN|. Trial 0 of every study is the current shipped value (``warm``)."""
    try:
        import optuna
    except ImportError as exc:
        raise RuntimeError("optuna not installed: uv pip install -e '.[tune]'") from exc

    root = root or find_repo_root()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    data = game_data(root)
    cells = {k: (k.split(".")[3], k.split(".")[1]) for k in AFFINITY_SPACE}   # path → (fighter, pet)
    studies = {k: optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=sampler_seed + i))
               for i, k in enumerate(sorted(cells))}
    warm = warm or {k: float(data["pets"][p].get("affinity", {}).get(f, 1.0)) for k, (f, p) in cells.items()}
    for k, st in studies.items():
        st.enqueue_trial({"v": warm[k]})
    log: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for n in range(trials):
        asked = {k: st.ask() for k, st in studies.items()}
        ov = [{"path": k, "value": round(tr.suggest_float("v", *AFFINITY_SPACE[k]), 3)} for k, tr in asked.items()]
        agg = run(BalanceConfig(seeds=seeds, seed_base=seed_base + 1000 * n, overrides=ov), root)
        row = {"trial": n, "seed_base": seed_base + 1000 * n, "mean": agg["mean_win_rate"], "combo_dev": agg["combo_deviation"],
               "cells": {}}
        for k, tr in asked.items():
            f, p = cells[k]
            wr = agg["matchups"][f"{f}+{p}"]["win_rate"]
            loss = abs(wr - TARGET_MEAN)
            studies[k].tell(tr, loss)
            row["cells"][k] = {"value": round(tr.params["v"], 3), "win_rate": wr, "loss": round(loss, 4)}
        log.append(row)
    best = []
    for k, st in studies.items():
        # Pick: one trial is noisy (SE ≈ 2.6 pp at 300 seeds), so pool every trial of this cell: least-squares line
        # win_rate ~ a + b·value over the trials near the target (|wr − target| < 8 pp; all trials if < 4), solved for
        # the target and clipped to the space. Falls back to the TPE best if the slope is not positive.
        pts = [(r["cells"][k]["value"], r["cells"][k]["win_rate"]) for r in log]
        near = [q for q in pts if abs(q[1] - TARGET_MEAN) < 0.08]
        use = near if len(near) >= 4 else pts
        n_ = len(use)
        mx, my = sum(x for x, _ in use) / n_, sum(y for _, y in use) / n_
        sxx = sum((x - mx) ** 2 for x, _ in use)
        slope = sum((x - mx) * (y - my) for x, y in use) / sxx if sxx > 1e-12 else 0.0
        lo, hi = AFFINITY_SPACE[k]
        tpe_best = st.best_params["v"]
        val = min(hi, max(lo, mx + (TARGET_MEAN - my) / slope)) if slope > 1e-6 else tpe_best
        best.append({"path": k, "value": round(val, 3), "fit": {"points": n_, "slope_per_unit": round(slope, 4),
                     "intercept": round(my - slope * mx, 4), "tpe_best": round(tpe_best, 3), "tpe_best_loss": round(st.best_value, 4)}})
    return {"best_overrides": best, "trials": log, "trials_n": trials, "seeds_per_cell_per_trial": seeds,
            "fights": trials * seeds * len(cells), "wall_s": round(time.perf_counter() - t0, 1),
            "sampler": f"12× TPE(seed={sampler_seed}+i), ask/tell on shared runs", "objective": "|cell win rate − 0.72|",
            "optuna": optuna.__version__, "warm_start": warm}
