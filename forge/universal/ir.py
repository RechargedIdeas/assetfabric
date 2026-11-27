# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Universal Scene & Asset IR — one in-memory model for 2D, 2.5D and 3D content.

* 2D: `Texture` (PNG bytes + semantic: base_color / normal / depth / emission / ao / orm), `Sprite` (atlas texture +
  frame rects + optional normal / depth / emission maps, pivot, pixels-per-unit, animations) — the data Sprite Lamp /
  Sprite Pro style lighting tools and 2D engines consume.
* 2.5D: `Layer25D` — isometric / orthographic / layered-billboard / depth-card placement of sprites with depth and
  parallax (exported to 3D tools as textured cards, to 2D engines as layered sprites).
* 3D: `MeshAsset` (TriMesh + material + optional skin), `Material` (glTF-style metallic-roughness PBR),
  `Skeleton` (joint hierarchy, rest transforms, inverse bind matrices), `PointCloud`, `SplatSet` (3DGS `.ply`).
* `Scene` holds nodes (4×4 local matrices, column vectors) in a declared coordinate convention (`coords`).

Serialisation is canonical JSON: arrays are stored as little-endian base64 with dtype + shape, so
`from_dict(to_dict(s))` is bit-exact and `digest()` is stable across runs and machines.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from forge.universal import IR_VERSION, coords
from forge.universal.mesh import TriMesh

DIMENSIONS = ("2d", "2.5d", "3d")
TEXTURE_SEMANTICS = ("base_color", "normal", "depth", "emission", "ao", "orm", "height", "lighting_profile")
PROJECTIONS = ("isometric", "orthographic", "layered_billboard", "depth_card")


def _arr(a: np.ndarray | None) -> dict[str, Any] | None:
    if a is None:
        return None
    a = np.ascontiguousarray(a)
    le = a.astype(a.dtype.newbyteorder("<"), copy=False)
    return {"dtype": le.dtype.str, "shape": list(a.shape), "b64": base64.b64encode(le.tobytes()).decode()}


def _unarr(d: dict[str, Any] | None) -> np.ndarray | None:
    if d is None:
        return None
    return np.frombuffer(base64.b64decode(d["b64"]), dtype=np.dtype(d["dtype"])).reshape(d["shape"]).copy()


@dataclass
class Texture:
    id: str
    png: bytes
    semantic: str = "base_color"
    filter: str = "nearest"                  # pixel-art default; "linear" for photographic/PBR maps
    colorspace: str = "srgb"                 # "srgb" | "linear" (normal/depth/ao/orm are linear)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "semantic": self.semantic, "filter": self.filter, "colorspace": self.colorspace,
                "png_b64": base64.b64encode(self.png).decode()}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Texture":
        return Texture(d["id"], base64.b64decode(d["png_b64"]), d["semantic"], d["filter"], d["colorspace"])


@dataclass
class Material:
    id: str
    base_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    metallic: float = 0.0
    roughness: float = 0.8
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)
    textures: dict[str, str] = field(default_factory=dict)     # semantic -> texture id
    alpha_mode: str = "OPAQUE"                                 # OPAQUE | MASK | BLEND
    alpha_cutoff: float = 0.5
    double_sided: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "base_color": list(self.base_color), "metallic": self.metallic,
                "roughness": self.roughness, "emissive": list(self.emissive), "textures": dict(sorted(self.textures.items())),
                "alpha_mode": self.alpha_mode, "alpha_cutoff": self.alpha_cutoff, "double_sided": self.double_sided}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Material":
        return Material(d["id"], tuple(d["base_color"]), d["metallic"], d["roughness"], tuple(d["emissive"]),
                        dict(d["textures"]), d["alpha_mode"], d["alpha_cutoff"], d["double_sided"])


@dataclass
class Skeleton:
    id: str
    joint_names: list[str]
    parents: list[int]                       # -1 = root
    rest_local: np.ndarray                   # (J, 4, 4) local rest transforms
    inverse_bind: np.ndarray                 # (J, 4, 4)

    def world_rest(self) -> np.ndarray:
        w = np.zeros_like(self.rest_local)
        for j, p in enumerate(self.parents):
            w[j] = self.rest_local[j] if p < 0 else w[p] @ self.rest_local[j]
        return w

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "joint_names": list(self.joint_names), "parents": list(self.parents),
                "rest_local": _arr(self.rest_local), "inverse_bind": _arr(self.inverse_bind)}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Skeleton":
        return Skeleton(d["id"], list(d["joint_names"]), list(d["parents"]), _unarr(d["rest_local"]), _unarr(d["inverse_bind"]))


@dataclass
class MeshAsset:
    id: str
    mesh: TriMesh
    material: str | None = None
    skeleton: str | None = None
    joints: np.ndarray | None = None         # (N, 4) uint16
    weights: np.ndarray | None = None        # (N, 4) float32, rows sum to 1

    def to_dict(self) -> dict[str, Any]:
        m = self.mesh
        return {"id": self.id, "material": self.material, "skeleton": self.skeleton,
                "positions": _arr(m.positions), "faces": _arr(m.faces), "normals": _arr(m.normals), "uvs": _arr(m.uvs),
                "joints": _arr(self.joints), "weights": _arr(self.weights)}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "MeshAsset":
        tm = TriMesh(_unarr(d["positions"]), _unarr(d["faces"]), _unarr(d["normals"]), _unarr(d["uvs"]))
        return MeshAsset(d["id"], tm, d["material"], d["skeleton"], _unarr(d["joints"]), _unarr(d["weights"]))


@dataclass
class Sprite:
    id: str
    atlas: str                                # base_color texture id
    frames: list[tuple[int, int, int, int]]   # x, y, w, h in atlas pixels (top-left origin)
    maps: dict[str, str] = field(default_factory=dict)   # normal / depth / emission / ao -> texture id (same layout)
    pivot: tuple[float, float] = (0.5, 1.0)   # normalised, top-left origin (feet pivot)
    pixels_per_unit: float = 16.0
    animations: dict[str, dict[str, Any]] = field(default_factory=dict)   # name -> {"frames": [...], "fps": n, "loop": bool}

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "atlas": self.atlas, "frames": [list(f) for f in self.frames],
                "maps": dict(sorted(self.maps.items())), "pivot": list(self.pivot), "pixels_per_unit": self.pixels_per_unit,
                "animations": {k: self.animations[k] for k in sorted(self.animations)}}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Sprite":
        return Sprite(d["id"], d["atlas"], [tuple(f) for f in d["frames"]], dict(d["maps"]), tuple(d["pivot"]),
                      d["pixels_per_unit"], dict(d["animations"]))


@dataclass
class Layer25D:
    id: str
    projection: str                           # isometric | orthographic | layered_billboard | depth_card
    sprite: str
    depth: float = 0.0                        # metres behind the picture plane (cards) / sort depth (2D)
    parallax: float = 1.0
    tile_size: tuple[int, int] = (32, 16)     # isometric diamond (2:1) in pixels
    grid_pos: tuple[int, int] = (0, 0)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "projection": self.projection, "sprite": self.sprite, "depth": self.depth,
                "parallax": self.parallax, "tile_size": list(self.tile_size), "grid_pos": list(self.grid_pos)}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Layer25D":
        return Layer25D(d["id"], d["projection"], d["sprite"], d["depth"], d["parallax"], tuple(d["tile_size"]), tuple(d["grid_pos"]))

    def screen_position(self) -> tuple[float, float]:
        """Pixel offset of the layer's anchor (isometric: standard 2:1 diamond projection)."""
        gx, gy = self.grid_pos
        tw, th = self.tile_size
        if self.projection == "isometric":
            return ((gx - gy) * tw / 2.0, (gx + gy) * th / 2.0)
        return (gx * tw * self.parallax, gy * th * self.parallax)


@dataclass
class PointCloud:
    id: str
    positions: np.ndarray                     # (N, 3) float32
    colors: np.ndarray | None = None          # (N, 3) uint8

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "positions": _arr(self.positions), "colors": _arr(self.colors)}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PointCloud":
        return PointCloud(d["id"], _unarr(d["positions"]), _unarr(d["colors"]))


@dataclass
class SplatSet:
    id: str
    ply: bytes                                # INRIA/OpenSplat 3DGS binary little-endian .ply

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "ply_b64": base64.b64encode(self.ply).decode()}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "SplatSet":
        return SplatSet(d["id"], base64.b64decode(d["ply_b64"]))


@dataclass
class Camera:
    """Pinhole camera: intrinsics in pixels; `pose` = camera-to-world 4×4 in the scene convention, camera looking down
    its local -Z with +Y up (OpenGL/glTF camera frame). Used by photogrammetry / splat exporters (COLMAP, nerfstudio)."""
    id: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    pose: np.ndarray = field(default_factory=lambda: np.eye(4))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "width": self.width, "height": self.height, "fx": self.fx, "fy": self.fy,
                "cx": self.cx, "cy": self.cy, "pose": _arr(np.asarray(self.pose, np.float64))}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Camera":
        return Camera(d["id"], d["width"], d["height"], d["fx"], d["fy"], d["cx"], d["cy"], _unarr(d["pose"]))


@dataclass
class Node:
    name: str
    matrix: np.ndarray = field(default_factory=lambda: np.eye(4))
    mesh: str | None = None
    sprite: str | None = None
    layer: str | None = None
    points: str | None = None
    splats: str | None = None
    children: list[int] = field(default_factory=list)
    camera: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "matrix": _arr(np.asarray(self.matrix, np.float64)), "mesh": self.mesh,
                "sprite": self.sprite, "layer": self.layer, "points": self.points, "splats": self.splats,
                "children": list(self.children), "camera": self.camera}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Node":
        return Node(d["name"], _unarr(d["matrix"]), d["mesh"], d["sprite"], d["layer"], d["points"], d["splats"],
                    list(d["children"]), d.get("camera"))


_COLL = (("textures", Texture), ("materials", Material), ("skeletons", Skeleton), ("meshes", MeshAsset),
         ("sprites", Sprite), ("layers", Layer25D), ("point_clouds", PointCloud), ("splats", SplatSet),
         ("cameras", Camera))


@dataclass
class Scene:
    name: str
    dimension: str = "3d"
    convention: str = "gltf"
    textures: dict[str, Texture] = field(default_factory=dict)
    materials: dict[str, Material] = field(default_factory=dict)
    skeletons: dict[str, Skeleton] = field(default_factory=dict)
    meshes: dict[str, MeshAsset] = field(default_factory=dict)
    sprites: dict[str, Sprite] = field(default_factory=dict)
    layers: dict[str, Layer25D] = field(default_factory=dict)
    point_clouds: dict[str, PointCloud] = field(default_factory=dict)
    splats: dict[str, SplatSet] = field(default_factory=dict)
    cameras: dict[str, Camera] = field(default_factory=dict)
    nodes: list[Node] = field(default_factory=list)
    roots: list[int] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, obj: Any) -> Any:
        for name, cls in _COLL:
            if isinstance(obj, cls):
                getattr(self, name)[obj.id] = obj
                return obj
        raise TypeError(type(obj))

    def add_node(self, node: Node, parent: int | None = None) -> int:
        self.nodes.append(node)
        i = len(self.nodes) - 1
        (self.roots if parent is None else self.nodes[parent].children).append(i)
        return i

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"ir_version": IR_VERSION, "name": self.name, "dimension": self.dimension,
                             "convention": self.convention, "meta": self.meta,
                             "nodes": [n.to_dict() for n in self.nodes], "roots": list(self.roots)}
        for name, _ in _COLL:
            coll = getattr(self, name)
            d[name] = [coll[k].to_dict() for k in sorted(coll)]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Scene":
        major = str(d.get("ir_version", "0")).split(".")[0]
        if major != IR_VERSION.split(".")[0]:
            raise ValueError(f"IR major version {d.get('ir_version')} not supported (this build: {IR_VERSION})")
        s = Scene(d["name"], d["dimension"], d["convention"], meta=dict(d.get("meta", {})))
        for name, cls in _COLL:
            for item in d.get(name, []):
                o = cls.from_dict(item)
                getattr(s, name)[o.id] = o
        s.nodes = [Node.from_dict(n) for n in d["nodes"]]
        s.roots = list(d["roots"])
        return s

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_json(text: str) -> "Scene":
        return Scene.from_dict(json.loads(text))

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    def world_matrices(self) -> list[np.ndarray]:
        out: list[np.ndarray | None] = [None] * len(self.nodes)

        def walk(i: int, parent: np.ndarray) -> None:
            out[i] = parent @ self.nodes[i].matrix
            for c in self.nodes[i].children:
                walk(c, out[i])
        for r in self.roots:
            walk(r, np.eye(4))
        return [m if m is not None else np.eye(4) for m in out]

    def converted(self, dst: str) -> "Scene":
        """A copy re-expressed in another coordinate convention: vertex data, normals, node matrices and UVs
        converted exactly; winding reversed when the handedness changes."""
        s = Scene.from_json(self.to_json())
        if dst == self.convention:
            return s
        m3 = coords.matrix(self.convention, dst)
        flip = coords.needs_winding_flip(self.convention, dst)
        for ma in s.meshes.values():
            tm = ma.mesh
            new = tm.transformed(m3, flip_winding=flip)
            if tm.normals is not None:
                new.normals = coords.convert_directions(tm.normals, self.convention, dst)
            if tm.uvs is not None:
                new.uvs = coords.convert_uv(tm.uvs, self.convention, dst)
            ma.mesh = new
        for sk in s.skeletons.values():
            m4 = coords.matrix4(self.convention, dst)
            inv = np.linalg.inv(m4)
            sk.rest_local = np.einsum("ij,njk,kl->nil", m4, sk.rest_local, inv)
            sk.inverse_bind = np.einsum("ij,njk,kl->nil", m4, sk.inverse_bind, inv)
        for pc in s.point_clouds.values():
            pc.positions = coords.convert_points(pc.positions, self.convention, dst).astype(pc.positions.dtype)
        for cam in s.cameras.values():
            # same physical camera re-expressed: position scaled + basis rotated/reflected (camera-local frame unchanged)
            m4 = coords.matrix4(self.convention, dst)
            pose = np.asarray(cam.pose, float)
            rot = coords.matrix(self.convention, dst) @ pose[:3, :3]
            rot = rot / np.linalg.norm(rot, axis=0, keepdims=True)   # a reflection (det -1) when handedness flips
            new = np.eye(4)
            new[:3, :3] = rot
            new[:3, 3] = (m4 @ np.append(pose[:3, 3], 1.0))[:3]
            cam.pose = new
        for n in s.nodes:
            n.matrix = coords.convert_transform(n.matrix, self.convention, dst)
        s.convention = dst
        return s


# ----------------------------------------------------------------------------- validation

def validate(s: Scene) -> dict[str, Any]:
    errs: list[str] = []
    if s.dimension not in DIMENSIONS:
        errs.append(f"dimension {s.dimension!r} not in {DIMENSIONS}")
    if s.convention not in coords.CONVENTIONS:
        errs.append(f"unknown convention {s.convention!r}")
    from forge.universal import png as _png
    for t in s.textures.values():
        if t.semantic not in TEXTURE_SEMANTICS:
            errs.append(f"texture {t.id}: semantic {t.semantic!r}")
        try:
            _png.info(t.png)
        except ValueError as e:
            errs.append(f"texture {t.id}: {e}")
    for m in s.materials.values():
        for sem, tid in m.textures.items():
            if tid not in s.textures:
                errs.append(f"material {m.id}: missing texture {tid}")
        if m.alpha_mode not in ("OPAQUE", "MASK", "BLEND"):
            errs.append(f"material {m.id}: alpha_mode")
        if not (0 <= m.metallic <= 1 and 0 <= m.roughness <= 1):
            errs.append(f"material {m.id}: metallic/roughness out of [0,1]")
    for ma in s.meshes.values():
        tm = ma.mesh
        if ma.material and ma.material not in s.materials:
            errs.append(f"mesh {ma.id}: missing material {ma.material}")
        if tm.faces.size and (tm.faces.min() < 0 or tm.faces.max() >= tm.n_vertices):
            errs.append(f"mesh {ma.id}: face index out of range")
        for nm, a, w in (("normals", tm.normals, 3), ("uvs", tm.uvs, 2)):
            if a is not None and a.shape != (tm.n_vertices, w):
                errs.append(f"mesh {ma.id}: {nm} shape {a.shape}")
        if ma.skeleton:
            sk = s.skeletons.get(ma.skeleton)
            if sk is None:
                errs.append(f"mesh {ma.id}: missing skeleton {ma.skeleton}")
            elif ma.joints is None or ma.weights is None:
                errs.append(f"mesh {ma.id}: skinned mesh without joints/weights")
            else:
                if ma.joints.shape != (tm.n_vertices, 4) or ma.weights.shape != (tm.n_vertices, 4):
                    errs.append(f"mesh {ma.id}: joints/weights must be (N,4)")
                elif ma.joints.max() >= len(sk.joint_names):
                    errs.append(f"mesh {ma.id}: joint index out of range")
                elif not np.allclose(ma.weights.sum(1), 1.0, atol=1e-4):
                    errs.append(f"mesh {ma.id}: weights do not sum to 1")
    for sk in s.skeletons.values():
        if any(p >= j for j, p in enumerate(sk.parents)):
            errs.append(f"skeleton {sk.id}: parents must precede children")
        if not np.allclose(sk.inverse_bind @ sk.world_rest(), np.eye(4), atol=1e-6):
            errs.append(f"skeleton {sk.id}: inverse_bind != inverse(world rest)")
    for sp in s.sprites.values():
        tex = s.textures.get(sp.atlas)
        if tex is None:
            errs.append(f"sprite {sp.id}: missing atlas {sp.atlas}")
            continue
        info = _png.info(tex.png)
        for (x, y, w, h) in sp.frames:
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > info["width"] or y + h > info["height"]:
                errs.append(f"sprite {sp.id}: frame {(x, y, w, h)} outside atlas")
        for sem, tid in sp.maps.items():
            t2 = s.textures.get(tid)
            if t2 is None:
                errs.append(f"sprite {sp.id}: missing {sem} map {tid}")
            elif (_png.info(t2.png)["width"], _png.info(t2.png)["height"]) != (info["width"], info["height"]):
                errs.append(f"sprite {sp.id}: {sem} map size differs from atlas")
        for an, a in sp.animations.items():
            if any(not (0 <= f < len(sp.frames)) for f in a.get("frames", [])):
                errs.append(f"sprite {sp.id}: animation {an} frame index out of range")
    for ly in s.layers.values():
        if ly.projection not in PROJECTIONS:
            errs.append(f"layer {ly.id}: projection {ly.projection!r}")
        if ly.sprite not in s.sprites:
            errs.append(f"layer {ly.id}: missing sprite {ly.sprite}")
    seen: set[int] = set()

    def walk(i: int, stack: tuple[int, ...]) -> None:
        if i in stack:
            errs.append(f"node cycle at {i}")
            return
        if not (0 <= i < len(s.nodes)):
            errs.append(f"node index {i} out of range")
            return
        if i in seen:
            errs.append(f"node {i} has more than one parent")
            return
        seen.add(i)
        n = s.nodes[i]
        for ref, coll in ((n.mesh, s.meshes), (n.sprite, s.sprites), (n.layer, s.layers), (n.points, s.point_clouds),
                          (n.splats, s.splats), (n.camera, s.cameras)):
            if ref is not None and ref not in coll:
                errs.append(f"node {n.name}: dangling reference {ref}")
        for c in n.children:
            walk(c, stack + (i,))
    for r in s.roots:
        walk(r, ())
    if len(seen) != len(s.nodes) and not errs:
        errs.append("unreachable nodes")
    return {"ok": not errs, "errors": errs}
