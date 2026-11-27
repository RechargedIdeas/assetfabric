# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Custom OpenSCAD integration: parametric templates → deterministic `.scad` → mesh → validated STL / OBJ / OFF / GLB.

* Templates (`content/universal/parametric/*.yaml`) declare a typed parameter schema (float/int, min/max/default),
  a triangle budget, units, and a declarative CSG tree whose numeric fields are expressions over the parameters.
* `emit_scad` writes byte-stable OpenSCAD source (parameters as top-level variables, `$fn`, the tree as nested modules).
* Backends (GroundWeave op `gen.parametric`): `openscad-cli` — the real OpenSCAD binary (`openscad -o model.stl
  --export-format binstl`), used when installed; `csg-sdf-cpu` — the pure-NumPy CSG fallback (`csg.polygonize`) that runs
  everywhere, including the 2-core/no-GPU acceptance node.
* Every result is validated: closed 2-manifold, consistent outward orientation, finite, inside the triangle budget,
  and (when both backends ran) OpenSCAD's volume must agree with the fallback's within `CROSS_CHECK_TOL`.
* OpenSCAD is Z-up right-handed (`zup-rh`); GLB output is converted to glTF (Y-up, metres) using the template's `unit_m`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from forge.paths import find_repo_root
from forge.universal import csg, gltf, ir
from forge.universal import mesh as M

TEMPLATE_DIR = Path("content/universal/parametric")
CROSS_CHECK_TOL = 0.04          # relative volume agreement OpenSCAD vs CSG fallback
BACKENDS = ("openscad-cli", "csg-sdf-cpu")


class ParametricError(ValueError):
    pass


def openscad_binary() -> str | None:
    env = os.environ.get("FORGE_OPENSCAD")
    if env and Path(env).exists():
        return env
    return shutil.which("openscad")


def openscad_version() -> str | None:
    b = openscad_binary()
    if not b:
        return None
    p = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=30)
    return (p.stdout + p.stderr).strip().splitlines()[-1] if (p.stdout + p.stderr).strip() else None


# ----------------------------------------------------------------------------- templates + params

def load_templates(root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = root or find_repo_root()
    out = {}
    for p in sorted((root / TEMPLATE_DIR).glob("*.yaml")):
        t = yaml.safe_load(p.read_text(encoding="utf-8"))
        check_template(t)
        out[t["id"]] = t
    return out


def check_template(t: dict[str, Any]) -> None:
    for k in ("id", "version", "title_key", "unit_m", "tri_budget", "params", "tree"):
        if k not in t:
            raise ParametricError(f"template {t.get('id')}: missing {k}")
    for name, spec in t["params"].items():
        if not name.isidentifier() or name.startswith("_"):
            raise ParametricError(f"param name {name!r} must be an identifier")
        if spec.get("type") not in ("float", "int"):
            raise ParametricError(f"param {name}: type must be float|int")
        if not (spec["min"] <= spec["default"] <= spec["max"]):
            raise ParametricError(f"param {name}: default outside [min, max]")
    csg.resolve(t["tree"], defaults(t))       # validates ops + expressions with defaults


def defaults(t: dict[str, Any]) -> dict[str, float]:
    return {k: v["default"] for k, v in t["params"].items()}


def bind(t: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, float]:
    p = defaults(t)
    for k, v in (overrides or {}).items():
        if k not in t["params"]:
            raise ParametricError(f"unknown parameter {k!r} for {t['id']}; known: {sorted(t['params'])}")
        spec = t["params"][k]
        try:
            val = int(v) if spec["type"] == "int" else float(v)
        except (TypeError, ValueError) as e:
            raise ParametricError(f"{k}: not a {spec['type']}: {v!r}") from e
        if spec["type"] == "int" and float(v) != int(val):
            raise ParametricError(f"{k}: must be an integer")
        if not (spec["min"] <= val <= spec["max"]):
            raise ParametricError(f"{k}={val} outside [{spec['min']}, {spec['max']}]")
        p[k] = val
    return p


# ----------------------------------------------------------------------------- .scad emission

def _num(v: float | int) -> str:
    if isinstance(v, int) or float(v).is_integer():
        return str(int(v))
    return format(float(v), ".10g")


def _val(v: Any) -> str:
    if isinstance(v, str):
        return f"({v.strip()})"
    return _num(v)


def _vec(v: list[Any]) -> str:
    return "[" + ", ".join(_val(x) for x in v) + "]"


def _emit(node: dict[str, Any], ind: int) -> list[str]:
    pad = "  " * ind
    op = node["op"]
    kids = node.get("children", [])
    center = "true" if node.get("center") else "false"

    def block(head: str) -> list[str]:
        out = [f"{pad}{head} {{"]
        for k in kids:
            out += _emit(k, ind + 1)
        return out + [f"{pad}}}"]
    if op == "cube":
        return [f"{pad}cube(size = {_vec(node['size'])}, center = {center});"]
    if op == "sphere":
        return [f"{pad}sphere(r = {_val(node['r'])});"]
    if op == "cylinder":
        if "r" in node:
            return [f"{pad}cylinder(h = {_val(node['h'])}, r = {_val(node['r'])}, center = {center});"]
        return [f"{pad}cylinder(h = {_val(node['h'])}, r1 = {_val(node['r1'])}, r2 = {_val(node['r2'])}, center = {center});"]
    if op == "torus":
        return [f"{pad}rotate_extrude() translate([{_val(node['R'])}, 0, 0]) circle(r = {_val(node['r'])});"]
    if op == "translate":
        return block(f"translate(v = {_vec(node['v'])})")
    if op == "rotate":
        return block(f"rotate(a = {_vec(node['a'])})")
    if op == "scale":
        return block(f"scale(v = {_vec(node['v'])})")
    if op == "repeat_rotate":
        ax = {"x": "[af_a, 0, 0]", "y": "[0, af_a, 0]", "z": "[0, 0, af_a]"}[node.get("axis", "z")]
        n = _val(node["n"])
        return block(f"for (af_i = [0 : {n} - 1]) let(af_a = af_i * 360 / {n}) rotate(a = {ax})")
    if op in csg.BOOLEANS:
        return block(f"{op}()")
    raise ParametricError(f"unknown op {op}")


def emit_scad(t: dict[str, Any], params: dict[str, float]) -> str:
    """Deterministic OpenSCAD source for template `t` bound to `params` (expressions preserved, values pinned)."""
    for node_expr in _exprs(t["tree"]):
        csg.check_expr(node_expr, set(params))
    digest = hashlib.sha256(json.dumps({"t": t["tree"], "p": params, "v": t["version"]}, sort_keys=True).encode()).hexdigest()
    lines = [f"// AssetFabric parametric model '{t['id']}' v{t['version']} — generated, do not edit.",
             "// Copyright (c) 2026 Recharged Ideas. All Rights Reserved.",
             f"// units: {t.get('units', 'm')} (1 unit = {t['unit_m']} m); axes: OpenSCAD right-handed Z-up",
             f"// source-digest: {digest}", ""]
    for k in sorted(params):
        lines.append(f"{k} = {_num(params[k])};")
    if t.get("fn"):
        lines.append(f"$fn = {_val(t['fn'])};")
    lines.append("")
    lines += _emit(t["tree"], 0)
    return "\n".join(lines) + "\n"


def _exprs(node: dict[str, Any]) -> list[str]:
    out = []
    for k, v in node.items():
        if k in ("op", "children", "axis", "center"):
            continue
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str):
                out.append(x)
    for c in node.get("children", []):
        out += _exprs(c)
    return out


# ----------------------------------------------------------------------------- compile

def compile_openscad(scad: str, fmt: str = "stl", timeout: float = 300.0) -> dict[str, Any]:
    """Run the real OpenSCAD CLI. Returns {ok, bytes, wall_s, stderr} (ok=False, reason when not installed)."""
    b = openscad_binary()
    if not b:
        return {"ok": False, "reason": "openscad_not_installed"}
    export = {"stl": "binstl", "off": "off", "asciistl": "asciistl"}[fmt]
    ext = "stl" if fmt in ("stl", "asciistl") else fmt
    with tempfile.TemporaryDirectory(prefix="af-scad-") as d:
        src, out = Path(d) / "model.scad", Path(d) / f"model.{ext}"
        src.write_text(scad, encoding="utf-8")
        t0 = time.perf_counter()
        p = subprocess.run([b, "-o", str(out), "--export-format", export, str(src)], capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, "LC_ALL": "C"})
        wall = time.perf_counter() - t0
        if p.returncode != 0 or not out.exists():
            return {"ok": False, "reason": "openscad_failed", "stderr": p.stderr[-1500:], "wall_s": round(wall, 3)}
        return {"ok": True, "bytes": out.read_bytes(), "wall_s": round(wall, 3),
                "warnings": [ln for ln in p.stderr.splitlines() if "WARNING" in ln][:20]}


def build_mesh(t: dict[str, Any], params: dict[str, float], backend: str = "auto",
               recipe: csg.MeshRecipe | None = None) -> dict[str, Any]:
    """Build the template's mesh with the requested backend; returns {mesh, backend, wall_s, ...}."""
    if backend not in ("auto", *BACKENDS):
        raise ParametricError(f"backend must be auto|{'|'.join(BACKENDS)}")
    if backend in ("auto", "openscad-cli") and openscad_binary():
        r = compile_openscad(emit_scad(t, params))
        if r["ok"]:
            m = M.read_stl(r["bytes"], weld_eps=1e-7 * max(1.0, _extent(t, params)))
            m.meta["backend"] = "openscad-cli"
            return {"mesh": m, "backend": "openscad-cli", "wall_s": r["wall_s"], "openscad_version": openscad_version(),
                    "warnings": r.get("warnings", [])}
        if backend == "openscad-cli":
            raise ParametricError(f"OpenSCAD failed: {r.get('reason')} {r.get('stderr', '')[-400:]}")
    elif backend == "openscad-cli":
        raise ParametricError("OpenSCAD is not installed (apt-get install openscad, or set FORGE_OPENSCAD)")
    tree = csg.resolve(t["tree"], params)
    rec = recipe or default_recipe(t, params)
    t0 = time.perf_counter()
    m, rec, passes = polygonize_within_budget(tree, rec, int(t["tri_budget"]))
    return {"mesh": m, "backend": "csg-sdf-cpu", "wall_s": round(time.perf_counter() - t0, 3),
            "recipe": {"cell": rec.cell, "newton_steps": rec.newton_steps, "budget_passes": passes}}


def polygonize_within_budget(tree: dict[str, Any], rec: csg.MeshRecipe, budget: int,
                             max_passes: int = 4) -> tuple[M.TriMesh, csg.MeshRecipe, int]:
    """Polygonise; if over the triangle budget, coarsen the cell (triangles scale ~ 1/cell²) and retry."""
    m = csg.polygonize(tree, rec)
    passes = 1
    while m.n_triangles > budget and passes < max_passes:
        rec = csg.MeshRecipe(cell=rec.cell * float(np.sqrt(m.n_triangles / budget)) * 1.05,
                             newton_steps=rec.newton_steps, pad_cells=rec.pad_cells)
        m = csg.polygonize(tree, rec)
        passes += 1
    return m, rec, passes


def _extent(t: dict[str, Any], params: dict[str, float]) -> float:
    lo, hi = csg.bounds(csg.resolve(t["tree"], params))
    return float(np.max(hi - lo))


def default_recipe(t: dict[str, Any], params: dict[str, float], root: Path | None = None) -> csg.MeshRecipe:
    """The active self-improvement recipe (content/universal/recipes/baseline.yaml unless a better one was promoted
    locally): cell = extent × cell_frac, Newton projection steps. Budget coarsening is applied by the caller."""
    from forge.universal import evolution
    rec = evolution.active_recipe("parametric.csg", root)
    return csg.MeshRecipe(cell=_extent(t, params) * float(rec["cell_frac"]), newton_steps=int(rec["newton_steps"]))


def to_scene(t: dict[str, Any], m: M.TriMesh) -> ir.Scene:
    """Wrap a parametric mesh (OpenSCAD units, Z-up RH) into an IR scene in metres."""
    s = ir.Scene(f"parametric-{t['id']}", "3d", "zup-rh", meta={"template": t["id"], "version": t["version"]})
    scaled = m.transformed(np.eye(3) * float(t["unit_m"]))
    scaled.normals = scaled.vertex_normals()
    s.add(ir.Material("mat_" + t["id"], base_color=(0.62, 0.52, 0.40, 1.0), metallic=0.0, roughness=0.75))
    s.add(ir.MeshAsset(t["id"], scaled, "mat_" + t["id"]))
    s.add_node(ir.Node(t["id"], mesh=t["id"]))
    return s


def build(template_id: str, overrides: dict[str, Any] | None = None, out_dir: Path | None = None,
          backend: str = "auto", cross_check: bool = True, root: Path | None = None) -> dict[str, Any]:
    """Full pipeline. Writes model.scad / .stl / .obj / .off / .glb + report.json into out_dir (when given)."""
    root = root or find_repo_root()
    tpls = load_templates(root)
    if template_id not in tpls:
        raise ParametricError(f"unknown template {template_id!r}; known: {sorted(tpls)}")
    t = tpls[template_id]
    params = bind(t, overrides)
    scad = emit_scad(t, params)
    res = build_mesh(t, params, backend)
    m = res["mesh"]
    val = M.validate(m, tri_budget=int(t["tri_budget"]))
    report: dict[str, Any] = {"template": t["id"], "version": t["version"], "params": params, "backend": res["backend"],
                              "wall_s": res["wall_s"], "validation": val, "unit_m": t["unit_m"],
                              "scad_sha256": hashlib.sha256(scad.encode()).hexdigest()}
    if res["backend"] == "openscad-cli":
        report["openscad_version"] = res.get("openscad_version")
        report["openscad_warnings"] = res.get("warnings", [])
        if cross_check:
            fb = build_mesh(t, params, "csg-sdf-cpu")
            v_fb = M.signed_volume(fb["mesh"])
            rel = abs(val["volume"] - v_fb) / max(abs(v_fb), 1e-12)
            report["cross_check"] = {"fallback_volume": round(v_fb, 6), "openscad_volume": val["volume"],
                                     "rel_diff": round(rel, 5), "tol": CROSS_CHECK_TOL, "ok": rel <= CROSS_CHECK_TOL}
    scene = to_scene(t, m)
    glb = gltf.write_glb(scene)
    gv = gltf.validate_glb(glb)
    report["glb"] = {"ok": gv["ok"], "errors": gv["errors"], "stats": gv["stats"], "sha256": hashlib.sha256(glb).hexdigest()}
    stl, obj, off = M.write_stl(m, f"assetfabric {t['id']}"), M.write_obj(m, name=t["id"]), M.write_off(m)
    report["files"] = {name: {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                       for name, b in (("model.scad", scad.encode()), ("model.stl", stl), ("model.obj", obj),
                                       ("model.off", off), ("model.glb", glb))}
    # re-read every interchange file and re-validate (format round-trip)
    rt = {"stl": M.validate(M.read_stl(stl))["ok"], "obj": M.validate(M.read_obj(obj))["ok"],
          "off": M.validate(M.read_off(off))["ok"]}
    report["roundtrip"] = rt
    report["ok"] = bool(val["ok"] and gv["ok"] and all(rt.values()) and report.get("cross_check", {}).get("ok", True))
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "model.scad").write_text(scad, encoding="utf-8")
        for name, b in (("model.stl", stl), ("model.obj", obj), ("model.off", off), ("model.glb", glb)):
            (out_dir / name).write_bytes(b)
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["_mesh"] = m
    report["_scene"] = scene
    return report
