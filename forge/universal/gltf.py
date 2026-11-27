# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""glTF 2.0 / GLB writer, reader and structural validator for the Universal IR (no third-party dependencies).

Writer: meshes (POSITION / NORMAL / TEXCOORD_0 / JOINTS_0 / WEIGHTS_0 + uint32 indices), metallic-roughness PBR
materials with embedded PNG textures (base colour, normal, emission, occlusion), skins with inverse bind matrices,
point clouds (mode 0 POINTS), and 2D sprites / 2.5D layers as alpha-masked textured cards. 3D Gaussian splats have no
ratified glTF encoding yet, so they are carried as an `extras` reference (and exported as `.ply` alongside by adapters).

glTF is right-handed, +Y up, metres: the scene is converted to the `gltf` convention before writing.
Output is byte-deterministic (sorted ids, fixed float32 packing, no timestamps)."""

from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np

from forge.universal import ir, png
from forge.universal.mesh import TriMesh

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
COMPONENT = {5120: (np.int8, 1), 5121: (np.uint8, 1), 5122: (np.int16, 2), 5123: (np.uint16, 2),
             5125: (np.uint32, 4), 5126: (np.float32, 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
GENERATOR = "AssetFabric Universal Engine U1"


class _Builder:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.doc: dict[str, Any] = {"asset": {"version": "2.0", "generator": GENERATOR}, "buffers": [],
                                    "bufferViews": [], "accessors": []}

    def view(self, data: bytes, target: int | None = None, stride: int | None = None) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        bv: dict[str, Any] = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            bv["target"] = target
        if stride:
            bv["byteStride"] = stride
        self.bin += data
        self.doc["bufferViews"].append(bv)
        return len(self.doc["bufferViews"]) - 1

    def accessor(self, arr: np.ndarray, ctype: int, typ: str, target: int | None = None, minmax: bool = False) -> int:
        dt = COMPONENT[ctype][0]
        a = np.ascontiguousarray(arr, dtype=np.dtype(dt).newbyteorder("<"))
        bv = self.view(a.tobytes(), target)
        acc: dict[str, Any] = {"bufferView": bv, "componentType": ctype, "count": int(a.shape[0]), "type": typ}
        if minmax:
            flat = a.reshape(a.shape[0], -1)
            acc["min"] = [float(x) for x in flat.min(0)]
            acc["max"] = [float(x) for x in flat.max(0)]
        self.doc["accessors"].append(acc)
        return len(self.doc["accessors"]) - 1

    def add(self, key: str, obj: dict[str, Any]) -> int:
        self.doc.setdefault(key, []).append(obj)
        return len(self.doc[key]) - 1

    def glb(self) -> bytes:
        while len(self.bin) % 4:
            self.bin.append(0)
        self.doc["buffers"] = [{"byteLength": len(self.bin)}] if self.bin else []
        for k in [k for k, v in self.doc.items() if isinstance(v, list) and not v]:
            del self.doc[k]
        js = json.dumps(self.doc, sort_keys=True, separators=(",", ":")).encode()
        js += b" " * ((4 - len(js) % 4) % 4)
        body = struct.pack("<II", len(js), CHUNK_JSON) + js
        if self.bin:
            body += struct.pack("<II", len(self.bin), CHUNK_BIN) + bytes(self.bin)
        return struct.pack("<III", GLB_MAGIC, 2, 12 + len(body)) + body


def _card(w: float, h: float, pivot: tuple[float, float], uv: tuple[float, float, float, float]) -> TriMesh:
    """A camera-facing quad in the XY plane (front faces +Z), pivot normalised top-left origin."""
    x0, y1 = -pivot[0] * w, pivot[1] * h
    x1, y0 = x0 + w, y1 - h
    u0, v0, u1, v1 = uv
    p = np.array([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0]], float)
    t = np.array([[u0, v1], [u1, v1], [u1, v0], [u0, v0]], float)
    n = np.tile([0.0, 0.0, 1.0], (4, 1))
    return TriMesh(p, np.array([[0, 1, 2], [0, 2, 3]]), n, t)


def write_glb(scene: ir.Scene) -> bytes:
    s = scene.converted("gltf")
    b = _Builder()
    tex_index: dict[str, int] = {}
    samplers = {"nearest": b.add("samplers", {"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}),
                "linear": b.add("samplers", {"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497})}

    def texture(tid: str) -> int:
        if tid not in tex_index:
            t = s.textures[tid]
            img = b.add("images", {"bufferView": b.view(t.png), "mimeType": "image/png", "name": tid})
            tex_index[tid] = b.add("textures", {"source": img, "sampler": samplers.get(t.filter, 0), "name": tid})
        return tex_index[tid]

    mat_index: dict[str, int] = {}
    for mid in sorted(s.materials):
        m = s.materials[mid]
        pbr: dict[str, Any] = {"baseColorFactor": list(m.base_color), "metallicFactor": m.metallic,
                               "roughnessFactor": m.roughness}
        md: dict[str, Any] = {"name": mid, "pbrMetallicRoughness": pbr, "alphaMode": m.alpha_mode,
                              "doubleSided": m.double_sided}
        if m.alpha_mode == "MASK":
            md["alphaCutoff"] = m.alpha_cutoff
        if any(m.emissive):
            md["emissiveFactor"] = list(m.emissive)
        tx = m.textures
        if "base_color" in tx:
            pbr["baseColorTexture"] = {"index": texture(tx["base_color"])}
        if "orm" in tx:
            pbr["metallicRoughnessTexture"] = {"index": texture(tx["orm"])}
        if "normal" in tx:
            md["normalTexture"] = {"index": texture(tx["normal"])}
        if "ao" in tx:
            md["occlusionTexture"] = {"index": texture(tx["ao"])}
        if "emission" in tx:
            md["emissiveTexture"] = {"index": texture(tx["emission"])}
            md.setdefault("emissiveFactor", [1.0, 1.0, 1.0])
        mat_index[mid] = b.add("materials", md)

    def prim(tm: TriMesh, material: str | None, ma: ir.MeshAsset | None = None) -> dict[str, Any]:
        attrs = {"POSITION": b.accessor(tm.positions.astype(np.float32), 5126, "VEC3", 34962, minmax=True)}
        nrm = tm.normals if tm.normals is not None else tm.vertex_normals()
        attrs["NORMAL"] = b.accessor(nrm.astype(np.float32), 5126, "VEC3", 34962)
        if tm.uvs is not None:
            attrs["TEXCOORD_0"] = b.accessor(tm.uvs.astype(np.float32), 5126, "VEC2", 34962)
        if ma is not None and ma.joints is not None:
            attrs["JOINTS_0"] = b.accessor(ma.joints.astype(np.uint16), 5123, "VEC4", 34962)
            attrs["WEIGHTS_0"] = b.accessor(ma.weights.astype(np.float32), 5126, "VEC4", 34962)
        p: dict[str, Any] = {"attributes": attrs, "mode": 4,
                             "indices": b.accessor(tm.faces.reshape(-1).astype(np.uint32), 5125, "SCALAR", 34963)}
        if material is not None:
            p["material"] = mat_index[material]
        return p

    mesh_index: dict[str, int] = {}
    for mid in sorted(s.meshes):
        ma = s.meshes[mid]
        mesh_index[mid] = b.add("meshes", {"name": mid, "primitives": [prim(ma.mesh, ma.material, ma)]})
    for pid in sorted(s.point_clouds):
        pc = s.point_clouds[pid]
        attrs = {"POSITION": b.accessor(pc.positions.astype(np.float32), 5126, "VEC3", 34962, minmax=True)}
        if pc.colors is not None:
            attrs["COLOR_0"] = b.accessor(pc.colors.astype(np.float32) / 255.0, 5126, "VEC3", 34962)
        mesh_index["points:" + pid] = b.add("meshes", {"name": pid, "primitives": [{"attributes": attrs, "mode": 0}]})
    for sid in sorted(s.sprites):                         # 2D sprite → alpha-masked card (first frame), metres via PPU
        sp = s.sprites[sid]
        info = png.info(s.textures[sp.atlas].png)
        x, y, w, h = sp.frames[0]
        uv = (x / info["width"], y / info["height"], (x + w) / info["width"], (y + h) / info["height"])
        card = _card(w / sp.pixels_per_unit, h / sp.pixels_per_unit, sp.pivot, uv)
        md: dict[str, Any] = {"name": "sprite:" + sid, "alphaMode": "MASK", "alphaCutoff": 0.5, "doubleSided": True,
                              "pbrMetallicRoughness": {"baseColorTexture": {"index": texture(sp.atlas)},
                                                       "metallicFactor": 0.0, "roughnessFactor": 1.0}}
        if "normal" in sp.maps:
            md["normalTexture"] = {"index": texture(sp.maps["normal"])}
        if "emission" in sp.maps:
            md["emissiveTexture"] = {"index": texture(sp.maps["emission"])}
            md["emissiveFactor"] = [1.0, 1.0, 1.0]
        mi = b.add("materials", md)
        p = prim(card, None)
        p["material"] = mi
        mesh_index["sprite:" + sid] = b.add("meshes", {"name": "sprite:" + sid, "primitives": [p]})

    skin_of: dict[str, int] = {}
    node_ids: list[int] = []
    cam_index: dict[str, int] = {}
    for cid in sorted(s.cameras):
        c = s.cameras[cid]
        cam_index[cid] = b.add("cameras", {"name": cid, "type": "perspective", "perspective": {
            "yfov": float(2 * np.arctan(c.height / (2 * c.fy))), "aspectRatio": float(c.width / c.height), "znear": 0.01}})
    for i, n in enumerate(s.nodes):
        nd: dict[str, Any] = {"name": n.name}
        mat = np.asarray(n.matrix, float)
        if n.camera:
            mat = mat @ np.asarray(s.cameras[n.camera].pose, float)   # IR camera pose is world; parent assumed identity
            nd["camera"] = cam_index[n.camera]
        if not np.allclose(mat, np.eye(4)):
            nd["matrix"] = [float(x) for x in mat.T.reshape(-1)]       # glTF matrices are column-major
        ref = (n.mesh if n.mesh else ("points:" + n.points if n.points else None))
        if n.sprite:
            ref = "sprite:" + n.sprite
        if n.layer:
            ly = s.layers[n.layer]
            ref = "sprite:" + ly.sprite
            nd.setdefault("extras", {})["layer"] = ly.to_dict()
        if ref:
            nd["mesh"] = mesh_index[ref]
        if n.splats:
            nd.setdefault("extras", {})["gaussian_splats"] = {"id": n.splats, "format": "3dgs-ply",
                                                             "note": "no ratified glTF splat encoding; see sidecar .ply"}
        if n.children:
            nd["children"] = list(n.children)
        node_ids.append(b.add("nodes", nd))
    # skins: joints become extra nodes appended after scene nodes
    for i, n in enumerate(s.nodes):
        if n.mesh and s.meshes[n.mesh].skeleton:
            sk = s.skeletons[s.meshes[n.mesh].skeleton]
            if sk.id not in skin_of:
                base = len(b.doc["nodes"])
                for j, name in enumerate(sk.joint_names):
                    jd: dict[str, Any] = {"name": name, "matrix": [float(x) for x in sk.rest_local[j].T.reshape(-1)]}
                    kids = [base + c for c, p in enumerate(sk.parents) if p == j]
                    if kids:
                        jd["children"] = kids
                    b.add("nodes", jd)
                ibm = b.accessor(sk.inverse_bind.transpose(0, 2, 1).reshape(len(sk.joint_names), 16).astype(np.float32),
                                 5126, "MAT4")
                skin_of[sk.id] = b.add("skins", {"name": sk.id, "joints": [base + j for j in range(len(sk.joint_names))],
                                                 "inverseBindMatrices": ibm, "skeleton": base})
                for j, p in enumerate(sk.parents):
                    if p < 0:
                        s.roots.append(base + j)  # joint roots live at scene level
            b.doc["nodes"][i]["skin"] = skin_of[sk.id]
    roots = list(s.roots)
    b.doc["scenes"] = [{"name": s.name, "nodes": roots}]
    b.doc["scene"] = 0
    b.doc["asset"]["extras"] = {"assetfabric_ir": {"dimension": s.dimension, "digest": scene.digest(),
                                                   "source_convention": scene.convention}}
    return b.glb()


# ----------------------------------------------------------------------------- reader / validator

def parse_glb(data: bytes) -> tuple[dict[str, Any], bytes]:
    if len(data) < 20:
        raise ValueError("too short for GLB")
    magic, version, length = struct.unpack("<III", data[:12])
    if magic != GLB_MAGIC:
        raise ValueError("bad GLB magic")
    if version != 2:
        raise ValueError(f"GLB version {version} != 2")
    if length != len(data):
        raise ValueError(f"GLB length header {length} != file size {len(data)}")
    clen, ctype = struct.unpack("<II", data[12:20])
    if ctype != CHUNK_JSON or clen % 4:
        raise ValueError("first chunk must be 4-byte aligned JSON")
    doc = json.loads(data[20:20 + clen].decode("utf-8"))
    pos, binc = 20 + clen, b""
    if pos < len(data):
        blen, btype = struct.unpack("<II", data[pos:pos + 8])
        if btype != CHUNK_BIN or blen % 4:
            raise ValueError("second chunk must be 4-byte aligned BIN")
        binc = data[pos + 8:pos + 8 + blen]
        if len(binc) != blen:
            raise ValueError("truncated BIN chunk")
    return doc, binc


def read_accessor(doc: dict[str, Any], binc: bytes, i: int) -> np.ndarray:
    acc = doc["accessors"][i]
    bv = doc["bufferViews"][acc["bufferView"]]
    dt, size = COMPONENT[acc["componentType"]]
    nc = NCOMP[acc["type"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride", size * nc)
    if stride == size * nc:
        a = np.frombuffer(binc, dtype=np.dtype(dt).newbyteorder("<"), count=acc["count"] * nc, offset=off)
        return a.reshape(acc["count"], nc) if nc > 1 else a.copy()
    rows = [np.frombuffer(binc, dtype=np.dtype(dt).newbyteorder("<"), count=nc, offset=off + k * stride)
            for k in range(acc["count"])]
    return np.stack(rows)


def validate_glb(data: bytes) -> dict[str, Any]:
    """Structural + semantic checks (spec §5 + common validator rules). Returns {ok, errors, stats}."""
    errs: list[str] = []
    try:
        doc, binc = parse_glb(data)
    except (ValueError, json.JSONDecodeError, struct.error) as e:
        return {"ok": False, "errors": [str(e)], "stats": {}}
    if doc.get("asset", {}).get("version") != "2.0":
        errs.append("asset.version must be '2.0'")
    bufs = doc.get("buffers", [])
    if bufs and bufs[0].get("byteLength", 0) > len(binc):
        errs.append("buffer 0 byteLength exceeds BIN chunk")
    for k, bv in enumerate(doc.get("bufferViews", [])):
        if bv.get("byteOffset", 0) + bv["byteLength"] > (bufs[bv["buffer"]]["byteLength"] if bufs else 0):
            errs.append(f"bufferView {k} out of buffer range")
    accs = doc.get("accessors", [])
    for k, acc in enumerate(accs):
        if acc.get("componentType") not in COMPONENT or acc.get("type") not in NCOMP:
            errs.append(f"accessor {k}: bad componentType/type")
            continue
        bv = doc["bufferViews"][acc["bufferView"]]
        size = COMPONENT[acc["componentType"]][1] * NCOMP[acc["type"]]
        if (bv.get("byteOffset", 0) + acc.get("byteOffset", 0)) % COMPONENT[acc["componentType"]][1]:
            errs.append(f"accessor {k}: misaligned")
        if acc.get("byteOffset", 0) + size * acc["count"] > bv["byteLength"]:
            errs.append(f"accessor {k}: exceeds bufferView")
    stats = {"meshes": len(doc.get("meshes", [])), "nodes": len(doc.get("nodes", [])),
             "materials": len(doc.get("materials", [])), "textures": len(doc.get("textures", [])),
             "skins": len(doc.get("skins", [])), "triangles": 0, "points": 0, "bytes": len(data)}
    if errs:
        return {"ok": False, "errors": errs, "stats": stats}
    for mi, m in enumerate(doc.get("meshes", [])):
        for pi, p in enumerate(m["primitives"]):
            at = p.get("attributes", {})
            if "POSITION" not in at:
                errs.append(f"mesh {mi}/{pi}: no POSITION")
                continue
            pos = read_accessor(doc, binc, at["POSITION"])
            acc = accs[at["POSITION"]]
            if "min" not in acc or "max" not in acc:
                errs.append(f"mesh {mi}/{pi}: POSITION min/max required")
            elif not (np.allclose(pos.min(0), acc["min"], atol=1e-6) and np.allclose(pos.max(0), acc["max"], atol=1e-6)):
                errs.append(f"mesh {mi}/{pi}: POSITION min/max mismatch")
            if not np.isfinite(pos).all():
                errs.append(f"mesh {mi}/{pi}: non-finite positions")
            for name, a in at.items():
                if accs[a]["count"] != acc["count"]:
                    errs.append(f"mesh {mi}/{pi}: {name} count != POSITION count")
            if "NORMAL" in at:
                nn = np.linalg.norm(read_accessor(doc, binc, at["NORMAL"]), axis=1)
                if not np.allclose(nn, 1.0, atol=1e-3):
                    errs.append(f"mesh {mi}/{pi}: NORMAL not unit length")
            if "WEIGHTS_0" in at and not np.allclose(read_accessor(doc, binc, at["WEIGHTS_0"]).sum(1), 1, atol=1e-3):
                errs.append(f"mesh {mi}/{pi}: WEIGHTS_0 rows must sum to 1")
            mode = p.get("mode", 4)
            if "indices" in p:
                idx = read_accessor(doc, binc, p["indices"])
                if idx.size and int(idx.max()) >= acc["count"]:
                    errs.append(f"mesh {mi}/{pi}: index out of range")
                if mode == 4:
                    if idx.size % 3:
                        errs.append(f"mesh {mi}/{pi}: index count not a multiple of 3")
                    stats["triangles"] += idx.size // 3
            elif mode == 0:
                stats["points"] += acc["count"]
            if "material" in p and p["material"] >= len(doc.get("materials", [])):
                errs.append(f"mesh {mi}/{pi}: material index out of range")
    ntex = len(doc.get("textures", []))
    for mi, m in enumerate(doc.get("materials", [])):
        refs = [m.get(k, {}).get("index") for k in ("normalTexture", "occlusionTexture", "emissiveTexture")]
        pbr = m.get("pbrMetallicRoughness", {})
        refs += [pbr.get(k, {}).get("index") for k in ("baseColorTexture", "metallicRoughnessTexture")]
        if any(r is not None and r >= ntex for r in refs):
            errs.append(f"material {mi}: texture index out of range")
    for ii, im in enumerate(doc.get("images", [])):
        bv = doc["bufferViews"][im["bufferView"]]
        blob = binc[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        try:
            png.decode(blob)
        except ValueError as e:
            errs.append(f"image {ii}: {e}")
    nodes = doc.get("nodes", [])
    parent: dict[int, int] = {}
    for ni, n in enumerate(nodes):
        for c in n.get("children", []):
            if c in parent or c >= len(nodes) or c == ni:
                errs.append(f"node {c}: invalid/duplicate parent")
            parent[c] = ni
        if "mesh" in n and n["mesh"] >= len(doc.get("meshes", [])):
            errs.append(f"node {ni}: mesh index out of range")
        if "matrix" in n and len(n["matrix"]) != 16:
            errs.append(f"node {ni}: matrix must have 16 numbers")
    for sc in doc.get("scenes", []):
        for r in sc.get("nodes", []):
            if r in parent:
                errs.append(f"scene root {r} has a parent")
    for si, sk in enumerate(doc.get("skins", [])):
        if any(j >= len(nodes) for j in sk["joints"]):
            errs.append(f"skin {si}: joint out of range")
        if "inverseBindMatrices" in sk and accs[sk["inverseBindMatrices"]]["count"] != len(sk["joints"]):
            errs.append(f"skin {si}: inverseBindMatrices count != joints")
    return {"ok": not errs, "errors": errs, "stats": stats}


def read_meshes(data: bytes) -> list[dict[str, Any]]:
    """Return [{name, positions, indices}] for triangle primitives (used for round-trip proofs)."""
    doc, binc = parse_glb(data)
    out = []
    for m in doc.get("meshes", []):
        for p in m["primitives"]:
            if p.get("mode", 4) != 4 or "indices" not in p:
                continue
            out.append({"name": m.get("name"), "positions": read_accessor(doc, binc, p["attributes"]["POSITION"]),
                        "indices": read_accessor(doc, binc, p["indices"]).reshape(-1, 3)})
    return out
