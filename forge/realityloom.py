"""RealityLoom (reconstruction orchestrator) + SplatForge / MeshWeaver path (C12) — SPEC §7 and §4 table.

SPEC §7: treat 3DGS as a parallel asset class. RealityLoom routes `backdrop` → splat (COLMAP + Nerfstudio/OpenSplat →
`.ply`/`.splat` → Godot GDGS) and `hero_prop` → photogrammetry or MeshWeaver. "AMD honesty": dominant 3DGS trainers are
CUDA-centric; paths are OpenSplat+ROCm on Linux (7900), CPU COLMAP + burst GPU, or photogrammetry-only Meshroom on CPU;
"always show honest ETAs".

REAL (CPU, deterministic, no external tools):
  * `route` — the spec's routing rule, `detect_tools` — which reconstruction binaries exist on this host,
  * `write_bundle` / `bundle_manifest` — content-addressed capture bundle (the input contract of every reconstruction
    backend: sorted view hashes, per-view LensForge quality, mode, target, route),
  * `plan` — stages, the GroundWeave op + required device of each, which stages are stubs (`blocked_by`), honest ETA class,
  * `cluster_devices` / `check_placement` — asks a LoomCluster whether any node advertises the device a stage needs
    (the spec's gpu_required + route: loomcluster rule, backed by C7's real placement),
  * `check_splat_ply` — validator for the 3DGS `.ply` a trainer must emit (INRIA layout) — the post-condition of SplatForge,
  * (0.7.7) `MeshWeaver.convert` — splat density → surface nets → OBJ; `GdgsImport.into_godot` — splat → Godot MultiMesh
    billboard scene, verified in Godot (`forge.splats`).

  * (0.7.7) `SplatForgeCPU.train` — bounded tiny-scene 3DGS training on CPU (`forge.splattrain`).
  * (0.7.7) `Photogrammetry.run` — incremental SIFT SfM on OpenCV (CPU) → sparse cloud + cameras (`forge.photogrammetry`).

STUB (refuses with `StubError`; nothing is queued, nothing is fabricated): full-scale `SplatForge.train` (GPU) and `submit` (after the real
placement check).
Whether any of this beats the CPU-only photogrammetry route on the fleet is unmeasured: no trainer has ever run here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

from forge import lensforge
from forge.i18n import t
from forge.stubs import refuse

MILESTONE = "C12"
TARGETS = ("backdrop", "hero_prop")
TOOLS = {"colmap": "colmap", "opensplat": "opensplat", "nerfstudio": "ns-train", "meshroom": "meshroom_batch"}
PLY_REQUIRED = ("x", "y", "z", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
                "f_dc_0", "f_dc_1", "f_dc_2")
SH_REST_TO_DEGREE = {0: 0, 9: 1, 24: 2, 45: 3}


def detect_tools() -> dict[str, str | None]:
    return {k: shutil.which(v) for k, v in TOOLS.items()}


def route(target: str) -> dict[str, Any]:
    """SPEC §7 hybrid rule: backdrop → splat; hero_prop → photogrammetry (collision/topology) or MeshWeaver."""
    if target == "backdrop":
        return {"target": target, "route": "splat", "alternatives": [], "spec": "§7 phase 1/2"}
    if target == "hero_prop":
        return {"target": target, "route": "photogrammetry", "alternatives": ["meshweaver"], "spec": "§7 phase 2"}
    raise ValueError(f"unknown reconstruction target {target!r}; known {TARGETS}")


# ------------------------------------------------------------------------------------------------ bundle

def bundle_manifest(images: list[bytes], target: str, mode: str, root: Path | None = None) -> dict[str, Any]:
    """Deterministic manifest of a capture set (no timestamps, no host paths): identical input ⇒ identical bytes."""
    rt = route(target)
    ass = lensforge.assess_set(images, mode, root)
    views = []
    for b, a in zip(images, ass["per_view"], strict=True):
        views.append({"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b),
                      **{k: a[k] for k in ("width", "height", "sharpness", "mean_luma", "verdict") if k in a}})
    sets = hashlib.sha256("\n".join(sorted({v["sha256"] for v in views})).encode()).hexdigest()
    return {"schema_version": "1.0", "target": target, "route": rt["route"], "mode": mode, "views": views,
            "capture_set_sha256": sets, "set_verdict": ass["verdict"], "usable_views": ass["usable_views"],
            "min_views": ass["min_views"], "overlap": ass["overlap"]}


def write_bundle(out: Path, images: list[bytes], target: str, mode: str, root: Path | None = None) -> dict[str, Any]:
    """Content-addressed bundle directory: `objects/aa/<sha>` + `bundle.json`."""
    m = bundle_manifest(images, target, mode, root)
    out = Path(out)
    for b in images:
        sha = hashlib.sha256(b).hexdigest()
        p = out / "objects" / sha[:2] / sha
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(b)
    (out / "bundle.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return m


# ------------------------------------------------------------------------------------------------ plan

STAGES = {
    "splat": [
        ("bundle", "recon.plan", "cpu", "real"),
        ("sfm", "recon.sfm", "cpu", "real"),
        ("train_splat", "recon.splat", "rocm", "stub"),
        ("validate_ply", "recon.plan", "cpu", "real"),
        ("import_godot", "shuttle.gdgs", "cpu", "real"),
    ],
    "photogrammetry": [
        ("bundle", "recon.plan", "cpu", "real"),
        ("photogrammetry_sfm", "recon.sfm", "cpu", "real"),
    ],
}
BLOCKERS = {"train_splat": "recon.splatforge"}


def plan(manifest: dict[str, Any], devices: list[str], tools: dict[str, str | None] | None = None) -> dict[str, Any]:
    """What RealityLoom would do with this bundle on a fleet offering `devices`, and what stops it today."""
    tools = detect_tools() if tools is None else tools
    r = manifest["route"]
    degraded = None
    if r == "splat" and "rocm" not in devices:
        degraded = "photogrammetry"            # the ladder's honest degraded route when no GPU node exists
    eff = degraded or r
    stages = []
    for sid, op, dev, status in STAGES[eff]:
        stages.append({"id": sid, "op": op, "device": dev, "status": status,
                       **({"blocked_by": BLOCKERS[sid]} if sid in BLOCKERS else {}),
                       **({"requires": {"device": dev}} if dev != "cpu" else {})})
    if manifest["usable_views"] < manifest["min_views"]:
        eta = t("recon.eta.none")
        problems = [t("recon.too_few_views", have=manifest["usable_views"], need=manifest["min_views"], mode=manifest["mode"])]
    else:
        eta = t("recon.eta.gpu") if (r == "splat" and degraded is None) else t("recon.eta.cpu")
        problems = []
    return {"route": r, "effective_route": eff, "degraded_from": r if degraded else None, "devices": list(devices),
            "stages": stages, "problems": problems, "eta": eta, "eta_measured": False,
            "runnable_today": not problems and all(s["status"] == "real" for s in stages), "blocked_by": sorted({s["blocked_by"] for s in stages if "blocked_by" in s}),
            "tools_on_host": tools}


# ------------------------------------------------------------------------------------------------ cluster

def cluster_devices(url: str) -> dict[str, list[str]]:
    """node id → advertised devices, from any LoomCluster node (real C7 protocol)."""
    from forge.loomcluster import _http
    st = _http(url.rstrip("/") + "/status", timeout=3.0)
    out = {st["id"]: st["devices"]}
    for p in st["peers"]:
        adv = _http(p + "/advert", timeout=3.0)
        out[adv["id"]] = adv["devices"]
    return out


def check_placement(url: str, device: str = "rocm") -> dict[str, Any]:
    nodes = cluster_devices(url)
    capable = sorted(n for n, d in nodes.items() if device in d)
    return {"device": device, "nodes": nodes, "capable": capable, "ok": bool(capable)}


def submit(manifest: dict[str, Any], cluster_url: str) -> None:
    """Try to run reconstruction on a cluster. REAL placement check first; then — because no SplatForge worker op exists —
    the stub refusal. Never submits a job, so nothing can be queued that no node can run."""
    p = check_placement(cluster_url, "rocm")
    if manifest["route"] == "splat" and not p["ok"]:
        raise RuntimeError(t("recon.no_gpu_node", device="rocm"))
    SplatForge().train(manifest)


# ------------------------------------------------------------------------------------------------ splat .ply check

def check_splat_ply(data: bytes) -> dict[str, Any]:
    """Validate a 3DGS `.ply` header + body size (INRIA/OpenSplat layout: binary little-endian float32 properties)."""
    def bad(why: str) -> ValueError:
        return ValueError(t("recon.splat.bad_ply", why=why))
    end = data.find(b"end_header\n")
    if not data.startswith(b"ply\n") or end < 0:
        raise bad("missing ply header")
    hdr = data[:end].decode("ascii", "replace").split("\n")
    if "format binary_little_endian 1.0" not in hdr:
        raise bad("format must be binary_little_endian 1.0")
    n, props, in_vertex = None, [], False
    for line in hdr[1:]:
        parts = line.split()
        if parts[:1] == ["element"]:
            in_vertex = parts[1:2] == ["vertex"]
            if in_vertex:
                n = int(parts[2])
        elif parts[:1] == ["property"] and in_vertex:
            if parts[1] != "float":
                raise bad(f"property {parts[-1]} is {parts[1]}, expected float")
            props.append(parts[2])
    if not n or n <= 0:
        raise bad("no vertices")
    missing = [p for p in PLY_REQUIRED if p not in props]
    if missing:
        raise bad(f"missing properties {missing}")
    rest = sum(1 for p in props if p.startswith("f_rest_"))
    if rest not in SH_REST_TO_DEGREE:
        raise bad(f"{rest} f_rest_* properties is not a spherical-harmonics degree 0-3 layout")
    body = len(data) - (end + len(b"end_header\n"))
    if body != n * len(props) * 4:
        raise bad(f"body is {body} bytes, header promises {n * len(props) * 4}")
    return {"vertices": n, "properties": len(props), "sh_degree": SH_REST_TO_DEGREE[rest], "bytes": len(data)}


def make_test_ply(n: int, sh_rest: int = 0) -> bytes:
    """A syntactically valid splat file of `n` zero Gaussians — TEST FIXTURE ONLY for the validator, not reconstruction output."""
    props = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", *[f"f_rest_{i}" for i in range(sh_rest)],
             "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    head = ("ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n"
            + "".join(f"property float {p}\n" for p in props) + "end_header\n").encode()
    return head + struct.pack("<f", 0.0) * (n * len(props))


# ------------------------------------------------------------------------------------------------ stubs

class SplatForge:
    """STUB (C12): full-scale 3DGS training (anisotropic, SH 3, densification, full resolution) from a capture bundle.
    GroundWeave op `recon.splat` (gpu_required, route loomcluster) — needs a ROCm/CUDA trainer (OpenSplat), none bundled.
    The bounded tiny-scene CPU trainer is real: `SplatForgeCPU` (op `recon.splat_cpu`)."""

    def train(self, bundle: dict[str, Any]) -> Path:
        refuse("recon.splatforge", "stub.recon.splatforge", MILESTONE)


class SplatForgeCPU:
    """SplatForge CPU rung (C12, 0.7.7): tiny-scene 3DGS training on CPU (`forge.splattrain` — isotropic Gaussians, SH 0,
    dense sorted alpha compositing, analytic gradients, Adam). Capture bundle → CPU SfM (poses + sparse init) → training
    at ≤ `MAX_W` px → `splat/point_cloud.ply` (validated by `check_splat_ply`) + `splat/train.json`. Bounded on purpose:
    beyond `MAX_SPLATS` / `MAX_W` / `MAX_VIEWS` it refuses (`recon.splat.cpu_too_large`) — full training is the GPU rung."""

    MAX_SPLATS, MAX_W, MAX_VIEWS = 2000, 96, 24

    def __init__(self, splats: int = 600, width: int = 64, iters: int = 400, focal_px: float | None = None,
                 holdout: int | None = None, seed: int = 0) -> None:
        self.splats, self.width, self.iters, self.focal_px, self.holdout, self.seed = splats, width, iters, focal_px, holdout, seed
        self.last: dict[str, Any] = {}

    def train(self, bundle: Path) -> Path:
        import numpy as np

        from forge import photogrammetry, splattrain
        bundle = Path(bundle)
        m = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
        n_views = len(m["views"])
        if self.splats > self.MAX_SPLATS or self.width > self.MAX_W or n_views > self.MAX_VIEWS:
            raise ValueError(t("recon.splat.cpu_too_large", splats=self.splats, width=self.width, views=n_views,
                               max_splats=self.MAX_SPLATS, max_w=self.MAX_W, max_views=self.MAX_VIEWS))
        imgs = [photogrammetry._decode((bundle / "objects" / v["sha256"][:2] / v["sha256"]).read_bytes()) for v in m["views"]]
        rec = photogrammetry.reconstruct(imgs, focal_px=self.focal_px)
        if len(rec["registered"]) < 3 or len(rec["points"]) < 20:
            raise ValueError(t("recon.splat.sfm_failed", registered=len(rec["registered"]), points=len(rec["points"])))
        d = splattrain.from_sfm(imgs, rec, self.width, self.holdout)
        lo, hi, s0 = splattrain.scene_bounds(rec["points"], None)
        p0 = splattrain.init_gaussians(self.splats, lo, hi, s0, self.seed, rec["points"], rec["colors"])
        r = splattrain.train(d["train"], d["K"], p0, iters=self.iters, seed=self.seed)
        w, h = d["w"], d["h"]

        def score(p: dict[str, Any], v: dict[str, Any]) -> float:
            return splattrain.psnr(splattrain.render_params(p, v["R"], v["t"], d["K"], w, h), v["image"])
        out = bundle / "splat"
        out.mkdir(exist_ok=True)
        ply = splattrain.to_ply(r["params"])
        check_splat_ply(ply)
        (out / "point_cloud.ply").write_bytes(ply)
        doc = {"method": "splatforge-numpy-cpu (isotropic 3DGS, SH0, dense raster)", "splats_init": self.splats,
               "splats": int(len(r["params"]["mu"])), "iters": r["iters"], "seconds": r["seconds"], "resolution": [w, h],
               "views_registered": len(rec["registered"]), "views_train": len(d["train"]),
               "psnr_train_mean": round(float(np.mean([score(r["params"], v) for v in d["train"]])), 3),
               "loss_first10": round(float(np.mean(r["curve"][:10])), 6), "loss_last10": round(float(np.mean(r["curve"][-10:])), 6),
               "scale": "arbitrary (monocular SfM)", "ply_sha256": hashlib.sha256(ply).hexdigest()}
        if d["test"] is not None:
            doc["holdout_view"] = self.holdout
            doc["psnr_holdout"] = round(score(r["params"], d["test"]), 3)
            doc["psnr_holdout_init"] = round(score(p0, d["test"]), 3)
        (out / "train.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        self.last = {**doc, "ply": str(out / "point_cloud.ply")}
        return out / "point_cloud.ply"


class Photogrammetry:
    """CPU photogrammetry (C12, the ladder's degraded route): incremental SIFT SfM on OpenCV over a capture bundle →
    `sfm/sparse.ply` + `sfm/cameras.json` (`forge.photogrammetry`). Dense MVS / texturing are not built (C-74)."""

    def __init__(self, focal_px: float | None = None) -> None:
        self.focal_px = focal_px
        self.last: dict[str, Any] = {}

    def run(self, bundle: Path) -> Path:
        from forge import photogrammetry
        r = photogrammetry.run_bundle(Path(bundle), self.focal_px)
        r.pop("rec")
        self.last = r
        return Path(r["sparse_ply"])


class MeshWeaver:
    """Splat → mesh on CPU (`forge.splats`): opacity-weighted Gaussian density on a voxel grid → naive surface nets →
    vertex-coloured OBJ. The learned SuGaR/GOF-class rung stays `planned` (ROCm)."""

    def __init__(self, voxel: float | None = None, iso_frac: float = 0.35) -> None:
        self.voxel, self.iso_frac = voxel, iso_frac
        self.last: dict[str, Any] = {}

    def convert(self, ply: Path, out: Path | None = None) -> Path:
        from forge import splats
        mesh = splats.mesh_from_splats(Path(ply).read_bytes(), self.voxel, self.iso_frac)
        out = Path(out) if out else Path(ply).with_suffix(".obj")
        out.write_bytes(splats.write_obj(mesh))
        self.last = {"vertices": len(mesh["vertices"]), "triangles": len(mesh["triangles"]), "voxel": mesh["voxel"], "grid": mesh["grid"]}
        return out


class GdgsImport:
    """ShuttleLine Godot 3DGS adapter (CPU): validated splat `.ply` → `<project>/splats/<name>.tscn` (MultiMesh billboard
    splats, Compatibility renderer). Exact anisotropic/sorted 3DGS rasterisation stays `planned` (`gdgs-raster-import@vulkan`)."""

    def __init__(self, max_splats: int | None = None) -> None:
        self.max_splats = max_splats
        self.last: dict[str, Any] = {}

    def into_godot(self, ply: Path, project: Path, name: str | None = None) -> Path:
        from forge import splats
        kw = {"max_splats": self.max_splats} if self.max_splats else {}
        self.last = splats.import_into_godot(Path(ply).read_bytes(), Path(project), name or Path(ply).stem, **kw)
        return Path(self.last["scene"])


STUB_PROBES = {
    "recon.splatforge": lambda: SplatForge().train({}),
}


def probe() -> dict[str, Any]:
    """`recon.plan` CPU-rung probe for GroundWeave verify: bundle + plan of a synthetic capture set, fixed devices."""
    m = bundle_manifest([lensforge.synthetic_png(96, 64, i) for i in range(4)], "backdrop", "burst")
    p = plan(m, ["cpu"], tools={k: None for k in TOOLS})
    ply = check_splat_ply(make_test_ply(5, 9))
    return {"manifest": m, "plan": p, "ply": ply}
