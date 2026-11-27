# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Pure-Python (NumPy) parametric CSG — the CPU fallback for OpenSCAD.

A parametric model is a declarative CSG tree (the same tree `openscad.emit_scad` turns into `.scad` source):

    primitives : cube{size, center} · sphere{r} · cylinder{h, r | r1+r2, center} · torus{R, r}
    transforms : translate{v} · rotate{a (deg, X then Y then Z like OpenSCAD)} · scale{v} · repeat_rotate{n, axis}
    booleans   : union · difference (first child minus the rest) · intersection

Numeric fields may be numbers or expressions over the template's parameters (`"width - 2*wall"`), evaluated by a
small AST whitelist (numbers, parameter names, + - * / % **, unary -, min/max/abs/sqrt/sin/cos/floor/ceil).

Evaluation samples the tree's signed distance field on a regular grid and polygonises it with **marching
tetrahedra** (6 conforming tetrahedra per cell, vertices keyed by global grid edge), which yields a closed,
consistently oriented 2-manifold by construction; optional Newton projection snaps vertices onto the exact surface.
Output is deterministic (no RNG, stable ordering)."""

from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass
from typing import Any

import numpy as np

from forge.universal.mesh import TriMesh

PRIMITIVES = ("cube", "sphere", "cylinder", "torus")
TRANSFORMS = ("translate", "rotate", "scale", "repeat_rotate")
BOOLEANS = ("union", "difference", "intersection")
OPS = PRIMITIVES + TRANSFORMS + BOOLEANS


class CsgError(ValueError):
    pass


# ----------------------------------------------------------------------------- expressions

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.Pow: operator.pow}
FUNCS = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil,
         "sin": lambda d: math.sin(math.radians(d)), "cos": lambda d: math.cos(math.radians(d))}   # OpenSCAD trig is degrees


def check_expr(expr: str, names: set[str]) -> None:
    """Raise CsgError unless `expr` only uses whitelisted syntax and known names (also safe to emit as OpenSCAD)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CsgError(f"bad expression {expr!r}: {e.msg}") from e
    for n in ast.walk(tree):
        if isinstance(n, (ast.Expression, ast.Load, ast.UAdd, ast.USub, ast.UnaryOp, ast.BinOp)) or type(n) in _BIN:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            continue
        if isinstance(n, ast.Name) and (n.id in names or n.id in FUNCS):
            continue
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            continue
        raise CsgError(f"expression {expr!r}: {type(n).__name__} {getattr(n, 'id', '')!s} not allowed")


def eval_expr(v: Any, params: dict[str, float]) -> float:
    if isinstance(v, bool):
        raise CsgError("booleans are not numeric")
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        raise CsgError(f"not a number/expression: {v!r}")
    check_expr(v, set(params))

    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            return float(params[n.id])
        if isinstance(n, ast.UnaryOp):
            x = ev(n.operand)
            return -x if isinstance(n.op, ast.USub) else x
        if isinstance(n, ast.BinOp):
            return float(_BIN[type(n.op)](ev(n.left), ev(n.right)))
        if isinstance(n, ast.Call):
            return float(FUNCS[n.func.id](*[ev(a) for a in n.args]))
        raise CsgError(type(n).__name__)
    return ev(ast.parse(v, mode="eval"))


def resolve(node: dict[str, Any], params: dict[str, float]) -> dict[str, Any]:
    """Evaluate every expression in the tree → a purely numeric tree (validated)."""
    op = node.get("op")
    if op not in OPS:
        raise CsgError(f"unknown op {op!r}")
    out: dict[str, Any] = {"op": op}
    for k, v in node.items():
        if k in ("op", "children") or k.startswith("_"):
            continue
        if k == "center":
            out[k] = bool(v)
        elif k == "axis":
            if v not in ("x", "y", "z"):
                raise CsgError("axis must be x|y|z")
            out[k] = v
        elif isinstance(v, list):
            out[k] = [eval_expr(x, params) for x in v]
        else:
            out[k] = eval_expr(v, params)
    kids = node.get("children", [])
    if op in PRIMITIVES and kids:
        raise CsgError(f"{op} takes no children")
    if op not in PRIMITIVES and not kids:
        raise CsgError(f"{op} needs children")
    out["children"] = [resolve(c, params) for c in kids]
    if op == "cube":
        s = out.get("size", [1, 1, 1])
        out["size"] = s * 3 if len(s) == 1 else s
        if len(out["size"]) != 3 or min(out["size"]) <= 0:
            raise CsgError("cube size must be 3 positive numbers")
    if op == "sphere" and out.get("r", 0) <= 0:
        raise CsgError("sphere r must be > 0")
    if op == "cylinder":
        if "r" in out:
            out["r1"] = out["r2"] = out.pop("r")
        if out.get("h", 0) <= 0 or out.get("r1", -1) < 0 or out.get("r2", -1) < 0 or out["r1"] + out["r2"] <= 0:
            raise CsgError("cylinder needs h > 0 and radii >= 0")
    if op == "torus" and not (0 < out.get("r", 0) < out.get("R", 0)):
        raise CsgError("torus needs 0 < r < R")
    if op in ("translate", "rotate", "scale") and len(out.get("v" if op != "rotate" else "a", [])) != 3:
        raise CsgError(f"{op} needs a 3-vector")
    if op == "scale" and min(abs(x) for x in out["v"]) == 0:
        raise CsgError("scale components must be non-zero")
    if op == "repeat_rotate" and not (1 <= int(out.get("n", 0)) <= 256):
        raise CsgError("repeat_rotate n in [1, 256]")
    return out


# ----------------------------------------------------------------------------- SDF

def _rot(a: list[float]) -> np.ndarray:
    ax, ay, az = (math.radians(x) for x in a)
    rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    return rz @ ry @ rx                       # OpenSCAD: rotate([x,y,z]) = Rz·Ry·Rx


def _axis_rot(axis: str, deg: float) -> np.ndarray:
    return _rot([deg if axis == "x" else 0, deg if axis == "y" else 0, deg if axis == "z" else 0])


def sdf(node: dict[str, Any], p: np.ndarray) -> np.ndarray:
    """Signed distance (negative inside) of a resolved tree at points p (N,3). Exact for primitives/rigid
    transforms; a sign-correct bound under non-uniform scale and booleans (enough for polygonisation)."""
    op = node["op"]
    if op == "cube":
        s = np.array(node["size"], float)
        c = np.zeros(3) if node.get("center") else s / 2
        q = np.abs(p - c) - s / 2
        return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(1), 0)
    if op == "sphere":
        return np.linalg.norm(p, axis=1) - node["r"]
    if op == "cylinder":
        h, r1, r2 = node["h"], node["r1"], node["r2"]
        z0 = -h / 2 if node.get("center") else 0.0
        t = np.clip((p[:, 2] - z0) / h, 0, 1)
        rz = r1 + (r2 - r1) * t
        slope = math.sqrt(1 + ((r2 - r1) / h) ** 2)
        d_side = (np.hypot(p[:, 0], p[:, 1]) - rz) / slope
        d_cap = np.abs(p[:, 2] - (z0 + h / 2)) - h / 2
        q = np.stack([d_side, d_cap], 1)
        return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(1), 0)
    if op == "torus":                                   # rotate_extrude() translate([R,0]) circle(r): ring in the XY plane
        return np.hypot(np.hypot(p[:, 0], p[:, 1]) - node["R"], p[:, 2]) - node["r"]
    kids = node["children"]
    if op == "translate":
        return _union([sdf(k, p - np.array(node["v"])) for k in kids])
    if op == "rotate":
        r = _rot(node["a"])
        return _union([sdf(k, p @ r) for k in kids])    # inverse rotation = Rᵀ; row-vector form p·R
    if op == "scale":
        v = np.array(node["v"], float)
        return _union([sdf(k, p / v) for k in kids]) * float(np.min(np.abs(v)))
    if op == "repeat_rotate":
        n, axis = int(node["n"]), node.get("axis", "z")
        parts = []
        for i in range(n):
            r = _axis_rot(axis, 360.0 * i / n)
            parts += [sdf(k, p @ r) for k in kids]
        return _union(parts)
    vals = [sdf(k, p) for k in kids]
    if op == "union":
        return _union(vals)
    if op == "intersection":
        return np.max(np.stack(vals), axis=0)
    if op == "difference":
        out = vals[0]
        for v in vals[1:]:
            out = np.maximum(out, -v)
        return out
    raise CsgError(op)


def _union(vals: list[np.ndarray]) -> np.ndarray:
    return vals[0] if len(vals) == 1 else np.min(np.stack(vals), axis=0)


def bounds(node: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Conservative axis-aligned bounds of a resolved tree."""
    op = node["op"]
    if op == "cube":
        s = np.array(node["size"], float)
        return (-s / 2, s / 2) if node.get("center") else (np.zeros(3), s)
    if op == "sphere":
        r = node["r"]
        return np.full(3, -r), np.full(3, r)
    if op == "cylinder":
        r = max(node["r1"], node["r2"])
        z0 = -node["h"] / 2 if node.get("center") else 0.0
        return np.array([-r, -r, z0]), np.array([r, r, z0 + node["h"]])
    if op == "torus":
        o = node["R"] + node["r"]
        return np.array([-o, -o, -node["r"]]), np.array([o, o, node["r"]])
    kb = [bounds(k) for k in node["children"]]
    lo = np.min([b[0] for b in kb], 0)
    hi = np.max([b[1] for b in kb], 0)
    if op == "difference":
        lo, hi = kb[0]
    elif op == "intersection":
        lo, hi = np.max([b[0] for b in kb], 0), np.min([b[1] for b in kb], 0)
    if op == "translate":
        return lo + node["v"], hi + node["v"]
    if op in ("rotate", "scale", "repeat_rotate"):
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        if op == "scale":
            pts = corners * np.array(node["v"])
        elif op == "rotate":
            pts = corners @ _rot(node["a"]).T
        else:
            n = int(node["n"])
            pts = np.concatenate([corners @ _axis_rot(node.get("axis", "z"), 360.0 * i / n).T for i in range(n)])
        return pts.min(0), pts.max(0)
    return lo, hi


# ----------------------------------------------------------------------------- marching tetrahedra

_CUBE = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]])
_TETS = np.array([[0, 5, 1, 6], [0, 1, 2, 6], [0, 2, 3, 6], [0, 3, 7, 6], [0, 7, 4, 6], [0, 4, 5, 6]])


@dataclass(frozen=True)
class MeshRecipe:
    """Tunable polygonisation recipe (the object the self-improvement loop evolves)."""
    cell: float = 0.05          # grid cell size in model units
    newton_steps: int = 0       # vertex projection steps onto the exact zero set
    pad_cells: int = 2


def polygonize(tree: dict[str, Any], recipe: MeshRecipe = MeshRecipe(), max_cells: int = 4_000_000) -> TriMesh:
    lo, hi = bounds(tree)
    if np.any(hi <= lo):
        raise CsgError("empty bounds (intersection of disjoint solids?)")
    h = float(recipe.cell)
    lo = lo - recipe.pad_cells * h
    hi = hi + recipe.pad_cells * h
    n = np.ceil((hi - lo) / h).astype(int) + 1
    if int(np.prod(n - 1)) > max_cells:
        raise CsgError(f"grid {tuple(n)} exceeds {max_cells} cells; raise `cell`")
    xs = [lo[i] + h * np.arange(n[i]) for i in range(3)]
    g = np.stack(np.meshgrid(*xs, indexing="ij"), -1).reshape(-1, 3)
    f = sdf(tree, g)
    f = np.where(f == 0, 1e-12, f)                      # nothing exactly on the iso level
    nx, ny, nz = (int(v) for v in n)
    vid = np.arange(nx * ny * nz).reshape(nx, ny, nz)
    base = vid[:-1, :-1, :-1].reshape(-1)
    off = np.array([o[0] * ny * nz + o[1] * nz + o[2] for o in _CUBE])
    corner = base[:, None] + off[None, :]               # (C, 8)
    # keep only cells whose corners straddle the surface
    s = f[corner] < 0
    cross = s.any(1) & ~s.all(1)
    corner = corner[cross]
    tets = corner[:, _TETS].reshape(-1, 4)              # (T, 4) global vertex ids
    ins = f[tets] < 0
    k = ins.sum(1)
    sel = (k > 0) & (k < 4)
    tets, ins, k = tets[sel], ins[sel], k[sel]
    perm = np.argsort(~ins, axis=1, kind="stable")      # inside vertices first
    tv = np.take_along_axis(tets, perm, 1)
    edges, tri_owner = [], []
    m1 = k == 1
    m3 = k == 3
    m2 = k == 2
    a, b, c, d = tv[:, 0], tv[:, 1], tv[:, 2], tv[:, 3]
    if m1.any():
        edges.append(np.stack([np.stack([a, b], 1), np.stack([a, c], 1), np.stack([a, d], 1)], 1)[m1])
        tri_owner.append(np.nonzero(m1)[0])
    if m3.any():
        edges.append(np.stack([np.stack([d, a], 1), np.stack([d, b], 1), np.stack([d, c], 1)], 1)[m3])
        tri_owner.append(np.nonzero(m3)[0])
    if m2.any():
        ac, ad, bd, bc = np.stack([a, c], 1), np.stack([a, d], 1), np.stack([b, d], 1), np.stack([b, c], 1)
        edges.append(np.stack([ac, ad, bd], 1)[m2])
        edges.append(np.stack([ac, bd, bc], 1)[m2])
        tri_owner += [np.nonzero(m2)[0], np.nonzero(m2)[0]]
    if not edges:
        raise CsgError("model produced no surface")
    E = np.concatenate(edges)                           # (F, 3, 2) grid-vertex pairs
    owner = np.concatenate(tri_owner)
    lo_e, hi_e = np.minimum(E[..., 0], E[..., 1]), np.maximum(E[..., 0], E[..., 1])
    key = lo_e.astype(np.int64) * (nx * ny * nz) + hi_e
    uk, first, inv = np.unique(key.reshape(-1), return_index=True, return_inverse=True)
    ek = E.reshape(-1, 2)[first]
    fa, fb = f[ek[:, 0]], f[ek[:, 1]]
    t = np.clip(fa / (fa - fb), 1e-3, 1 - 1e-3)
    verts = g[ek[:, 0]] + t[:, None] * (g[ek[:, 1]] - g[ek[:, 0]])
    faces = inv.reshape(-1, 3)
    # orient: normal must point from the tet's inside vertices toward its outside vertices
    tin = np.where(ins[owner][..., None], g[tets[owner]], 0).sum(1) / np.maximum(k[owner], 1)[:, None]
    tout = np.where(~ins[owner][..., None], g[tets[owner]], 0).sum(1) / np.maximum(4 - k[owner], 1)[:, None]
    p0, p1, p2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    nrm = np.cross(p1 - p0, p2 - p0)
    wrong = np.einsum("ij,ij->i", nrm, tout - tin) < 0
    faces[wrong] = faces[wrong][:, [0, 2, 1]]
    for _ in range(int(recipe.newton_steps)):
        verts = _project(tree, verts, h)
    # canonical order: sort triangles lexicographically for byte-stable output
    order = np.lexsort((faces[:, 2], faces[:, 1], faces[:, 0]))
    return TriMesh(verts, faces[order], meta={"backend": "csg-sdf-marching-tetrahedra", "cell": h,
                                              "grid": [nx, ny, nz], "newton_steps": int(recipe.newton_steps)})


def _project(tree: dict[str, Any], v: np.ndarray, h: float) -> np.ndarray:
    e = h * 1e-3
    fv = sdf(tree, v)
    grad = np.stack([(sdf(tree, v + e * ax) - sdf(tree, v - e * ax)) / (2 * e) for ax in np.eye(3)], 1)
    g2 = np.maximum((grad ** 2).sum(1), 1e-12)
    step = (fv / g2)[:, None] * grad
    # never move a vertex more than half a cell (keeps the topology from the grid intact)
    ln = np.linalg.norm(step, axis=1, keepdims=True)
    step = np.where(ln > 0.5 * h, step * (0.5 * h / np.maximum(ln, 1e-12)), step)
    return v - step


def reference_volume(tree: dict[str, Any], samples_per_axis: int = 160) -> float:
    """Deterministic voxel-count volume (cell-centre sampling) — the ground truth for recipe evaluation."""
    lo, hi = bounds(tree)
    n = samples_per_axis
    step = (hi - lo) / n
    xs = [lo[i] + step[i] * (np.arange(n) + 0.5) for i in range(3)]
    inside = 0
    for x in xs[0]:                                      # slab-wise to bound memory
        yy, zz = np.meshgrid(xs[1], xs[2], indexing="ij")
        p = np.stack([np.full(yy.size, x), yy.reshape(-1), zz.reshape(-1)], 1)
        inside += int((sdf(tree, p) < 0).sum())
    return float(inside * np.prod(step))
