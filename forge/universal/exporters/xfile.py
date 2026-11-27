# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""DirectX `.x` (text, xof 0303txt 0032) mesh writer + reader — read by GameGuru, AppGameKit, CopperCube and other
DirectX-lineage tools. Geometry is converted to left-handed Y-up (`directx-yup`); because the mirror also mirrors the
on-screen winding, original index order becomes clockwise-front as Direct3D expects (no index reversal)."""

from __future__ import annotations

import re

import numpy as np

from forge.universal import coords
from forge.universal.mesh import TriMesh


def _f(x: float) -> str:
    return f"{x:.6f}"


def write_x(meshes: list[tuple[str, TriMesh, tuple[float, float, float, float], str | None]], src_convention: str = "gltf") -> bytes:
    """meshes: (name, mesh, rgba base colour, texture file name or None)."""
    m3 = coords.matrix(src_convention, "directx-yup")
    lines = ["xof 0303txt 0032", "", "Frame AF_Root {", " FrameTransformMatrix {",
             "  1.000000,0.000000,0.000000,0.000000,0.000000,1.000000,0.000000,0.000000,"
             "0.000000,0.000000,1.000000,0.000000,0.000000,0.000000,0.000000,1.000000;;", " }"]
    for name, m, rgba, tex in meshes:
        safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
        p = m.positions @ m3.T
        n = coords.convert_directions(m.normals if m.normals is not None else m.vertex_normals(), src_convention, "directx-yup")
        lines.append(f" Mesh {safe} {{")
        lines.append(f"  {len(p)};")
        lines += [f"  {_f(a)};{_f(b)};{_f(c)};" + ("," if i < len(p) - 1 else ";") for i, (a, b, c) in enumerate(p)]
        lines.append(f"  {len(m.faces)};")
        lines += [f"  3;{a},{b},{c};" + ("," if i < len(m.faces) - 1 else ";") for i, (a, b, c) in enumerate(m.faces.tolist())]
        lines += ["  MeshNormals {", f"   {len(n)};"]
        lines += [f"   {_f(a)};{_f(b)};{_f(c)};" + ("," if i < len(n) - 1 else ";") for i, (a, b, c) in enumerate(n)]
        lines.append(f"   {len(m.faces)};")
        lines += [f"   3;{a},{b},{c};" + ("," if i < len(m.faces) - 1 else ";") for i, (a, b, c) in enumerate(m.faces.tolist())]
        lines.append("  }")
        if m.uvs is not None:
            uv = coords.convert_uv(m.uvs, src_convention, "directx-yup")
            lines += ["  MeshTextureCoords {", f"   {len(uv)};"]
            lines += [f"   {_f(u)};{_f(v)};" + ("," if i < len(uv) - 1 else ";") for i, (u, v) in enumerate(uv)]
            lines.append("  }")
        lines += ["  MeshMaterialList {", "   1;", f"   {len(m.faces)};"]
        lines += ["   " + ",".join("0" for _ in range(len(m.faces))) + ";"]
        lines += [f"   Material {safe}_mat {{", f"    {_f(rgba[0])};{_f(rgba[1])};{_f(rgba[2])};{_f(rgba[3])};;",
                  "    20.000000;", "    0.000000;0.000000;0.000000;;", "    0.000000;0.000000;0.000000;;"]
        if tex:
            lines.append(f'    TextureFilename {{ "{tex}"; }}')
        lines += ["   }", "  }", " }"]
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("ascii")


def read_x(data: bytes) -> list[TriMesh]:
    """Parse the Mesh blocks (positions + triangle faces) of a text .x file — used to verify our own output."""
    text = data.decode("ascii")
    if not text.startswith("xof 0303txt"):
        raise ValueError("not a text .x file")
    out = []
    for m in re.finditer(r"\n Mesh (\w+) \{\n(.*?)\n  MeshNormals", text, re.S):
        body = m.group(2).split("\n")
        nv = int(body[0].strip().rstrip(";"))
        verts = [[float(x) for x in ln.strip().rstrip(",;").split(";") if x] for ln in body[1:1 + nv]]
        nf = int(body[1 + nv].strip().rstrip(";"))
        faces = []
        for ln in body[2 + nv:2 + nv + nf]:
            cnt, idx = ln.strip().rstrip(",;").split(";", 1)
            faces.append([int(i) for i in idx.rstrip(";").split(",")])
        out.append(TriMesh(np.array(verts, float), np.array(faces, int), meta={"name": m.group(1)}))
    return out
