# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Deterministic reference scenes (2D, 2.5D, 3D/mixed) used by the adapter contract suite, `forge universal demo`
and `forge accept U1`. Everything is generated procedurally on CPU — no external assets, no RNG state."""

from __future__ import annotations

import numpy as np

from forge.universal import csg, ir, maps2d, png
from forge.universal import mesh as M

FRAME = 48                     # RPG Maker MV/MZ character frame size


def hero_atlas(frame: int = FRAME) -> np.ndarray:
    """3 walk frames × 4 directions (down, left, right, up) — the RPG Maker character-block layout."""
    rows = [np.concatenate([maps2d.character_frame(frame, d, k) for k in range(3)], axis=1) for d in maps2d.DIRECTIONS]
    return np.concatenate(rows, axis=0)


def sprite_maps(rgba: np.ndarray, recipe: maps2d.NormalRecipe = maps2d.NormalRecipe()) -> dict[str, np.ndarray]:
    """Per-frame height → normal / depth / AO / emission maps for an atlas (computed frame by frame so frames
    never bleed into each other)."""
    h, w = rgba.shape[:2]
    alpha = rgba[..., 3]
    height = np.zeros((h, w))
    for y in range(0, h, FRAME):
        for x in range(0, w, FRAME):
            height[y:y + FRAME, x:x + FRAME] = maps2d.height_from_alpha(alpha[y:y + FRAME, x:x + FRAME], recipe)
    n = maps2d.normals_from_height(height, recipe.strength)
    emis = np.zeros_like(rgba)
    eye = (rgba[..., 0] < 40) & (rgba[..., 2] < 50) & (alpha > 0) & (rgba[..., 1] < 40)
    emis[eye] = (255, 220, 120, 255)
    emis[~eye & (alpha > 0)] = (0, 0, 0, 255)
    return {"height": height, "normals": n, "normal": maps2d.encode_normals(n, alpha), "depth": maps2d.depth_map(height, alpha),
            "ao": maps2d.ambient_occlusion(height, alpha), "emission": emis}


def tiles_atlas(size: int = FRAME) -> np.ndarray:
    return np.concatenate([maps2d.tile(size, k, 0) for k in ("grass", "stone", "water", "dirt")], axis=1)


def add_hero(s: ir.Scene) -> None:
    atlas = hero_atlas()
    mp = sprite_maps(atlas)
    s.add(ir.Texture("hero_atlas", png.encode(atlas), "base_color"))
    s.add(ir.Texture("hero_normal", png.encode(mp["normal"]), "normal", colorspace="linear"))
    s.add(ir.Texture("hero_depth", png.encode(mp["depth"]), "depth", colorspace="linear"))
    s.add(ir.Texture("hero_emission", png.encode(mp["emission"]), "emission"))
    frames = [(x * FRAME, y * FRAME, FRAME, FRAME) for y in range(4) for x in range(3)]
    anims = {f"walk_{d}": {"frames": [i * 3 + 0, i * 3 + 1, i * 3 + 2, i * 3 + 1], "fps": 6, "loop": True}
             for i, d in enumerate(maps2d.DIRECTIONS)}
    s.add(ir.Sprite("hero", "hero_atlas", frames, {"normal": "hero_normal", "depth": "hero_depth", "emission": "hero_emission"},
                    (0.5, 1.0), 32.0, anims))


def add_tiles(s: ir.Scene) -> None:
    s.add(ir.Texture("tiles_atlas", png.encode(tiles_atlas()), "base_color"))
    s.add(ir.Sprite("tiles", "tiles_atlas", [(i * FRAME, 0, FRAME, FRAME) for i in range(4)], {}, (0.5, 0.5), 48.0, {}))


def crate_mesh(cell: float = 0.08) -> M.TriMesh:
    tree = csg.resolve({"op": "difference", "children": [
        {"op": "cube", "size": [1, 1, 1], "center": True},
        {"op": "translate", "v": [0, 0, 0.5], "children": [{"op": "cube", "size": [0.8, 0.8, 0.1], "center": True}]}]}, {})
    m = csg.polygonize(tree, csg.MeshRecipe(cell=cell, newton_steps=1))
    return M.box_project_uvs(m)


def skinned_bar() -> tuple[ir.MeshAsset, ir.Skeleton]:
    """A 2-bone bar (cylinder along +Y, 1 m) with linear blend weights — rigged-character smoke content."""
    cyl = M.cylinder(0.1, 1.0, 12, center=False).transformed(np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float))  # Z→Y
    y = cyl.positions[:, 1]
    w1 = np.clip((y - 0.25) / 0.5, 0, 1)
    weights = np.stack([1 - w1, w1, np.zeros_like(y), np.zeros_like(y)], 1).astype(np.float32)
    joints = np.tile(np.array([0, 1, 0, 0], np.uint16), (cyl.n_vertices, 1))
    rest = np.stack([np.eye(4), np.eye(4)])
    rest[1, 1, 3] = 0.5
    sk = ir.Skeleton("bar_rig", ["root", "elbow"], [-1, 0], rest, np.zeros((2, 4, 4)))
    sk.inverse_bind = np.linalg.inv(sk.world_rest())
    cyl.normals = cyl.vertex_normals()
    return ir.MeshAsset("bar", cyl, "mat_bar", "bar_rig", joints, weights), sk


def _trs(t: tuple[float, float, float], yaw_deg: float = 0.0) -> np.ndarray:
    a = np.radians(yaw_deg)
    m = np.eye(4)
    m[:3, :3] = [[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]]
    m[:3, 3] = t
    return m


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray = np.array([0.0, 1.0, 0.0])) -> np.ndarray:
    back = eye - target
    back = back / np.linalg.norm(back)
    right = np.cross(up, back)
    right /= np.linalg.norm(right)
    up2 = np.cross(back, right)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = right, up2, back, eye
    return m


def scene_3d() -> ir.Scene:
    """Mixed 3D reference: CSG crate (PBR + textures), skinned bar, sprite card, point cloud, splats, camera ring."""
    from forge import splats as _spl

    s = ir.Scene("af_reference_3d", "3d", "gltf")
    dirt = maps2d.tile(64, "dirt", 1)
    lum = dirt[..., :3].astype(float).mean(-1) / 255.0
    nrm = maps2d.encode_normals(maps2d.normals_from_height(lum, 1.5))
    s.add(ir.Texture("crate_albedo", png.encode(dirt), "base_color", "linear"))
    s.add(ir.Texture("crate_normal", png.encode(nrm), "normal", "linear", "linear"))
    s.add(ir.Material("mat_crate", (1, 1, 1, 1), 0.0, 0.7, (0, 0, 0), {"base_color": "crate_albedo", "normal": "crate_normal"}))
    s.add(ir.Material("mat_bar", (0.8, 0.3, 0.2, 1), 0.2, 0.5))
    crate = crate_mesh()
    s.add(ir.MeshAsset("crate", crate, "mat_crate"))
    bar, rig = skinned_bar()
    s.add(rig)
    s.add(bar)
    add_hero(s)
    pts = crate.positions[:: max(1, crate.n_vertices // 256)][:256].astype(np.float32)
    s.add(ir.PointCloud("crate_points", pts, np.tile(np.array([[200, 160, 90]], np.uint8), (pts.shape[0], 1))))
    s.add(ir.SplatSet("orb", _spl.sphere_splats(300, radius=0.4, seed=7)))
    root = s.add_node(ir.Node("root"))
    s.add_node(ir.Node("crate", _trs((2.0, 0.5, 0.0), 30.0), mesh="crate"), root)
    s.add_node(ir.Node("bar", _trs((-2.0, 0.0, 0.0)), mesh="bar"), root)
    s.add_node(ir.Node("hero", _trs((0.0, 0.0, 1.0)), sprite="hero"), root)
    s.add_node(ir.Node("points", _trs((2.0, 0.5, 3.0)), points="crate_points"), root)
    s.add_node(ir.Node("orb", _trs((0.0, 1.5, -2.0)), splats="orb"), root)
    for i in range(8):
        a = 2 * np.pi * i / 8
        eye = np.array([3.0 * np.cos(a), 1.2, 3.0 * np.sin(a)])
        cid = f"cam{i:02d}"
        s.add(ir.Camera(cid, 320, 240, 280.0, 280.0, 160.0, 120.0, look_at(eye, np.zeros(3))))
        s.add_node(ir.Node(cid, camera=cid), root)
    return s


def scene_2d() -> ir.Scene:
    s = ir.Scene("af_reference_2d", "2d", "gltf")
    add_hero(s)
    add_tiles(s)
    s.add_node(ir.Node("hero", sprite="hero"))
    s.add_node(ir.Node("ground", _trs((0.0, -0.5, -0.1)), sprite="tiles"))
    return s


def scene_25d() -> ir.Scene:
    s = ir.Scene("af_reference_25d", "2.5d", "gltf")
    add_hero(s)
    add_tiles(s)
    for gx in range(3):
        for gy in range(3):
            lid = f"floor_{gx}_{gy}"
            s.add(ir.Layer25D(lid, "isometric", "tiles", depth=float(gx + gy), parallax=1.0, tile_size=(48, 24), grid_pos=(gx, gy)))
            x, y = s.layers[lid].screen_position()
            s.add_node(ir.Node(lid, _trs((x / 48.0, -y / 48.0, -0.01 * (gx + gy))), layer=lid))
    s.add(ir.Layer25D("hero_card", "depth_card", "hero", depth=0.5, parallax=1.0, tile_size=(48, 24), grid_pos=(1, 1)))
    s.add_node(ir.Node("hero_card", _trs((0.0, 0.0, 0.5)), layer="hero_card"))
    return s


def all_scenes() -> dict[str, ir.Scene]:
    return {"3d": scene_3d(), "2d": scene_2d(), "2.5d": scene_25d()}
