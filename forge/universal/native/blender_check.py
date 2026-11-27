# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Runs INSIDE Blender (`blender -b --factory-startup -P blender_check.py -- <file> <report.json>`): import the file with
Blender's own importer and write what Blender sees."""
import json
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
ext = src.rsplit(".", 1)[-1].lower()
if ext in ("glb", "gltf"):
    res = bpy.ops.import_scene.gltf(filepath=src)
elif ext == "obj":
    res = bpy.ops.wm.obj_import(filepath=src)
elif ext == "stl":
    res = bpy.ops.wm.stl_import(filepath=src)
else:
    raise SystemExit(f"unsupported {ext}")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
rep = {"ok": "FINISHED" in res, "objects": len(bpy.data.objects), "mesh_objects": len(meshes),
       "armatures": len([o for o in bpy.data.objects if o.type == "ARMATURE"]),
       "materials": sorted(m.name for m in bpy.data.materials), "images": len(bpy.data.images),
       "vertices": sum(len(o.data.vertices) for o in meshes), "polygons": sum(len(o.data.polygons) for o in meshes),
       "per_mesh": sorted([[o.name, len(o.data.vertices), len(o.data.polygons)] for o in meshes])}
with open(out, "w") as f:
    json.dump(rep, f, sort_keys=True)
