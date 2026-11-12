"""F4 Substrate: sandbox tiers, live channel validation, statecharts, guardian."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from forge import sandbox
from forge.guardian import Backoff, Guardian, GuardianPolicy
from forge.live import LiveChannel, LiveError, diff_numeric, rule_for, validate_patch
from forge.pipeline import Context, load_briefs
from forge.statechart import StateChart, analyze, load

TIERS = [t for t in ("process", "bwrap") if sandbox.detect_tiers()[t]["available"]]


# ----------------------------------------------------------------------------- sandbox

def test_detect_tiers_reports_kvm_tiers_honestly() -> None:
    t = sandbox.detect_tiers()
    assert set(t) == {"firecracker", "gvisor", "bwrap", "process"}
    assert t["firecracker"]["available"] is False and t["firecracker"]["reason"]
    assert t["gvisor"]["available"] is False
    assert t["process"]["available"] is True
    assert sandbox.best_tier() in ("bwrap", "process")


@pytest.mark.parametrize("tier", TIERS)
def test_sandbox_refuses_network(root: Path, tier: str) -> None:
    code = ("import socket\ntry:\n s=socket.create_connection(('1.1.1.1',80),timeout=2); result='connected'\n"
            "except Exception as e:\n result='refused:'+type(e).__name__")
    with sandbox.Sandbox(tier=tier, profile="short", root=root) as sb:
        r = sb.python({"op": "exec", "code": code})
    assert r.ok, r.stderr
    assert r.json()["result"].startswith("refused"), r.json()


@pytest.mark.parametrize("tier", TIERS)
def test_sandbox_confines_writes(root: Path, tier: str, tmp_path: Path) -> None:
    target = tmp_path / "escape.txt"
    code = (f"open('inside.txt','w').write('ok')\ntry:\n open({str(target)!r},'w').write('x'); result='escaped'\n"
            "except Exception as e:\n result='refused'")
    with sandbox.Sandbox(tier=tier, profile="short", root=root) as sb:
        r = sb.python({"op": "exec", "code": code})
        assert (sb.scratch / "inside.txt").read_text() == "ok"
    assert r.json()["result"] == "refused"
    assert not target.exists()


@pytest.mark.parametrize("tier", TIERS)
def test_sandbox_wall_clock_kill(root: Path, tier: str) -> None:
    lim = sandbox.Limits(cpu_s=30, mem_mb=1024, wall_s=1.0)
    with sandbox.Sandbox(tier=tier, limits=lim, root=root) as sb:
        r = sb.python({"op": "exec", "code": "import time\ntime.sleep(30)"})
    assert r.killed == "wall" and not r.ok
    assert r.wall_ms < 5000


def test_sandbox_cpu_rlimit_kill(root: Path) -> None:
    lim = sandbox.Limits(cpu_s=1, mem_mb=1024, wall_s=20.0)
    with sandbox.Sandbox(tier="process", limits=lim, root=root) as sb:
        r = sb.python({"op": "exec", "code": "while True: pass"})
    assert r.killed in ("cpu", "signal:9") and not r.ok


def test_sandbox_lifecycle_and_disk_snapshot(root: Path) -> None:
    sb = sandbox.Sandbox(tier="process", profile="short", root=root).provision()
    (sb.scratch / "a.txt").write_text("one")
    blob = sb.snapshot()
    (sb.scratch / "a.txt").write_text("two")
    (sb.scratch / "b.txt").write_text("junk")
    sb.restore(blob)
    assert (sb.scratch / "a.txt").read_text() == "one" and not (sb.scratch / "b.txt").exists()
    sb.terminate()
    assert sb.history[:2] == ["CREATED", "PROVISIONING"] and sb.history[-1] == "TERMINATED"
    assert "SNAPSHOTTING" in sb.history and "RESTORING" in sb.history


@pytest.mark.parametrize("tier", TIERS)
def test_sandboxed_generator_is_byte_identical(root: Path, tier: str) -> None:
    from forge.generators import load_all

    brief = next(b for b in load_briefs(root) if b["kind"] == "sprite")
    direct = load_all()["sprite"](brief, Context.create(root))
    boxed = sandbox.generate(brief, root, tier=tier)
    assert boxed.meta["sandbox"]["tier"] == tier
    assert {a.name: a.data for a in direct.artifacts} == {a.name: a.data for a in boxed.artifacts}
    assert [g.ok for g in direct.gates] == [g.ok for g in boxed.gates]


# ----------------------------------------------------------------------------- live channel

@pytest.fixture
def game_data(root: Path) -> dict:
    return json.loads((root / "games/game-zero/data/generated/game_data.json").read_text())


def test_tune_limits_are_exported_with_game_data(game_data: dict) -> None:
    assert "tune_limits" in game_data
    assert rule_for(game_data["tune_limits"], "enemies.rock_brute.stats.hp") == [1.0, 9999.0]
    assert rule_for(game_data["tune_limits"], "sim.leash") == [16.0, 256.0]


@pytest.mark.parametrize("patch,ok", [
    ({"path": "enemies.rock_brute.stats.hp", "value": 30}, True),
    ({"path": "sim.leash", "value": 64}, True),
    ({"path": "enemies.rock_brute.stats.hp", "value": 99999}, False),     # out of range
    ({"path": "enemies.rock_brute.stats.hp", "value": float("nan")}, False),
    ({"path": "enemies.rock_brute.sprite_id", "value": 1}, False),       # structural
    ({"path": "enemies.nobody.stats.hp", "value": 5}, False),           # no such field
    ({"path": "sim.leash", "value": True}, False),                       # bool is not a number
])
def test_validate_patch(game_data: dict, patch: dict, ok: bool) -> None:
    assert (validate_patch(game_data, patch) is None) == ok


def test_diff_numeric_separates_structural() -> None:
    a = {"x": {"hp": 1, "name": "a"}, "y": [1, 2]}
    b = {"x": {"hp": 2, "name": "b"}, "y": [1, 2, 3]}
    patches, structural = diff_numeric(a, b)
    assert patches == [{"path": "x.hp", "value": 2}]
    assert "x.name" in structural and "y.2" in structural


def test_push_is_atomic_and_monotonic(root: Path, tmp_path: Path) -> None:
    ch = LiveChannel(tmp_path, root)
    with pytest.raises(LiveError):
        ch.push([{"path": "sim.leash", "value": 9999}])
    assert ch.head() == 0
    got: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(5):
            n = ch.push([{"path": "sim.leash", "value": 60}])
            with lock:
                got.append(n)

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == list(range(1, 21)) and ch.head() == 20
    for n in got:
        assert json.loads((tmp_path / "tickets" / f"{n}.json").read_text())["ticket"] == n


# ----------------------------------------------------------------------------- statecharts

def test_live_session_chart_has_parallel_regions_and_no_softlocks(root: Path) -> None:
    chart = load(root / "games/game-zero/data/statecharts/live_session.json")
    assert {"combat", "movement", "ai", "dialogue", "reload"} <= set(chart["regions"])
    rep = analyze(chart)
    assert rep["ok"], rep


def test_analyze_flags_softlocks() -> None:
    bad = {"id": "bad", "regions": {"r": {"initial": "a", "states": {
        "a": {"on": {"go": "b", "x": "ghost"}}, "b": {"on": {"loop": "c"}}, "c": {"on": {"back": "b"}},
        "island": {"on": {"z": "done"}}, "dead": {}, "done": {"final": True}}}}}
    r = analyze(bad)["regions"]["r"]
    assert not r["ok"]
    assert r["dangling"] == ["ghost"] and "island" in r["unreachable"] and "dead" in r["dead_ends"]
    assert {"a", "b", "c"} <= set(r["traps"])


def test_parallel_regions_and_guards() -> None:
    chart = {"regions": {"a": {"initial": "x", "states": {"x": {"on": {"e": "y"}}, "y": {"final": True}}},
                         "b": {"initial": "p", "states": {"p": {"on": {"e": {"target": "q", "guard": "ok"}}}, "q": {"final": True}}}}}
    c = StateChart(chart, guard=lambda g, r, s: False)
    c.send("e")
    assert c.active == {"a": "y", "b": "p"}
    c.guard = lambda g, r, s: g == "ok"
    c.send("e")
    assert c.done()


# ----------------------------------------------------------------------------- guardian

def _child(tmp: Path, body: str) -> list[str]:
    p = tmp / "child.py"
    p.write_text(body)
    return [sys.executable, str(p)]


def test_guardian_restarts_crashes_with_backoff(tmp_path: Path) -> None:
    body = ("import pathlib,sys\nc=pathlib.Path(sys.argv[0]).with_name('count')\n"
            "n=int(c.read_text()) if c.exists() else 0\nc.write_text(str(n+1))\nsys.exit(0 if n>=2 else 3)\n")
    g = Guardian(_child(tmp_path, body), tmp_path, restart_args=["--resume"],
                 policy=GuardianPolicy(backoff=Backoff(0.05, 2.0, 1.0)))
    assert g.run(poll_s=0.02) == "exited"
    s = g.summary()
    assert s["restarts"] == 2 and [f["kind"] for f in s["failures"]] == ["crash", "crash"]
    assert s["backoffs"] == [0.05, 0.1]
    assert (tmp_path / "guardian.jsonl").exists()


def test_guardian_detects_hang_via_heartbeat(tmp_path: Path) -> None:
    hb = tmp_path / "hb"
    body = (f"import pathlib,sys,time\nhb=pathlib.Path({str(hb)!r})\n"
            "if '--resume' in sys.argv: sys.exit(0)\nhb.write_text('1')\ntime.sleep(60)\n")
    g = Guardian(_child(tmp_path, body), tmp_path, heartbeat=hb, restart_args=["--resume"],
                 policy=GuardianPolicy(hang_s=0.5, backoff=Backoff(0.05, 2.0, 1.0)))
    t0 = time.monotonic()
    assert g.run(poll_s=0.02) == "exited"
    assert time.monotonic() - t0 < 10
    assert [f["kind"] for f in g.summary()["failures"]] == ["hang"]


def test_guardian_gives_up_on_crash_loop(tmp_path: Path) -> None:
    g = Guardian(_child(tmp_path, "import sys\nsys.exit(1)\n"), tmp_path,
                 policy=GuardianPolicy(max_restarts=3, backoff=Backoff(0.01, 1.0, 0.01)))
    assert g.run(poll_s=0.01) == "gave_up"
    assert g.summary()["restarts"] == 3


def test_backoff_is_capped() -> None:
    b = Backoff(0.5, 2.0, 8.0)
    assert [b.delay(k) for k in range(6)] == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]
