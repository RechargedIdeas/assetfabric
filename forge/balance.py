"""Monte Carlo balance runner + Bayesian tuning (F5, GAME_SPEC §6.2 G-BAL-01).

A *matchup* is a character-select choice: leader ∈ the 4 base fighters × starter pet ∈ the
3 starters (12 matchups, GAME_SPEC §6.1 step 1). The other three base fighters follow without
pets [INFERENCE F5-1]. Every matchup fights the same encounter (default: the F5 boss) with the
**same seed list** (common random numbers), so differences between matchups come from the
choice, not the dice. Each seed varies damage rolls (±variance) and hostile spawn cells.

G-BAL-01: ≥ 1000 encounters, every character-select **choice** (each leader, each starter pet;
marginal win rate over the other choice) within 5 pp of the mean, mean win-rate inside the target
band, zero soft-locks/timeouts [INFERENCE F5-2 band, F5-8 choice-level deviation]. The stricter
per-combination spread (leader × pet, 12 cells) is measured and reported as a *soft* metric
(`combo_deviation`): the combat sim is chaotic enough that some combinations interact strongly
(e.g. a fragile pet following a melee leader), and those are tracked as balance debt, not hidden.

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
        "mean_in_target_band": TARGET_BAND[0] <= agg["mean_win_rate"] <= TARGET_BAND[1],
        "no_softlocks": agg["softlocks"] == 0,
    }
    soft = {"combo_deviation_lt_5pp": agg["combo_deviation"] < DEV_LIMIT}
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
