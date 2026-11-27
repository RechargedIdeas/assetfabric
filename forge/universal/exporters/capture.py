# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Photogrammetry & 3D Gaussian Splatting adapters: COLMAP text model (cameras/images/points3D), nerfstudio
transforms.json, INRIA 3DGS .ply, and OBJ/PLY ingestion for Meshroom / RealityCapture / OpenMVS / Fuse outputs."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from forge.universal import ir
from forge.universal import mesh as M
from forge.universal.exporters.base import Adapter, Pack, finish_verify, read_manifest
from forge.universal.exporters.three_d import _quat, _safe

GL_TO_CV = np.diag([1.0, -1.0, -1.0, 1.0])     # OpenGL camera frame (−Z view, +Y up) → OpenCV (+Z view, +Y down)


def _rotmat_from_quat(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    return np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                     [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                     [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])


def colmap_text(scene: ir.Scene) -> dict[str, str]:
    s = scene.converted("opengl-yup") if scene.convention != "opengl-yup" else scene
    cams, imgs = ["# Camera list: CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]"], ["# Image list: IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME", "#   POINTS2D[] as (X, Y, POINT3D_ID)"]
    for k, cid in enumerate(sorted(s.cameras), start=1):
        c = s.cameras[cid]
        cams.append(f"{k} PINHOLE {c.width} {c.height} {c.fx:.6f} {c.fy:.6f} {c.cx:.6f} {c.cy:.6f}")
        c2w = np.asarray(c.pose, float) @ GL_TO_CV
        w2c = np.linalg.inv(c2w)
        x, y, z, w = _quat(w2c[:3, :3])
        t = w2c[:3, 3]
        imgs.append(f"{k} {w:.9f} {x:.9f} {y:.9f} {z:.9f} {t[0]:.9f} {t[1]:.9f} {t[2]:.9f} {k} {cid}.png")
        imgs.append("")
    pts = ["# 3D point list: POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)"]
    pid = 1
    for pcid in sorted(s.point_clouds):
        pc = s.point_clouds[pcid]
        col = pc.colors if pc.colors is not None else np.full((len(pc.positions), 3), 200, np.uint8)
        for p, c in zip(pc.positions.astype(float), col):
            pts.append(f"{pid} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {int(c[0])} {int(c[1])} {int(c[2])} 0")
            pid += 1
    return {"cameras.txt": "\n".join(cams) + "\n", "images.txt": "\n".join(imgs) + "\n", "points3D.txt": "\n".join(pts) + "\n"}


def read_colmap_text(folder: Path) -> dict[str, Any]:
    cams = {}
    for ln in (folder / "cameras.txt").read_text().splitlines():
        if ln and not ln.startswith("#"):
            t = ln.split()
            cams[int(t[0])] = {"model": t[1], "w": int(t[2]), "h": int(t[3]), "params": [float(x) for x in t[4:]]}
    centers = {}
    lines = [ln for ln in (folder / "images.txt").read_text().splitlines() if not ln.startswith("#")]
    for i in range(0, len(lines), 2):
        if not lines[i].strip():
            continue
        t = lines[i].split()
        r = _rotmat_from_quat(*map(float, t[1:5]))
        tv = np.array([float(x) for x in t[5:8]])
        centers[t[9].rsplit(".", 1)[0]] = (-r.T @ tv)
    pts = [ln.split() for ln in (folder / "points3D.txt").read_text().splitlines() if ln and not ln.startswith("#")]
    return {"cameras": cams, "centers": centers, "points": np.array([[float(x) for x in p[1:4]] for p in pts]) if pts else np.zeros((0, 3))}


def nerfstudio_transforms(scene: ir.Scene) -> str:
    s = scene.converted("opengl-yup") if scene.convention != "opengl-yup" else scene
    frames = []
    for cid in sorted(s.cameras):
        c = s.cameras[cid]
        frames.append({"file_path": f"images/{cid}.png", "fl_x": c.fx, "fl_y": c.fy, "cx": c.cx, "cy": c.cy, "w": c.width, "h": c.height,
                       "transform_matrix": [[round(float(v), 9) for v in row] for row in np.asarray(c.pose, float)]})
    return json.dumps({"camera_model": "OPENCV", "frames": frames, "ply_file_path": "sparse_pc.ply" if s.point_clouds else None,
                       "note": "transform_matrix = camera-to-world, OpenGL camera frame (nerfstudio convention); images come from the capture"},
                      indent=2, sort_keys=True)


def write_ply_points(p: np.ndarray, c: np.ndarray | None) -> bytes:
    n = len(p)
    hdr = ["ply", "format binary_little_endian 1.0", f"element vertex {n}", "property float x", "property float y", "property float z"]
    if c is not None:
        hdr += ["property uchar red", "property uchar green", "property uchar blue"]
    hdr.append("end_header")
    dt = [("p", "<f4", 3)] + ([("c", "u1", 3)] if c is not None else [])
    rec = np.zeros(n, dtype=dt)
    rec["p"] = p
    if c is not None:
        rec["c"] = c
    return ("\n".join(hdr) + "\n").encode() + rec.tobytes()


def write_ply_mesh(m: M.TriMesh) -> bytes:
    hdr = ["ply", "format binary_little_endian 1.0", f"element vertex {m.n_vertices}", "property float x", "property float y",
           "property float z", f"element face {m.n_triangles}", "property list uchar int vertex_indices", "end_header"]
    v = m.positions.astype("<f4").tobytes()
    f = b"".join(struct.pack("<B3i", 3, *map(int, t)) for t in m.faces)
    return ("\n".join(hdr) + "\n").encode() + v + f


def read_ply_mesh(data: bytes) -> M.TriMesh:
    """PLY (ascii or binary little-endian) with float x/y/z vertices and an optional face list → TriMesh."""
    end = data.index(b"end_header") + len(b"end_header")
    end += 2 if data[end:end + 2] == b"\r\n" else 1
    header = data[:end].decode("ascii").splitlines()
    fmt = next(l.split()[1] for l in header if l.startswith("format"))
    elems: list[tuple[str, int, list[tuple[str, str]]]] = []
    for l in header:
        t = l.split()
        if t and t[0] == "element":
            elems.append((t[1], int(t[2]), []))
        elif t and t[0] == "property":
            elems[-1][2].append((t[-1], " ".join(t[1:-1])))
    if fmt == "ascii":
        rows = data[end:].decode("ascii").split("\n")
        pos, faces, i = [], [], 0
        for name, cnt, props in elems:
            for _ in range(cnt):
                vals = rows[i].split()
                i += 1
                if name == "vertex":
                    names = [p[0] for p in props]
                    pos.append([float(vals[names.index(a)]) for a in ("x", "y", "z")])
                elif name == "face":
                    k = int(vals[0])
                    idx = [int(x) for x in vals[1:1 + k]]
                    faces += [[idx[0], idx[j], idx[j + 1]] for j in range(1, k - 1)]
        return M.TriMesh(np.array(pos), np.array(faces, int).reshape(-1, 3))
    if fmt != "binary_little_endian":
        raise ValueError(f"PLY format {fmt} not supported")
    tmap = {"float": "<f4", "float32": "<f4", "double": "<f8", "uchar": "u1", "uint8": "u1", "char": "i1", "int": "<i4",
            "int32": "<i4", "uint": "<u4", "short": "<i2", "ushort": "<u2"}
    off = end
    pos = np.zeros((0, 3))
    faces: list[list[int]] = []
    for name, cnt, props in elems:
        if all(not t.startswith("list") for _, t in props):
            dt = np.dtype([(pn, tmap[t]) for pn, t in props])
            rec = np.frombuffer(data, dtype=dt, count=cnt, offset=off)
            off += dt.itemsize * cnt
            if name == "vertex":
                pos = np.stack([rec["x"], rec["y"], rec["z"]], 1).astype(np.float64)
        else:
            _, lt = props[0]
            _, ct, it = lt.split()
            cd, idt = np.dtype(tmap[ct]), np.dtype(tmap[it])
            for _ in range(cnt):
                k = int(np.frombuffer(data, cd, 1, off)[0])
                off += cd.itemsize
                idx = np.frombuffer(data, idt, k, off).astype(int).tolist()
                off += idt.itemsize * k
                faces += [[idx[0], idx[j], idx[j + 1]] for j in range(1, k - 1)]
    return M.TriMesh(pos, np.array(faces, int).reshape(-1, 3))


class ColmapAdapter(Adapter):
    id, name, tier, direction = "colmap", "COLMAP / OpenMVS text model", "interchange_pack", "both"
    dims, convention, formats = ("3d",), "opengl-yup", ("colmap-text-model",)

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        for k, v in colmap_text(scene).items():
            pk.add(f"sparse/0/{k}", v)
        s = scene.converted("opengl-yup")
        centers = {cid: [round(float(x), 9) for x in np.asarray(s.cameras[cid].pose)[:3, 3]] for cid in sorted(s.cameras)}
        return pk.finish(self, scene, cameras=len(scene.cameras), expected_centers=centers,
                         points=int(sum(len(p.positions) for p in scene.point_clouds.values())),
                         images="not included — supplied by the capture (COLMAP NAME column references them)")

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        man = read_manifest(out)
        m = read_colmap_text(out / "sparse/0")
        errs = []
        ctr_ok = len(m["centers"]) == man["cameras"] and all(
            np.allclose(m["centers"][k], v, atol=1e-6) for k, v in man["expected_centers"].items())
        if not ctr_ok:
            errs.append("camera centres from (q, t) do not reproduce the IR poses")
        return finish_verify({"camera_centres_roundtrip": ctr_ok, "points": len(m["points"]) == man["points"],
                              "pinhole_models": all(c["model"] == "PINHOLE" and len(c["params"]) == 4 for c in m["cameras"].values())},
                             errs, out)

    def import_(self, path: Path) -> ir.Scene:
        m = read_colmap_text(Path(path))
        s = ir.Scene("colmap_import", "3d", "opengl-yup")
        s.add(ir.PointCloud("sparse", m["points"].astype(np.float32)))
        s.add_node(ir.Node("sparse", points="sparse"))
        return s

    def sample_input(self, out: Path) -> Path:
        from forge.universal import reference
        for k, v in colmap_text(reference.scene_3d()).items():
            (Path(out) / k).write_text(v)
        return Path(out)


class SplatsAdapter(Adapter):
    id, name, tier, direction = "splats", "3D Gaussian Splatting pack (OpenSplat / nerfstudio / Postshot / SuperSplat)", "interchange_pack", "both"
    dims, convention, formats = ("3d",), "opengl-yup", ("3dgs-ply", "nerfstudio-transforms", "colmap-text-model")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        for sid in sorted(scene.splats):
            pk.add(f"{_safe(sid)}.ply", scene.splats[sid].ply)
        if scene.cameras:
            pk.add("transforms.json", nerfstudio_transforms(scene))
            for k, v in colmap_text(scene).items():
                pk.add(f"colmap/sparse/0/{k}", v)
        if scene.point_clouds:
            s = scene.converted("opengl-yup")
            pc = s.point_clouds[sorted(s.point_clouds)[0]]
            pk.add("sparse_pc.ply", write_ply_points(pc.positions, pc.colors))
        return pk.finish(self, scene, splats=sorted(scene.splats), cameras=len(scene.cameras))

    def verify(self, out: Path) -> dict[str, Any]:
        from forge import realityloom
        out = Path(out)
        man = read_manifest(out)
        errs = []
        ply_ok = True
        for sid in man["splats"]:
            try:
                r = realityloom.check_splat_ply((out / f"{_safe(sid)}.ply").read_bytes())
                ply_ok &= int(r.get("vertices", 0)) > 0
            except Exception as e:  # noqa: BLE001 — validator raises on malformed files
                ply_ok = False
                errs.append(f"{sid}: {e}")
        tf_ok = True
        if (out / "transforms.json").exists():
            doc = json.loads((out / "transforms.json").read_text())
            tf_ok = len(doc["frames"]) == man["cameras"] and all(
                np.allclose(np.linalg.det(np.array(f["transform_matrix"])[:3, :3]), 1.0, atol=1e-6) for f in doc["frames"])
        return finish_verify({"splat_ply_valid": ply_ok, "nerfstudio_transforms": tf_ok}, errs, out)

    def import_(self, path: Path) -> ir.Scene:
        from forge import realityloom
        data = Path(path).read_bytes()
        r = realityloom.check_splat_ply(data)          # raises on malformed input
        if int(r.get("vertices", 0)) <= 0:
            raise ValueError(f"not a valid 3DGS .ply: {r}")
        s = ir.Scene(Path(path).stem, "3d", "opengl-yup")
        s.add(ir.SplatSet(_safe(Path(path).stem), data))
        s.add_node(ir.Node(_safe(Path(path).stem), splats=_safe(Path(path).stem)))
        return s

    def sample_input(self, out: Path) -> Path:
        from forge import splats
        p = Path(out) / "sample_splats.ply"
        p.write_bytes(splats.sphere_splats(200, seed=3))
        return p


class ReconImportAdapter(Adapter):
    """Meshroom / AliceVision, RealityCapture, OpenMVS mesh outputs (OBJ or PLY) → validated IR meshes."""
    id, name, tier, direction = "recon-import", "Photogrammetry mesh import (Meshroom / RealityCapture / OpenMVS)", "interchange_pack", "import"
    dims, convention, formats = ("3d",), "opengl-yup", ("obj", "ply")

    def import_(self, path: Path) -> ir.Scene:
        path = Path(path)
        data = path.read_bytes()
        m = read_ply_mesh(data) if path.suffix.lower() == ".ply" else M.read_obj(data)
        if m.n_triangles == 0:
            raise ValueError("no triangles")
        m = M.weld(m, 1e-7)
        s = ir.Scene(_safe(path.stem), "3d", "opengl-yup", meta={"validation": {k: v for k, v in M.validate(m).items() if k != "ok"}})
        s.add(ir.MeshAsset(_safe(path.stem), m))
        s.add_node(ir.Node(_safe(path.stem), mesh=_safe(path.stem)))
        return s

    def sample_input(self, out: Path) -> Path:
        p = Path(out) / "recon_mesh.ply"                   # stand-in (our writer), not real tool output
        p.write_bytes(write_ply_mesh(M.uv_sphere(0.5, 16, 8)))
        return p


class FuseAdapter(ReconImportAdapter):
    id, name, tier, direction = "fuse", "Adobe Fuse CC character import (OBJ)", "interchange_pack", "import"
    formats = ("obj",)

    def sample_input(self, out: Path) -> Path:
        p = Path(out) / "fuse_character.obj"               # stand-in (our writer), not real Fuse output
        body = M.merge([M.cylinder(0.15, 0.9, 12), M.uv_sphere(0.12, 12, 6).transformed(np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 1.05], [0, 0, 0, 1]], float))])
        p.write_bytes(M.write_obj(body, name="fuse_character"))
        return p
