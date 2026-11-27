"""F6 acceptance: "vertical slice" (SPEC §13, GAME_SPEC §6.1).

One headless QA-autopilot playthrough of the whole slice (select → farm → tunnels → cave → farm →
craft → Cave Warden → open world → save) plus:

1. Save / quit / reload — the run quits right after a mid-slice checkpoint; a *new* process resumes
   from the save; the loaded state equals the saved one and the resumed run's final state is
   byte-identical (canonical JSON) to the uninterrupted run.
2. Selection matrix — every leader × starter pet (4 × 3 = 12) clears the slice (``FORGE_ACCEPT_FAST=1``:
   2 representative selections, used by pytest/CI).
3. Parity — Python twins replay the Godot quest trace (forge.world.QuestLog) and loot probe rolls
   (forge.world.roll_loot) exactly; save v1–v3 fixtures migrate to v4 identically.
5. World fights (P7, 0.7.15) — every fight each selection actually fought is replayed from its recorded start state
   over many seeds (forge/worldfights.py); wipe rate and engaged clear time must sit in the trash / elite / boss
   bands of content/tune/worldfights.yaml (INFERENCE C-98) for every selection × fight.
4. Static — Codegen-World gates (schema, cross-refs, quest-chart soft-lock analysis, economy
   solvability, loot tables, music rules) recorded in the registry; every locale key the slice uses exists.

Slice length (Q4, 0.7.12): GAME_SPEC §6.1 asks for 15–20 minutes. The QA bot plays at machine efficiency, so its
game time is a floor and is reported as-is. The *gate* is the human-pace estimate (forge/pace.py,
content/tune/pace.yaml, INFERENCE C-92) computed from what each run actually did: every one of the 12 selections
must land inside 15–20 min. It is a model, not a measurement; a human GUI playtest replaces it (F6.md).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from forge.accept_f4 import _godot_argv

LEADERS = ["kael", "nyra", "bram", "sola"]
PETS = ["ember_fox", "stone_tortle", "lumen_wisp"]
FAST_SELECTIONS = [("sola", "lumen_wisp"), ("bram", "stone_tortle")]
QUIT_AT = 5            # checkpoint 5 = back in the tunnels after clearing the deep cave (mid-slice; Q4 added the hollow)
PROBE = [("cave_mite", 1), ("emberling", 1), ("rock_brute", 2), ("cave_warden", 3), ("cave_mite", 1)]
TARGET_MIN = (15.0, 20.0)
TILEMAPS = ("field_01", "tunnels_01", "hollow_01", "cave_deep", "ridge_01")


def fast_mode() -> bool:
    return os.environ.get("FORGE_ACCEPT_FAST", "") not in ("", "0")


def _slice(root: Path, save_dir: Path, *extra: str, timeout: int = 300) -> tuple[int, dict[str, Any]]:
    from forge.milestones import parse_output

    args = ("--scene=slice", "--autoplay", "--no-live", f"--watchdog={timeout - 20}", f"--save-dir={save_dir}", *extra)
    proc = subprocess.run(_godot_argv(root, *args), capture_output=True, text=True, timeout=timeout)
    out = parse_output(proc.stdout + proc.stderr)
    out["_script_errors"] = len(re.findall(r"SCRIPT ERROR", proc.stdout + proc.stderr))
    return proc.returncode, out


def _summary(s: dict[str, Any]) -> dict[str, Any]:
    from forge.pace import estimate_for
    from forge.paths import find_repo_root

    est = estimate_for(find_repo_root(), s) if s.get("ticks") else {}
    return {"completed": s.get("completed"), "ticks": s.get("ticks"), "game_minutes": s.get("game_minutes"),
            "human_estimate_min": est.get("human_estimate_min"),
            "wipes": s.get("wipes"), "softlocks": len(s.get("softlocks", [])), "boss_attempt": (s.get("boss") or {}).get("attempt"),
            "boss_ticks": (s.get("boss") or {}).get("ticks"), "wall_ms": s.get("wall_ms")}


def w_variants(root: Path) -> list[str]:
    from forge.a11y import game_table
    from forge.patternvault import PatternVault

    return game_table(PatternVault(root))["variants"]


def locale_report(root: Path) -> dict[str, Any]:
    """Every literal ``tr("key")`` in the slice scripts + every dynamic id key exists in locale/en.json."""
    from forge.world import load_world

    game = root / "games" / "game-zero"
    loc = json.loads((game / "locale" / "en.json").read_text(encoding="utf-8"))
    used: set[str] = set()
    for f in ["scenes/slice.gd", "scenes/encounter.gd", "audio/music_director.gd", "world/world_state.gd",
              "ui/settings_menu.gd", "autoload/fabric.gd"]:
        p = game / f
        if p.exists():
            used |= {k for k in re.findall(r'(?:tr|hint)\("([a-z0-9_.]+)"\)', p.read_text(encoding="utf-8"))}
    # G-A11Y-01 (0.7.10): every action has a Settings label, every palette variant a name, every tactic a word
    fab = (game / "autoload" / "fabric.gd").read_text(encoding="utf-8")
    schema = fab[fab.index("const INPUT_SCHEMA"):fab.index("## Order of the rows")]
    used |= {f"input.{a}" for a in re.findall(r'^\t"([a-z0-9_]+)": \{', schema, re.M)}
    used |= {f"settings.palette.{v}" for v in w_variants(root)} | {"tactic.aggressive", "tactic.defensive", "input.pad.generic"}
    w = load_world(root)
    used |= {f"item.{i}" for i in w["items"]} | {f"area.{a}" for a in w["areas"]}
    for q in w["quests"]:
        used |= {f"quest.{q['id']}.title", f"quest.{q['id']}.done"} | {f"quest.{q['id']}.{s['id']}" for s in q["stages"]}
    gd = json.loads((game / "data" / "generated" / "game_data.json").read_text(encoding="utf-8"))
    fs, ps = gd.get("fighters", {}), gd.get("pets", {})
    used |= {f"roster.{k}" for k in fs} | {f"role.{f['role']}" for f in fs.values()}
    used |= {f"pet.{k}" for k in ps} | {f"pet.style.{p['style']}" for p in ps.values()}
    missing = sorted(k for k in used if k not in loc)
    actions = set(re.findall(r'^\t"([a-z0-9_]+)": \{', schema, re.M))
    bad_ph = sorted(f"{k}:{{{ph}}}" for k, v in loc.items() for ph in re.findall(r"\{([a-z0-9_]+)\}", str(v)) if ph not in actions)
    return {"ok": not missing and not bad_ph, "keys_checked": len(used), "missing": missing + bad_ph}


def f6_run(root: Path) -> tuple[int, dict[str, Any]]:
    from forge.save import FIXTURES, canonical_json, migrate, validate
    from forge.world import Lcg, QuestLog, load_world, roll_loot

    tmp = Path(tempfile.mkdtemp(prefix="fabric-f6-"))
    try:
        code, res = _slice(root, tmp / "a")
        s = res.get("slice", {})
        from forge.pace import estimate_for

        result: dict[str, Any] = {"slice": {k: v for k, v in s.items() if k not in ("final_state", "quest_trace")},
                                  "script_errors": res["_script_errors"],
                                  "pace": estimate_for(root, s) if s.get("ticks") else {}}
        # 1. save / quit / reload in a new process
        cq, rq = _slice(root, tmp / "b", f"--quit-after-checkpoint={QUIT_AT}")
        cr, rr = _slice(root, tmp / "b", "--resume")
        q, r = rq.get("slice_quit", {}), rr.get("slice", {})
        saved = q.get("state", {})
        result["save_quit_reload"] = {
            "quit_checkpoint": q.get("checkpoint"), "quit_tick": q.get("tick"), "quit_area": q.get("area"),
            "loaded_equal_saved": canonical_json(r.get("resumed_from", {}).get("state", {})) == canonical_json(saved),
            "python_validates_save": validate(saved) == [] if saved else False,
            "resumed_completed": r.get("completed"), "resumed_ticks": r.get("ticks"),
            "final_equal_uninterrupted": bool(s.get("final_state")) and canonical_json(r.get("final_state", {})) == canonical_json(s.get("final_state", {})),
            "final_checksum": (s.get("final_state") or {}).get("checksum"),
            "exit_codes": [cq, cr], "script_errors": rq["_script_errors"] + rr["_script_errors"],
        }
        fx = tmp / "fixtures.json"
        fx.write_text(json.dumps(FIXTURES), encoding="utf-8")
        _, chk = _slice_check(root, tmp / "a", fx)
        parity = {}
        for name, f in FIXTURES.items():
            py, steps = migrate(f)
            g = chk.get("migrated", {}).get(name, {})
            parity[name] = {"steps_py": steps, "steps_gd": g.get("steps"), "gd_errors": g.get("errors"),
                            "checksum_equal": py["checksum"] == (g.get("save") or {}).get("checksum")}
        result["save_quit_reload"]["migration_parity"] = parity
        # Q5 economy design targets (ADR-0018): loot MC over the recorded kill sequence + XP pacing
        from forge.economy import load_design, slice_report

        result["economy"] = slice_report(load_world(root), load_design(root), s) if s.get("ticks") else {"ok": False}
        # 2. selection matrix
        sels = FAST_SELECTIONS if fast_mode() else [(l, p) for l in LEADERS for p in PETS]
        def one(sel: tuple[str, str]) -> dict[str, Any]:
            c, o = _slice(root, tmp / f"m_{sel[0]}_{sel[1]}", f"--leader={sel[0]}", f"--pet={sel[1]}")
            ms = o.get("slice", {})
            eco = slice_report(load_world(root), load_design(root), ms) if ms.get("ticks") else {"ok": False}
            return ({"leader": sel[0], "pet": sel[1], "exit": c, "script_errors": o["_script_errors"]} | _summary(ms)
                    | {"economy_ok": eco.get("ok"), "levels": {k: v["level"] for k, v in eco.get("levels", {}).items()},
                       "_fights": ms.get("fights", [])})
        with ThreadPoolExecutor(max_workers=max(1, min(4, (os.cpu_count() or 2)))) as ex:
            runs = list(ex.map(one, sels))
        fights_by_sel = {f"{x['leader']}+{x['pet']}": x.pop("_fights") for x in runs}
        result["matrix"] = {"mode": "fast" if fast_mode() else "full", "runs": runs}
        # P7 world-fight bands (0.7.15, C-98): replay every recorded fight of every selection over many seeds
        from forge import worldfights

        wcfg = worldfights.load_config(root)
        wld = load_world(root)
        units = {k: worldfights.fight_units(v, wld) for k, v in fights_by_sel.items()}
        wf = worldfights.run(units, wcfg["seeds"]["fast" if fast_mode() else "full"], root)
        result["world_fights"] = worldfights.summary(wf) | {"mode": "fast" if fast_mode() else "full"}
        # 3. parity with the Python twins
        w = load_world(root)
        ql, mism = QuestLog(w), []
        for e in s.get("quest_trace", []):
            py = [[t["region"], t["from"], t["to"]] for t in ql.send(e["event"], e["counters"])]
            if py != e["taken"]:
                mism.append({"tick": e["tick"], "event": e["event"], "gd": e["taken"], "py": py})
        rng = Lcg(int(s.get("loot", {}).get("probe_seed", 12345)))
        py_rolls = [roll_loot(w, tier, ref, rng) for ref, tier in PROBE]
        result["parity"] = {"quest_events": len(s.get("quest_trace", [])), "quest_mismatches": mism[:5],
                            "loot_probe_equal": py_rolls == s.get("loot", {}).get("probe_rolls")}
        # 4. static gates + locale
        from forge.pipeline import build_all

        rep = build_all(root, pattern="f6/*.yaml", export=False)     # re-gate the slice briefs (no export)
        reg = json.loads((root / "games" / "game-zero" / "assets" / "generated" / "fabric_assets.json").read_text(encoding="utf-8"))
        result["world_gates"] = (rep["assets"].get("world") or {}).get("gates", {})
        result["world_meta"] = {k: v for k, v in (reg["assets"].get("world") or {}).get("meta", {}).items()
                                if k in ("node_counts", "supply", "loot_ev", "quests")}
        result["tilemaps"] = {a: (rep["assets"].get(a) or {}).get("gates", {}) for a in TILEMAPS}
        result["locale"] = locale_report(root)
        return (code or cq or cr), result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _slice_check(root: Path, save_dir: Path, fixtures: Path) -> tuple[int, dict[str, Any]]:
    from forge.milestones import parse_output

    proc = subprocess.run(_godot_argv(root, "--scene=savecheck", f"--save-dir={save_dir}", f"--fixtures={fixtures}"),
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, parse_output(proc.stdout + proc.stderr).get("savecheck", {})


def f6_check(r: dict[str, Any]) -> list[str]:
    from forge.milestones import _need

    errs: list[str] = []
    s = r.get("slice", {})
    _need(r.get("script_errors") == 0, f"script errors: {r.get('script_errors')}", errs)
    _need(s.get("completed") is True and s.get("quests", {}).get("q_warden") == "done", f"slice not completed: {s.get('quests')}", errs)
    _need(not s.get("softlocks"), f"runtime soft-locks: {s.get('softlocks')}", errs)
    # §6.1 (1) character select among 4 + starter pet
    _need(bool(s.get("selection", {}).get("leader")) and bool(s.get("selection", {}).get("pet")), "no selection", errs)
    m = r.get("matrix", {})
    runs = m.get("runs", [])
    _need(len(runs) == (2 if m.get("mode") == "fast" else 12), f"matrix size {len(runs)}", errs)
    for x in runs:
        _need(x.get("completed") is True and x.get("exit") == 0 and x.get("script_errors") == 0 and x.get("softlocks") == 0,
              f"selection {x.get('leader')}+{x.get('pet')} failed: {x}", errs)
    # (2) farming beat yields usable resources
    fm = s.get("farming", {})
    _need(len(fm.get("harvested", [])) >= 2 and "moss_salve" in fm.get("crafted", []) and "ember_tonic" in fm.get("crafted", []),
          f"farming beat: {fm.get('harvested')} {fm.get('crafted')}", errs)
    _need(bool((s.get("buff_at_boss") or {}).get("buffs")), "crafted tonic not used in the boss fight", errs)
    # (3) solvable cave  (4) open-world transition
    areas = [a["area"] for a in s.get("areas", [])]
    _need("cave_deep" in areas and s.get("stage_ticks", {}).get("q_warden.clear_cave") is not None, "cave not cleared", errs)
    _need(areas[-1:] == ["field"] and "warden_lair" in areas, f"open-world transition: {areas}", errs)
    _need(all(g is True for t in r.get("tilemaps", {}).values() for g in t.values()) and len(r.get("tilemaps", {})) == len(TILEMAPS),
          f"tilemap gates: {r.get('tilemaps')}", errs)
    # §6.1 "15–20 minutes" — human-pace estimate for the main run and every selection (bot time reported as-is)
    pace = r.get("pace", {})
    ests = [pace.get("human_estimate_min")] + [x.get("human_estimate_min") for x in runs]
    _need(all(e is not None and TARGET_MIN[0] <= e <= TARGET_MIN[1] for e in ests),
          f"length: human-pace estimates {ests} min outside {TARGET_MIN}", errs)
    # Q5 economy / loot / XP targets (content/world/economy_design.yaml) on the main run and every selection
    eco = r.get("economy", {})
    _need(eco.get("ok") is True, f"economy targets: {eco.get('checks')} levels={eco.get('levels')}", errs)
    _need(all(x.get("economy_ok") is True for x in runs), f"economy targets per selection: {[(x.get('leader'), x.get('pet'), x.get('levels')) for x in runs if not x.get('economy_ok')]}", errs)
    # (5) party combat with followers + pet
    ps = s.get("party_stats", {})
    _need(sum(1 for k, v in ps.items() if not v.get("pet") and v.get("damage", 0) + v.get("healing", 0) > 0) >= 4
          and any(v.get("pet") for v in ps.values()), f"party combat: {ps}", errs)
    # (6) time-freeze swap with overlay
    _need(len(s.get("swaps", [])) >= 1 and all(s.get("swap_parity", [False])) and len(s.get("overlay", [])) >= 5,
          f"freeze swap: {s.get('swaps')} parity={s.get('swap_parity')}", errs)
    # (7) Cave Warden boss clear
    b = s.get("boss", {})
    _need(b.get("defeated") is True and b.get("tier") == 3 and b.get("phases_reached", 0) >= 3, f"boss: {b}", errs)
    _need("vex" in s.get("unlocked", []), "boss reward unlock missing", errs)
    # (8) save / quit / reload
    sq = r.get("save_quit_reload", {})
    for k in ("loaded_equal_saved", "python_validates_save", "resumed_completed", "final_equal_uninterrupted"):
        _need(sq.get(k) is True, f"save/quit/reload {k}: {sq}", errs)
    for name, p in sq.get("migration_parity", {}).items():
        _need(p["steps_py"] == p["steps_gd"] and p["checksum_equal"] and not p["gd_errors"], f"migration parity {name}: {p}", errs)
    # loop wiring
    mu = s.get("music", {})
    _need({t["state"] for t in mu.get("trace", [])} >= {"explore", "tension", "combat", "boss"}
          and {t["biome"] for t in mu.get("trace", [])} >= {"field", "cave"}, "adaptive music did not cover biomes × states", errs)
    _need(any(int(d[1]) == 3 for d in s.get("loot", {}).get("drops", [])), "no tier-3 loot drop", errs)
    p = r.get("parity", {})
    _need(not p.get("quest_mismatches") and p.get("quest_events", 0) > 0, f"quest parity: {p.get('quest_mismatches')}", errs)
    _need(p.get("loot_probe_equal") is True, "loot probe rolls differ between GDScript and Python", errs)
    _need(bool(r.get("world_gates")) and all(v is True for v in r.get("world_gates", {}).values()), f"world gates: {r.get('world_gates')}", errs)
    _need(r.get("locale", {}).get("ok") is True, f"missing locale keys: {r.get('locale', {}).get('missing')}", errs)
    # P7 world-fight wipe-rate / clear-time bands (content/tune/worldfights.yaml, C-98), every selection × fight
    wfr = r.get("world_fights", {})
    wv = wfr.get("verdict", {})
    _need(wv.get("ok") is True, f"world-fight bands: {wv.get('checks')} {wv.get('out_of_band', [])[:6]} errors={wfr.get('errors')}", errs)
    _need(sum((c or {}).get("cells", 0) for c in (wfr.get("classes") or {}).values()) >= 18 * len(runs),
          f"world-fight MC covered too few fights: {wfr.get('classes')}", errs)
    return errs


def f6_perf(r: dict[str, Any]) -> dict[str, Any]:
    s = r.get("slice", {})
    gm = s.get("game_minutes") or 0
    runs = r.get("matrix", {}).get("runs", [])
    pace = r.get("pace", {})
    ests = [x.get("human_estimate_min") for x in runs if x.get("human_estimate_min") is not None]
    return {"slice_ticks": s.get("ticks"), "slice_game_minutes": gm, "slice_wall_ms": s.get("wall_ms"),
            "target_minutes": list(TARGET_MIN), "bot_length_within_target": TARGET_MIN[0] <= gm <= TARGET_MIN[1],
            "human_estimate_min": pace.get("human_estimate_min"), "human_estimate_components_s": pace.get("components_s"),
            "human_wait_slack_s": pace.get("wait_slack_s"),
            "matrix_human_estimate_min": [min(ests), max(ests)] if ests else None,
            "length_within_target": bool(pace.get("within_target")) and all(TARGET_MIN[0] <= e <= TARGET_MIN[1] for e in ests),
            "length_note": "gate = human-pace estimate (forge/pace.py, INFERENCE C-92; a model, not a playtest); "
                           "bot game time is the machine-efficiency floor, reported as-is; a human GUI playtest replaces the model",
            "matrix_game_minutes": [x.get("game_minutes") for x in runs],
            "matrix_wipes": sum(x.get("wipes") or 0 for x in runs),
            "world_fights_wall_s": r.get("world_fights", {}).get("wall_s"),
            "world_fights_encounters": r.get("world_fights", {}).get("encounters"),
            "world_fights_classes": {k: {"wipe_rate_max": v["wipe_rate_range"][1], "clear_median_s": v["clear_median_range_s"],
                                         "clear_p90_max_s": v["clear_p90_max_s"]}
                                     for k, v in (r.get("world_fights", {}).get("classes") or {}).items()},
            "swap_wall_ms": [x.get("wall_ms") for x in s.get("swaps", [])]}
