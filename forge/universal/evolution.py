# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Self-improvement loop — bounded, benchmark-gated, reversible.

    telemetry → propose → evaluate (sandboxable, deterministic suite) → gate → promote | reject → history / rollback

* **Families** (`content/universal/recipes/baseline.yaml`): a named recipe with typed, bounded parameters, a scalar
  objective (lower is better) computed on a fixed deterministic benchmark suite, and hard gates.
* **Propose**: deterministic neighbourhood search around the active recipe (each parameter ± its step / × its
  multiplier, clamped to bounds, plus the best pairwise combination of improving moves) — no RNG, no network.
* **Promote** only if `objective(candidate) < objective(active) − min_gain` AND every gate passes. Anything else is
  rejected with the reason recorded. Every version stays in history; `rollback(family, version)` re-activates any of
  them. Local state lives in `.fabric/universal/evolution/` (git-ignored), telemetry in `telemetry.jsonl`.
* Timing is recorded as telemetry and gated only by a generous wall budget — the objective itself is deterministic, so
  the same suite gives the same decision on every machine.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from forge.paths import find_repo_root

BASELINE_PATH = Path("content/universal/recipes/baseline.yaml")
REF_VOLUMES_PATH = Path("content/universal/recipes/reference_volumes.json")
STATE_DIR = Path(".fabric/universal/evolution")
MIN_GAIN = 1e-6


def _root(root: Path | None) -> Path:
    return root or find_repo_root()


def load_baseline(root: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((_root(root) / BASELINE_PATH).read_text(encoding="utf-8"))


def baseline_recipe(family: str, root: Path | None = None) -> dict[str, Any]:
    return {k: v["value"] for k, v in load_baseline(root)["families"][family]["params"].items()}


class Store:
    def __init__(self, root: Path | None = None, state_dir: Path | None = None) -> None:
        self.root = _root(root)
        self.dir = Path(state_dir) if state_dir else self.root / STATE_DIR
        self.path = self.dir / "state.json"

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"families": {}}

    def save(self, st: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def family(self, st: dict[str, Any], fam: str) -> dict[str, Any]:
        if fam not in st["families"]:
            st["families"][fam] = {"active": 1, "versions": [{"version": 1, "recipe": baseline_recipe(fam, self.root),
                                                              "source": "baseline.yaml", "objective": None}],
                                   "rejected": []}
        return st["families"][fam]

    def telemetry(self, rec: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "telemetry.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")


def active_recipe(family: str, root: Path | None = None, state_dir: Path | None = None) -> dict[str, Any] | None:
    """The promoted recipe for `family` (None when nothing was ever promoted — callers then use their default)."""
    s = Store(root, state_dir)
    if not s.path.exists():
        return None
    st = s.load()
    f = st["families"].get(family)
    if not f or f["active"] == 1:
        return None
    return next(v["recipe"] for v in f["versions"] if v["version"] == f["active"])


# ----------------------------------------------------------------------------- benchmark suites

@dataclass
class Evaluation:
    recipe: dict[str, Any]
    objective: float
    gates: dict[str, bool]
    metrics: dict[str, Any]
    wall_s: float

    @property
    def passed(self) -> bool:
        return all(self.gates.values())

    def to_dict(self) -> dict[str, Any]:
        return {"recipe": self.recipe, "objective": round(self.objective, 9), "gates": self.gates, "passed": self.passed,
                "metrics": self.metrics, "wall_s": round(self.wall_s, 3)}


def _template_key(t: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"tree": t["tree"], "params": t["params"], "v": t["version"]}, sort_keys=True).encode()).hexdigest()[:16]


REF_FN = 128          # OpenSCAD facets for reference volumes: polygon/circle area ratio 1 − (2π/n)²/6 ≈ 1 − 4e-4


def reference_volumes(root: Path | None = None, rebuild: bool = False, samples: int = 320) -> dict[str, Any]:
    """Reference volumes per template at default parameters (cached in a committed JSON, rebuilt when a template
    changes). Preferred source: the real OpenSCAD CLI at $fn=128 (exact CSG, near-exact curves); fallback when
    OpenSCAD is absent: cell-centre voxel counting at `samples`³ (recorded as such)."""
    from forge.universal import csg, openscad
    from forge.universal import mesh as M
    root = _root(root)
    p = root / REF_VOLUMES_PATH
    cache = json.loads(p.read_text()) if p.exists() and not rebuild else {}
    changed = False
    for tid, t in openscad.load_templates(root).items():
        key = _template_key(t)
        if cache.get(tid, {}).get("key") != key:
            params = openscad.defaults(t)
            entry: dict[str, Any] = {"key": key}
            if openscad.openscad_binary():
                tt = dict(t)
                tt["fn"] = REF_FN
                r = openscad.compile_openscad(openscad.emit_scad(tt, params), timeout=1800)
                if r["ok"]:
                    entry.update(volume=M.signed_volume(M.read_stl(r["bytes"], 1e-9)), source=f"openscad $fn={REF_FN}",
                                 tool=openscad.openscad_version())
            if "volume" not in entry:
                tree = csg.resolve(t["tree"], params)
                entry.update(volume=csg.reference_volume(tree, samples), source=f"voxel {samples}^3")
            cache[tid] = entry
            changed = True
    if changed:
        p.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return cache


def eval_parametric(recipe: dict[str, Any], root: Path | None = None, templates: list[str] | None = None,
                    gates_cfg: dict[str, Any] | None = None) -> Evaluation:
    from forge.universal import csg, openscad
    from forge.universal import mesh as M
    root = _root(root)
    gcfg = gates_cfg or load_baseline(root)["families"]["parametric.csg"]["gates"]
    tpls = openscad.load_templates(root)
    refs = reference_volumes(root)
    names = templates or sorted(tpls)
    t0 = time.perf_counter()
    errs, ratios, per = [], [], {}
    manifold = budget = True
    for tid in names:
        t = tpls[tid]
        params = openscad.defaults(t)
        tree = csg.resolve(t["tree"], params)
        lo, hi = csg.bounds(tree)
        rec = csg.MeshRecipe(cell=float(np.max(hi - lo)) * float(recipe["cell_frac"]), newton_steps=int(recipe["newton_steps"]))
        m = csg.polygonize(tree, rec)
        v = M.validate(m)
        rel = abs(v["volume"] - refs[tid]["volume"]) / refs[tid]["volume"]
        ratio = m.n_triangles / float(t["tri_budget"])
        manifold &= bool(v["manifold"] and v["watertight"] and v["outward_oriented"])
        budget &= ratio <= 1.0
        errs.append(rel)
        ratios.append(ratio)
        per[tid] = {"rel_volume_error": round(rel, 6), "triangles": m.n_triangles, "tri_budget": t["tri_budget"]}
    wall = time.perf_counter() - t0
    obj = float(np.mean(errs) + 0.02 * np.mean(ratios))
    gates = {"manifold_watertight": manifold, "tri_budget_first_pass": budget,
             "max_rel_volume_error": max(errs) <= float(gcfg["max_rel_volume_error"]),
             "suite_wall_s": wall <= float(gcfg["suite_wall_s"])}
    return Evaluation(dict(recipe), obj, gates, {"per_template": per, "mean_rel_volume_error": round(float(np.mean(errs)), 6),
                                                 "mean_tri_ratio": round(float(np.mean(ratios)), 6)}, wall)


def _analytic_cases() -> list[tuple[np.ndarray, np.ndarray]]:
    """Silhouettes with known ground-truth normals: a hemisphere (disc) and a half-ellipsoid (ellipse)."""
    out = []
    for (w, h, rx, ry) in ((48, 48, 20.0, 20.0), (64, 48, 28.0, 16.0), (32, 32, 12.0, 12.0)):
        yy, xx = np.mgrid[0:h, 0:w].astype(float)
        u, v = (xx - (w - 1) / 2) / rx, (yy - (h - 1) / 2) / ry
        r2 = u ** 2 + v ** 2
        alpha = (r2 < 1).astype(np.uint8) * 255
        z = np.sqrt(np.clip(1 - r2, 1e-9, 1))
        # ellipsoid x²/rx² + y²/ry² + z²/rz² = 1 with rz = min(rx, ry): gradient-based normal, image +Y up
        rz = min(rx, ry)
        n = np.stack([u / rx, -v / ry, z / rz], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        out.append((alpha, n))
    return out


def eval_normals(recipe: dict[str, Any], root: Path | None = None, gates_cfg: dict[str, Any] | None = None) -> Evaluation:
    from forge.universal import maps2d
    gcfg = gates_cfg or load_baseline(root)["families"]["maps2d.normal"]["gates"]
    t0 = time.perf_counter()
    errs, finite, unit = [], True, True
    for alpha, n_true in _analytic_cases():
        rec = maps2d.NormalRecipe(blur=int(recipe["blur"]), strength=1.0, dome=float(recipe["dome"]))
        h = maps2d.height_from_alpha(alpha, rec)
        m = alpha > 0
        dmax = 0.0
        cur = m.copy()
        while cur.any():          # inscribed radius in pixels (same erosion metric as height_from_alpha)
            dmax += 1
            cur = maps2d._erode4(cur)
        n = maps2d.normals_from_height(h, float(recipe["relief"]) * dmax)
        finite &= bool(np.isfinite(n).all())
        unit &= bool(np.allclose(np.linalg.norm(n, axis=-1), 1.0, atol=1e-6))
        inner = m & maps2d._erode4(maps2d._erode4(m))       # ignore the 2-px rim (undefined slope at the silhouette)
        errs.append(maps2d.angular_error_deg(n, n_true, inner)["mean"])
    wall = time.perf_counter() - t0
    obj = float(np.mean(errs))
    gates = {"finite": finite, "unit_length": unit, "max_mean_error_deg": max(errs) <= float(gcfg["max_mean_error_deg"])}
    return Evaluation(dict(recipe), obj, gates, {"mean_error_deg_per_case": [round(e, 4) for e in errs]}, wall)


SUITES: dict[str, Callable[..., Evaluation]] = {"parametric.csg": eval_parametric, "maps2d.normal": eval_normals}


# ----------------------------------------------------------------------------- propose / decide / evolve

def neighbours(family: str, recipe: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    spec = load_baseline(root)["families"][family]["params"]
    out = []
    for k in sorted(spec):
        s = spec[k]
        vals = []
        if "step_mul" in s:
            vals = [recipe[k] * s["step_mul"], recipe[k] / s["step_mul"]]
        else:
            vals = [recipe[k] + s["step"], recipe[k] - s["step"]]
        for v in vals:
            v = min(max(v, s["min"]), s["max"])
            v = int(round(v)) if s.get("int") else round(float(v), 10)
            if v != recipe[k]:
                c = dict(recipe)
                c[k] = v
                if c not in out:
                    out.append(c)
    return out


def decide(base: Evaluation, cand: Evaluation, min_gain: float = MIN_GAIN) -> tuple[bool, str]:
    failed = [g for g, ok in cand.gates.items() if not ok]
    if failed:
        return False, "gate failed: " + ", ".join(failed)
    if not cand.objective < base.objective - min_gain:
        return False, f"no strict improvement ({cand.objective:.6g} vs active {base.objective:.6g})"
    return True, f"objective {base.objective:.6g} → {cand.objective:.6g}"


def evolve(family: str, rounds: int = 1, root: Path | None = None, state_dir: Path | None = None,
           suite_kwargs: dict[str, Any] | None = None, extra_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run `rounds` of propose→evaluate→decide. Promotes at most one recipe per round (the best passing one)."""
    store = Store(root, state_dir)
    st = store.load()
    fam = store.family(st, family)
    suite = SUITES[family]
    kw = suite_kwargs or {}
    log: list[dict[str, Any]] = []
    for r in range(rounds):
        active = next(v for v in fam["versions"] if v["version"] == fam["active"])
        base = suite(active["recipe"], root, **kw)
        if active.get("objective") is None:
            active["objective"] = round(base.objective, 9)
        cands = neighbours(family, active["recipe"], root) + (extra_candidates or [] if r == 0 else [])
        evals = [suite(c, root, **kw) for c in cands]
        # pairwise combination of the two best individually-improving passing moves
        good = sorted([e for e in evals if e.passed and e.objective < base.objective], key=lambda e: e.objective)
        if len(good) >= 2:
            combo = dict(active["recipe"])
            for e in good[:2]:
                for k, v in e.recipe.items():
                    if v != active["recipe"][k]:
                        combo[k] = v
            if combo not in [e.recipe for e in evals]:
                evals.append(suite(combo, root, **kw))
        decisions = []
        for e in evals:
            ok, why = decide(base, e)
            decisions.append((ok, why, e))
            store.telemetry({"family": family, "round": r, "recipe": e.recipe, "objective": e.objective, "gates": e.gates,
                             "wall_s": round(e.wall_s, 3), "accepted_candidate": ok, "reason": why, "t": round(time.time(), 3)})
        winners = sorted([d for d in decisions if d[0]], key=lambda d: d[2].objective)
        for ok, why, e in decisions:
            if not ok:
                fam["rejected"].append({"round": r, "recipe": e.recipe, "objective": round(e.objective, 9), "reason": why})
        promoted = None
        if winners:
            _, why, e = winners[0]
            ver = max(v["version"] for v in fam["versions"]) + 1
            fam["versions"].append({"version": ver, "recipe": e.recipe, "objective": round(e.objective, 9), "source": "evolve",
                                    "promoted_from": fam["active"], "reason": why, "gates": e.gates, "metrics": e.metrics})
            fam["active"] = ver
            promoted = {"version": ver, "recipe": e.recipe, "objective": e.objective, "reason": why}
        log.append({"round": r, "baseline": base.to_dict(), "candidates": len(evals),
                    "rejected": sum(1 for d in decisions if not d[0]), "promoted": promoted})
        store.save(st)
        if promoted is None:
            break
    return {"family": family, "active": fam["active"], "rounds": log, "versions": len(fam["versions"])}


def rollback(family: str, version: int, root: Path | None = None, state_dir: Path | None = None) -> dict[str, Any]:
    store = Store(root, state_dir)
    st = store.load()
    fam = store.family(st, family)
    if version not in {v["version"] for v in fam["versions"]}:
        raise ValueError(f"{family}: no version {version}; have {[v['version'] for v in fam['versions']]}")
    prev = fam["active"]
    fam["active"] = version
    fam.setdefault("rollbacks", []).append({"from": prev, "to": version, "t": round(time.time(), 3)})
    store.save(st)
    return {"family": family, "active": version, "previous": prev}


def history(family: str, root: Path | None = None, state_dir: Path | None = None) -> dict[str, Any]:
    store = Store(root, state_dir)
    st = store.load()
    return store.family(st, family)


def evaluate_one(family: str, recipe: dict[str, Any], root: Path | None = None, **kw: Any) -> Evaluation:
    return SUITES[family](recipe, root, **kw)


def combos(family: str, root: Path | None = None) -> int:
    spec = load_baseline(root)["families"][family]["params"]
    return len(list(itertools.product(*[[0, 1, 2] for _ in spec])))
