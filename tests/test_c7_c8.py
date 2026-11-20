"""Companion track C7 (LoomCluster) + C8 (GroundWeave) — fast half.

Full proofs (12-brief determinism over 1/2/3 nodes, SIGKILL failover, origin restart, Kotlin LoomLink hop, 2-core
verify of every op incl. Godot probes) live in `forge accept C7` / `C8` and CI's `pocketloom` job.
"""

from __future__ import annotations

import copy
import json
import urllib.error
from pathlib import Path

import pytest

from forge import groundweave as gw
from forge import loomcluster as lc
from forge.loomlink import OPS, op_hashchain
from forge.milestones import INCREMENTS


# ----------------------------------------------------------------------------- GroundWeave (C8)

def test_ladder_static_rules_pass(root: Path) -> None:
    r = gw.check(root)
    assert r["ok"], r["problems"]
    assert {"sprite", "tilemap", "material", "audio", "codegen", "callouts", "persona_lm", "policy", "world"} <= set(r["kinds"])


def test_check_rejects_missing_cpu_rung_and_undeclared_kind(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = copy.deepcopy(gw.load_ladder(root))
    bad["ops"]["gen.sprite"]["ladder"] = [s for s in bad["ops"]["gen.sprite"]["ladder"] if s["device"] != "cpu"]
    del bad["ops"]["gen.world"]
    monkeypatch.setattr(gw, "load_ladder", lambda r=None: bad)
    probs = gw.check(root)["problems"]
    assert any("gen.sprite: no real CPU backend" in p for p in probs)
    assert any("'world' has no GroundWeave op" in p for p in probs)


def test_cpu_rung_must_be_last_and_real(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = copy.deepcopy(gw.load_ladder(root))
    bad["ops"]["gen.sprite"]["ladder"] = list(reversed(bad["ops"]["gen.sprite"]["ladder"]))
    monkeypatch.setattr(gw, "load_ladder", lambda r=None: bad)
    assert any("CPU backend must be the last rung" in p for p in gw.check(root)["problems"])


def test_selection_never_picks_a_planned_backend(root: Path) -> None:
    for op_id, op in gw.load_ladder(root)["ops"].items():
        for devs in (["cpu"], ["cpu", *gw.SIMULATED_GPU_DEVICES]):
            sel = gw.select(op_id, devs, root)
            if sel.get("backend"):
                assert sel["device"] == "cpu", (op_id, sel)       # every GPU rung is `planned` today
            elif op.get("planned"):                  # C9–C12: specified-but-unbuilt ops select nothing and say so
                assert sel["status"] == "planned" and sel["route"] in ("loomcluster", "local")
            else:
                assert op.get("gpu_required") and sel["route"] == "loomcluster"


def test_runtime_fallback_demotes_failing_gpu_rung() -> None:
    ladder = {"ops": {"t": {"ladder": [{"id": "g", "device": "rocm", "impl": "real"},
                                       {"id": "c", "device": "cpu", "impl": "real"}]}}}

    def boom() -> int:
        raise MemoryError("VRAM")

    ok = gw.execute("t", {"g": lambda: 1, "c": lambda: 1}, ["cpu", "rocm"], ladder=ladder)
    assert (ok["backend"], ok["fallback"]) == ("g", False)
    dem = gw.execute("t", {"g": boom, "c": lambda: 2}, ["cpu", "rocm"], ladder=ladder)
    assert (dem["backend"], dem["fallback"], dem["value"]) == ("c", True, 2)
    assert dem["attempts"][0]["ok"] is False and "VRAM" in dem["attempts"][0]["error"]
    nogpu = gw.execute("t", {"g": boom, "c": lambda: 3}, ["cpu"], ladder=ladder)
    assert len(nogpu["attempts"]) == 1
    with pytest.raises(gw.GroundWeaveError):
        gw.execute("t", {"g": boom}, ["cpu", "rocm"], ladder=ladder)


def test_pipeline_refuses_generator_without_ladder_entry(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.pipeline import Context, load_briefs, run_brief

    bad = copy.deepcopy(gw.load_ladder(root))
    del bad["ops"]["gen.sprite"]
    monkeypatch.setattr(gw, "load_ladder", lambda r=None: bad)
    brief = next(b for b in load_briefs(root) if b["kind"] == "sprite")
    with pytest.raises(gw.GroundWeaveError, match="no GroundWeave op"):
        run_brief(brief, Context.create(root), export=False)


def test_two_core_gpu_hidden_run_is_byte_identical(root: Path) -> None:
    r = gw.verify(root, ops=["gen.sprite", "gen.tilemap", "gen.codegen"])
    assert r["ok"], r
    for x in r["results"]:
        assert x["device"] == "cpu" and x["cores"] == 2 and x["identical_to_unpinned"] and x["identical_with_simulated_gpu"]


# ----------------------------------------------------------------------------- LoomCluster (C7)

def test_caps_slots_follow_allocation_cap() -> None:
    assert lc.Caps("n", 8, ["cpu"], allocation_cap_pct=25).slots == 2
    assert lc.Caps("n", 1, ["cpu"], allocation_cap_pct=10).slots == 1          # never zero
    assert lc.can_run({"requires": {"device": "rocm"}}, ["cpu"]) is False
    assert lc.can_run({}, ["cpu"]) is True


def test_batch_digest_is_order_independent() -> None:
    a = {"x": {"value": {"d": 1}}, "y": {"value": {"d": 2}}}
    assert lc.batch_digest(a) == lc.batch_digest(dict(reversed(list(a.items()))))
    assert lc.batch_digest(a) != lc.batch_digest({**a, "y": {"value": {"d": 3}}})


@pytest.fixture(scope="module")
def fleet(tmp_path_factory: pytest.TempPathFactory):
    with lc.Fleet(tmp_path_factory.mktemp("fleet")) as fl:
        fl.add("a", 1, "cpu")
        fl.add("b", 2, "cpu,vulkan")
        assert fl.wait_mesh(20)
        yield fl


def test_fleet_results_equal_direct_run_and_work_is_stolen(fleet: lc.Fleet) -> None:
    jobs = [{"id": f"h{i:02d}", "op": "hashchain", "payload": {"seed": i, "rounds": 300000}} for i in range(20)]
    jobs.append({"id": "gen:cave_01", "op": "gen", "payload": {"brief_id": "cave_01"}})
    ref = {j["id"]: {"value": OPS[j["op"]](j["payload"])} for j in jobs}
    res = lc.run_batch(fleet.urls["a"], jobs, 60)
    assert set(res) == set(ref)
    assert lc.batch_digest(res) == lc.batch_digest(ref)
    assert fleet.status("b")["stats"]["stolen_in"] > 0
    assert {r["node"] for r in res.values()} == {"a", "b"}


def test_retry_then_give_up(fleet: lc.Fleet, tmp_path: Path) -> None:
    res = lc.run_batch(fleet.urls["a"], [
        {"id": "r-ok", "op": "flaky", "payload": {"marker": str(tmp_path / "m1"), "fail_first": 2}},
        {"id": "r-bad", "op": "flaky", "payload": {"marker": str(tmp_path / "m2"), "fail_first": 99}}], 30)
    assert res["r-ok"]["ok"] and res["r-ok"]["attempts"] == 3
    assert not res["r-bad"]["ok"] and res["r-bad"]["attempts"] == lc.protocol_config()["max_attempts"]


def test_device_placement_and_refusal(fleet: lc.Fleet) -> None:
    res = lc.run_batch(fleet.urls["a"], [{"id": f"v{i}", "op": "hashchain", "payload": {"seed": i, "rounds": 100},
                                          "requires": {"device": "vulkan"}} for i in range(4)], 20)
    assert {r["node"] for r in res.values()} == {"b"}
    with pytest.raises(urllib.error.HTTPError) as e:
        lc._http(fleet.urls["a"] + "/submit", {"op": "hashchain", "payload": {}, "requires": {"device": "rocm"}})
    assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError):
        lc._http(fleet.urls["a"] + "/submit", {"op": "format-disk", "payload": {}})


def test_loomlink_offload_runs_on_fleet_and_falls_back(fleet: lc.Fleet, tmp_path: Path) -> None:
    from forge.accept_companions import Desktop, free_port
    from forge.loomlink import LinkClient

    d = Desktop(tmp_path / "desk", port=free_port()).start()
    try:
        d.srv.cluster = lc.ClusterBridge(fleet.urls["a"])
        cli = LinkClient(d.srv.url, "phone")
        cli.pair(d.srv.code, ["offload"])
        rs = [cli.offload({"id": f"o{i}", "op": "hashchain", "payload": {"seed": i, "rounds": 3000}}) for i in range(4)]
        assert all(r["via"] == "loomcluster" and r["value"] == op_hashchain({"seed": i, "rounds": 3000})
                   for i, r in enumerate(rs))
        d.srv.cluster = lc.ClusterBridge("http://127.0.0.1:9", timeout_s=2.0)     # nothing listens there
        r = cli.offload({"id": "fb", "op": "hashchain", "payload": {"seed": "q", "rounds": 100}})
        assert r["ok"] and r["node"] == "desktop" and "via" not in r
    finally:
        d.halt()


def test_acceptance_registered_with_results_schema(root: Path) -> None:
    for m in ("C7", "C8"):
        assert m in INCREMENTS and INCREMENTS[m].runner is not None
