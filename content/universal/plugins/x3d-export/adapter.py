# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""X3D exporter plugin: example of the U1 plugin contract (static policy + sandboxed determinism/verify suite)."""

import json
import xml.etree.ElementTree as ET

import numpy as np

from forge.universal.exporters.base import Adapter, Pack, finish_verify
from forge.universal.exporters.three_d import world_meshes


def _fmt(a):
    return " ".join(f"{v:.6g}" for v in np.asarray(a, dtype=np.float64).ravel())


class X3DAdapter(Adapter):
    id = "x3d-export"
    name = "X3D (ISO/IEC 19776-1 XML encoding) exporter"
    tier = "interchange_pack"
    direction = "export"
    dims = ("3d",)
    convention = "gltf"
    formats = ("x3d",)
    version = "1.0.0"

    def export(self, scene, out):
        pack = Pack(out)
        root = ET.Element("X3D", {"profile": "Interchange", "version": "3.3"})
        head = ET.SubElement(root, "head")
        ET.SubElement(head, "meta", {"name": "generator", "content": "AssetFabric x3d-export plugin 1.0.0"})
        sc = ET.SubElement(root, "Scene")
        stats = {}
        for name, m, ma in world_meshes(scene, self.convention):
            shape = ET.SubElement(sc, "Shape", {"DEF": name})
            app = ET.SubElement(shape, "Appearance")
            mat = scene.materials.get(ma.material) if ma.material else None
            col = mat.base_color[:3] if mat else (0.8, 0.8, 0.8)
            ET.SubElement(app, "Material", {"diffuseColor": _fmt(col)})
            its = ET.SubElement(shape, "IndexedTriangleSet", {"index": " ".join(str(int(i)) for i in m.faces.ravel()),
                                                                "solid": "true", "ccw": "true"})
            ET.SubElement(its, "Coordinate", {"point": _fmt(m.positions)})
            stats[name] = {"triangles": int(len(m.faces)), "vertices": int(len(m.positions))}
        ET.indent(root)
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
        pack.add("scene.x3d", xml)
        pack.add("x3d_stats.json", json.dumps(stats, indent=2, sort_keys=True) + "\n")
        return pack.finish(self, scene, shapes=len(stats))

    def verify(self, out):
        errs = []
        doc = ET.fromstring((out / "scene.x3d").read_bytes())
        stats = json.loads((out / "x3d_stats.json").read_text())
        shapes = {s.get("DEF"): s for s in doc.iter("Shape")}
        for name, st in stats.items():
            s = shapes.get(name)
            if s is None:
                errs.append(f"shape {name} missing")
                continue
            its = s.find("IndexedTriangleSet")
            idx = [int(v) for v in its.get("index").split()]
            pts = its.find("Coordinate").get("point").split()
            if len(idx) != 3 * st["triangles"] or len(pts) != 3 * st["vertices"]:
                errs.append(f"{name}: counts differ")
            if idx and max(idx) >= st["vertices"]:
                errs.append(f"{name}: index out of range")
        checks = {"xml_parses": doc.tag == "X3D", "shapes_match": len(shapes) == len(stats) and not errs}
        return finish_verify(checks, errs, out, shapes=len(shapes))
