# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Triangle meshes: primitives, STL/OBJ/OFF I/O, welding, and manifold / watertight / volume validation (NumPy)."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class TriMesh:
    positions: np.ndarray                      # (N, 3) float64
    faces: np.ndarray                          # (M, 3) int64, counter-clockwise = outward (right-handed)
    normals: np.ndarray | None = None          # (N, 3) per-vertex
    uvs: np.ndarray | None = None              # (N, 2)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.positions = np.asarray(self.positions, np.float64).reshape(-1, 3)
        self.faces = np.asarray(self.faces, np.int64).reshape(-1, 3)

    @property
    def n_vertices(self) -> int:
        return int(self.positions.shape[0])

    @property
    def n_triangles(self) -> int:
        return int(self.faces.shape[0])

    def copy(self) -> "TriMesh":
        return TriMesh(self.positions.copy(), self.faces.copy(),
                       None if self.normals is None else self.normals.copy(),
                       None if self.uvs is None else self.uvs.copy(), dict(self.meta))

    def bbox(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.n_vertices:
            return np.zeros(3), np.zeros(3)
        return self.positions.min(0), self.positions.max(0)

    def transformed(self, m: np.ndarray, flip_winding: bool | None = None) -> "TriMesh":
        m = np.asarray(m, float)
        lin = m[:3, :3] if m.shape == (4, 4) else m
        t = m[:3, 3] if m.shape == (4, 4) else np.zeros(3)
        out = self.copy()
        out.positions = self.positions @ lin.T + t
        if self.normals is not None:
            nm = np.linalg.inv(lin).T
            n = self.normals @ nm.T
            out.normals = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        flip = (np.linalg.det(lin) < 0) if flip_winding is None else flip_winding
        if flip:
            out.faces = self.faces[:, [0, 2, 1]]
        return out

    def vertex_normals(self) -> np.ndarray:
        p, f = self.positions, self.faces
        fn = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
        vn = np.zeros_like(p)
        for k in range(3):
            np.add.at(vn, f[:, k], fn)
        n = np.linalg.norm(vn, axis=1, keepdims=True)
        return vn / np.where(n == 0, 1, n)


def box_project_uvs(m: TriMesh, scale: float = 1.0) -> TriMesh:
    """Unshare vertices per face and assign box-projected UVs (dominant face-normal axis) — texture-ready CSG output."""
    p, f = m.positions, m.faces
    tri = p[f]                                            # (F, 3, 3)
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ax = np.argmax(np.abs(fn), axis=1)
    keep = np.array([[1, 2], [0, 2], [0, 1]])[ax]        # project onto the two other axes
    uv = np.take_along_axis(tri, np.repeat(keep[:, None, :], 3, axis=1), axis=2) * scale
    nrm = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-20)
    out = TriMesh(tri.reshape(-1, 3), np.arange(f.shape[0] * 3).reshape(-1, 3),
                  np.repeat(nrm, 3, axis=0), uv.reshape(-1, 2) % 1.0 if False else uv.reshape(-1, 2), dict(m.meta))
    return out


def merge(meshes: list[TriMesh]) -> TriMesh:
    pos, fac, off = [], [], 0
    for m in meshes:
        pos.append(m.positions)
        fac.append(m.faces + off)
        off += m.n_vertices
    return TriMesh(np.concatenate(pos) if pos else np.zeros((0, 3)), np.concatenate(fac) if fac else np.zeros((0, 3), int))


def weld(m: TriMesh, eps: float = 1e-6) -> TriMesh:
    """Merge vertices closer than `eps` (grid quantisation, deterministic) and drop degenerate faces."""
    if not m.n_vertices:
        return m.copy()
    q = np.round(m.positions / eps).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(first, kind="stable")            # keep first-seen order → stable output
    remap = np.empty_like(order)
    remap[order] = np.arange(order.size)
    pos = m.positions[first[order]]
    f = remap[inv[m.faces]]
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return TriMesh(pos, f[keep], meta=dict(m.meta))


# ----------------------------------------------------------------------------- validation

def edge_report(m: TriMesh) -> dict[str, Any]:
    f = m.faces
    if not f.size:
        return {"edges": 0, "boundary_edges": 0, "nonmanifold_edges": 0, "inconsistent_edges": 0}
    directed = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    und = np.sort(directed, axis=1)
    uniq, counts = np.unique(und, axis=0, return_counts=True)
    # orientation consistency: each interior edge must appear once as (a,b) and once as (b,a)
    d_uniq, d_counts = np.unique(directed, axis=0, return_counts=True)
    dup_directed = int((d_counts > 1).sum())
    return {"edges": int(uniq.shape[0]), "boundary_edges": int((counts == 1).sum()),
            "nonmanifold_edges": int((counts > 2).sum()), "inconsistent_edges": dup_directed}


def signed_volume(m: TriMesh) -> float:
    p, f = m.positions, m.faces
    if not f.size:
        return 0.0
    a, b, c = p[f[:, 0]], p[f[:, 1]], p[f[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def surface_area(m: TriMesh) -> float:
    p, f = m.positions, m.faces
    if not f.size:
        return 0.0
    return float(0.5 * np.linalg.norm(np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]]), axis=1).sum())


def validate(m: TriMesh, tri_budget: int | None = None) -> dict[str, Any]:
    e = edge_report(m)
    used = np.unique(m.faces) if m.faces.size else np.zeros(0, int)
    lo, hi = m.bbox()
    euler = m.n_vertices - e["edges"] + m.n_triangles
    vol = signed_volume(m)
    watertight = e["boundary_edges"] == 0 and e["nonmanifold_edges"] == 0 and m.n_triangles > 0
    rep = {
        "vertices": m.n_vertices, "triangles": m.n_triangles, **e,
        "unreferenced_vertices": int(m.n_vertices - used.size),
        "manifold": e["nonmanifold_edges"] == 0 and e["inconsistent_edges"] == 0,
        "watertight": watertight, "euler_characteristic": int(euler),
        "volume": round(vol, 9), "outward_oriented": vol > 0, "area": round(surface_area(m), 9),
        "bbox_min": [round(float(x), 6) for x in lo], "bbox_max": [round(float(x), 6) for x in hi],
        "finite": bool(np.isfinite(m.positions).all()),
    }
    if tri_budget is not None:
        rep["tri_budget"] = tri_budget
        rep["within_budget"] = m.n_triangles <= tri_budget
    rep["ok"] = bool(rep["manifold"] and rep["watertight"] and rep["outward_oriented"] and rep["finite"]
                     and rep.get("within_budget", True))
    return rep


# ----------------------------------------------------------------------------- primitives (watertight, outward CCW)

def box(size: tuple[float, float, float] = (1, 1, 1), center: bool = True) -> TriMesh:
    sx, sy, sz = size
    p = np.array([[x, y, z] for z in (0, sz) for y in (0, sy) for x in (0, sx)], float)
    if center:
        p -= np.array(size, float) / 2
    f = [[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4],
         [2, 6, 3], [3, 6, 7], [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]]
    return TriMesh(p, np.array(f))


def uv_sphere(r: float = 1.0, seg: int = 24, rings: int = 12) -> TriMesh:
    pts = [[0, 0, r]]
    for i in range(1, rings):
        th = np.pi * i / rings
        for j in range(seg):
            ph = 2 * np.pi * j / seg
            pts.append([r * np.sin(th) * np.cos(ph), r * np.sin(th) * np.sin(ph), r * np.cos(th)])
    pts.append([0, 0, -r])
    f = []
    for j in range(seg):
        f.append([0, 1 + j, 1 + (j + 1) % seg])
    for i in range(rings - 2):
        a, b = 1 + i * seg, 1 + (i + 1) * seg
        for j in range(seg):
            j2 = (j + 1) % seg
            f += [[a + j, b + j, b + j2], [a + j, b + j2, a + j2]]
    last = len(pts) - 1
    base = 1 + (rings - 2) * seg
    for j in range(seg):
        f.append([base + j, last, base + (j + 1) % seg])
    return TriMesh(np.array(pts, float), np.array(f))


def cylinder(r: float = 0.5, h: float = 1.0, seg: int = 24, center: bool = False) -> TriMesh:
    z0 = -h / 2 if center else 0.0
    ang = 2 * np.pi * np.arange(seg) / seg
    ring = np.stack([r * np.cos(ang), r * np.sin(ang)], 1)
    p = np.concatenate([np.c_[ring, np.full(seg, z0)], np.c_[ring, np.full(seg, z0 + h)], [[0, 0, z0], [0, 0, z0 + h]]])
    cb, ct = 2 * seg, 2 * seg + 1
    f = []
    for j in range(seg):
        j2 = (j + 1) % seg
        f += [[j, j2, seg + j2], [j, seg + j2, seg + j], [cb, j2, j], [ct, seg + j, seg + j2]]
    return TriMesh(p, np.array(f))


# ----------------------------------------------------------------------------- I/O

def write_stl(m: TriMesh, name: str = "assetfabric") -> bytes:
    p, f = m.positions.astype(np.float32), m.faces
    n = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
    n = (n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-20)).astype(np.float32)
    rec = np.zeros(m.n_triangles, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, p[f]
    hdr = name.encode()[:80].ljust(80, b"\0")
    return hdr + struct.pack("<I", m.n_triangles) + rec.tobytes()


def read_stl(data: bytes, weld_eps: float = 1e-6) -> TriMesh:
    """Binary or ASCII STL → welded TriMesh."""
    is_ascii = data[:5].lower() == b"solid" and b"facet" in data[:1024]
    if not is_ascii and len(data) >= 84:
        (n,) = struct.unpack("<I", data[80:84])
        if 84 + 50 * n == len(data):
            rec = np.frombuffer(data[84:], dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")], count=n)
            v = rec["v"].astype(np.float64).reshape(-1, 3)
            return weld(TriMesh(v, np.arange(v.shape[0]).reshape(-1, 3)), weld_eps)
    verts = [list(map(float, ln.split()[1:4])) for ln in data.decode("ascii", "replace").splitlines()
             if ln.strip().startswith("vertex")]
    v = np.array(verts, float).reshape(-1, 3)
    return weld(TriMesh(v, np.arange(v.shape[0]).reshape(-1, 3)), weld_eps)


def _fmt(a: np.ndarray) -> list[str]:
    return [" ".join(f"{x:.6f}".rstrip("0").rstrip(".") if x != 0 else "0" for x in row) for row in np.asarray(a, float)]


def write_obj(m: TriMesh, mtl: str | None = None, material: str | None = None, name: str = "mesh") -> bytes:
    lines = ["# AssetFabric universal OBJ export"]
    if mtl:
        lines.append(f"mtllib {mtl}")
    lines.append(f"o {name}")
    lines += ["v " + s for s in _fmt(m.positions + 0.0)]
    has_uv = m.uvs is not None
    has_n = m.normals is not None
    if has_uv:
        lines += ["vt " + s for s in _fmt(m.uvs)]
    if has_n:
        lines += ["vn " + s for s in _fmt(m.normals)]
    if material:
        lines.append(f"usemtl {material}")
    for a, b, c in (m.faces + 1).tolist():
        if has_uv and has_n:
            lines.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")
        elif has_uv:
            lines.append(f"f {a}/{a} {b}/{b} {c}/{c}")
        elif has_n:
            lines.append(f"f {a}//{a} {b}//{b} {c}//{c}")
        else:
            lines.append(f"f {a} {b} {c}")
    return ("\n".join(lines) + "\n").encode()


def read_obj(data: bytes) -> TriMesh:
    v, f = [], []
    for ln in data.decode("utf-8", "replace").splitlines():
        s = ln.split()
        if not s:
            continue
        if s[0] == "v":
            v.append([float(x) for x in s[1:4]])
        elif s[0] == "f":
            idx = [int(t.split("/")[0]) for t in s[1:]]
            idx = [i - 1 if i > 0 else len(v) + i for i in idx]
            for k in range(1, len(idx) - 1):                 # fan-triangulate polygons
                f.append([idx[0], idx[k], idx[k + 1]])
    return TriMesh(np.array(v, float).reshape(-1, 3), np.array(f, int).reshape(-1, 3))


def write_off(m: TriMesh) -> bytes:
    lines = ["OFF", f"{m.n_vertices} {m.n_triangles} 0"] + _fmt(m.positions + 0.0)
    lines += [f"3 {a} {b} {c}" for a, b, c in m.faces.tolist()]
    return ("\n".join(lines) + "\n").encode()


def read_off(data: bytes) -> TriMesh:
    toks = [ln.split("#")[0].strip() for ln in data.decode("utf-8", "replace").splitlines()]
    toks = [t for t in toks if t]
    if not toks or not toks[0].startswith("OFF"):
        raise ValueError("not an OFF file")
    head, i = toks[0][3:].split(), 1
    if not head:
        head, i = toks[1].split(), 2
    nv, nf = int(head[0]), int(head[1])
    body = toks[i:]
    v = np.array([[float(x) for x in body[k].split()[:3]] for k in range(nv)], float).reshape(-1, 3)
    f = []
    for k in range(nv, nv + nf):
        s = [int(x) for x in body[k].split()]
        idx = s[1:1 + s[0]]
        for j in range(1, len(idx) - 1):
            f.append([idx[0], idx[j], idx[j + 1]])
    return TriMesh(v, np.array(f, int).reshape(-1, 3))
