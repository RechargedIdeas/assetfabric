"""SplatForge full-scale runner (C12, post-F9 0.9.2) — external OpenSplat/gsplat-class trainer on a ROCm node.

SPEC §4 "SplatForge — 3DGS training from capture (C12)", §7 "OpenSplat+ROCm on Linux (7900)", §9 AMD honesty. INFERENCE C-102.

Pipeline (each step real and tested; the trainer binary is the only external part):
  1. capture bundle (`forge recon bundle`) → CPU SfM (`forge.photogrammetry.reconstruct`: poses + sparse cloud),
  2. export a **nerfstudio project** — `transforms.json` (per-frame intrinsics + camera-to-world in the OpenGL/nerfstudio
     convention) + `images/` + `sparse_pc.ply` (`ply_file_path`), the input format OpenSplat reads [INFERENCE C-102: keys
     taken from OpenSplat's nerfstudio.cpp reader; OpenSplat needs sparse points, random init is unsupported],
  3. a deterministic `config.json` (sorted keys, no host paths, no timestamps) whose SHA-256 names the run,
  4. the trainer command from a template — `FORGE_SPLAT_CMD` / `--trainer-cmd`, default
     `opensplat {data} -n {iters} -o {out} --sh-degree {sh_degree} -d {downscale}` — run with a timeout, log captured,
  5. the output `.ply` validated by `realityloom.check_splat_ply` (INRIA layout, SH degree, body size) plus finite
     positions inside a generous multiple of the SfM bounds; `train.json` records config SHA, ply SHA, argv, timings.

Device rule: the run refuses unless GroundWeave reports `rocm` (the `recon.splat` op is gpu_required, route loomcluster) —
except with `contract_probe=True`, which is how pytest / `forge accept C12` exercise the whole runner contract on CPU with
the bundled **contract-probe trainer** (`python -m forge.splatforge_gpu probe-trainer …`). That probe does NOT train: it
checks the exported project (cameras re-project the sparse cloud into the images) and writes a valid SH-3 `.ply` seeded from
the sparse points. Its output is labelled `contract_probe: true` and never counts as a reconstruction.

Status honesty: `real_unverified_on_gpu`. The runner has never executed a real trainer on an AMD GPU (the build box has no
GPU and no OpenSplat build); OpenSplat exposes no RNG seed, so GPU output is not claimed bit-reproducible — only the
config and the exported project are. OpenSplat is AGPL-3.0: invoked as an external program, never bundled or linked.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from forge.i18n import t

STATUS = "real_unverified_on_gpu"
CMD_ENV = "FORGE_SPLAT_CMD"
DEFAULT_CMD = "opensplat {data} -n {iters} -o {out} --sh-degree {sh_degree} -d {downscale}"
PROBE_CMD = f"{shlex.quote(sys.executable)} -m forge.splatforge_gpu probe-trainer {{data}} -n {{iters}} -o {{out}} --sh-degree {{sh_degree}}"
SCHEMA = "splatforge-gpu-config/1"
_GL = np.diag([1.0, -1.0, -1.0])     # OpenCV camera axes (x right, y down, z fwd) ↔ OpenGL/nerfstudio (y up, z back)


class SplatRunError(RuntimeError):
    """A refusal or a failed external run — the message is a locale string; nothing is fabricated."""


def _sniff_ext(b: bytes) -> str:
    if b.startswith(b"\x89PNG"):
        return ".png"
    if b[:3] == b"\xff\xd8\xff":
        return ".jpg"
    raise SplatRunError(t("recon.splat.gpu.bad_image"))


def c2w_gl(R: np.ndarray, tv: np.ndarray) -> np.ndarray:
    """World→camera (OpenCV, x_c = R X + t) → camera→world 4×4 in the nerfstudio/OpenGL convention."""
    R = np.asarray(R, float)
    tv = np.asarray(tv, float).reshape(3)
    m = np.eye(4)
    m[:3, :3] = R.T @ _GL
    m[:3, 3] = -R.T @ tv
    return m


def w2c_cv(c2w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c2w = np.asarray(c2w, float)
    R = (c2w[:3, :3] @ _GL).T
    return R, -R @ c2w[:3, 3]


def export_project(bundle: Path, out: Path, focal_px: float | None = None) -> dict[str, Any]:
    """Capture bundle → CPU SfM → nerfstudio project directory `out` (transforms.json, images/, sparse_pc.ply)."""
    from forge import photogrammetry
    bundle, out = Path(bundle), Path(out)
    m = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    raw = [(bundle / "objects" / v["sha256"][:2] / v["sha256"]).read_bytes() for v in m["views"]]
    imgs = [photogrammetry._decode(b) for b in raw]
    rec = photogrammetry.reconstruct(imgs, focal_px=focal_px)
    if len(rec["registered"]) < 3 or len(rec["points"]) < 20:
        raise SplatRunError(t("recon.splat.sfm_failed", registered=len(rec["registered"]), points=len(rec["points"])))
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)
    K = np.asarray(rec["K"], float)
    frames = []
    for i, pose in enumerate(rec["poses"]):
        if pose is None:
            continue
        name = f"images/frame_{i:05d}{_sniff_ext(raw[i])}"
        (out / name).write_bytes(raw[i])
        h, w = imgs[i].shape[:2]
        frames.append({"file_path": name, "w": int(w), "h": int(h), "fl_x": float(K[0, 0]), "fl_y": float(K[1, 1]),
                       "cx": float(K[0, 2]), "cy": float(K[1, 2]),
                       "transform_matrix": np.round(c2w_gl(pose[0], pose[1]), 9).tolist(),
                       "view_sha256": m["views"][i]["sha256"]})
    tr = {"camera_model": "OPENCV", "frames": frames, "ply_file_path": "sparse_pc.ply"}
    (out / "transforms.json").write_text(json.dumps(tr, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "sparse_pc.ply").write_bytes(photogrammetry.write_points_ply(rec["points"], rec["colors"]))
    pts = np.asarray(rec["points"], float)
    return {"frames": len(frames), "views": len(m["views"]), "points": int(len(pts)),
            "bounds": [pts.min(0).round(6).tolist(), pts.max(0).round(6).tolist()],
            "transforms_sha256": hashlib.sha256((out / "transforms.json").read_bytes()).hexdigest(),
            "sparse_sha256": hashlib.sha256((out / "sparse_pc.ply").read_bytes()).hexdigest(),
            "capture_set_sha256": m["capture_set_sha256"]}


def trainer_template(cmd: str | None = None, contract_probe: bool = False) -> tuple[str, str]:
    """(template, source). Order: explicit → contract probe → FORGE_SPLAT_CMD → `opensplat` on PATH → refuse."""
    if cmd:
        return cmd, "argument"
    if contract_probe:
        return PROBE_CMD, "contract_probe"
    if os.environ.get(CMD_ENV):
        return os.environ[CMD_ENV], CMD_ENV
    if shutil.which("opensplat"):
        return DEFAULT_CMD, "opensplat on PATH"
    raise SplatRunError(t("recon.splat.gpu.no_trainer", env=CMD_ENV))


class GpuSplatRunner:
    """Full-scale SplatForge training through an external trainer (OpenSplat on ROCm by default). See module docstring."""

    def __init__(self, iters: int = 30000, sh_degree: int = 3, downscale: float = 1.0, seed: int = 0,
                 trainer_cmd: str | None = None, timeout_s: float = 6 * 3600, focal_px: float | None = None,
                 contract_probe: bool = False, devices: list[str] | None = None) -> None:
        if not 1 <= int(iters) <= 1_000_000 or int(sh_degree) not in (1, 2, 3) or not 1.0 <= float(downscale) <= 16.0:
            raise SplatRunError(t("recon.splat.gpu.bad_config", iters=iters, sh=sh_degree, downscale=downscale))
        self.iters, self.sh_degree, self.downscale, self.seed = int(iters), int(sh_degree), float(downscale), int(seed)
        self.trainer_cmd, self.timeout_s, self.focal_px = trainer_cmd, float(timeout_s), focal_px
        self.contract_probe, self.devices = contract_probe, devices
        self.last: dict[str, Any] = {}

    def device(self) -> str:
        if self.contract_probe:
            return "cpu"
        from forge import groundweave
        devs = self.devices if self.devices is not None else groundweave.detect_devices()
        if "rocm" not in devs:
            raise SplatRunError(t("recon.splat.gpu.no_device", devices=",".join(devs) or "none"))
        return "rocm"

    def config(self, project: dict[str, Any], template: str) -> dict[str, Any]:
        return {"schema": SCHEMA, "trainer_template": template, "iters": self.iters, "sh_degree": self.sh_degree,
                "downscale": self.downscale, "seed": self.seed, "seed_honoured_by_trainer": False,
                "input": {k: project[k] for k in ("capture_set_sha256", "transforms_sha256", "sparse_sha256", "frames", "points")},
                "contract_probe": self.contract_probe}

    def train(self, bundle: Path) -> Path:
        bundle = Path(bundle)
        device = self.device()                                   # refuse before any work when no ROCm node is here
        template, source = trainer_template(self.trainer_cmd, self.contract_probe)
        work = bundle / "splat_gpu"
        work.mkdir(exist_ok=True)
        t0 = time.perf_counter()
        project = export_project(bundle, work / "data", self.focal_px)
        export_s = time.perf_counter() - t0
        cfg = self.config(project, template)
        cfg_bytes = (json.dumps(cfg, indent=2, sort_keys=True) + "\n").encode()
        (work / "config.json").write_bytes(cfg_bytes)
        out = work / "point_cloud.ply"
        out.unlink(missing_ok=True)
        fields = {"data": shlex.quote(str(work / "data")), "out": shlex.quote(str(out)), "iters": self.iters,
                  "sh_degree": self.sh_degree, "downscale": self.downscale, "seed": self.seed}
        try:
            argv = shlex.split(template.format(**fields))
        except (KeyError, ValueError) as e:
            raise SplatRunError(t("recon.splat.gpu.bad_template", why=f"{type(e).__name__}: {e}")) from e
        env = dict(os.environ)
        if self.contract_probe:
            env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parents[1]), env.get("PYTHONPATH", "")])
        t1 = time.perf_counter()
        try:
            p = subprocess.run(argv, cwd=work, capture_output=True, text=True, timeout=self.timeout_s, env=env)
        except FileNotFoundError as e:
            raise SplatRunError(t("recon.splat.gpu.no_trainer", env=CMD_ENV)) from e
        except subprocess.TimeoutExpired as e:
            out.unlink(missing_ok=True)
            raise SplatRunError(t("recon.splat.gpu.timeout", seconds=int(self.timeout_s))) from e
        train_s = time.perf_counter() - t1
        (work / "trainer.log").write_text((p.stdout or "") + (p.stderr or ""), encoding="utf-8")
        if p.returncode != 0:
            raise SplatRunError(t("recon.splat.gpu.trainer_failed", code=p.returncode, tail=((p.stderr or p.stdout or "")[-300:]).strip()))
        if not out.is_file():
            raise SplatRunError(t("recon.splat.gpu.no_output", path=out.name))
        data = out.read_bytes()
        info = check_output(data, project["bounds"])
        doc = {"status": STATUS, "verified_on_gpu": False, "contract_probe": self.contract_probe, "device": device,
               "trainer": {"source": source, "argv0": Path(argv[0]).name, "returncode": p.returncode},
               "config_sha256": hashlib.sha256(cfg_bytes).hexdigest(), "ply_sha256": hashlib.sha256(data).hexdigest(),
               "ply": info, "project": project, "export_s": round(export_s, 3), "train_s": round(train_s, 3),
               "note": t("recon.splat.gpu.probe_note") if self.contract_probe else t("recon.splat.gpu.unverified_note")}
        (work / "train.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.last = {**doc, "ply_path": str(out), "work": str(work)}
        return out


def check_output(data: bytes, bounds: list[list[float]], slack: float = 10.0) -> dict[str, Any]:
    """`check_splat_ply` + finite positions inside `slack` × the SfM bounding box (catches garbage/NaN trainer output)."""
    from forge.realityloom import check_splat_ply
    info = check_splat_ply(data)
    end = data.find(b"end_header\n") + len(b"end_header\n")
    arr = np.frombuffer(data[end:], "<f4").reshape(info["vertices"], info["properties"])
    xyz = arr[:, :3].astype(float)
    if not np.isfinite(arr).all():
        raise SplatRunError(t("recon.splat.gpu.bad_output", why="non-finite values"))
    lo, hi = np.asarray(bounds[0], float), np.asarray(bounds[1], float)
    c, half = (lo + hi) / 2, np.maximum((hi - lo) / 2, 1e-6) * slack
    inside = float(np.mean(np.all(np.abs(xyz - c) <= half, axis=1)))
    if inside < 0.95:
        raise SplatRunError(t("recon.splat.gpu.bad_output", why=f"only {inside:.0%} of splats near the SfM scene"))
    return {**info, "inside_scene_frac": round(inside, 4)}


# ------------------------------------------------------------------------------------------------ LoomCluster job (0.9.2)
# `forge recon submit BUNDLE --cluster URL` → LoomCluster op `recon.splat` with `requires: {device: rocm}`: the fleet's
# negotiated placement sends it to a node that advertises ROCm; that node unpacks the bundle (every object re-hashed),
# runs `GpuSplatRunner` with ITS OWN trainer (node env FORGE_SPLAT_CMD / opensplat on PATH — a payload can never name a
# command) and returns point_cloud.ply / train.json / config.json as hash-verified blobs (Q6 blob path).

PACK_MAX_BYTES = 256 << 20
PACK_SCHEMA = "splatforge-bundle/1"


def pack_bundle(bundle: Path) -> dict[str, Any]:
    """Capture bundle → JSON-safe dict (bundle.json + the content-addressed view objects it references)."""
    import base64
    bundle = Path(bundle)
    raw = (bundle / "bundle.json").read_bytes()
    m = json.loads(raw)
    objs: dict[str, str] = {}
    total = len(raw)
    for v in m["views"]:
        sha = v["sha256"]
        if sha in objs:
            continue
        b = (bundle / "objects" / sha[:2] / sha).read_bytes()
        if hashlib.sha256(b).hexdigest() != sha:
            raise SplatRunError(t("recon.splat.cluster.bad_bundle", why=f"object {sha[:12]} does not match its hash"))
        total += len(b)
        if total > PACK_MAX_BYTES:
            raise SplatRunError(t("recon.splat.cluster.too_large", mib=PACK_MAX_BYTES >> 20))
        objs[sha] = base64.b64encode(b).decode()
    return {"schema": PACK_SCHEMA, "bundle_json": base64.b64encode(raw).decode(), "objects": objs}


def unpack_bundle(packed: dict[str, Any], dest: Path) -> Path:
    """Worker side: rebuild the bundle directory, re-verifying every object hash and that every view is present."""
    import base64
    if packed.get("schema") != PACK_SCHEMA:
        raise SplatRunError(t("recon.splat.cluster.bad_bundle", why=f"schema {packed.get('schema')!r}"))
    dest = Path(dest)
    raw = base64.b64decode(packed["bundle_json"])
    m = json.loads(raw)
    objs = packed.get("objects") or {}
    for v in m.get("views") or []:
        sha = str(v.get("sha256", ""))
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha) or sha not in objs:
            raise SplatRunError(t("recon.splat.cluster.bad_bundle", why=f"view {sha[:12]!r} missing"))
    for sha, b64 in objs.items():
        b = base64.b64decode(b64)
        if hashlib.sha256(b).hexdigest() != sha:
            raise SplatRunError(t("recon.splat.cluster.bad_bundle", why=f"object {sha[:12]} does not match its hash"))
        o = dest / "objects" / sha[:2] / sha
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_bytes(b)
    (dest / "bundle.json").write_bytes(raw)
    return dest


CLUSTER_ARTIFACTS = ("point_cloud.ply", "train.json", "config.json")


def cluster_job(bundle: Path, iters: int = 30000, sh_degree: int = 3, downscale: float = 1.0, seed: int = 0,
                focal_px: float | None = None, contract_probe: bool = False, timeout_s: float = 6 * 3600,
                job_id: str | None = None) -> dict[str, Any]:
    """The LoomCluster job dict for one full-scale splat run (placement: a node advertising `rocm`)."""
    payload = {"bundle": pack_bundle(bundle), "iters": int(iters), "sh_degree": int(sh_degree),
               "downscale": float(downscale), "seed": int(seed), "focal_px": focal_px,
               "contract_probe": bool(contract_probe), "timeout_s": float(timeout_s)}
    jid = job_id or "splat:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return {"id": jid, "op": "recon.splat", "requires": {"device": "rocm"}, "payload": payload}


def cluster_op(payload: dict[str, Any], devices: list[str] | None = None, timeout_s: float | None = None) -> dict[str, Any]:
    """LoomCluster worker body of op `recon.splat` (runs on the node the job was placed on)."""
    import base64
    import tempfile
    limit = float(payload.get("timeout_s") or 6 * 3600)
    if timeout_s:
        limit = min(limit, float(timeout_s))
    with tempfile.TemporaryDirectory(prefix="splatjob-") as td:
        b = unpack_bundle(payload["bundle"], Path(td) / "bundle")
        r = GpuSplatRunner(iters=payload.get("iters", 30000), sh_degree=payload.get("sh_degree", 3),
                           downscale=payload.get("downscale", 1.0), seed=payload.get("seed", 0), trainer_cmd=None,
                           timeout_s=limit, focal_px=payload.get("focal_px"),
                           contract_probe=bool(payload.get("contract_probe")), devices=devices)
        r.train(b)
        work = Path(r.last["work"])
        data = {n: (work / n).read_bytes() for n in CLUSTER_ARTIFACTS}
        doc = {k: v for k, v in r.last.items() if k not in ("ply_path", "work")}
    return {"train": doc, "artifacts": {n: hashlib.sha256(v).hexdigest() for n, v in data.items()},
            "data_b64": {n: base64.b64encode(v).decode() for n, v in data.items()}}


def submit_to_cluster(bundle: Path, url: str, timeout_s: float = 6 * 3600, poll_s: float = 1.0,
                      **kw: Any) -> dict[str, Any]:
    """Origin side: real placement check (a `rocm` node must exist), submit, wait, pull + verify the blobs, write
    BUNDLE/splat_gpu/{point_cloud.ply,train.json,config.json} and re-validate the .ply locally."""
    from forge import loomcluster as lc
    from forge import realityloom
    bundle = Path(bundle)
    url = url.rstrip("/")
    place = realityloom.check_placement(url, "rocm")
    if not place["ok"]:
        raise SplatRunError(t("recon.no_gpu_node", device="rocm"))
    job = cluster_job(bundle, timeout_s=timeout_s, **kw)
    lc._http(url + "/submit", job, 30.0)
    deadline = time.time() + timeout_s + 60
    while True:
        r = lc._http(url + f"/result/{job['id']}", timeout=5.0)
        if not r.get("pending"):
            break
        if time.time() > deadline:
            raise SplatRunError(t("recon.splat.gpu.timeout", seconds=int(timeout_s)))
        time.sleep(poll_s)
    if not r.get("ok"):
        raise SplatRunError(t("recon.splat.cluster.job_failed", node=r.get("node", "?"), why=str(r.get("error"))[:300]))
    v = r["value"]
    work = bundle / "splat_gpu"
    work.mkdir(exist_ok=True)
    for n in CLUSTER_ARTIFACTS:
        bl = v["blobs"][n]
        data = lc.fetch_blob(url, bl["sha256"], 60.0)
        if v["artifacts"][n] != bl["sha256"]:
            raise SplatRunError(t("recon.splat.cluster.bad_bundle", why=f"{n} digest mismatch"))
        (work / n).write_bytes(data)
    ply = (work / "point_cloud.ply").read_bytes()
    info = check_output(ply, v["train"]["project"]["bounds"])
    return {**v["train"], "cluster": {"job_id": job["id"], "node": r.get("node"), "attempts": r.get("attempts"),
                                      "wall_s": r.get("wall_s"), "capable_nodes": place["capable"]},
            "ply": info, "ply_path": str(work / "point_cloud.ply"), "work": str(work)}


# ------------------------------------------------------------------------------------------------ contract-probe trainer

def _read_ascii_points(p: Path) -> tuple[np.ndarray, np.ndarray]:
    txt = p.read_text(encoding="ascii").split("end_header\n", 1)[1].split()
    a = np.array(txt, float).reshape(-1, 6)
    return a[:, :3], a[:, 3:] / 255.0


def probe_trainer(data: Path, iters: int, out: Path, sh_degree: int) -> dict[str, Any]:
    """NOT a trainer. Validates a nerfstudio project the way a real trainer consumes it (frames, images, 4×4 c2w, sparse
    cloud re-projects in front of and inside ≥ 80 % of cameras on average) and writes a valid SH-`sh_degree` splat `.ply`
    seeded from the sparse points (isotropic, fixed opacity) — the runner contract, nothing learned."""
    from forge import photogrammetry
    from forge.splats import C0
    tr = json.loads((data / "transforms.json").read_text(encoding="utf-8"))
    assert tr.get("camera_model") and tr.get("frames"), "transforms.json: camera_model/frames missing"
    pts, rgb = _read_ascii_points(data / tr["ply_file_path"])
    vis = []
    for f in tr["frames"]:
        img = photogrammetry._decode((data / f["file_path"]).read_bytes())
        assert img.shape[:2] == (f["h"], f["w"]), f"{f['file_path']}: size mismatch"
        m = np.asarray(f["transform_matrix"], float)
        assert m.shape == (4, 4) and np.allclose(m[3], [0, 0, 0, 1]), "transform_matrix must be 4×4 homogeneous"
        assert abs(np.linalg.det(m[:3, :3]) - 1) < 1e-6, "rotation not orthonormal"
        R, tv = w2c_cv(m)
        pc = pts @ R.T + tv
        z = pc[:, 2]
        u = f["fl_x"] * pc[:, 0] / np.where(z > 0, z, 1) + f["cx"]
        v = f["fl_y"] * pc[:, 1] / np.where(z > 0, z, 1) + f["cy"]
        vis.append(float(np.mean((z > 0) & (u >= 0) & (u < f["w"]) & (v >= 0) & (v < f["h"]))))
    assert np.mean(vis) >= 0.8, f"sparse cloud re-projects into only {np.mean(vis):.0%} of the views — camera convention wrong"
    n = len(pts)
    rest = {1: 9, 2: 24, 3: 45}[sh_degree]
    nn = np.sort(np.linalg.norm(pts[:, None] - pts[None, :min(n, 256)], axis=2), axis=1)[:, 1] if n > 1 else np.ones(1)
    s = np.log(np.maximum(np.median(nn), 1e-4))
    cols = [pts[:, 0], pts[:, 1], pts[:, 2], np.zeros(n), np.zeros(n), np.zeros(n), *((rgb[:, i] - 0.5) / C0 for i in range(3)),
            *(np.zeros(n) for _ in range(rest)), np.full(n, 2.0), *(np.full(n, s) for _ in range(3)),
            np.ones(n), np.zeros(n), np.zeros(n), np.zeros(n)]
    props = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", *[f"f_rest_{i}" for i in range(rest)],
             "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    head = ("ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n"
            + "".join(f"property float {p}\n" for p in props) + "end_header\n").encode()
    out.write_bytes(head + np.stack(cols, 1).astype("<f4").tobytes())
    return {"frames": len(tr["frames"]), "points": n, "reproj_visible_mean": round(float(np.mean(vis)), 4), "iters_ignored": iters}


def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m forge.splatforge_gpu")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pt = sub.add_parser("probe-trainer", help="contract probe (does not train)")
    pt.add_argument("data", type=Path)
    pt.add_argument("-n", "--num-iters", type=int, default=30000)
    pt.add_argument("-o", "--output", type=Path, required=True)
    pt.add_argument("--sh-degree", type=int, default=3)
    a = ap.parse_args(argv)
    try:
        print(json.dumps(probe_trainer(a.data, a.num_iters, a.output, a.sh_degree)))
    except (AssertionError, OSError, ValueError, KeyError) as e:
        print(f"probe-trainer: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
