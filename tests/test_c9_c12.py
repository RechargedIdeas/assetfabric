"""Companion track C9–C12 (MirrorWeave, LensForge, metric depth, SplatForge path) — fast half (≈ 10 s).

Full proofs (signed LoomLink loopback incl. the Kotlin client, 2-core verify of every new op, loopback LoomCluster placement,
FabricCore JUnit parity) live in `forge accept C9`…`C12` / `C9-C12` and CI's `pocketloom` job.
"""

from __future__ import annotations

import base64
import copy
import io
import json
import sys
import urllib.error
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from forge import depth, lensforge, mirrorweave, realityloom, registry
from forge import groundweave as gw
from forge.cli import main
from forge.milestones import CX_ORDER, INCREMENTS
from forge.stubs import StubError, is_stub_message
from forge.vectors_c9_c12 import make_vectors


def png(kind: str = "sharp", w: int = 640, h: int = 480, seed: int = 1) -> bytes:
    from forge.accept_c9_c12 import _png
    return _png(kind, w, h, seed)


# ----------------------------------------------------------------------------- register / stubs / shared vectors

def test_register_matches_code_and_every_stub_refuses(root: Path) -> None:
    r = registry.check(root)
    assert r["ok"], r["problems"]
    # 0.9.2: 25 real (incl. the tiny-scene CPU SplatForge rung) · 8 real_unverified_on_device (Android-only, compiled, never on a
    # phone) · 1 real_unverified_on_gpu (full-scale SplatForge runner, never on an AMD GPU) · 1 stub (cluster splat submit)
    assert (len(r["real"]), len(r["real_unverified_on_device"]), len(r["real_unverified_on_gpu"]), len(r["stubs"])) == (25, 8, 1, 1)
    assert r["real_unverified_on_gpu"] == ["recon.splatforge"] and r["stubs"] == ["recon.splat_submit"]
    for fid, rec in r["stub_refusals"].items():
        assert rec["message"].startswith(f"[STUB {fid} C"), rec


def test_register_check_catches_unverified_without_android_impl(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = registry.load(root)
    for f in reg["features"]:
        if f["id"] == "mirror.android_input":
            f["android_impl"] = "NoSuchService"
    monkeypatch.setattr(registry, "load", lambda r=None: reg)
    assert any("android_impl" in p for p in registry.check(root, "C9")["problems"])


def test_register_check_catches_a_stub_that_returns(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(realityloom.STUB_PROBES, "recon.splat_submit", lambda: "fake job id")
    probs = registry.check(root, "C12")["problems"]
    assert any("recon.splat_submit: stub returned" in p for p in probs)


def test_register_check_requires_gpu_unverified_flag(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = copy.deepcopy(registry.load(root))
    row = next(f for f in reg["features"] if f["id"] == "recon.splatforge")
    row.pop("verified_on_gpu")
    monkeypatch.setattr(registry, "load", lambda r=None: reg)
    assert any("recon.splatforge: real_unverified_on_gpu must carry verified_on_gpu: false" in p for p in registry.check(root, "C12")["problems"])
    assert registry.descriptor("C12", root) and True


def test_register_check_catches_unregistered_locale_key(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = copy.deepcopy(registry.load(root))
    next(f for f in reg["features"] if f["id"] == "recon.splat_submit")["reason_key"] = "stub.recon.nope"
    monkeypatch.setattr(registry, "load", lambda r=None: reg)
    assert any("recon.splat_submit: reason_key" in p for p in registry.check(root, "C12")["problems"])


def test_shared_vectors_are_current(root: Path) -> None:
    on_disk = json.loads((root / "tests" / "fixtures" / "c9_c12_vectors.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(make_vectors())), "run `python -m forge.vectors_c9_c12` (Kotlin reads this file)"


def test_i18n_fails_loudly_on_a_missing_key() -> None:
    from forge.i18n import t
    with pytest.raises(KeyError):
        t("no.such.key")


# ----------------------------------------------------------------------------- C9 MirrorWeave

def test_frame_envelope_validates_and_round_trips() -> None:
    data = png("sharp", 32, 24)
    env = mirrorweave.FrameEnvelope("screen", 1, 5, "screen", "png", 32, 24, data)
    assert mirrorweave.FrameEnvelope.from_wire(json.loads(json.dumps(env.to_wire()))) == env
    for bad in (dict(stream="Bad"), dict(codec="jpeg"), dict(kind="telemetry"), dict(seq=-1), dict(data=b"")):
        kw = dict(stream="s", seq=0, ts_ms=0, kind="screen", codec="png", width=0, height=0, data=data) | bad
        with pytest.raises(ValueError):
            mirrorweave.FrameEnvelope(**kw)
    with pytest.raises(ValueError):                         # video kind needs video bytes; still bytes are refused
        mirrorweave.FrameEnvelope("s", 0, 0, "camera_video", "h264", 0, 0, data)
    with pytest.raises(ValueError):
        mirrorweave.FrameEnvelope("s", 0, 0, "screen", "av1", 0, 0, data)


def test_hub_orders_drops_and_persists(tmp_path: Path) -> None:
    data = png("sharp", 16, 16)
    hub = mirrorweave.FrameHub(tmp_path, ring=2)
    for s in (0, 1, 5):
        hub.accept(mirrorweave.FrameEnvelope("s", s, 1000 + s * 100, "screen", "png", 0, 0, data))
    with pytest.raises(ValueError, match="stale"):
        hub.accept(mirrorweave.FrameEnvelope("s", 5, 1, "screen", "png", 0, 0, data))
    st = hub.stats()["s"]
    assert st["dropped"] == 3 and st["buffered"] == 2 and hub.latest("s").seq == 5
    meta, blob = mirrorweave.load_persisted(tmp_path, "s")
    assert meta["seq"] == 5 and blob == data


def test_loomlink_mirror_routes_enforce_capabilities(tmp_path: Path) -> None:
    from forge.accept_companions import Desktop
    from forge.loomlink import LinkClient

    d = Desktop(tmp_path / "d", allow=("offload", "sync", "mirror", "drive_studio")).start()
    try:
        c = LinkClient(d.srv.url, "p")
        c.pair(d.srv.code, ["mirror", "drive_studio"])
        data = png("sharp", 24, 24)
        assert c.mirror_frame(mirrorweave.FrameEnvelope("screen", 0, 1, "screen", "png", 0, 0, data))["accepted"]
        assert base64.b64decode(c.mirror_latest("screen")["frame"]["data_b64"]) == data
        assert c.mirror_control(mirrorweave.ControlMessage("desktop", "query", "forge.status"))["ok"]
        assert c.mirror_control(mirrorweave.ControlMessage("desktop", "input", "key", {"key": "a"}))["ok"]
        for msg, code in ((mirrorweave.ControlMessage("desktop", "query", "rm -rf /"), 403),
                          (mirrorweave.ControlMessage("android", "input", "tap"), 403),      # phone input is desktop-local only
                          (mirrorweave.ControlMessage("desktop", "focus", "x"), 403),
                          (mirrorweave.ControlMessage("desktop", "input", "key", {"key": "F13"}), 403),   # not allow-listed
                          (mirrorweave.ControlMessage("desktop", "input", "shell", {"cmd": "ls"}), 400)):
            with pytest.raises(urllib.error.HTTPError) as e:
                c.mirror_control(msg)
            assert e.value.code == code, msg
        weak = LinkClient(d.srv.url, "w")
        weak.pair(d.srv.code, ["offload"])
        with pytest.raises(urllib.error.HTTPError) as e:
            weak.mirror_frame(mirrorweave.FrameEnvelope("x", 0, 1, "screen", "png", 0, 0, data))
        assert e.value.code == 403
    finally:
        d.halt()


def test_linkclient_bumps_timestamp_when_two_signs_share_a_millisecond(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server verify() rejects t <= last_ts (ms). Kotlin nextTs already bumps; Python must too."""
    from forge import loomlink
    from forge.loomlink import LinkClient

    monkeypatch.setattr(loomlink.time, "time_ns", lambda: 42_000_000_000)  # always 42000 ms
    c = LinkClient("http://example", "p")
    c.key = b"\x00" * 16
    tss = [int(c._sign("POST", "/mirror/control", b"{}")["X-Loom-Ts"]) for _ in range(8)]
    assert tss == list(range(42_000, 42_008))


def test_linkclient_rapid_signed_queries_are_not_false_replays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge import loomlink
    from forge.accept_companions import Desktop
    from forge.loomlink import LinkClient

    d = Desktop(tmp_path / "d", allow=("offload", "sync", "mirror", "drive_studio")).start()
    try:
        c = LinkClient(d.srv.url, "p")
        c.pair(d.srv.code, ["mirror", "drive_studio"])
        # Freeze the clock after pairing so every subsequent sign would collide without a bump.
        frozen_ms = loomlink.time.time_ns() // 1_000_000
        monkeypatch.setattr(loomlink.time, "time_ns", lambda: frozen_ms * 1_000_000)
        monkeypatch.setattr(loomlink.time, "time", lambda: frozen_ms / 1000.0)
        for _ in range(16):
            assert c.mirror_control(mirrorweave.ControlMessage("desktop", "query", "forge.status"))["ok"]
    finally:
        d.halt()


def test_mirror_input_cli_queues_signed_events(tmp_path: Path) -> None:
    r = CliRunner().invoke(main, ["mirror", "input", "--state-dir", str(tmp_path), "--device", "phone-a", "tap", "--x", "0.5", "--y", "0.5"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["seq"] == 0
    r = CliRunner().invoke(main, ["mirror", "input", "--state-dir", str(tmp_path), "--device", "phone-a", "tap", "--x", "2", "--y", "0"])
    assert r.exit_code == 1                                     # out of range → refused, nothing queued
    rows = mirrorweave.InputOutbox(tmp_path / "mirror" / "outbox").read("phone-a")
    assert [x["event"] for x in rows] == [{"type": "tap", "x": 0.5, "y": 0.5}]


# ----------------------------------------------------------------------------- C10 LensForge

def test_png_decoder_matches_pillow_on_filtered_pngs() -> None:
    PIL = pytest.importorskip("PIL.Image")
    rng = np.random.default_rng(7)
    for mode, ch in (("RGB", 3), ("RGBA", 4), ("L", 1)):
        arr = (rng.integers(0, 256, (40, 56, ch)) if ch > 1 else rng.integers(0, 256, (40, 56))).astype(np.uint8)
        arr[8:20, 8:30] = 128                                    # smooth region → adaptive filters (sub/up/avg/paeth) kick in
        buf = io.BytesIO()
        PIL.fromarray(arr, mode).save(buf, "PNG", optimize=True)
        got, w, h, media = lensforge.decode_gray(buf.getvalue())
        ref = np.asarray(PIL.fromarray(arr, mode).convert("RGB"), dtype=np.int64)
        want = (299 * ref[:, :, 0] + 587 * ref[:, :, 1] + 114 * ref[:, :, 2]) // 1000
        assert (w, h, media) == (56, 40, "image/png") and np.array_equal(got, want), mode


def test_quality_verdicts_and_determinism(root: Path) -> None:
    want = {"sharp": [], "blurry": ["blurry"], "dark": ["too_dark", "clipped"], "bright": ["too_bright", "clipped"]}
    for k, reasons in want.items():
        a = lensforge.assess(png(k), "still", root)
        assert a["reasons"] == reasons and a["verdict"] == ("pass" if not reasons else "warn") and a["advisory"]
    assert lensforge.assess(png("sharp"), "still", root) == lensforge.assess(png("sharp"), "still", root)
    assert "low_resolution" in lensforge.assess(png("sharp", 100, 80), "orbit", root)["reasons"]
    assert lensforge.assess_or_reason(b"junk")["verdict"] == "unassessed"


def test_jpeg_needs_pillow_and_says_so(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    jpg = (root / "tests" / "fixtures" / "capture_640x480.jpg").read_bytes()
    monkeypatch.setitem(sys.modules, "PIL", None)               # simulate Pillow not installed
    with pytest.raises(lensforge.DecodeError, match="Pillow"):
        lensforge.assess(jpg, "still", root)
    assert lensforge.assess(png("sharp"), "still", root)["verdict"] == "pass"      # PNG needs no Pillow
    assert lensforge.assess_or_reason(jpg)["verdict"] == "unassessed"


def test_capture_set_rules_and_stub_modes(root: Path) -> None:
    imgs = [png("sharp", 640, 480, s) for s in (1, 2, 3)]
    ok = lensforge.assess_set(imgs, "burst", root)
    assert ok["verdict"] == "pass" and ok["overlap"] == "not_measured" and ok["best_index"] in (0, 1, 2)
    assert lensforge.assess_set(imgs[:2], "burst", root)["reasons"] == ["too_few_usable_views"]
    dup = lensforge.assess_set([imgs[0], imgs[0], imgs[1], imgs[2]], "burst", root)
    assert dup["duplicates"] == [{"index": 1, "duplicate_of": 0}] and dup["usable_views"] == 3
    assert lensforge.assess_set(imgs, "depth_assist", root)["reasons"] == ["too_few_usable_views"]   # real mode since 0.7.6
    with pytest.raises(ValueError):
        lensforge.assess_set(imgs, "nope", root)


def test_telemetry_contract() -> None:
    t = lensforge.CaptureTelemetry(device="x", focal_length_mm=6.9, iso=100, orientation=6)
    assert lensforge.CaptureTelemetry.from_dict(json.loads(json.dumps(t.to_dict()))) == t
    for bad in ({"iso": 0}, {"orientation": 9}, {"focal_length_mm": 1e9}, {"iso": True}):
        with pytest.raises(ValueError):
            lensforge.CaptureTelemetry(**bad)
    with pytest.raises(ValueError):
        lensforge.CaptureTelemetry.from_dict({"gps": 1})


def test_exif_read_leaves_missing_tags_unset() -> None:
    PIL = pytest.importorskip("PIL.Image")
    ex = PIL.Exif()
    ex[0x0112] = 6
    ex.get_ifd(0x8769)[0x920A] = 6.9
    buf = io.BytesIO()
    PIL.new("RGB", (8, 8)).save(buf, "JPEG", exif=ex)
    e = lensforge.read_exif(buf.getvalue())
    assert e.focal_length_mm == pytest.approx(6.9) and e.orientation == 6 and e.iso is None and e.sensor_width_mm is None


def test_loomlink_offload_assesses_captures(tmp_path: Path, root: Path) -> None:
    from forge.accept_companions import Desktop
    from forge.loomlink import LinkClient

    d = Desktop(tmp_path / "d").start()
    try:
        c = LinkClient(d.srv.url, "p")
        c.pair(d.srv.code, ["offload"])
        r = c.offload({"id": "j", "op": "recon.capture",
                       "payload": {"id": "cap_1", "data_b64": base64.b64encode(png("blurry")).decode(), "media": "image/png"}})
        assert r["value"]["reconstruction"] == "stub" and r["value"]["quality"]["reasons"] == ["blurry"]
        assert d.srv.store.entries["cap_1"]["provenance"]["quality"] == r["value"]["quality"]
    finally:
        d.halt()


# ----------------------------------------------------------------------------- C11 depth

def test_pinhole_distance_has_analytic_ground_truth() -> None:
    f = depth.focal_px(4000, 6.9, 9.6)
    assert f == pytest.approx(2875.0)
    d = depth.distance_to_object(0.30, 120.0, f)
    assert d["distance_m"] == pytest.approx(7.1875) and d["lo_m"] < d["distance_m"] < d["hi_m"]
    assert depth.distance_to_object(0.30, 60.0, f)["distance_m"] == pytest.approx(2 * d["distance_m"])
    assert depth.focal_px(1920, hfov_deg=90.0) == pytest.approx(960.0)
    assert depth.focal_px(640, 4.0, 5.6, 28.0) == pytest.approx(4.0 / 5.6 * 640)     # mm+sensor outranks 35 mm-equiv
    with pytest.raises(ValueError, match="focal length"):
        depth.focal_px(1000)                                                          # refuses to guess optics


def test_inverse_depth_alignment_recovers_metric_depth() -> None:
    ys, xs = np.mgrid[0:48, 0:64]
    z = 2.0 + 0.02 * xs + 0.01 * ys
    rel = 0.37 / z + 0.05
    anchors = [depth.Anchor(2, 2, float(z[2, 2])), depth.Anchor(60, 40, float(z[40, 60])), depth.Anchor(30, 20, float(z[20, 30]))]
    al = depth.align_inverse_depth(rel, anchors)
    assert float(np.nanmax(np.abs(al["depth_m"] - z))) < 1e-9 and al["invalid_fraction"] == 0.0
    for bad in (anchors[:1], [depth.Anchor(99, 99, 1.0), depth.Anchor(0, 0, 2.0)], [depth.Anchor(0, 0, -1.0), depth.Anchor(5, 5, 2.0)]):
        with pytest.raises(ValueError):
            depth.align_inverse_depth(rel, bad)
    with pytest.raises(ValueError, match="not positive"):
        depth.align_inverse_depth(-rel, anchors)                                      # inverted polarity is refused, not flipped


def test_arcore_depth_ingest_synthetic_frame(root: Path) -> None:
    from forge import arcore
    fr = arcore.synthetic_frame(160, 120)
    v = depth.ARCoreDepth().ingest(arcore.payload(fr["depth_mm"], fr["confidence"], [0, 0, 0, 0, 0, 0, 1], {"image_w": 640, "image_h": 480}))
    vec = json.loads((root / "tests" / "fixtures" / "arcore_vectors.json").read_text())
    assert v["anchors"] == vec["anchors_160x120_640x480"] and v["dense"] == {"skipped": "no_image"}
    assert all(a["depth_m"] > 0 for a in v["anchors"]) and 0 < v["valid_fraction"] < 1


def test_arcore_pose_coverage_orbit() -> None:
    import math

    from forge import arcore
    from forge.accept_c9_c12 import _orbit_poses
    c = arcore.coverage(_orbit_poses())
    assert abs(c["angular_spread_deg"] - 180) < 1e-3 and abs(c["max_step_deg"] - 15) < 1e-3 and abs(c["max_baseline_m"] - 1.2) < 1e-6
    assert arcore.coverage([[0, 0, 0, 0, 0, 0, 1]])["path_m"] == 0.0
    with pytest.raises(ValueError):
        arcore.coverage([[0, 0, 0, 0, 0, math.nan, 1]])


def test_dense_depth_without_weights_names_the_fetch_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_MODELS_DIR", str(tmp_path))          # empty models dir → refuse with the remedy, no fake map
    with pytest.raises(FileNotFoundError, match="forge models fetch depth-anything-v2-small"):
        depth.DepthAnythingV2()


def test_render_scene_depth_is_analytic() -> None:
    sc = depth.render_scene(64, 48, pitch_deg=0.0, cam_h=1.5)
    d = sc["depth_m"]
    # bottom-centre ray with zero pitch hits the ground at z = cam_h * f / (y_px offset)
    f = sc["focal_px"]
    y = 47
    want = 1.5 * f / ((y + 0.5) - 24)
    assert abs(d[y, 60] - want) < 1e-9          # column 60 is right of the crate
    assert np.nanmax(d) <= 9.0 + 1e-9 and sc["rgb"].dtype == np.uint8


# ----------------------------------------------------------------------------- C12 reconstruction path

def test_routing_bundle_and_plan(tmp_path: Path, root: Path) -> None:
    assert realityloom.route("backdrop")["route"] == "splat"
    assert realityloom.route("hero_prop") == {"target": "hero_prop", "route": "photogrammetry", "alternatives": ["meshweaver"],
                                              "spec": "§7 phase 2"}
    with pytest.raises(ValueError):
        realityloom.route("nope")
    imgs = [png("sharp", 640, 480, s) for s in range(1, 5)]
    m = realityloom.write_bundle(tmp_path / "b", imgs, "backdrop", "burst", root)
    assert m == realityloom.bundle_manifest(list(imgs), "backdrop", "burst", root)
    assert realityloom.bundle_manifest(imgs[::-1], "backdrop", "burst", root)["capture_set_sha256"] == m["capture_set_sha256"]
    assert len([p for p in (tmp_path / "b" / "objects").rglob("*") if p.is_file()]) == 4
    cpu = realityloom.plan(m, ["cpu"], tools={})
    assert (cpu["effective_route"], cpu["degraded_from"], cpu["runnable_today"], cpu["eta_measured"]) == ("photogrammetry", "splat", True, False)   # CPU route real since 0.7.7
    gpu = realityloom.plan(m, ["cpu", "rocm"], tools={})
    assert gpu["effective_route"] == "splat" and gpu["blocked_by"] == [] and gpu["runnable_today"] is True     # 0.9.2
    assert gpu["unverified_on_gpu"] == ["recon.splatforge"] and gpu["cluster_submit"] == "stub: recon.splat_submit"
    assert next(s for s in gpu["stages"] if s["id"] == "train_splat")["requires"] == {"device": "rocm"}
    few = realityloom.plan(realityloom.bundle_manifest(imgs[:1], "backdrop", "burst", root), ["cpu"], tools={})
    assert few["problems"] and "no runnable route" in few["eta"]


def test_splat_ply_validator() -> None:
    assert realityloom.check_splat_ply(realityloom.make_test_ply(7, 45))["sh_degree"] == 3
    data = realityloom.make_test_ply(4, 9)
    for blob in (b"hello", data.replace(b"binary_little_endian", b"ascii"), data[:-4], data.replace(b"scale_1", b"scale_x"),
                 realityloom.make_test_ply(2, 5), data.replace(b"element vertex 4", b"element vertex 0")):
        with pytest.raises(ValueError, match="splat"):
            realityloom.check_splat_ply(blob)


def test_recon_stubs_refuse_and_cli_exit_3() -> None:
    for stage in ("splat",):                                    # photogrammetry/mesh/godot-import are real since 0.7.7
        r = CliRunner().invoke(main, ["recon", "train", "--stage", stage])
        assert r.exit_code == 3 and is_stub_message(json.loads(r.output)["message"])


def test_submit_checks_placement_then_refuses(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = realityloom.bundle_manifest([png("sharp", 640, 480, s) for s in range(1, 5)], "backdrop", "burst", root)
    monkeypatch.setattr(realityloom, "cluster_devices", lambda url: {"a": ["cpu"], "b": ["cpu", "vulkan"]})
    with pytest.raises(RuntimeError, match="No cluster node advertises rocm"):
        realityloom.submit(m, "http://x")
    monkeypatch.setattr(realityloom, "cluster_devices", lambda url: {"a": ["cpu"], "g": ["cpu", "rocm"]})
    with pytest.raises(StubError) as e:
        realityloom.submit(m, "http://x")
    assert e.value.feature == "recon.splatforge"


# ----------------------------------------------------------------------------- GroundWeave planned ops

def test_ladder_declares_new_ops_and_planned_ops_select_nothing(root: Path) -> None:
    r = gw.check(root)
    assert r["ok"], r["problems"]
    ladder = gw.load_ladder(root)["ops"]
    for op in ("mirror.encode", "lens.assess", "depth.distance", "recon.plan", "recon.mesh", "shuttle.gdgs"):
        assert gw.select(op, ["cpu", *gw.SIMULATED_GPU_DEVICES], root)["device"] == "cpu"
    # 0.9.2: DepthAnything's ROCm/DirectML rungs are real code paths (forge.onnx_ep) but never ran on a GPU → verified: false
    assert ladder["depth.estimate"]["ladder"][0] == {"id": "depthanything-v2-onnx", "device": "rocm", "impl": "real", "verified": False}
    sel = gw.select("depth.estimate", ["cpu", *gw.SIMULATED_GPU_DEVICES], root)
    assert (sel["device"], sel["verified"]) == ("rocm", False)
    assert gw.select("depth.estimate", ["cpu"], root)["backend"] == "depthanything-v2-onnx-cpu"
    for op in ("recon.mesh", "shuttle.gdgs"):                   # GPU rungs stay planned above the CPU rung (0.7.7)
        assert ladder[op]["ladder"][0]["impl"] == "planned" and ladder[op]["ladder"][-1]["device"] == "cpu"
    assert ladder["recon.splat"]["gpu_required"] and ladder["recon.splat"]["route"] == "loomcluster"


def test_check_rejects_planned_op_that_claims_a_real_rung(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = copy.deepcopy(gw.load_ladder(root))
    bad["ops"]["shuttle.gdgs"]["planned"] = True                  # a planned op keeping its real CPU rung → rejected
    bad["ops"]["shuttle.gdgs"]["route"] = "local"
    bad["ops"]["recon.mesh"]["planned"] = True                    # planned without a route → rejected
    bad["ops"]["recon.mesh"].pop("route", None)
    monkeypatch.setattr(gw, "load_ladder", lambda r=None: bad)
    probs = gw.check(root)["problems"]
    assert any("shuttle.gdgs: planned op must not claim a real backend" in p for p in probs)
    assert any("recon.mesh: planned op must declare route" in p for p in probs)


def test_two_core_gpu_hidden_run_of_new_cpu_ops_is_byte_identical(root: Path) -> None:
    r = gw.verify(root, ops=["mirror.encode", "lens.assess", "depth.distance", "depth.estimate", "recon.plan"])
    assert r["ok"], r
    by = {x["op"]: x for x in r["results"]}
    assert by["depth.estimate"]["status"] in ("ok", "model_absent")      # weights are heavy: absent in CI
    for op in ("mirror.encode", "lens.assess", "depth.distance", "recon.plan"):
        x = by[op]
        assert x["device"] == "cpu" and x["cores"] == 2 and x["identical_to_unpinned"] and x["identical_with_simulated_gpu"]


def test_acceptance_registered(root: Path) -> None:
    assert CX_ORDER == ["C9", "C10", "C11", "C12"]
    for m in CX_ORDER:
        assert m in INCREMENTS and INCREMENTS[m].runner is not None


def test_loomlink_offload_depth_arcore(tmp_path: Path) -> None:
    from forge import arcore
    from forge.accept_companions import Desktop
    from forge.loomlink import LinkClient

    fr = arcore.synthetic_frame(32, 24)
    d = Desktop(tmp_path / "d").start()
    try:
        c = LinkClient(d.srv.url, "p")
        c.pair(d.srv.code, ["offload"])
        r = c.offload({"id": "a", "op": "depth.arcore",
                       "payload": arcore.payload(fr["depth_mm"], fr["confidence"], [0.1, 0, 0, 0, 0, 0, 1], {"image_w": 320, "image_h": 240})})
        assert r["ok"] and r["value"]["width"] == 32 and r["value"]["anchors"] and r["value"]["dense"] == {"skipped": "no_image"}
        bad = c.offload({"id": "b", "op": "depth.arcore", "payload": {"width": 4, "height": 4, "depth_u16_b64": "AAAA"}})
        assert not bad["ok"] and "mismatch" in bad["error"]
    finally:
        d.halt()
