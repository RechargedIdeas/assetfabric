# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""3D adapters: glTF (universal), Godot (native), Unreal, Unity, Blender bridge (native), OpenSCAD bridge (CLI),
and the OBJ/.x mesh-pack family (GameGuru, CopperCube 6, Esenthel, AGFPRO 3, RaySupreme 3D)."""

from __future__ import annotations

import ast
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from forge.universal import coords, gltf, ir, png
from forge.universal import mesh as M
from forge.universal.exporters import two_d
from forge.universal.exporters.base import Adapter, Pack, finish_verify, read_manifest
from forge.universal.exporters.xfile import read_x, write_x


def world_meshes(scene: ir.Scene, dst: str) -> list[tuple[str, M.TriMesh, ir.MeshAsset]]:
    """Every mesh node baked to world space in convention `dst` (index order kept CCW-outward for RH targets)."""
    s = scene.converted(dst)
    wm = s.world_matrices()
    out = []
    for i, n in enumerate(s.nodes):
        if n.mesh:
            ma = s.meshes[n.mesh]
            m = ma.mesh.transformed(wm[i])
            if ma.mesh.uvs is not None:
                m.uvs = ma.mesh.uvs.copy()
            out.append((n.name, m, ma))
    return out


def _quat(r: np.ndarray) -> list[float]:
    """Rotation matrix (orthonormal, det +1) → quaternion [x, y, z, w] (w ≥ 0, canonical)."""
    t = np.trace(r)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
    else:
        i = int(np.argmax(np.diag(r)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = np.sqrt(1.0 + r[i, i] - r[j, j] - r[k, k]) * 2
        q = [0.0] * 4
        q[i] = 0.25 * s
        q[j] = (r[j, i] + r[i, j]) / s
        q[k] = (r[k, i] + r[i, k]) / s
        q[3] = (r[k, j] - r[j, k]) / s
    q = np.array(q)
    q = q / np.linalg.norm(q)
    return [round(float(x), 9) for x in (q if q[3] >= 0 else -q)]


def decompose(m: np.ndarray) -> dict[str, Any]:
    t = m[:3, 3]
    lin = m[:3, :3]
    sc = np.linalg.norm(lin, axis=0)
    r = lin / np.where(sc == 0, 1, sc)
    det = np.linalg.det(r)
    if det < 0:                       # a reflection: fold it into a negative X scale (engine convention)
        sc[0] = -sc[0]
        r[:, 0] = -r[:, 0]
    return {"location": [round(float(x), 6) for x in t], "rotation_quat_xyzw": _quat(r),
            "scale": [round(float(x), 6) for x in sc]}


def _glb_node_worlds(glb: bytes) -> dict[str, np.ndarray]:
    doc, _ = gltf.parse_glb(glb)
    nodes = doc.get("nodes", [])
    out: dict[str, np.ndarray] = {}

    def walk(i: int, parent: np.ndarray) -> None:
        nd = nodes[i]
        loc = np.array(nd["matrix"], float).reshape(4, 4).T if "matrix" in nd else np.eye(4)
        w = parent @ loc
        out[nd.get("name", str(i))] = w
        for c in nd.get("children", []):
            walk(c, w)
    for r in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        walk(r, np.eye(4))
    return out


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


# ============================================================================ glTF / Godot

class GltfAdapter(Adapter):
    id, name, tier, direction = "gltf", "glTF 2.0 / GLB (universal)", "interchange_pack", "both"
    dims, convention, formats = ("2d", "2.5d", "3d"), "gltf", ("glb",)

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        glb = gltf.write_glb(scene)
        pk.add(f"{_safe(scene.name)}.glb", glb)
        for sid in sorted(scene.splats):                       # splats ride alongside (no ratified glTF encoding)
            pk.add(f"{_safe(sid)}.splat.ply", scene.splats[sid].ply)
        return pk.finish(self, scene, glb=f"{_safe(scene.name)}.glb", expected={
            "meshes": len(scene.meshes), "triangles": int(sum(m.mesh.n_triangles for m in scene.meshes.values()))})

    def verify(self, out: Path) -> dict[str, Any]:
        man = read_manifest(out)
        glb = (Path(out) / man["glb"]).read_bytes()
        v = gltf.validate_glb(glb)
        tri_ok = v["stats"].get("triangles", 0) >= man["expected"]["triangles"]
        return finish_verify({"glb_valid": v["ok"], "triangles_preserved": tri_ok}, v["errors"], out, stats=v["stats"])

    def import_(self, path: Path) -> ir.Scene:
        data = Path(path).read_bytes()
        v = gltf.validate_glb(data)
        if not v["ok"]:
            raise ValueError(f"invalid GLB: {v['errors'][:3]}")
        s = ir.Scene(Path(path).stem, "3d", "gltf")
        for k, m in enumerate(gltf.read_meshes(data)):
            mid = _safe(m["name"] or f"mesh{k}")
            if mid in s.meshes:
                mid = f"{mid}_{k}"
            tm = M.TriMesh(m["positions"].astype(np.float64), m["indices"].astype(np.int64))
            s.add(ir.MeshAsset(mid, tm))
            s.add_node(ir.Node(mid, mesh=mid))
        return s

    def sample_input(self, out: Path) -> Path:
        from forge.universal import reference
        p = Path(out) / "sample.glb"
        p.write_bytes(gltf.write_glb(reference.scene_3d()))
        return p


class GodotAdapter(GltfAdapter):
    id, name, tier, direction = "godot", "Godot 4", "native_verified", "both"
    convention, formats = "godot", ("glb", "tres-spriteframes", "png")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        base = _safe(scene.name)
        pk.add(f"{base}.glb", gltf.write_glb(scene))
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            pk.add(f"sprites/{_safe(sp.atlas)}.png", scene.textures[sp.atlas].png)
            pk.add(f"sprites/{_safe(sid)}.tres", two_d.godot_spriteframes(sp, f"res://assetfabric/{base}/sprites/{_safe(sp.atlas)}.png"))
        return pk.finish(self, scene, glb=f"{base}.glb", res_root=f"res://assetfabric/{base}/",
                         expected={"meshes": len(scene.meshes), "skins": sum(1 for m in scene.meshes.values() if m.skeleton),
                                   "triangles": int(sum(m.mesh.n_triangles for m in scene.meshes.values()))})

    def verify(self, out: Path) -> dict[str, Any]:
        base = super().verify(out)
        tres_ok = all(p.read_text().startswith('[gd_resource type="SpriteFrames"') for p in Path(out).glob("sprites/*.tres"))
        base["checks"]["spriteframes_tres"] = tres_ok
        base["ok"] = base["ok"] and tres_ok
        return base

    def native_check(self, out: Path) -> dict[str, Any]:
        from forge.universal import native
        man = read_manifest(out)
        r = native.godot_load_glb(Path(out) / man["glb"])
        if r.get("ran") and r.get("ok"):
            r["skins_match"] = r.get("skins") == man["expected"]["skins"]
            r["ok"] = r["skins_match"] and r.get("meshes", 0) >= man["expected"]["meshes"]
        return r


# ============================================================================ Unreal

UNREAL_SCRIPT = '''# AssetFabric → Unreal Engine import script (Editor Python). Generated — Copyright (c) 2026 Recharged Ideas.
# Run inside the Unreal Editor: Tools > Execute Python Script..., or `UnrealEditor-Cmd <project> -run=pythonscript -script=<this file>`.
import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = json.load(open(os.path.join(HERE, "AssetFabricImport.json")))
DEST = MANIFEST["destination_path"]


def import_file(path, dest):
    task = unreal.AssetImportTask()
    task.filename = os.path.join(HERE, path)
    task.destination_path = dest
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return list(task.imported_object_paths)


imported = import_file(MANIFEST["glb"], DEST)
for tex in MANIFEST["textures"]:
    import_file(tex["file"], DEST + "/Textures")
for actor in MANIFEST["actors"]:
    asset = unreal.EditorAssetLibrary.load_asset(DEST + "/" + actor["asset"])
    if asset is None:
        continue
    loc = unreal.Vector(*actor["location_cm"])
    q = actor["rotation_quat_xyzw"]
    rot = unreal.Quat(q[0], q[1], q[2], q[3]).rotator()
    a = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, loc, rot)
    a.set_actor_scale3d(unreal.Vector(*actor["scale"]))
    a.set_actor_label(actor["name"])
unreal.log("AssetFabric import complete: %d objects" % len(imported))
'''


class UnrealAdapter(Adapter):
    id, name, tier, direction = "unreal", "Unreal Engine 5", "interchange_pack", "export"
    dims, convention = ("2d", "3d"), "unreal"
    formats = ("glb", "png", "texturepacker-json", "unreal-python", "json-manifest")
    UNREAL_API = {"AssetImportTask", "AssetToolsHelpers", "EditorAssetLibrary", "Vector", "Quat", "EditorLevelLibrary", "log"}

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        base = _safe(scene.name)
        glb = gltf.write_glb(scene)
        pk.add(f"{base}.glb", glb)
        ue = scene.converted("unreal")
        wm = ue.world_matrices()
        actors = []
        for i, n in enumerate(ue.nodes):
            if not (n.mesh or n.sprite):
                continue
            d = decompose(wm[i])
            actors.append({"name": n.name, "asset": n.mesh or n.sprite, "location_cm": d["location"],
                           "rotation_quat_xyzw": d["rotation_quat_xyzw"], "scale": d["scale"]})
        textures = []
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            pk.add(f"Sprites/{_safe(sid)}.png", scene.textures[sp.atlas].png)
            pk.add(f"Sprites/{_safe(sid)}.json", two_d.texturepacker_json(sp, scene, f"{_safe(sid)}.png"))
            textures.append({"file": f"Sprites/{_safe(sid)}.png", "kind": "paper2d_sheet"})
            if "normal" in sp.maps:
                src = png.decode(scene.textures[sp.maps["normal"]].png)
                pk.add(f"Sprites/{_safe(sid)}_N.png", png.encode(coords.convert_normal_map(src, "gltf", "unreal")))
                textures.append({"file": f"Sprites/{_safe(sid)}_N.png", "kind": "normal_directx", "source_texture": sp.maps["normal"]})
        mats = [{"name": m.id, "base_color": list(m.base_color), "metallic": m.metallic, "roughness": m.roughness,
                 "textures": m.textures} for m in (scene.materials[k] for k in sorted(scene.materials))]
        lods = [{"mesh": k, "lod": 0, "screen_size": 1.0, "triangles": scene.meshes[k].mesh.n_triangles,
                 "note": "single LOD (no decimator in U1)"} for k in sorted(scene.meshes)]
        manifest = {"destination_path": f"/Game/AssetFabric/{base}", "glb": f"{base}.glb",
                    "unreal": {"units": "centimeters", "up": "+Z", "forward": "+X", "handedness": "left"},
                    "actors": actors, "textures": textures, "materials": mats, "lods": lods,
                    "fbx": "not written (no verified FBX writer in U1); UE5 Interchange imports the GLB"}
        pk.add("AssetFabricImport.json", json.dumps(manifest, indent=2, sort_keys=True))
        pk.add("import_assetfabric_unreal.py", UNREAL_SCRIPT)
        return pk.finish(self, scene, glb=f"{base}.glb")

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        errs: list[str] = []
        man = json.loads((out / "AssetFabricImport.json").read_text())
        glb = (out / man["glb"]).read_bytes()
        v = gltf.validate_glb(glb)
        errs += v["errors"]
        worlds = _glb_node_worlds(glb)                                     # glTF space (metres, Y-up RH)
        conv_ok = True
        for a in man["actors"]:
            w = worlds.get(a["name"])
            if w is None:
                conv_ok = False
                errs.append(f"actor {a['name']} not in GLB")
                continue
            expect = coords.convert_points(w[:3, 3][None], "gltf", "unreal")[0]
            if not np.allclose(expect, a["location_cm"], atol=1e-3):
                conv_ok = False
                errs.append(f"actor {a['name']}: location {a['location_cm']} != converted {expect.round(4).tolist()}")
        nm_ok = True
        for t in man["textures"]:
            if t["kind"] == "normal_directx":
                sheet = json.loads((out / t["file"].replace("_N.png", ".json")).read_text())
                nm_ok &= two_d.normal_map_is_y_down(png.decode((out / t["file"]).read_bytes()), sheet)
        try:
            tree = ast.parse((out / "import_assetfabric_unreal.py").read_text())
            used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "unreal"}
            api_ok = used <= self.UNREAL_API
            if not api_ok:
                errs.append(f"unreal API outside allow-list: {sorted(used - self.UNREAL_API)}")
        except SyntaxError as e:
            api_ok = False
            errs.append(f"script syntax: {e}")
        tp_ok = all(two_d.check_texturepacker_json(json.loads(p.read_text()), out / "Sprites") for p in out.glob("Sprites/*.json"))
        return finish_verify({"glb_valid": v["ok"], "actors_converted_zup_cm": conv_ok, "normal_maps_directx": nm_ok,
                              "script_ast": api_ok, "paper2d_json": tp_ok}, errs, out)


# ============================================================================ Unity

def unity_guid(path: str) -> str:
    return hashlib.md5(("assetfabric:" + path).encode()).hexdigest()   # noqa: S324 — deterministic id, not security


def _meta(path: str, importer: str, body: dict[str, Any] | None = None, folder: bool = False) -> str:
    d: dict[str, Any] = {"fileFormatVersion": 2, "guid": unity_guid(path)}
    if folder:
        d["folderAsset"] = "yes"
    d[importer] = body or {"externalObjects": {}, "userData": None, "assetBundleName": None, "assetBundleVariant": None}
    return yaml.safe_dump(d, sort_keys=False)


class UnityAdapter(Adapter):
    id, name, tier, direction = "unity", "Unity (UPM package + .unitypackage)", "interchange_pack", "export"
    dims, convention = ("2d", "2.5d", "3d"), "unity"
    formats = ("upm-package", "unitypackage", "meta-yaml", "obj", "glb", "png")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        base = _safe(scene.name).lower()
        pkg = f"com.rechargedideas.assetfabric.{re.sub(r'[^a-z0-9]', '', base)}"
        root = f"Packages/{pkg}"
        assets: dict[str, bytes] = {}                 # package-relative path → bytes (for .unitypackage)
        metas: dict[str, str] = {}

        def put(rel: str, data: bytes | str, importer: str, body: dict[str, Any] | None = None) -> None:
            b = data.encode() if isinstance(data, str) else data
            pk.add(f"{root}/{rel}", b)
            meta = _meta(f"{pkg}/{rel}", importer, body)
            pk.add(f"{root}/{rel}.meta", meta)
            assets[rel], metas[rel] = b, meta
        package = {"name": pkg, "version": "1.0.0", "displayName": f"AssetFabric {scene.name}", "unity": "2021.3",
                   "description": "Generated by AssetFabric (Copyright (c) 2026 Recharged Ideas). GLB import needs glTFast.",
                   "dependencies": {"com.unity.cloud.gltfast": "6.0.1"}}
        pk.add(f"{root}/package.json", json.dumps(package, indent=2, sort_keys=True))
        pk.add(f"{root}/package.json.meta", _meta(f"{pkg}/package.json", "PackageManifestImporter"))
        for folder in ("Runtime", "Runtime/Models", "Runtime/Sprites"):
            pk.add(f"{root}/{folder}.meta", _meta(f"{pkg}/{folder}", "DefaultImporter", folder=True))
        put(f"Runtime/Models/{base}.glb", gltf.write_glb(scene), "ScriptedImporter")
        for name, m, ma in world_meshes(scene, "gltf"):     # OBJ stays right-handed: Unity's OBJ importer mirrors X itself
            put(f"Runtime/Models/{_safe(name)}.obj", M.write_obj(m, name=_safe(name)), "ModelImporter",
                {"globalScale": 1, "useFileScale": 1, "importAnimation": 0, "userData": None})
        sprites_meta = []
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            info = png.info(scene.textures[sp.atlas].png)
            rects = []
            for k, (x, y, w, h) in enumerate(sp.frames):
                ux, uy = x, info["height"] - y - h               # Unity sprite rects: bottom-left origin
                rects.append({"name": f"{sid}_{k:02d}", "rect": {"serializedVersion": 2, "x": ux, "y": uy, "width": w, "height": h},
                              "alignment": 9, "pivot": {"x": float(sp.pivot[0]), "y": float(1 - sp.pivot[1])}})
            put(f"Runtime/Sprites/{_safe(sid)}.png", scene.textures[sp.atlas].png, "TextureImporter",
                {"serializedVersion": 12, "textureType": 8, "spriteMode": 2, "spritePixelsToUnits": float(sp.pixels_per_unit),
                 "filterMode": 0, "alphaIsTransparency": 1, "spriteSheet": {"serializedVersion": 2, "sprites": rects}})
            sprites_meta.append({"sprite": sid, "texture": f"Runtime/Sprites/{_safe(sid)}.png", "frames": len(rects),
                                 "animations": sp.animations})
            if "normal" in sp.maps:
                put(f"Runtime/Sprites/{_safe(sid)}_Normal.png", scene.textures[sp.maps["normal"]].png, "TextureImporter",
                    {"serializedVersion": 12, "textureType": 1, "filterMode": 0, "sRGBTexture": 0})
        un = scene.converted("unity")
        wm = un.world_matrices()
        nodes = [{"name": n.name, **decompose(wm[i]), "mesh": n.mesh, "sprite": n.sprite, "layer": n.layer}
                 for i, n in enumerate(un.nodes)]
        put("Runtime/AssetFabricScene.json", json.dumps({"convention": "unity (left-handed, +Y up, metres)", "nodes": nodes,
                                                         "sprites": sprites_meta}, indent=2, sort_keys=True), "TextScriptImporter")
        pk.add(f"{base}.unitypackage", _unitypackage(pkg, assets, metas))
        return pk.finish(self, scene, package=pkg, unitypackage=f"{base}.unitypackage")

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        man = read_manifest(out)
        root = out / "Packages" / man["package"]
        errs: list[str] = []
        guids = []
        meta_ok = True
        for mp in sorted(root.rglob("*.meta")):
            d = yaml.safe_load(mp.read_text())
            g = d.get("guid", "")
            guids.append(g)
            rel = str(mp.relative_to(out / "Packages"))[:-5]
            if d.get("fileFormatVersion") != 2 or not re.fullmatch(r"[0-9a-f]{32}", g) or g != unity_guid(rel):
                meta_ok = False
                errs.append(f"bad meta {mp.name}")
            if not Path(str(mp)[:-5]).exists():
                meta_ok = False
                errs.append(f"meta without asset {mp.name}")
        uniq = len(guids) == len(set(guids))
        rect_ok = True
        for mp in root.glob("Runtime/Sprites/*.png.meta"):
            d = yaml.safe_load(mp.read_text())["TextureImporter"]
            if d.get("textureType") != 8:
                continue
            info = png.info(Path(str(mp)[:-5]).read_bytes())
            for s in d["spriteSheet"]["sprites"]:
                r = s["rect"]
                rect_ok &= 0 <= r["x"] and r["x"] + r["width"] <= info["width"] and 0 <= r["y"] and r["y"] + r["height"] <= info["height"]
        pj = json.loads((root / "package.json").read_text())
        pj_ok = bool(re.fullmatch(r"com\.[a-z0-9]+(\.[a-z0-9]+)+", pj["name"])) and pj["version"] == "1.0.0"
        up_ok, up_n = _check_unitypackage(out / man["unitypackage"])
        if not up_ok:
            errs.append("unitypackage structure")
        obj_ok = all(M.validate(M.read_obj(p.read_bytes()))["triangles"] > 0 for p in root.glob("Runtime/Models/*.obj"))
        glb_ok = all(gltf.validate_glb(p.read_bytes())["ok"] for p in root.glob("Runtime/Models/*.glb"))
        return finish_verify({"meta_guids_deterministic": meta_ok, "guids_unique": uniq, "sprite_rects_bottom_left": rect_ok,
                              "package_json": pj_ok, "unitypackage": up_ok, "obj": obj_ok, "glb": glb_ok}, errs, out,
                             unitypackage_assets=up_n)


def _tar_add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    ti = tarfile.TarInfo(name)
    ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(data), 0, 0o644, 0, 0, "", ""
    tar.addfile(ti, io.BytesIO(data))


def _unitypackage(pkg: str, assets: dict[str, bytes], metas: dict[str, str]) -> bytes:
    """Unity's .unitypackage: gzip'd tar of <guid>/asset, <guid>/asset.meta, <guid>/pathname (deterministic)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for rel in sorted(assets):
            g = unity_guid(f"{pkg}/{rel}")
            _tar_add(tar, f"{g}/asset", assets[rel])
            _tar_add(tar, f"{g}/asset.meta", metas[rel].encode())
            _tar_add(tar, f"{g}/pathname", f"Assets/AssetFabric/{pkg}/{rel}".encode())
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return buf.getvalue()


def _check_unitypackage(p: Path) -> tuple[bool, int]:
    with tarfile.open(p, "r:gz") as tar:
        names = tar.getnames()
        groups: dict[str, set[str]] = {}
        for n in names:
            g, _, leaf = n.partition("/")
            groups.setdefault(g, set()).add(leaf)
        ok = bool(groups) and all(v == {"asset", "asset.meta", "pathname"} and re.fullmatch(r"[0-9a-f]{32}", g) for g, v in groups.items())
        for g in groups:
            meta = yaml.safe_load(tar.extractfile(f"{g}/asset.meta").read())
            ok &= meta["guid"] == g
            ok &= tar.extractfile(f"{g}/pathname").read().decode().startswith("Assets/")
    return ok, len(groups)


# ============================================================================ Blender bridge

BLENDER_SCRIPT = '''# AssetFabric → Blender bridge (bpy). Generated — Copyright (c) 2026 Recharged Ideas.
# Usage: blender --background --python import_assetfabric.py -- [--report report.json]   (or run from Blender's Text Editor)
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = json.load(open(os.path.join(HERE, "assetfabric_blender.json")))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
report_path = argv[argv.index("--report") + 1] if "--report" in argv else None

bpy.ops.wm.read_factory_settings(use_empty=True)
for item in MANIFEST["imports"]:
    path = os.path.join(HERE, item["file"])
    if item["kind"] == "glb":
        bpy.ops.import_scene.gltf(filepath=path)
    elif item["kind"] == "obj":
        bpy.ops.wm.obj_import(filepath=path, forward_axis="NEGATIVE_Z", up_axis="Y")
    elif item["kind"] == "stl":
        bpy.ops.wm.stl_import(filepath=path)
# pixel-art textures: nearest-neighbour sampling; sprite cards: alpha clip
for mat in bpy.data.materials:
    if mat.node_tree is None:
        continue
    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and mat.name in MANIFEST["pixel_art_materials"]:
            node.interpolation = "Closest"
for obj in bpy.data.objects:
    obj["assetfabric_source_digest"] = MANIFEST["source_digest"]
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
report = {
    "ok": True,
    "objects": len(bpy.data.objects),
    "mesh_objects": len(meshes),
    "armatures": len([o for o in bpy.data.objects if o.type == "ARMATURE"]),
    "materials": sorted(m.name for m in bpy.data.materials),
    "images": len(bpy.data.images),
    "polygons": sum(len(o.data.polygons) for o in meshes),
    "tagged": sum(1 for o in bpy.data.objects if o.get("assetfabric_source_digest") == MANIFEST["source_digest"]),
}
if report_path:
    with open(report_path, "w") as fh:
        json.dump(report, fh, sort_keys=True)
print("AF_BLENDER " + json.dumps(report, sort_keys=True))
'''
BLENDER_ALLOWED_IMPORTS = {"bpy", "json", "os", "sys"}


class BlenderAdapter(Adapter):
    id, name, tier, direction = "blender", "Blender bridge", "native_verified", "both"
    dims, convention, formats = ("3d", "2.5d"), "blender", ("glb", "obj", "bpy-script")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        base = _safe(scene.name)
        pk.add(f"{base}.glb", gltf.write_glb(scene))
        imports = [{"file": f"{base}.glb", "kind": "glb"}]
        pixel = sorted(f"sprite:{k}" for k in scene.sprites) + sorted(m.id for m in scene.materials.values()
                                                                      if any(scene.textures[t].filter == "nearest" for t in m.textures.values()))
        expected = {"materials": len(scene.materials) + len(scene.sprites), "mesh_nodes": sum(1 for n in scene.nodes if n.mesh or n.sprite or n.points or n.layer),
                    "armatures": sum(1 for m in scene.meshes.values() if m.skeleton),
                    "triangles": int(sum(m.mesh.n_triangles for m in scene.meshes.values()))}
        pk.add("assetfabric_blender.json", json.dumps({"imports": imports, "pixel_art_materials": pixel,
                                                       "source_digest": scene.digest(), "expected": expected,
                                                       "convention": "Blender: right-handed, +Z up, metres (glTF importer converts)"},
                                                      indent=2, sort_keys=True))
        pk.add("import_assetfabric.py", BLENDER_SCRIPT)
        return pk.finish(self, scene, script="import_assetfabric.py", expected=expected)

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        errs = []
        tree = ast.parse((out / "import_assetfabric.py").read_text())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        imp_ok = mods <= BLENDER_ALLOWED_IMPORTS
        if not imp_ok:
            errs.append(f"script imports outside allow-list: {sorted(mods - BLENDER_ALLOWED_IMPORTS)}")
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        danger = {c for c in calls if c in ("eval", "exec", "os.system", "__import__") or c.startswith("subprocess")}
        if danger:
            errs.append(f"dangerous calls {sorted(danger)}")
        bm = json.loads((out / "assetfabric_blender.json").read_text())
        files_ok = all((out / i["file"]).exists() for i in bm["imports"])
        glb_ok = all(gltf.validate_glb((out / i["file"]).read_bytes())["ok"] for i in bm["imports"] if i["kind"] == "glb")
        return finish_verify({"script_ast_allowlist": imp_ok and not danger, "imports_present": files_ok, "glb": glb_ok}, errs, out)

    def native_check(self, out: Path) -> dict[str, Any]:
        from forge.universal import native
        out = Path(out)
        man = read_manifest(out)
        rep = out.parent / f".{out.name}.blender-report.json"
        r = native.blender_run_bridge(out / man["script"], rep)
        if rep.exists():
            rep.unlink()
        if r.get("ran") and r.get("ok"):
            exp = man["expected"]
            r["materials_match"] = len([m for m in r["materials"] if m != "Material"]) >= exp["materials"]
            r["armatures_match"] = r["armatures"] == exp["armatures"]
            r["all_tagged"] = r["tagged"] == r["objects"]
            r["polygons_ge_triangles"] = r["polygons"] >= exp["triangles"]
            r["ok"] = all((r["materials_match"], r["armatures_match"], r["all_tagged"], r["polygons_ge_triangles"]))
        return r

    def import_(self, path: Path) -> ir.Scene:
        return GltfAdapter().import_(path)

    def sample_input(self, out: Path) -> Path:
        return GltfAdapter().sample_input(out)


# ============================================================================ OpenSCAD bridge

class OpenScadAdapter(Adapter):
    id, name, tier, direction = "openscad", "OpenSCAD bridge", "cli_bridge", "both"
    dims, convention, formats = ("3d",), "zup-rh", ("scad", "stl")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        """Each mesh → STL (OpenSCAD units = metres, Z-up) + an assembly .scad that import()s and places them."""
        pk = Pack(out)
        lines = ["// AssetFabric scene assembly for OpenSCAD — generated. Copyright (c) 2026 Recharged Ideas.",
                 f"// source-digest: {scene.digest()}", "union() {"]
        tris = 0
        for name, m, _ in world_meshes(scene, "zup-rh"):
            m = M.weld(m, 1e-7)                         # UV seams split vertices; CGAL needs the closed solid
            v = M.validate(m)
            if not v["watertight"]:
                lines.append(f"  // skipped {name}: not watertight (OpenSCAD CGAL needs closed solids)")
                continue
            fn = f"{_safe(name)}.stl"
            pk.add(fn, M.write_stl(m, name))
            lines.append(f'  import("{fn}", convexity = 10);')
            tris += m.n_triangles
        lines.append("}")
        pk.add("assembly.scad", "\n".join(lines) + "\n")
        return pk.finish(self, scene, assembly="assembly.scad", triangles=tris)

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        ok = all(M.validate(M.read_stl(p.read_bytes()))["watertight"] for p in out.glob("*.stl"))
        imports = re.findall(r'import\("([^"]+)"', (out / "assembly.scad").read_text())
        refs_ok = all((out / f).exists() for f in imports) and bool(imports)
        return finish_verify({"stl_watertight": ok, "assembly_refs": refs_ok}, [], out)

    def native_check(self, out: Path) -> dict[str, Any]:
        from forge.universal import openscad
        b = openscad.openscad_binary()
        if not b:
            return {"ran": False, "reason": "openscad_not_installed"}
        out = Path(out)
        res = out.parent / f".{out.name}.render.stl"
        p = subprocess.run([b, "-o", str(res), "--export-format", "binstl", str(out / "assembly.scad")],
                           capture_output=True, text=True, timeout=600, cwd=str(out))
        if p.returncode != 0 or not res.exists():
            return {"ran": True, "ok": False, "stderr": p.stderr[-600:]}
        m = M.read_stl(res.read_bytes())
        res.unlink()
        v = M.validate(m)
        return {"ran": True, "ok": v["manifold"] and v["triangles"] > 0, "tool": "openscad", "version": openscad.openscad_version(),
                "triangles": v["triangles"], "volume": v["volume"]}

    def import_(self, path: Path) -> ir.Scene:
        s = ir.Scene(Path(path).stem, "3d", "zup-rh")
        m = M.read_stl(Path(path).read_bytes())
        s.add(ir.MeshAsset("stl", m))
        s.add_node(ir.Node("stl", mesh="stl"))
        return s

    def sample_input(self, out: Path) -> Path:
        p = Path(out) / "sample.stl"
        p.write_bytes(M.write_stl(M.box((0.5, 0.4, 0.3))))
        return p


# ============================================================================ mesh-pack family (OBJ/MTL/PNG + optional .x / STL)

class MeshPackAdapter(Adapter):
    direction, dims = "export", ("3d",)
    write_x, write_stl, fpe = False, False, False

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        xm = []
        listing = []
        for name, m, ma in world_meshes(scene, "gltf"):
            nm = _safe(name)
            mat = scene.materials.get(ma.material) if ma.material else None
            tex = None
            if mat and "base_color" in mat.textures:
                tex = f"{nm}_albedo.png"
                pk.add(tex, scene.textures[mat.textures["base_color"]].png)
            rgba = mat.base_color if mat else (0.8, 0.8, 0.8, 1.0)
            mtl = [f"newmtl {nm}_mat", f"Kd {rgba[0]:.4f} {rgba[1]:.4f} {rgba[2]:.4f}", f"d {rgba[3]:.4f}", "illum 2"]
            if tex:
                mtl.append(f"map_Kd {tex}")
            pk.add(f"{nm}.mtl", "\n".join(mtl) + "\n")
            mo = m.copy()
            if mo.uvs is not None:
                mo.uvs = coords.convert_uv(mo.uvs, "gltf", "opengl-yup")       # OBJ: bottom-left UV origin
            pk.add(f"{nm}.obj", M.write_obj(mo, mtl=f"{nm}.mtl", material=f"{nm}_mat", name=nm))
            if self.write_stl:
                pk.add(f"{nm}.stl", M.write_stl(m, nm))
            xm.append((nm, m, rgba, tex))
            listing.append({"mesh": nm, "obj": f"{nm}.obj", "triangles": m.n_triangles,
                            "x": f"{nm}.x" if self.write_x else None, "texture": tex})
            if self.fpe:
                pk.add(f"{nm}.fpe", "\n".join([";header", f"desc          = {nm}", ";visualinfo", f"model         = {nm}.x",
                                                 f"textured      = {tex or ''}", "scale         = 100", ";orientation",
                                                 "defaultstatic = 1", ""]) + "\n")
        if self.write_x and xm:
            for nm, m, rgba, tex in xm:
                pk.add(f"{nm}.x", write_x([(nm, m, rgba, tex)]))
        return pk.finish(self, scene, meshes=listing, obj_convention="right-handed +Y up metres, UV bottom-left",
                         x_convention="directx-yup (left-handed, clockwise front faces)" if self.write_x else None)

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        man = read_manifest(out)
        errs = []
        obj_ok = x_ok = True
        for it in man["meshes"]:
            m = M.read_obj((out / it["obj"]).read_bytes())
            obj_ok &= m.n_triangles == it["triangles"]
            if it.get("x"):
                xs = read_x((out / it["x"]).read_bytes())
                # mirrored geometry with unchanged index order ⇒ outward faces are clockwise ⇒ signed volume < 0
                x_ok &= len(xs) == 1 and xs[0].n_triangles == it["triangles"] and M.signed_volume(xs[0]) <= 0
        mtl_ok = all("newmtl" in (out / p.name).read_text() for p in out.glob("*.mtl"))
        return finish_verify({"obj_roundtrip": obj_ok, "x_roundtrip_lh_cw": x_ok, "mtl": mtl_ok}, errs, out)


def _mp(id_: str, name: str, conv: str, x: bool = False, stl: bool = False, fpe: bool = False, formats: tuple = ()) -> MeshPackAdapter:
    a = MeshPackAdapter()
    a.id, a.name, a.convention, a.write_x, a.write_stl, a.fpe = id_, name, conv, x, stl, fpe
    a.formats = formats
    return a


MESH_PACKS = [
    _mp("meshpack-gameguru", "GameGuru mesh pack (.x + .fpe + OBJ)", "directx-yup", x=True, fpe=True, formats=("x", "fpe", "obj", "png")),
    _mp("meshpack-coppercube", "CopperCube 6 mesh pack (OBJ/MTL + .x)", "directx-yup", x=True, formats=("obj", "mtl", "x", "png")),
    _mp("meshpack-esenthel", "Esenthel mesh pack (OBJ/MTL)", "gltf", formats=("obj", "mtl", "png")),
    _mp("meshpack-agfpro", "AGFPRO 3 mesh pack (OBJ/MTL)", "gltf", formats=("obj", "mtl", "png")),
    _mp("meshpack-raysupreme", "RaySupreme 3D mesh pack (OBJ + STL)", "gltf", stl=True, formats=("obj", "stl")),
]
