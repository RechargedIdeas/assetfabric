"""3D Gaussian Splat files → mesh (MeshWeaver) and → Godot scene (GDGS import) — C12, CPU only.

* `read_ply` / `write_ply`: INRIA/OpenSplat 3DGS `.ply` (binary little-endian float32; validated by
  `realityloom.check_splat_ply`). Colour = SH degree-0 (`0.5 + C0·f_dc`), opacity = sigmoid, scale = exp, rot = wxyz.
* `MeshWeaver` (`mesh_from_splats`): splat density field (Σ opacityᵢ·N(x; μᵢ, σᵢ), isotropic σ = mean scale) sampled on a
  voxel grid, iso-surface by **naive surface nets** (own NumPy code, no dependency), per-vertex colour from the nearest
  splats, written as OBJ (`v x y z r g b`). This is the classical density-iso route, not SuGaR/GOF (those stay `planned`
  on ROCm): fine for props/backdrop proxies and collision, not a learned surface.
* `GdgsImport` (`write_godot_scene`): a Godot 4 `.tscn` with one `MultiMeshInstance3D` — one camera-facing quad per splat
  (position, isotropic scale, colour + opacity, radial-falloff texture), unshaded/alpha on the Compatibility renderer. A
  billboard approximation of 3DGS (no anisotropic covariance, no sorted alpha compositing — that is the planned
  `gdgs-raster-import@vulkan` rung). Verified by loading the scene in headless Godot.

Inputs used in tests/acceptance are synthetic splats with known geometry (INFERENCES C-71…)."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

C0 = 0.28209479177387814           # SH degree-0 basis constant


# ------------------------------------------------------------------------------------------------ .ply I/O

def read_ply(data: bytes) -> dict[str, np.ndarray]:
    from forge.realityloom import check_splat_ply
    check_splat_ply(data)
    end = data.find(b"end_header\n") + len(b"end_header\n")
    hdr = data[:end].decode("ascii").split("\n")
    props = [ln.split()[2] for ln in hdr if ln.startswith("property float ")]
    n = next(int(ln.split()[2]) for ln in hdr if ln.startswith("element vertex "))
    arr = np.frombuffer(data[end:], dtype="<f4").reshape(n, len(props)).astype(np.float64)
    col = {p: arr[:, i] for i, p in enumerate(props)}
    pos = np.stack([col["x"], col["y"], col["z"]], 1)
    rgb = np.clip(0.5 + C0 * np.stack([col["f_dc_0"], col["f_dc_1"], col["f_dc_2"]], 1), 0.0, 1.0)
    opacity = 1.0 / (1.0 + np.exp(-col["opacity"]))
    scale = np.exp(np.stack([col["scale_0"], col["scale_1"], col["scale_2"]], 1))
    rot = np.stack([col["rot_0"], col["rot_1"], col["rot_2"], col["rot_3"]], 1)
    return {"pos": pos, "rgb": rgb, "opacity": opacity, "scale": scale, "rot": rot}


def write_ply(pos: np.ndarray, rgb: np.ndarray, opacity: np.ndarray, scale: np.ndarray, rot: np.ndarray | None = None) -> bytes:
    n = len(pos)
    rot = np.tile([1.0, 0, 0, 0], (n, 1)) if rot is None else rot
    op = np.clip(opacity, 1e-6, 1 - 1e-6)
    cols = [pos[:, 0], pos[:, 1], pos[:, 2], np.zeros(n), np.zeros(n), np.zeros(n),
            *((np.asarray(rgb)[:, i] - 0.5) / C0 for i in range(3)), np.log(op / (1 - op)),
            *(np.log(np.asarray(scale)[:, i]) for i in range(3)), *(rot[:, i] for i in range(4))]
    props = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2",
             "rot_0", "rot_1", "rot_2", "rot_3"]
    head = ("ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n"
            + "".join(f"property float {p}\n" for p in props) + "end_header\n").encode()
    return head + np.stack(cols, 1).astype("<f4").tobytes()


def sphere_splats(n: int = 2000, radius: float = 0.5, sigma: float = 0.03, seed: int = 0) -> bytes:
    """Synthetic splats on a sphere surface (known geometry), colour = f(direction) — test/acceptance input only."""
    rng = np.random.default_rng(seed)
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    rgb = 0.5 + 0.5 * d
    return write_ply(d * radius, rgb, np.full(n, 0.9), np.full((n, 3), sigma))


# ------------------------------------------------------------------------------------------------ MeshWeaver

def density_grid(s: dict[str, np.ndarray], voxel: float, pad: float) -> tuple[np.ndarray, np.ndarray]:
    lo = s["pos"].min(0) - pad
    hi = s["pos"].max(0) + pad
    dims = np.maximum(2, np.ceil((hi - lo) / voxel).astype(int) + 1)
    if int(np.prod(dims)) > 8_000_000:
        raise ValueError(f"grid {dims.tolist()} too large — raise the voxel size")
    g = np.zeros(dims, dtype=np.float64)
    sig = s["scale"].mean(1)
    for p, o, sg in zip(s["pos"], s["opacity"], sig):
        r = max(1, int(math.ceil(3 * sg / voxel)))
        c = np.round((p - lo) / voxel).astype(int)
        a = np.maximum(c - r, 0)
        b = np.minimum(c + r + 1, dims)
        ax = [lo[k] + voxel * np.arange(a[k], b[k]) - p[k] for k in range(3)]
        e = [np.exp(-(v * v) / (2 * sg * sg)) for v in ax]
        g[a[0]:b[0], a[1]:b[1], a[2]:b[2]] += o * e[0][:, None, None] * e[1][None, :, None] * e[2][None, None, :]
    return g, lo


def surface_nets(f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Naive surface nets on scalar grid `f` (iso 0, inside > 0). Returns vertices (grid units) and triangles."""
    nx, ny, nz = f.shape
    inside = f > 0
    csum = np.zeros((nx - 1, ny - 1, nz - 1, 3))
    ccnt = np.zeros((nx - 1, ny - 1, nz - 1))
    edges = []
    for ax in range(3):
        sl_a = [slice(None)] * 3
        sl_b = [slice(None)] * 3
        sl_a[ax] = slice(0, -1)
        sl_b[ax] = slice(1, None)
        a, b = f[tuple(sl_a)], f[tuple(sl_b)]
        cr = inside[tuple(sl_a)] != inside[tuple(sl_b)]
        idx = np.argwhere(cr)
        t = a[cr] / (a[cr] - b[cr])
        pts = idx.astype(np.float64)
        pts[:, ax] += t
        others = [k for k in range(3) if k != ax]
        for d0 in (0, -1):
            for d1 in (0, -1):
                cell = idx.copy()
                cell[:, others[0]] += d0
                cell[:, others[1]] += d1
                ok = np.all((cell >= 0) & (cell < np.array([nx - 1, ny - 1, nz - 1])), axis=1)
                np.add.at(csum, tuple(cell[ok].T), pts[ok])
                np.add.at(ccnt, tuple(cell[ok].T), 1)
        edges.append((ax, idx, a[cr] > 0))
    active = ccnt > 0
    vid = -np.ones(ccnt.shape, dtype=np.int64)
    vid[active] = np.arange(int(active.sum()))
    verts = csum[active] / ccnt[active][:, None]
    tris = []
    for ax, idx, a_in in edges:
        o0, o1 = [k for k in range(3) if k != ax]
        keep = (idx[:, o0] >= 1) & (idx[:, o1] >= 1) & (idx[:, o0] <= f.shape[o0] - 2) & (idx[:, o1] <= f.shape[o1] - 2)
        idx, a_in = idx[keep], a_in[keep]
        quad = []
        for d0, d1 in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            c = idx.copy()
            c[:, o0] += d0
            c[:, o1] += d1
            quad.append(vid[tuple(c.T)])
        q = np.stack(quad, 1)
        flip = a_in if ax != 1 else ~a_in           # consistent outward winding across axes
        q[flip] = q[flip][:, ::-1]
        tris.append(q[:, [0, 1, 2]])
        tris.append(q[:, [0, 2, 3]])
    t = np.concatenate(tris) if tris else np.zeros((0, 3), dtype=np.int64)
    return verts, t[(t >= 0).all(1)]


def mesh_from_splats(data: bytes, voxel: float | None = None, iso_frac: float = 0.35) -> dict[str, Any]:
    s = read_ply(data)
    sig = float(np.median(s["scale"].mean(1)))
    voxel = voxel or max(sig, 1e-4)
    g, lo = density_grid(s, voxel, pad=4 * sig)
    iso = iso_frac * float(g.max())
    v, t = surface_nets(g - iso)
    world = lo + v * voxel
    # vertex colour: opacity-weighted mean of the 8 nearest splats
    rgb = np.zeros((len(world), 3))
    for i in range(0, len(world), 4096):
        d = ((world[i:i + 4096, None, :] - s["pos"][None, :, :]) ** 2).sum(-1)
        nn = np.argpartition(d, min(8, d.shape[1] - 1), axis=1)[:, :8]
        w = s["opacity"][nn]
        rgb[i:i + 4096] = (s["rgb"][nn] * w[..., None]).sum(1) / w.sum(1, keepdims=True)
    return {"vertices": world, "triangles": t, "colors": rgb, "voxel": voxel, "iso": iso, "grid": list(g.shape)}


def write_obj(mesh: dict[str, Any]) -> bytes:
    lines = ["# AssetFabric MeshWeaver (splat density → surface nets), CPU"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f} {r:.4f} {g:.4f} {b:.4f}" for (x, y, z), (r, g, b) in zip(mesh["vertices"], mesh["colors"])]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh["triangles"]]
    return ("\n".join(lines) + "\n").encode()


# ------------------------------------------------------------------------------------------------ GDGS import (Godot)

MAX_GODOT_SPLATS = 50_000


def _fmt(vals: np.ndarray) -> str:
    return ", ".join(f"{v:.6g}" for v in vals.ravel())


def write_godot_scene(data: bytes, name: str = "splats", max_splats: int = MAX_GODOT_SPLATS) -> tuple[str, dict[str, Any]]:
    """Text `.tscn`: Node3D → MultiMeshInstance3D(MultiMesh: QuadMesh × N, transform_format 3D, use_colors)."""
    s = read_ply(data)
    n_all = len(s["pos"])
    order = np.argsort(-s["opacity"], kind="stable")[:max_splats]       # keep the most opaque splats if capped
    order.sort()
    pos, rgb, op = s["pos"][order], s["rgb"][order], s["opacity"][order]
    size = 2.0 * 3.0 * s["scale"][order].mean(1)                        # quad edge = ±3σ footprint
    n = len(order)
    buf = np.zeros((n, 16), dtype=np.float64)
    buf[:, 0] = size
    buf[:, 5] = size
    buf[:, 10] = size
    buf[:, 3], buf[:, 7], buf[:, 11] = pos[:, 0], pos[:, 1], pos[:, 2]
    buf[:, 12:15] = rgb
    buf[:, 15] = op
    scene = f"""[gd_scene load_steps=5 format=3]

[sub_resource type="Gradient" id="g"]
offsets = PackedFloat32Array(0, 0.33, 0.66, 1)
colors = PackedColorArray(1, 1, 1, 1, 1, 1, 1, 0.61, 1, 1, 1, 0.135, 1, 1, 1, 0)

[sub_resource type="GradientTexture2D" id="tex"]
gradient = SubResource("g")
width = 32
height = 32
fill = 1
fill_from = Vector2(0.5, 0.5)
fill_to = Vector2(1, 0.5)

[sub_resource type="StandardMaterial3D" id="mat"]
transparency = 1
shading_mode = 0
vertex_color_use_as_albedo = true
albedo_texture = SubResource("tex")
billboard_mode = 1
billboard_keep_scale = true

[sub_resource type="QuadMesh" id="quad"]
material = SubResource("mat")

[sub_resource type="MultiMesh" id="mm"]
transform_format = 1
use_colors = true
mesh = SubResource("quad")
instance_count = {n}
buffer = PackedFloat32Array({_fmt(buf)})

[node name="{name}" type="Node3D"]
metadata/gdgs = {json.dumps(json.dumps({"source_splats": n_all, "imported": n, "approx": "billboard quads, isotropic, unsorted alpha"}))}

[node name="Splats" type="MultiMeshInstance3D" parent="."]
multimesh = SubResource("mm")
"""
    return scene, {"source_splats": n_all, "imported": n, "pruned": n_all - n,
                   "probe": [{"i": int(i), "pos": pos[i].round(5).tolist(), "rgba": [*rgb[i].round(4).tolist(), round(float(op[i]), 4)]}
                             for i in sorted({0, n // 2, n - 1})]}


VERIFY_GD = """extends SceneTree
var frames = 0
var out = {}
var probes_done = false

func _initialize():
\tvar path = OS.get_cmdline_user_args()[0]
\tvar sc = load(path)
\tout["loaded"] = sc != null
\tout["renderer"] = ProjectSettings.get_setting("rendering/renderer/rendering_method")
\tout["display"] = DisplayServer.get_name()
\tif sc == null:
\t\treturn
\tvar inst = sc.instantiate()
\troot.add_child(inst)
\tvar mm = inst.get_node("Splats").multimesh
\tout["count"] = mm.instance_count
\tvar probes = []
\tfor i in [0, mm.instance_count / 2, mm.instance_count - 1]:
\t\tvar t = mm.get_instance_transform(i)
\t\tvar c = mm.get_instance_color(i)
\t\tprobes.append({"i": i, "pos": [t.origin.x, t.origin.y, t.origin.z], "rgba": [c.r, c.g, c.b, c.a], "scale": t.basis.x.x})
\tout["probes"] = probes
\tvar cam = Camera3D.new()
\tcam.position = Vector3(0, 0, 2.2)
\troot.add_child(cam)
\tcam.make_current()
\tRenderingServer.set_default_clear_color(Color(0, 0, 0, 1))

func _process(_delta):
\tframes += 1
\tif frames < 6 and out.get("loaded", false):
\t\treturn false
\tif out.get("loaded", false) and DisplayServer.get_name() != "headless":
\t\tvar img = root.get_viewport().get_texture().get_image()
\t\tvar lit = 0
\t\tvar sum = Vector3()
\t\tfor y in img.get_height():
\t\t\tfor x in img.get_width():
\t\t\t\tvar c = img.get_pixel(x, y)
\t\t\t\tif c.r + c.g + c.b > 0.15:
\t\t\t\t\tlit += 1
\t\t\t\t\tsum += Vector3(c.r, c.g, c.b)
\t\tout["render"] = {"w": img.get_width(), "h": img.get_height(), "lit": lit, "mean_rgb": [sum.x / max(lit, 1), sum.y / max(lit, 1), sum.z / max(lit, 1)]}
\tprint("GDGS_VERIFY " + JSON.stringify(out))
\treturn true
"""

PROJECT_GODOT = """config_version=5

[application]
config/name="gdgs-import"

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""


def import_into_godot(data: bytes, project: Path, name: str = "splats", max_splats: int = MAX_GODOT_SPLATS) -> dict[str, Any]:
    """Write `<project>/splats/<name>.tscn` (creating a minimal Compatibility-renderer project if none exists)."""
    if not (project / "project.godot").exists():
        project.mkdir(parents=True, exist_ok=True)
        (project / "project.godot").write_text(PROJECT_GODOT)
    scene, info = write_godot_scene(data, name, max_splats)
    out = project / "splats" / f"{name}.tscn"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(scene)
    return {"scene": str(out), "res_path": f"res://splats/{name}.tscn", **info}


def verify_in_godot(project: Path, res_path: str, root: Path | None = None, timeout: float = 180.0) -> dict[str, Any]:
    """Load the scene in headless Godot and read back instance count + probe transforms/colours."""
    import subprocess

    from forge import milestones
    from forge.paths import find_repo_root
    godot = milestones.godot_binary(root or find_repo_root())
    if godot is None:
        raise FileNotFoundError("Godot binary not found (GODOT_BIN, PATH, or godot-bin/godot)")
    import shutil
    script = project / "gdgs_verify.gd"
    script.write_text(VERIFY_GD)
    xvfb = shutil.which("xvfb-run")
    # A real (software GL, Mesa llvmpipe) renderer under Xvfb: headless Godot uses a dummy RenderingServer that drops
    # MultiMesh data, so the read-back + render check need a display. Without Xvfb only load + count are checked.
    head = [xvfb, "-a", str(godot), "--rendering-driver", "opengl3", "--resolution", "320x240"] if xvfb else [str(godot), "--headless"]
    p = subprocess.run([*head, "--path", str(project), "--script", "res://gdgs_verify.gd", "--", res_path],
                       capture_output=True, text=True, timeout=timeout)
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("GDGS_VERIFY ")), None)
    if line is None:
        return {"ok": False, "exit": p.returncode, "stderr": p.stderr[-800:]}
    return {"ok": True, "exit": p.returncode, **json.loads(line[len("GDGS_VERIFY "):])}


__all__ = ["read_ply", "write_ply", "sphere_splats", "mesh_from_splats", "surface_nets", "write_obj", "write_godot_scene",
           "import_into_godot", "verify_in_godot"]
