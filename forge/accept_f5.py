"""F5 acceptance: "first boss + balance" (SPEC §13, GAME_SPEC §5 "≥1 tier-3 boss proven by balance runner").

1. Boss clear — headless BT + policy party vs. the tier-3 Cave Warden (3 phases, summons, enrage)
   in its G1-Tile boss arena; victory writes the Player State save.
2. Save round-trip — a second save (creates `.bak`), a *new* process loads + validates it; a torn
   primary falls back to the backup; v1/v2 fixtures migrate identically in GDScript and Python.
3. G-BAL-01 — Monte Carlo: 12 character-select matchups × 200 seeds (CRN) = 2400 boss fights.
4. Soft-lock — static report ok; zero runtime soft-locks in (3); a mis-tuned probe run *is* flagged.
5. Hold-out (Q5, full mode) — the 12 leader × pet cells on 1000 unseen seeds each (seed_base 9000): per-pair spread
   ≤ 3.5 pp (INFERENCE C-94). FAST mode (pytest/CI) records it as skipped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from forge.accept_f4 import _godot_argv


def _godot_result(root: Path, *args: str, timeout: int = 300) -> tuple[int, dict[str, Any]]:
    from forge.milestones import parse_output

    proc = subprocess.run(_godot_argv(root, *args), capture_output=True, text=True, timeout=timeout)
    return proc.returncode, parse_output(proc.stdout + proc.stderr)


def f5_run(root: Path) -> tuple[int, dict[str, Any]]:
    from forge.balance import BalanceConfig, run
    from forge.save import FIXTURES, canonical_json, migrate, validate
    from forge.softlock import stall_probe_overrides, static_report
    import hashlib

    tmp = Path(tempfile.mkdtemp(prefix="fabric-f5-"))
    try:
        saves = tmp / "saves"
        code, result = _godot_result(root, "--scene=boss", "--autoplay", "--no-live", f"--save-dir={saves}")
        first = result.get("save", {})
        # second clear → slot0 rewritten, previous kept as .bak
        code2, r2 = _godot_result(root, "--scene=boss", "--autoplay", "--no-live", f"--save-dir={saves}")
        second = r2.get("save", {})
        fx = tmp / "fixtures.json"
        fx.write_text(json.dumps(FIXTURES), encoding="utf-8")
        _, chk = _godot_result(root, "--scene=savecheck", f"--save-dir={saves}", f"--fixtures={fx}")
        sc = chk.get("savecheck", {})
        # torn primary → backup
        (saves / "slot0.json").write_text('{"format": "gamezero-save", "version": 3, "profile": {', encoding="utf-8")
        _, chk2 = _godot_result(root, "--scene=savecheck", f"--save-dir={saves}")
        sc2 = chk2.get("savecheck", {})
        parity = {}
        for name, f in FIXTURES.items():
            py, steps = migrate(f)
            g = sc.get("migrated", {}).get(name, {})
            parity[name] = {"steps_py": steps, "steps_gd": g.get("steps"), "gd_errors": g.get("errors"),
                            "canonical_equal": hashlib.sha256(canonical_json(py).encode()).hexdigest() == g.get("canonical_sha"),
                            "checksum_equal": py["checksum"] == (g.get("save") or {}).get("checksum")}
        result["save_roundtrip"] = {
            "first_checksum": first.get("checksum"), "second_checksum": second.get("checksum"),
            "loaded_equal_second": sc.get("loaded") == second.get("state") or
                canonical_json(sc.get("loaded", {})) == canonical_json(second.get("state", {})),
            "python_validates_godot_save": validate(sc.get("loaded", {})) == [],
            "last_load": sc.get("last_load"),
            "torn_primary": {"last_load": sc2.get("last_load"),
                             "loaded_equal_first": canonical_json(sc2.get("loaded", {})) == canonical_json(first.get("state", {}))},
            "migration_parity": parity,
        }
        result["boss_clear_2"] = {"outcome": r2.get("outcome"), "ticks": r2.get("ticks")}
        result["softlock_static"] = {k: v for k, v in static_report(root).items() if k != "chart_details"}
        bal = run(BalanceConfig(), root)
        result["balance"] = {k: v for k, v in bal.items() if k != "config"} | {"config": bal["config"]}
        # Q5 (C-94): out-of-sample per-pair spread on unseen seeds (full mode; 12 000 fights ≈ 4 min on 8 vCPU)
        from forge.accept_f6 import fast_mode
        from forge.balance import holdout

        if fast_mode():
            result["holdout"] = {"mode": "fast", "skipped": "FORGE_ACCEPT_FAST=1 (pytest/CI): run `forge accept F5` for the gate"}
        else:
            ho = holdout(root)
            result["holdout"] = ho["holdout"] | {"mode": "full", "mean_win_rate": ho["mean_win_rate"], "wall_s": ho["wall_s"],
                                                 "win_rates": {k: v["win_rate"] for k, v in ho["matchups"].items()},
                                                 "marginals": ho["marginals"], "softlocks": ho["softlocks"], "errors": ho["errors"]}
        probe = run(BalanceConfig(seeds=2, overrides=stall_probe_overrides(root)), root)
        result["softlock_probe"] = {"encounters": probe["encounters"], "softlocks": probe["softlocks"], "outcomes": probe["outcomes"]}
        return (code or code2), result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def f5_check(r: dict[str, Any]) -> list[str]:
    from forge.milestones import _need

    errs: list[str] = []
    _need(r.get("outcome") == "victory", f"boss fight outcome={r.get('outcome')}", errs)
    boss = r.get("boss", {})
    _need(boss.get("tier") == 3 and boss.get("defeated") is True, f"tier-3 boss not defeated: {boss}", errs)
    _need(boss.get("phases_reached", 0) >= 3, f"boss phases reached={boss.get('phases_reached')}", errs)
    _need(boss.get("summons", 0) >= 1, "boss never summoned adds", errs)
    _need(bool(r.get("music_loaded")) and r.get("music_stem") == "boss", "boss music stem not loaded", errs)
    sr = r.get("save_roundtrip", {})
    _need(bool(sr.get("first_checksum")) and bool(sr.get("second_checksum")), "save not written on victory", errs)
    _need(sr.get("loaded_equal_second") is True, "new process did not load the exact saved state", errs)
    _need(sr.get("python_validates_godot_save") is True, "forge/save.py rejects the Godot save", errs)
    _need((sr.get("torn_primary", {}).get("last_load") or {}).get("recovered_from_backup") is True
          and sr.get("torn_primary", {}).get("loaded_equal_first") is True, f"torn save not recovered: {sr.get('torn_primary')}", errs)
    for name, p in sr.get("migration_parity", {}).items():
        _need(p["steps_py"] == p["steps_gd"] and p["canonical_equal"] and p["checksum_equal"] and not p["gd_errors"],
              f"migration parity {name}: {p}", errs)
    _need(r.get("softlock_static", {}).get("ok") is True, f"static soft-lock report: {r.get('softlock_static')}", errs)
    bal = r.get("balance", {})
    v = bal.get("verdict", {})
    _need(v.get("G-BAL-01") is True, f"G-BAL-01 failed: {v.get('checks')} mean={bal.get('mean_win_rate')} "
          f"choice_dev={bal.get('choice_deviation')} combo_dev={bal.get('combo_deviation')} n={bal.get('encounters')}", errs)
    _need(not bal.get("errors"), f"balance worker errors: {bal.get('errors')}", errs)
    ho = r.get("holdout", {})
    _need(ho.get("mode") == "fast" or ho.get("ok") is True,
          f"per-pair hold-out spread {ho.get('combo_deviation')} > {ho.get('limit')} on unseen seeds (seed_base {ho.get('seed_base')})", errs)
    _need(r.get("softlock_probe", {}).get("softlocks", 0) > 0, "soft-lock detector never fired on the mis-tuned probe", errs)
    return errs


def f5_perf(r: dict[str, Any]) -> dict[str, Any]:
    bal = r.get("balance", {})
    n = bal.get("encounters", 0) or 1
    return {"balance_wall_s": bal.get("wall_s"), "balance_workers": bal.get("workers"),
            "holdout_wall_s": r.get("holdout", {}).get("wall_s"), "holdout_combo_deviation": r.get("holdout", {}).get("combo_deviation"),
            "ms_per_encounter_per_worker": round(1000 * bal.get("wall_s", 0) * bal.get("workers", 1) / n, 1),
            "boss_ticks": r.get("ticks"), "boss_sim_ms": r.get("sim_ms")}
