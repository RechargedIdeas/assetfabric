"""C12 real CPU paths (0.7.7): splat .ply I/O, MeshWeaver (density → surface nets → OBJ), GDGS import into Godot."""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from forge import milestones, realityloom, splats


def test_ply_round_trip_and_validator() -> None:
    ply = splats.sphere_splats(300, seed=4)
    assert realityloom.check_splat_ply(ply)["vertices"] == 300
    s = splats.read_ply(ply)
    assert np.allclose(np.linalg.norm(s["pos"], axis=1), 0.5, atol=1e-6)
    assert np.allclose(s["opacity"], 0.9, atol=1e-5) and np.allclose(s["scale"], 0.03, atol=1e-6)


def test_surface_nets_on_analytic_sphere() -> None:
    ax = np.linspace(-1, 1, 33)
    x, y, z = np.meshgrid(ax, ax, ax, indexing="ij")
    v, t = splats.surface_nets(0.6 - np.sqrt(x * x + y * y + z * z))
    r = np.linalg.norm(-1 + v * (2 / 32), axis=1)
    assert np.abs(r - 0.6).max() < 0.0625 / 2 and len(t) > 1000
    e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), 1)
    assert set(np.unique(np.unique(e, axis=0, return_counts=True)[1])) == {2}     # closed 2-manifold


def test_meshweaver_convert(tmp_path: Path) -> None:
    p = tmp_path / "s.ply"
    p.write_bytes(splats.sphere_splats(1500, seed=1))
    mw = realityloom.MeshWeaver()
    obj = mw.convert(p)
    assert obj.suffix == ".obj" and mw.last["triangles"] > 1000
    vs = np.array([[float(x) for x in ln.split()[1:4]] for ln in obj.read_text().splitlines() if ln.startswith("v ")])
    assert abs(float(np.median(np.linalg.norm(vs, axis=1))) - 0.5) < 0.03
    assert obj.read_bytes() == realityloom.MeshWeaver().convert(p, tmp_path / "b.obj").read_bytes()   # deterministic


def test_gdgs_scene_text_and_prune(tmp_path: Path) -> None:
    ply = splats.sphere_splats(500, seed=3)
    scene, info = splats.write_godot_scene(ply, "x", max_splats=200)
    assert info == {**info, "source_splats": 500, "imported": 200, "pruned": 300}
    assert 'type="MultiMesh"' in scene and "instance_count = 200" in scene and "gl_compatibility" not in scene


@pytest.mark.skipif(milestones.godot_binary(Path(".")) is None or shutil.which("xvfb-run") is None,
                    reason="needs Godot + Xvfb (headless Godot drops MultiMesh data)")
def test_gdgs_import_loads_and_renders_in_godot(tmp_path: Path, root: Path) -> None:
    p = tmp_path / "s.ply"
    p.write_bytes(splats.sphere_splats(800, seed=5))
    gi = realityloom.GdgsImport()
    scene = gi.into_godot(p, tmp_path / "proj")
    assert scene.exists()
    g = splats.verify_in_godot(tmp_path / "proj", gi.last["res_path"], root)
    assert g["ok"] and g["count"] == 800 and g["renderer"] == "gl_compatibility"
    for gp, ep in zip(g["probes"], gi.last["probe"]):
        assert np.allclose(gp["pos"], ep["pos"], atol=1e-4) and np.allclose(gp["rgba"], ep["rgba"], atol=4e-3)
    assert g["render"]["lit"] > 500 and g["render"]["mean_rgb"][2] > g["render"]["mean_rgb"][0]


def test_photogrammetry_recovers_rendered_cameras(tmp_path: Path, root: Path) -> None:
    from forge import photogrammetry as pg
    sc = pg.render_views(8, arc_deg=90)
    b = tmp_path / "b"
    realityloom.write_bundle(b, [pg.png_bytes(i) for i in sc["images"]], "hero_prop", "burst", root)
    ph = realityloom.Photogrammetry(float(sc["K"][0, 0]))
    ply = ph.run(b)
    assert ply.exists() and ph.last["registered"] == 8 and ph.last["points"] > 300
    rec = pg.reconstruct(sc["images"], focal_px=float(sc["K"][0, 0]))
    ev = pg.evaluate(rec, sc["poses"])
    assert ev["rot_err_deg_max"] < 2.0 and ev["center_err_rel_max"] < 0.05
