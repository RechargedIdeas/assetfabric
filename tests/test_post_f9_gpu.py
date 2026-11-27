"""Post-F9 batch 2 (0.9.2): AMD-first ONNX EP selection (forge.onnx_ep) and the full-scale SplatForge runner
(forge.splatforge_gpu). No GPU here: GPU paths are exercised against a fake onnxruntime / the contract-probe trainer, and
every status says `rocm_ready_unverified` / `real_unverified_on_gpu`."""
from __future__ import annotations

import copy
import json
import shlex
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from forge import groundweave as gw
from forge import onnx_ep, realityloom
from forge import splatforge_gpu as sg


# ----------------------------------------------------------------------------- onnx_ep

def test_onnx_ep_contract_against_fake_ort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(onnx_ep.EP_ENV, raising=False)
    r = onnx_ep.selftest()
    assert r["ok"], r["cases"]
    assert r["status"] == "rocm_ready_unverified" and r["host"]["verified_on_gpu"] is False


def test_onnx_ep_env_and_hip_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    f = onnx_ep.FakeOrt([*onnx_ep.DEVICE_EPS["rocm"], onnx_ep.CPU])
    monkeypatch.setenv(onnx_ep.EP_ENV, "cpu")
    assert onnx_ep.plan(f, ["cpu", "rocm"])["providers"] == [onnx_ep.CPU]
    monkeypatch.setenv(onnx_ep.EP_ENV, "directml")           # preferred device not offered → CPU, reason recorded
    p = onnx_ep.plan(f, ["cpu", "rocm"])
    assert p["providers"] == [onnx_ep.CPU] and p["skipped"][0]["device"] == "directml"
    monkeypatch.delenv(onnx_ep.EP_ENV)
    monkeypatch.setenv(gw.DEVICE_ENV, "cpu,rocm")
    assert onnx_ep.plan(f)["device"] == "rocm"
    monkeypatch.delenv(gw.DEVICE_ENV)
    monkeypatch.setattr(gw, "_probe_devices", lambda: ("cpu", "rocm"))
    monkeypatch.setenv("HIP_VISIBLE_DEVICES", "-1")
    assert onnx_ep.plan(f)["device"] == "cpu"


def test_real_onnxruntime_sessions_go_through_onnx_ep(root: Path) -> None:
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnx")
    from forge import girt_onnx
    model = girt_onnx.to_onnx(girt_onnx.load_policy(root))
    s = girt_onnx.session(model)
    assert isinstance(s, onnx_ep.Session) and s.info["providers"] == [onnx_ep.CPU] and not s.on_gpu
    r = girt_onnx.parity(root, n=200)
    assert r["ok"], r


def test_depth_session_reports_ep(monkeypatch: pytest.MonkeyPatch) -> None:
    from forge import depth, models
    if not models.status(depth.MODEL_ID, verify=False)["ready"]:
        pytest.skip("DepthAnything weights not fetched")
    est = depth.DepthAnythingV2(threads=1)
    est.estimate_rgb(depth.render_scene(64, 48)["rgb"])
    assert est.ep["active"][0] == onnx_ep.CPU and est.ep["device"] == "cpu"


# ----------------------------------------------------------------------------- ladder honesty

def test_real_gpu_rungs_must_declare_verified(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = copy.deepcopy(gw.load_ladder(root))
    bad["ops"]["recon.splat"]["ladder"][0].pop("verified")
    bad["ops"]["depth.estimate"]["ladder"][0]["verified"] = True
    monkeypatch.setattr(gw, "load_ladder", lambda r=None: bad)
    probs = gw.check(root)["problems"]
    assert any("recon.splat: real rocm backend opensplat-rocm must declare verified" in p for p in probs)
    assert any("depth.estimate: backend depthanything-v2-onnx verified: true needs an evidence path" in p for p in probs)


def test_no_ladder_rung_claims_gpu_verification(root: Path) -> None:
    for op_id, op in gw.load_ladder(root)["ops"].items():
        for st in op["ladder"]:
            assert st.get("verified") is not True, (op_id, st)


# ----------------------------------------------------------------------------- SplatForge runner

@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, float]:
    from forge import photogrammetry as pg
    sc = pg.render_views(9)
    b = tmp_path_factory.mktemp("gpu") / "bundle"
    realityloom.write_bundle(b, [pg.png_bytes(im) for im in sc["images"]], "backdrop", "sweep")
    return b, float(sc["K"][0, 0])


def test_c2w_convention_round_trip() -> None:
    rng = np.random.default_rng(1)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    R = q * np.sign(np.linalg.det(q))
    tv = rng.normal(size=3)
    m = sg.c2w_gl(R, tv)
    R2, t2 = sg.w2c_cv(m)
    assert np.allclose(R, R2) and np.allclose(tv, t2)
    assert np.allclose(m[:3, 3], -R.T @ tv)                          # camera centre
    assert np.allclose(m[:3, 2], -R[2])                              # OpenGL: camera looks down −z


def test_runner_contract_probe_end_to_end(bundle: tuple[Path, float]) -> None:
    b, f = bundle
    r = sg.GpuSplatRunner(iters=50, contract_probe=True, focal_px=f)
    out = r.train(b)
    info = realityloom.check_splat_ply(out.read_bytes())
    assert info["sh_degree"] == 3 and info["vertices"] == r.last["project"]["points"] >= 20
    doc = json.loads((b / "splat_gpu" / "train.json").read_text())
    assert doc["status"] == "real_unverified_on_gpu" and doc["verified_on_gpu"] is False and doc["contract_probe"] is True
    cfg = json.loads((b / "splat_gpu" / "config.json").read_text())
    assert cfg["seed_honoured_by_trainer"] is False and cfg["iters"] == 50 and str(b) not in json.dumps(cfg)
    first = doc["config_sha256"]
    r.train(b)
    assert r.last["config_sha256"] == first                         # deterministic config + project


def test_runner_refuses_without_rocm_or_trainer(bundle: tuple[Path, float], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    b, _ = bundle
    with pytest.raises(sg.SplatRunError, match="ROCm"):
        sg.GpuSplatRunner(devices=["cpu"]).train(b)
    monkeypatch.delenv(sg.CMD_ENV, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(sg.SplatRunError, match=sg.CMD_ENV):
        sg.GpuSplatRunner(devices=["cpu", "rocm"]).train(b)
    with pytest.raises(sg.SplatRunError, match="out of range"):
        sg.GpuSplatRunner(sh_degree=7)


def test_runner_uses_env_template_and_default_opensplat_argv(bundle: tuple[Path, float], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    b, f = bundle
    fake = tmp_path / "opensplat"                     # a fake `opensplat` on PATH: records argv, delegates to the probe
    log = tmp_path / "argv.json"
    fake.write_text(f"#!{sys.executable}\nimport json,sys,subprocess\njson.dump(sys.argv[1:], open({str(log)!r},'w'))\n"
                    "a=sys.argv[1:]\n"
                    f"sys.exit(subprocess.call([{sys.executable!r},'-m','forge.splatforge_gpu','probe-trainer',a[0],'-n',a[2],'-o',a[4],'--sh-degree',a[6]]))\n")
    fake.chmod(0o755)
    monkeypatch.delenv(sg.CMD_ENV, raising=False)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("PYTHONPATH", str(Path(sg.__file__).resolve().parents[1]))
    r = sg.GpuSplatRunner(iters=123, downscale=2, focal_px=f, devices=["cpu", "rocm"])
    r.train(b)
    argv = json.loads(log.read_text())
    assert argv[1:] == ["-n", "123", "-o", str(b / "splat_gpu" / "point_cloud.ply"), "--sh-degree", "3", "-d", "2.0"]
    assert r.last["trainer"]["source"] == "opensplat on PATH" and r.last["device"] == "rocm" and r.last["contract_probe"] is False
    monkeypatch.setenv(sg.CMD_ENV, sg.PROBE_CMD)
    r2 = sg.GpuSplatRunner(iters=5, focal_px=f, devices=["cpu", "rocm"])
    r2.train(b)
    assert r2.last["trainer"]["source"] == sg.CMD_ENV and r2.last["verified_on_gpu"] is False


def test_probe_trainer_catches_a_wrong_camera_convention(bundle: tuple[Path, float], tmp_path: Path) -> None:
    b, f = bundle
    proj = sg.export_project(b, tmp_path / "data", f)
    assert proj["frames"] >= 6
    tr = json.loads((tmp_path / "data" / "transforms.json").read_text())
    for fr in tr["frames"]:                          # drop the OpenCV→OpenGL axis flip: cameras now look away from the scene
        m = np.asarray(fr["transform_matrix"])
        m[:3, :3] = m[:3, :3] @ np.diag([1.0, -1.0, -1.0])
        fr["transform_matrix"] = m.tolist()
    (tmp_path / "data" / "transforms.json").write_text(json.dumps(tr))
    p = subprocess.run([sys.executable, "-m", "forge.splatforge_gpu", "probe-trainer", str(tmp_path / "data"), "-o",
                        str(tmp_path / "x.ply")], capture_output=True, text=True, timeout=120)
    assert p.returncode == 1 and "camera convention" in p.stderr


def test_runner_rejects_bad_trainer_output(bundle: tuple[Path, float]) -> None:
    b, f = bundle
    py = shlex.quote(sys.executable)
    far = (f"{py} -c \"import sys; from forge.realityloom import make_test_ply as m; d=m(50,45); "
           f"h=d.index(b'end_header')+11; import numpy as n; a=n.frombuffer(d[h:],'<f4').copy().reshape(50,-1); a[:,0]=1e6; "
           f"open(sys.argv[1],'wb').write(d[:h]+a.tobytes())\" {{out}}")
    with pytest.raises(sg.SplatRunError, match="near the SfM scene"):
        sg.GpuSplatRunner(iters=5, trainer_cmd=far, contract_probe=True, focal_px=f).train(b)
    with pytest.raises(sg.SplatRunError, match="code 7"):
        sg.GpuSplatRunner(iters=5, trainer_cmd=f"{py} -c \"import sys; sys.exit(7)\"", contract_probe=True, focal_px=f).train(b)


def test_cli_stage_splat_contract_probe(root: Path, bundle: tuple[Path, float]) -> None:
    b, f = bundle
    p = subprocess.run([sys.executable, "-m", "forge.cli", "recon", "train", str(b), "--stage", "splat", "--contract-probe",
                        "--iters", "20", "--focal-px", str(f)], cwd=root, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    d = json.loads(p.stdout)
    assert d["status"] == "real_unverified_on_gpu" and d["ply"]["sh_degree"] == 3
    p = subprocess.run([sys.executable, "-m", "forge.cli", "recon", "train", str(b), "--stage", "splat"], cwd=root,
                       capture_output=True, text=True, timeout=120, env={**__import__("os").environ, gw.DEVICE_ENV: "cpu"})
    assert p.returncode == 1 and "ROCm" in json.loads(p.stdout)["error"]
