# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""U1 universal engine — unit/contract tests (fast half, ≈ 30 s). The full proof is `forge accept U1`
(tests/test_game_increments.py::test_increment_acceptance[U1])."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from forge.universal import coords, csg, evolution, gltf, ir, maps2d, native, openscad, plugins, reference
from forge.universal import mesh as M
from forge.universal import registry as R
from forge.universal.exporters import BUILTINS, REGISTRY
from forge.universal.exporters.base import AdapterError, Pack

FIX = Path("tests/fixtures/universal_plugins")
EXAMPLE = Path("content/universal/plugins/x3d-export")
requires_openscad = pytest.mark.skipif(openscad.openscad_binary() is None, reason="OpenSCAD not installed")
requires_blender = pytest.mark.skipif(native.blender_binary() is None, reason="Blender not installed")
requires_godot_u = pytest.mark.skipif(native.godot_binary() is None, reason="Godot not installed")


# ----------------------------------------------------------------------------------------------- coordinates + IR

@pytest.mark.parametrize("dst", sorted(coords.CONVENTIONS))
def test_convention_matrices_are_proper_and_invertible(dst: str) -> None:
    m = coords.matrix("gltf", dst)
    assert np.allclose(m @ m.T, np.eye(3) * (m @ m.T)[0, 0])          # orthogonal up to uniform unit scale
    back = coords.matrix(dst, "gltf")
    assert np.allclose(back @ m, np.eye(3), atol=1e-12)


@pytest.mark.parametrize("dim", ["2d", "2.5d", "3d"])
def test_ir_json_and_convention_round_trips(dim: str) -> None:
    s = reference.all_scenes()[dim]
    assert ir.validate(s)["ok"]
    assert ir.Scene.from_json(s.to_json()).digest() == s.digest()
    w0 = s.world_matrices()
    for c in ("unity", "unreal", "blender", "source"):
        back = s.converted(c).converted(s.convention)
        for a, b in zip(w0, back.world_matrices()):
            assert np.abs(a - b).max() < 1e-9, c


def test_ir_rejects_future_major_version() -> None:
    d = reference.scene_2d().to_dict()
    d["ir_version"] = "99.0.0"
    with pytest.raises(ValueError):
        ir.Scene.from_dict(d)


# ----------------------------------------------------------------------------------------------- parametric

def test_template_expressions_are_whitelisted() -> None:
    for bad in ("__import__('os')", "open('x')", "a.__class__", "[x for x in y]", "lambda: 1"):
        with pytest.raises(Exception):
            csg.check_expr(bad, {"a", "y"})
    assert csg.eval_expr("max(a, 2) * cos(0)", {"a": 3}) == pytest.approx(3.0)


@pytest.mark.parametrize("tid", ["crate", "pillar", "barrel", "cog"])
def test_csg_fallback_builds_closed_mesh_within_budget(tid: str, tmp_path: Path) -> None:
    r = openscad.build(tid, out_dir=tmp_path, backend="csg-sdf-cpu", cross_check=False)
    v = r["validation"]
    assert r["ok"] and v["manifold"] and v["watertight"] and v["outward_oriented"] and v["within_budget"]
    assert all(r["roundtrip"].values()) and r["glb"]["ok"]
    assert {p.name for p in tmp_path.iterdir()} >= {"model.scad", "model.stl", "model.obj", "model.off", "model.glb", "report.json"}
    r2 = openscad.build(tid, backend="csg-sdf-cpu", cross_check=False)
    assert M.write_stl(r2["_mesh"]) == M.write_stl(r["_mesh"]) and r2["scad_sha256"] == r["scad_sha256"]


def test_templates_have_locale_titles(root: Path) -> None:
    loc = json.loads((root / "locales/en.json").read_text())
    for tid, t in openscad.load_templates(root).items():
        assert t.get("title_key") in loc, tid


def test_parameter_ranges_are_enforced() -> None:
    t = openscad.load_templates()["cog"]
    with pytest.raises(openscad.ParametricError):
        openscad.bind(t, {"teeth": 10_000})
    with pytest.raises(openscad.ParametricError):
        openscad.bind(t, {"no_such_param": 1})


@requires_openscad
def test_openscad_cli_agrees_with_fallback() -> None:
    r = openscad.build("crate")
    assert r["backend"] == "openscad-cli" and r["cross_check"]["ok"], r.get("cross_check")
    assert r["validation"]["manifold"]


def test_reference_volumes_come_from_openscad_or_are_labelled() -> None:
    refs = json.loads(Path(evolution.REF_VOLUMES_PATH).read_text())
    tpls = openscad.load_templates()
    assert set(refs) == set(tpls)
    for tid, t in tpls.items():       # stale cache ⇒ regenerate with OpenSCAD and commit (never silently in CI)
        assert refs[tid]["key"] == evolution._template_key(t), f"{tid}: rerun evolution.reference_volumes(rebuild=True)"
    for r in refs.values():
        assert r["volume"] > 0 and r["source"].startswith(("openscad", "voxel"))


# ----------------------------------------------------------------------------------------------- glTF + 2D maps

def test_glb_writer_validates_and_reads_back() -> None:
    s = reference.scene_3d()
    glb = gltf.write_glb(s)
    v = gltf.validate_glb(glb)
    assert v["ok"], v["errors"]
    assert v["stats"]["skins"] >= 1 and v["stats"]["meshes"] >= 3
    assert gltf.write_glb(s) == glb


def test_normals_pipeline_is_unit_and_finite() -> None:
    a = np.zeros((32, 32), np.uint8)
    a[6:26, 6:26] = 255
    n, h = maps2d.normals_for_silhouette(a, evolution.baseline_recipe("maps2d.normal"))
    assert np.isfinite(n).all() and np.allclose(np.linalg.norm(n, axis=-1), 1, atol=1e-6)
    assert h.max() <= 1 and h[a == 0].max() == 0


# ----------------------------------------------------------------------------------------------- adapters

@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from forge.universal import engine
    return engine.demo(tmp_path_factory.mktemp("demo"), native=False)


def test_every_adapter_exports_and_verifies(demo: dict) -> None:
    bad = [r for r in demo["exports"] + demo["imports"] if not r["ok"]]
    assert not bad, bad[:3]
    assert demo["counts"]["exports"] >= 30 and demo["counts"]["imports"] >= 8
    covered = {r["adapter"] for r in demo["exports"]} | {r["adapter"] for r in demo["imports"]}
    assert covered == {a.id for a in BUILTINS}


@pytest.mark.parametrize("aid", ["gltf", "unity", "unreal", "rpgmaker", "spritelamp", "splats", "meshpack-gameguru"])
def test_exports_are_byte_deterministic(aid: str, tmp_path: Path) -> None:
    a = REGISTRY[aid]
    dim = "3d" if "3d" in a.dims else a.dims[0]
    s = reference.all_scenes()[dim]
    m1, m2 = a.export(s, tmp_path / "a"), a.export(s, tmp_path / "b")
    assert m1["files"] == m2["files"]


def test_pack_refuses_path_escape(tmp_path: Path) -> None:
    p = Pack(tmp_path)
    for bad in ("../x", "/etc/x", "a/../../x"):
        with pytest.raises(AdapterError):
            p.add(bad, b"x")


def test_tiers_are_honest() -> None:
    for a in BUILTINS:
        assert a.tier in ("native_verified", "cli_bridge", "interchange_pack", "descriptor_only")
        overrides_native = type(a).native_check is not type(a).__mro__[-2].native_check
        if a.tier in ("native_verified", "cli_bridge"):
            assert overrides_native, a.id


@requires_godot_u
def test_godot_loads_exported_glb(tmp_path: Path) -> None:
    a = REGISTRY["godot"]
    a.export(reference.scene_3d(), tmp_path)
    r = a.native_check(tmp_path)
    assert r["ran"] and r["ok"], r


@requires_blender
def test_blender_bridge_imports_pack(tmp_path: Path) -> None:
    a = REGISTRY["blender"]
    a.export(reference.scene_3d(), tmp_path)
    r = a.native_check(tmp_path)
    assert r["ran"] and r["ok"], r


# ----------------------------------------------------------------------------------------------- catalog

def test_catalog_integrity_and_named_tools() -> None:
    rep = R.integrity()
    assert rep["ok"], rep["errors"]
    assert rep["wikipedia_unique"] >= 150 and rep["named_tools"] >= 18 and rep["entries_total"] >= 170
    for name in ("unreal-engine", "unity", "blender", "openscad", "rpg-maker-mz", "sprite-lamp", "gameguru", "construct-2",
                 "coppercube", "esenthel-engine", "appgamekit", "clickteam-fusion"):
        assert R.search(name.replace("-", " ").split()[0]), name


def test_catalog_search_and_resolve() -> None:
    hits = R.search("godot")
    assert any(h["id"] == "godot" for h in hits)
    e = R.resolve("godot")
    assert e["tier"] == "native_verified"


# ----------------------------------------------------------------------------------------------- self-improvement

def test_normals_evolution_promotes_and_rolls_back(tmp_path: Path) -> None:
    r = evolution.evolve("maps2d.normal", rounds=2, state_dir=tmp_path)
    objs = [x["promoted"]["objective"] for x in r["rounds"] if x["promoted"]]
    assert len(objs) == 2 and objs[1] < objs[0] < r["rounds"][0]["baseline"]["objective"]
    assert evolution.active_recipe("maps2d.normal", state_dir=tmp_path) != evolution.baseline_recipe("maps2d.normal")
    evolution.rollback("maps2d.normal", 1, state_dir=tmp_path)
    assert evolution.active_recipe("maps2d.normal", state_dir=tmp_path) == evolution.baseline_recipe("maps2d.normal")


def test_decide_requires_every_gate_and_strict_gain() -> None:
    E = evolution.Evaluation
    base = E({"a": 1}, 1.0, {"g": True}, {}, 0.0)
    assert evolution.decide(base, E({"a": 2}, 0.5, {"g": True}, {}, 0.0))[0]
    ok, why = evolution.decide(base, E({"a": 3}, 0.1, {"g": False}, {}, 0.0))
    assert not ok and "gate failed" in why
    assert not evolution.decide(base, E({"a": 4}, 1.0, {"g": True}, {}, 0.0))[0]


def test_parametric_gate_rejects_too_coarse_recipe() -> None:
    ev = evolution.eval_parametric({"cell_frac": 0.05, "newton_steps": 0})
    assert not ev.gates["max_rel_volume_error"]


# ----------------------------------------------------------------------------------------------- plugins + gaps

def test_static_policy_flags_hostile_fixtures() -> None:
    assert plugins.security_scan(EXAMPLE)["ok"]
    assert not plugins.security_scan(FIX / "net-exfil")["ok"]
    assert not plugins.security_scan(FIX / "sandbox-escape")["ok"]
    assert plugins.security_scan(FIX / "nondeterministic")["ok"]       # only the runtime determinism gate catches it


def test_manifest_rules() -> None:
    m = plugins.read_manifest(EXAMPLE)
    assert plugins.check_manifest(m, {a.id for a in BUILTINS}) == []
    for k, v, frag in (("tier", "native_verified", "not allowed"), ("version", "1.0", "semver"), ("id", "gltf", "collides"),
                       ("api_version", "2.0", "incompatible"), ("entrypoint", "../x.py:X", "entrypoint")):
        errs = plugins.check_manifest({**m, k: v}, {a.id for a in BUILTINS})
        assert any(frag in e for e in errs), (k, errs)
    assert plugins.check_manifest({**m, "permissions": {"network": True}})


def test_plugin_lifecycle(tmp_path: Path) -> None:
    sd = tmp_path / "state"
    assert any(g["id"] == "x3d" for g in plugins.gaps(sd=sd)["gaps"])
    r = plugins.register(EXAMPLE, sd=sd)
    assert r["ok"], r["verify"]["errors"]
    assert not plugins.register(EXAMPLE, sd=sd)["ok"]                  # same version refused
    assert not any(g["id"] == "x3d" for g in plugins.gaps(sd=sd)["gaps"])
    reg = dict(REGISTRY)
    assert plugins.load_active(reg, sd=sd)["loaded"] == ["x3d-export@1.0.0"]
    out = tmp_path / "x3d"
    m = reg["x3d-export"].export(reference.scene_3d(), out)
    assert "scene.x3d" in m["files"] and reg["x3d-export"].verify(out)["ok"]
    f = sd / plugins.active(sd=sd)["x3d-export"]["path"] / "adapter.py"
    f.write_text(f.read_text() + "# tamper\n")
    assert "x3d-export" in plugins.load_active(dict(REGISTRY), sd=sd)["refused"]
    assert plugins.rollback("x3d-export", sd=sd)["to"] is None


@pytest.mark.parametrize("name", ["net-exfil", "nondeterministic", "sandbox-escape"])
def test_hostile_plugins_are_rejected(name: str) -> None:
    r = plugins.verify(FIX / name)
    assert not r["ok"]
    if name == "nondeterministic":
        assert r["checks"]["security_policy"] and not r["checks"]["contract"]
        assert any("not deterministic" in e for e in r["errors"])


@pytest.mark.parametrize("tier", ["auto", "process"])
def test_sandbox_blocks_escape_even_without_static_gate(root: Path, tier: str) -> None:
    esc = FIX / "sandbox-escape"
    res, meta = plugins._sandbox_call(esc, {"op": "contract", "manifest": plugins.read_manifest(esc)}, root, tier=tier)
    msg = " ".join(res.get("errors", []))
    assert "net=open" not in msg and "fs=written" not in msg and "net=" in msg, (meta, msg)
    assert not Path("/var/tmp/assetfabric_sandbox_escape_probe").exists()


def test_scaffold_fails_contract_until_implemented(tmp_path: Path) -> None:
    sc = plugins.scaffold("usd-export", tmp_path / "p", ["usd"], ["3d"])
    assert plugins.security_scan(Path(sc["path"]))["ok"]
    r = plugins.verify(Path(sc["path"]))
    assert not r["ok"] and any("NotImplementedError" in e for e in r["errors"])


# ----------------------------------------------------------------------------------------------- CLI + GroundWeave

def test_cli_surface(tmp_path: Path) -> None:
    from forge.cli import main
    cr = CliRunner()
    r = cr.invoke(main, ["universal", "catalog", "--summary"])
    assert r.exit_code == 0 and json.loads(r.output)["ok"]
    r = cr.invoke(main, ["parametric", "scad", "cog", "--set", "teeth=14"])
    assert r.exit_code == 0 and "teeth = 14" in r.output
    r = cr.invoke(main, ["universal", "export", "gamemaker", "--scene", "ref:2d", "--out", str(tmp_path / "gm")])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["verify"]["ok"]
    r = cr.invoke(main, ["universal", "export", "no-such-engine", "--out", str(tmp_path / "x")])
    assert r.exit_code == 1
    r = cr.invoke(main, ["universal", "gaps"])
    assert r.exit_code == 0 and json.loads(r.output)["formats_total"] >= 10


def test_groundweave_has_universal_ops(root: Path) -> None:
    from forge import groundweave
    chk = groundweave.check(root)
    assert chk["ok"], chk["problems"]
    ops = groundweave.load_ladder(root)["ops"]
    assert {"gen.parametric", "universal.export"} <= set(ops)
    assert groundweave.select("gen.parametric", root=root)["backend"] == "csg-sdf-cpu"
