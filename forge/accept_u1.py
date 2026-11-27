# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""U1 acceptance: "Universal 2D/2.5D/3D engine" (user request t65u). docs/acceptance-tests/U1.md has the mapping.

Pure Python + whatever native tools are installed; Godot is not required (its check is recorded when present).
Every step uses throw-away directories; the repo's .fabric state is never touched.

 1. parametric   — every template builds through the real OpenSCAD CLI when installed (else the CSG fallback) and through
                   the NumPy CSG fallback; meshes manifold/watertight/in budget; OpenSCAD ↔ fallback volume within
                   tolerance; STL/OBJ/OFF/GLB round-trip; same parameters twice → byte-identical .scad and fallback STL.
 2. ir           — 2D, 2.5D and 3D reference scenes: JSON round-trip keeps the digest; converting through the Unity,
                   Unreal and Blender conventions and back restores every world matrix; ir.validate ok.
 3. adapters     — every built-in exporter × every reference scene it accepts exports + verifies; a second run is
                   byte-identical; every importer round-trips its sample; native_verified/cli_bridge adapters run the
                   real tool headlessly when installed (Godot GLTFDocument, Blender bridge script, OpenSCAD render).
 4. catalog      — integrity (unique ids, valid tiers/conventions, every named tool from t65u present, Wikipedia
                   revision pinned); counts recorded.
 5. evolution    — temp state: maps2d.normal improves over ≥2 promoted versions; parametric.csg promotes a strictly
                   better recipe, rejects an injected regression and an injected budget-gate violation; rollback
                   restores the baseline recipe.
 6. plugins      — gap report lists x3d; the X3D example plugin verifies in the sandbox, registers, hot-loads, exports +
                   verifies through the sandboxed proxy and closes the gap; a same-version re-register is refused; a
                   v1.1.0 registers and rolls back; a tampered install is refused; the network-exfiltration,
                   nondeterministic and sandbox-escape fixtures are rejected (static policy, determinism gate, and —
                   with the static gate bypassed — the sandbox itself); a scaffold fails the contract until implemented.
 7. groundweave  — gen.parametric + universal.export ops pass `groundweave check` (real CPU rung, budgets).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

FIX = Path("tests/fixtures/universal_plugins")
EXAMPLE = Path("content/universal/plugins/x3d-export")


def _parametric(root: Path, td: Path) -> dict[str, Any]:
    from forge.universal import mesh as M
    from forge.universal import openscad
    out: dict[str, Any] = {"openscad": openscad.openscad_version(), "templates": {}}
    for tid in sorted(openscad.load_templates(root)):
        r = openscad.build(tid, out_dir=td / "param" / tid, root=root)
        fb1 = openscad.build(tid, backend="csg-sdf-cpu", cross_check=False, root=root)
        fb2 = openscad.build(tid, backend="csg-sdf-cpu", cross_check=False, root=root)
        v = r["validation"]
        out["templates"][tid] = {
            "ok": r["ok"], "backend": r["backend"], "triangles": v["triangles"], "manifold": v["manifold"],
            "watertight": v["watertight"], "within_budget": v.get("within_budget", True), "volume": v["volume"],
            "cross_check": r.get("cross_check"), "roundtrip": r["roundtrip"], "glb_ok": r["glb"]["ok"],
            "fallback_ok": fb1["ok"], "fallback_triangles": fb1["validation"]["triangles"],
            "deterministic": fb1["scad_sha256"] == fb2["scad_sha256"]
                             and hashlib.sha256(M.write_stl(fb1["_mesh"])).digest() == hashlib.sha256(M.write_stl(fb2["_mesh"])).digest(),
            "files": sorted(p.name for p in (td / "param" / tid).iterdir())}
    r = openscad.build("cog", {"teeth": 20}, root=root)
    out["override_cog_teeth20"] = {"ok": r["ok"], "backend": r["backend"], "cross_check": r.get("cross_check")}
    return out


def _ir(root: Path) -> dict[str, Any]:
    from forge.universal import ir, reference
    res = {}
    for dim, s in reference.all_scenes().items():
        rt = ir.Scene.from_json(s.to_json())
        w0 = s.world_matrices()
        errs = {}
        for c in ("unity", "unreal", "blender"):
            back = s.converted(c).converted(s.convention)
            errs[c] = float(max(np.abs(a - b).max() for a, b in zip(w0, back.world_matrices()))) if w0 else 0.0
        res[dim] = {"json_digest_equal": rt.digest() == s.digest(), "valid": ir.validate(s)["ok"], "nodes": len(s.nodes),
                    "max_world_err_after_roundtrip": errs, "convention": s.convention}
    return res


def _adapters(root: Path, td: Path) -> dict[str, Any]:
    from forge.universal import engine, native
    t0 = time.perf_counter()
    d1 = engine.demo(td / "demo1", native=True, root=root)
    t1 = time.perf_counter()
    d2 = engine.demo(td / "demo2", native=False, root=root)
    man = lambda d, r: json.loads((Path(r["out"]) / "assetfabric_manifest.json").read_text())["files"]  # noqa: E731
    nondet = [f"{a['adapter']}/{a['dimension']}" for a, b in zip(d1["exports"], d2["exports"])
              if a.get("ok") and b.get("ok") and man(d1, a) != man(d2, b)]
    nat = {f"{r['adapter']}/{r['dimension']}": {k: r["native"].get(k) for k in ("ran", "ok", "tool", "version", "reason")}
           for r in d1["exports"] if "native" in r}
    fails = [{k: r.get(k) for k in ("adapter", "dimension", "error", "verify")} for r in d1["exports"] + d1["imports"] if not r["ok"]]
    return {"counts": d1["counts"], "deterministic": not nondet, "nondeterministic": nondet, "failures": fails,
            "availability": native.availability(), "native": nat, "demo_s": round(t1 - t0, 2),
            "by_adapter": sorted({(r["adapter"], r.get("tier")) for r in d1["exports"]})}


def _catalog(root: Path) -> dict[str, Any]:
    from forge.universal import registry as R
    return R.integrity(root)


def _evolution(root: Path, td: Path) -> dict[str, Any]:
    from forge.universal import evolution as E
    sd = td / "evo"
    n = E.evolve("maps2d.normal", rounds=3, root=root, state_dir=sd)
    base = E.baseline_recipe("parametric.csg", root)
    regression = dict(base, cell_frac=0.025, newton_steps=0)   # coarser, no projection: passes gates but is worse
    gate_violator = dict(base, cell_frac=0.05, newton_steps=0)  # too coarse: breaks the max_rel_volume_error gate
    p = E.evolve("parametric.csg", rounds=1, root=root, state_dir=sd, extra_candidates=[regression, gate_violator])
    hist = E.history("parametric.csg", root=root, state_dir=sd)
    rej = {json.dumps(r["recipe"], sort_keys=True): r["reason"] for r in hist["rejected"]}
    promoted = p["rounds"][0]["promoted"]
    promoted_active = E.active_recipe("parametric.csg", root=root, state_dir=sd)
    rb = E.rollback("parametric.csg", 1, root=root, state_dir=sd)
    after = E.active_recipe("parametric.csg", root=root, state_dir=sd)
    nrounds = [r["promoted"]["objective"] for r in n["rounds"] if r["promoted"]]
    return {"normals": {"baseline_objective_deg": round(n["rounds"][0]["baseline"]["objective"], 4),
                        "promoted_objectives_deg": [round(x, 4) for x in nrounds], "versions": n["versions"]},
            "parametric": {"baseline": base, "baseline_objective": round(p["rounds"][0]["baseline"]["objective"], 6),
                           "promoted": promoted and {"recipe": promoted["recipe"], "objective": round(promoted["objective"], 6)},
                           "candidates": p["rounds"][0]["candidates"],
                           "regression_rejected": rej.get(json.dumps(regression, sort_keys=True)),
                           "gate_violator_rejected": rej.get(json.dumps(gate_violator, sort_keys=True))},
            "rollback": {"active": rb["active"], "previous": rb["previous"], "restored_baseline": after == base,
                         "production_used_promoted": promoted_active == (promoted or {}).get("recipe")}}


def _plugins(root: Path, td: Path) -> dict[str, Any]:
    from forge.universal import plugins as P
    from forge.universal import reference
    from forge.universal.exporters import REGISTRY
    sd = td / "plugins"
    out: dict[str, Any] = {}
    g0 = P.gaps(root, sd)
    out["gaps_before"] = {"x3d_listed": any(g["id"] == "x3d" for g in g0["gaps"]), "formats_covered": g0["formats_covered"],
                          "formats_total": g0["formats_total"], "gaps": len(g0["gaps"])}
    t0 = time.perf_counter()
    reg = P.register(root / EXAMPLE, root, sd)
    out["register"] = {"ok": reg["ok"], "version": reg.get("version"), "verify_s": round(time.perf_counter() - t0, 2),
                       "sandbox_tier": reg["verify"].get("sandbox", {}).get("sandbox_tier"),
                       "contract": reg["verify"].get("contract", {}).get("checks")}
    again = P.register(root / EXAMPLE, root, sd)
    out["same_version_refused"] = (not again["ok"]) and "not newer" in again.get("reason", "")
    regy = dict(REGISTRY)
    out["hot_load"] = P.load_active(regy, root, sd)
    px = regy.get("x3d-export")
    if px is not None:
        o = td / "x3d-out"
        m = px.export(reference.scene_3d(), o)
        out["proxy_export"] = {"files": sorted(m["files"]), "verify": px.verify(o)["ok"], "plugin": getattr(px, "plugin", False)}
    g1 = P.gaps(root, sd)
    out["gaps_after"] = {"x3d_listed": any(g["id"] == "x3d" for g in g1["gaps"]), "formats_covered": g1["formats_covered"]}
    v2 = td / "x3d-v110"
    shutil.copytree(root / EXAMPLE, v2)
    for f, a, b in (("plugin.yaml", "version: 1.0.0", "version: 1.1.0"), ("adapter.py", 'version = "1.0.0"', 'version = "1.1.0"')):
        (v2 / f).write_text((v2 / f).read_text().replace(a, b))
    r2 = P.register(v2, root, sd)
    rb = P.rollback("x3d-export", root, sd)
    out["upgrade_rollback"] = {"v110_registered": r2["ok"], "previous": r2.get("previous"), "rollback": rb}
    act = P.active(root, sd)["x3d-export"]
    f = sd / act["path"] / "adapter.py"
    f.write_text(f.read_text() + "\n# tampered after registration\n")
    out["tamper"] = P.load_active(dict(REGISTRY), root, sd)
    hostile = {}
    for name in ("net-exfil", "nondeterministic", "sandbox-escape"):
        r = P.verify(root / FIX / name, root)
        hostile[name] = {"rejected": not r["ok"], "checks": r["checks"], "first_errors": r["errors"][:2]}
    esc = root / FIX / "sandbox-escape"
    probe = Path("/var/tmp/assetfabric_sandbox_escape_probe")
    rt = {}
    for tier in ("auto", "process"):
        res, meta = P._sandbox_call(esc, {"op": "contract", "manifest": P.read_manifest(esc)}, root, tier=tier)
        rt[meta["sandbox_tier"]] = (res.get("errors") or ["?"])[0]
    hostile["sandbox-escape"]["runtime_with_static_gate_bypassed"] = rt
    hostile["sandbox-escape"]["escape_file_exists"] = probe.exists()
    out["hostile"] = hostile
    sc = P.scaffold("fbx-export", td / "scaffold", ["fbx"], ["3d"])
    rs = P.verify(Path(sc["path"]), root)
    out["scaffold"] = {"created": sc["files"], "contract_fails_until_implemented": not rs["ok"],
                       "first_error": rs["errors"][:1]}
    return out


def u1_run(root: Path) -> tuple[int, dict[str, Any]]:
    from forge import groundweave
    res: dict[str, Any] = {}
    timings = {}
    with tempfile.TemporaryDirectory(prefix="af-u1-") as t:
        td = Path(t)
        for name, fn in (("parametric", lambda: _parametric(root, td)), ("ir", lambda: _ir(root)),
                         ("adapters", lambda: _adapters(root, td)), ("catalog", lambda: _catalog(root)),
                         ("evolution", lambda: _evolution(root, td)), ("plugins", lambda: _plugins(root, td))):
            t0 = time.perf_counter()
            res[name] = fn()
            timings[name] = round(time.perf_counter() - t0, 2)
    gw = groundweave.check(root)
    res["groundweave"] = {"ok": gw["ok"], "problems": gw["problems"],
                          "ops": [op for op in ("gen.parametric", "universal.export")
                                  if op in groundweave.load_ladder(root)["ops"]]}
    res["timings_s"] = timings
    return 0, res


def u1_check(r: dict[str, Any]) -> list[str]:
    from forge.milestones import _need
    e: list[str] = []
    p = r.get("parametric", {})
    for tid, t in p.get("templates", {}).items():
        _need(t["ok"] and t["fallback_ok"], f"parametric {tid}: build not ok", e)
        _need(t["manifold"] and t["watertight"], f"parametric {tid}: not manifold/watertight", e)
        _need(t["deterministic"], f"parametric {tid}: not deterministic", e)
        _need(all(t["roundtrip"].values()) and t["glb_ok"], f"parametric {tid}: interchange round-trip failed", e)
        if p.get("openscad"):
            _need(t["backend"] == "openscad-cli", f"parametric {tid}: OpenSCAD installed but not used", e)
            _need(bool(t["cross_check"] and t["cross_check"]["ok"]), f"parametric {tid}: OpenSCAD/fallback disagree", e)
    _need(len(p.get("templates", {})) >= 4, "fewer than 4 parametric templates", e)
    _need(p.get("override_cog_teeth20", {}).get("ok"), "parametric override build failed", e)
    for dim in ("2d", "2.5d", "3d"):
        s = r.get("ir", {}).get(dim)
        _need(bool(s), f"ir: no {dim} scene", e)
        if s:
            _need(s["json_digest_equal"] and s["valid"], f"ir {dim}: JSON round-trip/validate failed", e)
            _need(max(s["max_world_err_after_roundtrip"].values()) < 1e-9, f"ir {dim}: convention round-trip error", e)
    a = r.get("adapters", {})
    c = a.get("counts", {})
    _need(c.get("exports", 0) >= 30 and c.get("exports_ok") == c.get("exports"), f"adapters: exports {c}", e)
    _need(c.get("imports", 0) >= 8 and c.get("imports_ok") == c.get("imports"), f"adapters: imports {c}", e)
    _need(a.get("deterministic"), f"adapters: nondeterministic packs {a.get('nondeterministic')}", e)
    av = a.get("availability", {})
    for key, tool in (("godot/3d", "godot"), ("blender/3d", "blender"), ("openscad/3d", "openscad")):
        n = a.get("native", {}).get(key, {})
        if av.get(tool):
            _need(n.get("ran") and n.get("ok"), f"native {key}: {n}", e)
    cat = r.get("catalog", {})
    _need(cat.get("ok"), f"catalog integrity: {cat.get('errors')}", e)
    _need(cat.get("wikipedia_unique", 0) >= 150 and cat.get("named_tools", 0) >= 18, "catalog too small", e)
    ev = r.get("evolution", {})
    _need(len(ev.get("normals", {}).get("promoted_objectives_deg", [])) >= 2, "evolution: normals did not improve twice", e)
    pr = ev.get("parametric", {})
    _need(bool(pr.get("promoted")) and pr["promoted"]["objective"] < pr.get("baseline_objective", 0),
          "evolution: parametric not improved", e)
    _need("no strict improvement" in str(pr.get("regression_rejected")), "evolution: injected regression not rejected", e)
    _need("gate failed" in str(pr.get("gate_violator_rejected")), "evolution: gate violator not rejected by a gate", e)
    _need(ev.get("rollback", {}).get("restored_baseline"), "evolution: rollback did not restore baseline", e)
    _need(ev.get("rollback", {}).get("production_used_promoted"), "evolution: production path ignored the promoted recipe", e)
    pl = r.get("plugins", {})
    _need(pl.get("gaps_before", {}).get("x3d_listed") and not pl.get("gaps_after", {}).get("x3d_listed", True),
          "plugins: x3d gap not closed by the plugin", e)
    _need(pl.get("register", {}).get("ok"), "plugins: example plugin did not register", e)
    _need(pl.get("same_version_refused"), "plugins: same-version re-register accepted", e)
    _need(pl.get("proxy_export", {}).get("verify"), "plugins: hot-loaded proxy export failed", e)
    _need(pl.get("upgrade_rollback", {}).get("v110_registered") and pl["upgrade_rollback"]["rollback"].get("to") == "1.0.0",
          "plugins: upgrade/rollback failed", e)
    _need("x3d-export" in pl.get("tamper", {}).get("refused", {}), "plugins: tampered install loaded", e)
    for name, h in pl.get("hostile", {}).items():
        _need(h["rejected"], f"plugins: hostile fixture {name} accepted", e)
    esc = pl.get("hostile", {}).get("sandbox-escape", {})
    for tier, msg in esc.get("runtime_with_static_gate_bypassed", {}).items():
        _need("net=open" not in msg and "fs=written" not in msg, f"plugins: sandbox {tier} let the escape through: {msg}", e)
    _need(not esc.get("escape_file_exists", True), "plugins: escape probe file exists", e)
    _need(pl.get("scaffold", {}).get("contract_fails_until_implemented"), "plugins: empty scaffold passed the contract", e)
    gw = r.get("groundweave", {})
    _need(gw.get("ok") and len(gw.get("ops", [])) == 2, f"groundweave: {gw}", e)
    return e


def u1_perf(r: dict[str, Any]) -> dict[str, Any]:
    p = r.get("parametric", {}).get("templates", {})
    return {"timings_s": r.get("timings_s"), "adapters_demo_s": r.get("adapters", {}).get("demo_s"),
            "openscad_vs_fallback_rel_diff": {k: (v.get("cross_check") or {}).get("rel_diff") for k, v in p.items()},
            "plugin_verify_s": r.get("plugins", {}).get("register", {}).get("verify_s")}
