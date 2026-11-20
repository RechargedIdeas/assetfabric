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
  * `check_splat_ply` — validator for the 3DGS `.ply` a trainer must emit (INRIA layout) — the post-condition of SplatForge.

STUB (refuses with `StubError`; nothing is queued, nothing is fabricated): `SplatForge.train`, `Photogrammetry.run`,
`MeshWeaver.convert`, `GdgsImport.into_godot`, and `submit` (after the real placement check).
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
        ("sfm_colmap", "recon.splat", "cpu", "stub"),
        ("train_splat", "recon.splat", "rocm", "stub"),
        ("validate_ply", "recon.plan", "cpu", "real"),
        ("import_godot", "shuttle.gdgs", "cpu", "stub"),
    ],
    "photogrammetry": [
        ("bundle", "recon.plan", "cpu", "real"),
        ("photogrammetry_run", "recon.splat", "cpu", "stub"),
    ],
}
BLOCKERS = {"sfm_colmap": "recon.photogrammetry", "train_splat": "recon.splatforge", "import_godot": "recon.gdgs_import",
            "photogrammetry_run": "recon.photogrammetry"}


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
            "runnable_today": False, "blocked_by": sorted({s["blocked_by"] for s in stages if "blocked_by" in s}),
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
    """STUB (C12): 3DGS training from a capture bundle. GroundWeave op `recon.splat` (gpu_required, route loomcluster)."""

    def train(self, bundle: dict[str, Any]) -> Path:
        refuse("recon.splatforge", "stub.recon.splatforge", MILESTONE)


class Photogrammetry:
    """STUB (C12): CPU COLMAP/Meshroom photogrammetry (the ladder's degraded rung)."""

    def run(self, bundle: dict[str, Any]) -> Path:
        refuse("recon.photogrammetry", "stub.recon.photogrammetry", MILESTONE)


class MeshWeaver:
    """STUB (spec: Phase 2 reconstruction): splat → mesh (SuGaR / GOF class)."""

    def convert(self, ply: Path) -> Path:
        refuse("recon.meshweaver", "stub.recon.meshweaver", MILESTONE)


class GdgsImport:
    """STUB: ShuttleLine Godot 3DGS (GDGS) adapter — import a validated splat into a Godot project."""

    def into_godot(self, ply: Path, project: Path) -> Path:
        refuse("recon.gdgs_import", "stub.recon.gdgs_import", MILESTONE)


STUB_PROBES = {
    "recon.splatforge": lambda: SplatForge().train({}),
    "recon.photogrammetry": lambda: Photogrammetry().run({}),
    "recon.meshweaver": lambda: MeshWeaver().convert(Path("x.ply")),
    "recon.gdgs_import": lambda: GdgsImport().into_godot(Path("x.ply"), Path(".")),
}


def probe() -> dict[str, Any]:
    """`recon.plan` CPU-rung probe for GroundWeave verify: bundle + plan of a synthetic capture set, fixed devices."""
    m = bundle_manifest([lensforge.synthetic_png(96, 64, i) for i in range(4)], "backdrop", "burst")
    p = plan(m, ["cpu"], tools={k: None for k in TOOLS})
    ply = check_splat_ply(make_test_ply(5, 9))
    return {"manifest": m, "plan": p, "ply": ply}
