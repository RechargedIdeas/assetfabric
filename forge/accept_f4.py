"""F4 acceptance: "live tune without a full rebuild" (SPEC §13), in two phases.

Phase A — deterministic (headless autoplay, `--live-backlog`): tickets are staged *before*
the run and consumed at a scripted tick boundary, so the result is reproducible in CI:
  1 numeric tune (enemy HP + sim.leash) → committed
  2 sprite regenerated inside the Substrate sandbox and hot-swapped → committed
  3 tune with an injected probe failure → rolled back, state hash restored exactly
  4 out-of-range value that bypassed forge validation → rejected by the game (defense in depth)
  + snapshot at tick 120 → on-disk restore + WAL replay reproduces the final state hash
  + statechart event log replayed by forge/statechart.py reproduces the GDScript state

Phase B — live process under the Guardian (`--serve`, real time):
  tune → committed while running · crash during commit → guardian restart with backoff,
  `--live-resume` restores the session snapshot, quarantines the poison ticket, re-applies
  committed tunes · hang → heartbeat timeout → kill → restart · quit → clean exit.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from forge.live import LiveChannel

TUNE_HP_A = 30
TUNE_LEASH_A = 72
TUNE_HP_B = 40
TUNE_LEASH_B = 80
TUNE_HP_B2 = 45
ACK_TARGET_MS = 500.0      # [INFERENCE] F4-4: live tune must land within ~0.5 s of the push
RESTART_TARGET_S = 10.0    # [INFERENCE] F4-5: guardian recovery (detect + backoff + boot + resume)


def _godot_argv(root: Path, *args: str) -> list[str]:
    from forge.manifest import load_manifest
    from forge.milestones import godot_binary

    gb = godot_binary(root)
    if not gb:
        raise FileNotFoundError("Godot binary not found (GODOT_BIN, PATH, or godot-bin/godot)")
    project = root / load_manifest(None, root).game.project_path
    return [gb, "--headless", "--path", str(project), "--", *args]


def _phase_a(root: Path, live: Path) -> tuple[int, dict[str, Any]]:
    import subprocess

    from forge.milestones import parse_output

    ch = LiveChannel(live, root)
    ch.push([{"path": "enemies.rock_brute.stats.hp", "value": TUNE_HP_A},
             {"path": "sim.leash", "value": TUNE_LEASH_A}], source="accept F4: tune")
    ch.push_sprite("spr_rock_brute", seed=4242)
    ch.push([{"path": "enemies.rock_brute.stats.atk", "value": 5}], source="accept F4: probe fault", fault="probe")
    ch.push([{"path": "enemies.rock_brute.stats.hp", "value": 99999}], source="accept F4: bypass", validate=False)
    proc = subprocess.run(_godot_argv(root, "--scene=live", "--autoplay", f"--live-dir={live}", "--live-backlog",
                                      "--allow-fault-injection"), capture_output=True, text=True, timeout=240)
    return proc.returncode, parse_output(proc.stdout + proc.stderr)


def _wait(pred, timeout: float, poll: float = 0.05):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(poll)
    return None


def _phase_b(root: Path, live: Path) -> dict[str, Any]:
    from forge.guardian import Backoff, Guardian, GuardianPolicy

    ch = LiveChannel(live, root)
    g = Guardian(_godot_argv(root, "--scene=live", "--autoplay", "--serve", f"--live-dir={live}", "--allow-fault-injection"),
                 state_dir=live, heartbeat=live / "status.json", restart_args=["--live-resume"],
                 policy=GuardianPolicy(hang_s=3.0, grace_s=60.0, max_restarts=4, window_s=120.0,
                                       backoff=Backoff(0.25, 2.0, 4.0)),
                 log_child=live / "godot.log", root=root).start()
    out: dict[str, Any] = {"steps": []}

    def status():
        return ch.status()

    def ready_pid(exclude: set[int]):
        s = status()
        return s if s.get("ready") and s.get("pid") not in exclude else None

    try:
        _phase_b_steps(ch, g, out, status, ready_pid)
    except Exception as exc:   # report, don't crash the acceptance run
        out["error"] = repr(exc)
    finally:
        if g.status == "running":
            g.stop()
    out["guardian"] = g.summary()
    return out


def _phase_b_steps(ch, g, out, status, ready_pid) -> None:
    if True:
        s0 = _wait(lambda: ready_pid(set()), 60)
        if not s0:
            out["error"] = "game never became ready"
            return
        pids = {s0["pid"]}
        # 1. live tune on the running process
        n1 = ch.push([{"path": "enemies.rock_brute.stats.hp", "value": TUNE_HP_B},
                      {"path": "sim.leash", "value": TUNE_LEASH_B}], source="accept F4 serve: tune")
        a1 = ch.wait_ack(n1, 10)
        s1 = _wait(lambda: (lambda s: s if s.get("applied", 0) >= n1 else None)(status()), 5) or {}
        out["steps"].append({"step": "tune", "ticket": n1, "status": a1["status"], "ack_ms": a1["ack_latency_ms"],
                             "tuned": s1.get("tuned", {})})
        # 2. crash mid-commit → guardian restart → resume
        t_c = time.monotonic()
        n2 = ch.push([{"path": "enemies.rock_brute.stats.atk", "value": 6}], source="accept F4 serve: crash", fault="crash")
        s2 = _wait(lambda: ready_pid(pids), 60)
        a2 = ch.ack(n2) or {}
        out["steps"].append({"step": "crash", "ticket": n2, "status": a2.get("status"), "recover_s": round(time.monotonic() - t_c, 2),
                             "resume": (s2 or {}).get("resume", {}), "tuned": (s2 or {}).get("tuned", {})})
        if s2:
            pids.add(s2["pid"])
        # 3. tune after recovery
        n3 = ch.push([{"path": "enemies.rock_brute.stats.hp", "value": TUNE_HP_B2}], source="accept F4 serve: tune 2")
        a3 = ch.wait_ack(n3, 10)
        s3 = _wait(lambda: (lambda s: s if s.get("applied", 0) >= n3 else None)(status()), 5) or {}
        out["steps"].append({"step": "tune_after_restart", "ticket": n3, "status": a3["status"], "ack_ms": a3["ack_latency_ms"],
                             "tuned": s3.get("tuned", {})})
        # 4. hang → heartbeat timeout → restart
        t_h = time.monotonic()
        n4 = ch.push([{"path": "enemies.rock_brute.stats.def", "value": 3}], source="accept F4 serve: hang", fault="hang")
        s4 = _wait(lambda: ready_pid(pids), 60)
        a4 = ch.ack(n4) or {}
        out["steps"].append({"step": "hang", "ticket": n4, "status": a4.get("status"), "recover_s": round(time.monotonic() - t_h, 2),
                             "resume": (s4 or {}).get("resume", {}), "tuned": (s4 or {}).get("tuned", {})})
        # 5. clean shutdown
        n5 = ch.push(control="quit", source="accept F4 serve: quit")
        a5 = _wait(lambda: ch.ack(n5), 10) or {}
        out["steps"].append({"step": "quit", "ticket": n5, "status": a5.get("status")})
        g.join(20)


def f4_run(root: Path) -> tuple[int, dict[str, Any]]:
    from forge.statechart import StateChart, analyze, load

    tmp = Path(tempfile.mkdtemp(prefix="fabric-f4-"))
    try:
        code, result = _phase_a(root, tmp / "backlog")
        chart_path = root / "games" / "game-zero" / "data" / "statecharts" / "live_session.json"
        chart = load(chart_path)
        result["statechart_analysis"] = analyze(chart)
        main = result.get("live", {}).get("chart_main", {})
        py = StateChart(chart)
        for e in main.get("events", []):
            py.send(e)
        result["statechart_parity"] = {"active_equal": py.active == main.get("active"),
                                       "transitions_equal": len(py.trace) == main.get("transitions"),
                                       "events": len(main.get("events", []))}
        from forge.sandbox import describe

        result["sandbox"] = describe()
        result["serve"] = _phase_b(root, tmp / "serve")
        return code, result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def f4_check(r: dict[str, Any]) -> list[str]:
    from forge.milestones import _need

    errs: list[str] = []
    live = r.get("live", {})
    _need(r.get("outcome") == "victory", f"outcome={r.get('outcome')}", errs)
    statuses = [a.get("status") for a in live.get("acks", [])]
    _need(statuses == ["committed", "committed", "rolled_back", "rejected"], f"phase A ack statuses={statuses}", errs)
    acks = live.get("acks", [])
    if len(acks) >= 3:
        _need(acks[2].get("restored_equal") is True, "rollback did not restore the exact pre-commit state hash", errs)
        _need("sandbox=" in str(acks[1].get("source", "")), "sprite was not regenerated inside a sandbox", errs)
    tuned = live.get("tuned", {})
    _need(tuned.get("rock_brute_max_hp") == TUNE_HP_A, f"tuned enemy HP not live: {tuned}", errs)
    _need(float(tuned.get("leash", 0)) == TUNE_LEASH_A, f"sim.leash not live: {tuned}", errs)
    _need("/stage/" in str(tuned.get("sprite_override", "")), "sprite hot-swap not visible in the registry", errs)
    _need(live.get("replay", {}).get("restored_hash_equal") is True, "snapshot restore hash mismatch", errs)
    _need(live.get("replay_equal") is True, "snapshot + WAL replay did not reproduce the final state", errs)
    _need(live.get("chart_replay_equal") is True, "statechart state after replay differs", errs)
    _need(r.get("statechart_analysis", {}).get("ok") is True, f"statechart soft-lock analysis: {r.get('statechart_analysis')}", errs)
    par = r.get("statechart_parity", {})
    _need(par.get("active_equal") and par.get("transitions_equal"), f"GDScript vs Python statechart parity: {par}", errs)
    regions = set(live.get("chart_main", {}).get("active", {}))
    _need({"combat", "movement", "ai", "dialogue"} <= regions, f"parallel regions missing: {regions}", errs)
    sb = r.get("sandbox", {})
    _need(sb.get("selected") in ("bwrap", "process"), f"no sandbox tier: {sb.get('selected')}", errs)
    serve = r.get("serve", {})
    steps = {s["step"]: s for s in serve.get("steps", [])}
    _need(not serve.get("error"), f"serve: {serve.get('error')}", errs)
    t = steps.get("tune", {})
    _need(t.get("status") == "committed" and t.get("tuned", {}).get("rock_brute_max_hp") == TUNE_HP_B,
          f"serve tune not live: {t}", errs)
    c = steps.get("crash", {})
    _need(c.get("status") == "quarantined", f"crash ticket not quarantined: {c.get('status')}", errs)
    _need(c.get("resume", {}).get("from_snapshot") is True, "restart did not resume from the session snapshot", errs)
    _need(float(c.get("tuned", {}).get("leash", 0)) == TUNE_LEASH_B and c.get("tuned", {}).get("rock_brute_max_hp") == TUNE_HP_B,
          f"committed tunes lost across crash: {c.get('tuned')}", errs)
    t2 = steps.get("tune_after_restart", {})
    _need(t2.get("status") == "committed" and t2.get("tuned", {}).get("rock_brute_max_hp") == TUNE_HP_B2,
          f"tune after restart: {t2}", errs)
    h = steps.get("hang", {})
    _need(h.get("status") == "quarantined", f"hang ticket not quarantined: {h.get('status')}", errs)
    kinds = [f.get("kind") for f in serve.get("guardian", {}).get("failures", [])]
    _need(kinds == ["crash", "hang"], f"guardian failures={kinds}", errs)
    _need(steps.get("quit", {}).get("status") == "committed" and serve.get("guardian", {}).get("status") == "exited",
          f"clean shutdown: {steps.get('quit')} guardian={serve.get('guardian', {}).get('status')}", errs)
    return errs


def f4_perf(r: dict[str, Any]) -> dict[str, Any]:
    steps = {s["step"]: s for s in r.get("serve", {}).get("steps", [])}
    acks = r.get("live", {}).get("acks", [])
    ack_ms = [steps[k]["ack_ms"] for k in ("tune", "tune_after_restart") if k in steps and "ack_ms" in steps[k]]
    rec = [steps[k]["recover_s"] for k in ("crash", "hang") if k in steps and "recover_s" in steps[k]]
    return {"ack_ms": ack_ms, "ack_target_ms": ACK_TARGET_MS, "ack_target_met": bool(ack_ms) and max(ack_ms) <= ACK_TARGET_MS,
            "recover_s": rec, "recover_target_s": RESTART_TARGET_S,
            "recover_target_met": bool(rec) and max(rec) <= RESTART_TARGET_S,
            "commit_apply_us": [a.get("apply_us") for a in acks if a.get("apply_us")],
            "snapshot_bytes": r.get("live", {}).get("snapshot_bytes"),
            "backoffs_s": r.get("serve", {}).get("guardian", {}).get("backoffs")}
