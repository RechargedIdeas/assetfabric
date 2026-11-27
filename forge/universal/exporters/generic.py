# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Catalog-driven generic adapter: serves every Wikipedia-listed engine from its interchange profile
(`registry.profile_for`): GLB + OBJ for 3D (with the engine's documented axis/unit conversion matrix recorded),
PNG atlas + TexturePacker JSON + frames for 2D, plus the isometric layer manifest and GLB cards for 2.5D."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from forge.universal import coords, gltf, ir, png
from forge.universal import mesh as M
from forge.universal.exporters import two_d
from forge.universal.exporters.base import Adapter, Pack, finish_verify, read_manifest
from forge.universal.exporters.three_d import _safe, world_meshes


class CatalogGenericAdapter(Adapter):
    id, name, tier, direction = "catalog-generic", "Catalog generic interchange pack", "interchange_pack", "export"
    dims, convention, formats = ("2d", "2.5d", "3d"), "gltf", ("glb", "obj", "png-atlas", "texturepacker-json", "layer-manifest")

    def __init__(self, entry: dict[str, Any] | None = None) -> None:
        self.entry = entry or {"id": "any", "name": "any engine", "dims": ["2d", "2.5d", "3d"], "convention": "gltf"}
        self.convention = self.entry.get("convention", "gltf")
        if self.entry.get("tier") == "descriptor_only":
            self.tier = "descriptor_only"

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        dims = set(self.entry["dims"])
        parts = []
        if dims & {"3d", "2.5d"}:
            pk.add(f"{_safe(scene.name)}.glb", gltf.write_glb(scene))
            parts.append("glb")
        if "3d" in dims:
            for name, m, _ in world_meshes(scene, "gltf"):
                pk.add(f"obj/{_safe(name)}.obj", M.write_obj(m, name=_safe(name)))
            parts.append("obj")
        if dims & {"2d", "2.5d"}:
            for sid in sorted(scene.sprites):
                sp = scene.sprites[sid]
                pk.add(f"2d/{_safe(sid)}.png", scene.textures[sp.atlas].png)
                pk.add(f"2d/{_safe(sid)}.json", two_d.texturepacker_json(sp, scene, f"{_safe(sid)}.png"))
            parts.append("atlas")
        if "2.5d" in dims and scene.layers:
            pk.add("layers.json", json.dumps({"layers": [scene.layers[k].to_dict() | {"screen_px": list(scene.layers[k].screen_position())}
                                                         for k in sorted(scene.layers)]}, indent=2, sort_keys=True))
            parts.append("layers")
        conv = {"engine": self.entry["name"], "target_convention": self.convention,
                "source": "glTF 2.0 (right-handed, +Y up, metres)",
                "matrix_gltf_to_target": np.round(coords.matrix("gltf", self.convention), 9).tolist(),
                "winding_flip": coords.needs_winding_flip("gltf", self.convention),
                "convention_source": self.entry.get("convention_source", "curated" if self.convention != "gltf" else "inference:U1-1")}
        pk.add("conventions.json", json.dumps(conv, indent=2, sort_keys=True))
        return pk.finish(self, scene, engine=self.entry["id"], parts=parts)

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        man = read_manifest(out)
        glb_ok = all(gltf.validate_glb(p.read_bytes())["ok"] for p in out.glob("*.glb"))
        obj_ok = all(M.read_obj(p.read_bytes()).n_triangles > 0 for p in out.glob("obj/*.obj"))
        tp_ok = all(two_d.check_texturepacker_json(json.loads(p.read_text()), out / "2d") for p in out.glob("2d/*.json"))
        conv = json.loads((out / "conventions.json").read_text())
        m = np.array(conv["matrix_gltf_to_target"])
        conv_ok = bool(np.allclose(m, coords.matrix("gltf", conv["target_convention"]), atol=1e-8))
        return finish_verify({"glb": glb_ok, "obj": obj_ok, "atlas_json": tp_ok, "convention_matrix": conv_ok,
                              "has_parts": bool(man["parts"])}, [], out)
