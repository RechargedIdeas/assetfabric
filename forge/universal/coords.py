# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Coordinate conventions and exact basis changes between engines/tools.

A convention names where an asset's *own* up, forward and right point in that tool's coordinates, the length unit, the
UV origin and the normal-map green-channel convention. Conversion goes through semantic (right, up, forward) axes, so
every pair is exact (a signed permutation times a unit scale); when the handedness differs the determinant is negative
and triangle winding must be reversed (`needs_winding_flip`).

Facts used (public docs): glTF 2.0 is right-handed, +Y up, metres, asset front faces +Z; Unity is left-handed +Y up,
+Z forward, metres; Unreal is left-handed +Z up, +X forward, +Y right, centimetres; Blender is right-handed +Z up with
the front view looking along +Y (asset front faces -Y), metres; Godot 4 is right-handed +Y up, model front +Z, metres.
Normal maps: Unreal/DirectX-style tools use green-down (Y-), OpenGL-style tools green-up (Y+).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_AX = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}


@dataclass(frozen=True)
class Convention:
    id: str
    handedness: str          # "RH" | "LH"
    up: str                  # e.g. "+Y"
    forward: str             # asset front direction
    unit_m: float            # metres per unit
    uv_origin: str = "top-left"     # "top-left" (glTF/D3D) | "bottom-left" (OpenGL/OBJ)
    normal_map_y: str = "+Y"        # "+Y" (OpenGL) | "-Y" (DirectX)

    def basis(self) -> np.ndarray:
        """3×3 matrix whose columns are the convention's (right, up, forward) unit vectors."""
        u = np.array(_AX[self.up], float)
        f = np.array(_AX[self.forward], float)
        if abs(float(u @ f)) > 1e-9:
            raise ValueError(f"{self.id}: up and forward must be orthogonal")
        r = np.cross(f, u) if self.handedness == "RH" else np.cross(u, f)
        return np.stack([r, u, f], axis=1)


CONVENTIONS: dict[str, Convention] = {c.id: c for c in (
    Convention("gltf", "RH", "+Y", "+Z", 1.0, "top-left", "+Y"),
    Convention("godot", "RH", "+Y", "+Z", 1.0, "top-left", "+Y"),
    Convention("unity", "LH", "+Y", "+Z", 1.0, "bottom-left", "+Y"),
    Convention("unreal", "LH", "+Z", "+X", 0.01, "top-left", "-Y"),
    Convention("blender", "RH", "+Z", "-Y", 1.0, "bottom-left", "+Y"),
    Convention("opengl-yup", "RH", "+Y", "+Z", 1.0, "bottom-left", "+Y"),
    Convention("directx-yup", "LH", "+Y", "+Z", 1.0, "top-left", "-Y"),
    Convention("zup-rh", "RH", "+Z", "-Y", 1.0, "bottom-left", "+Y"),         # 3ds Max / OpenSCAD / CAD style
    Convention("source", "RH", "+Z", "+X", 0.0254, "top-left", "-Y"),        # Source/Hammer units ≈ 1 inch
)}


def get(cid: str) -> Convention:
    try:
        return CONVENTIONS[cid]
    except KeyError as e:
        raise KeyError(f"unknown coordinate convention {cid!r}; known: {sorted(CONVENTIONS)}") from e


def matrix(src: str | Convention, dst: str | Convention) -> np.ndarray:
    """3×3 linear map taking a point in `src` coordinates to `dst` coordinates (rotation/reflection × unit scale)."""
    a = src if isinstance(src, Convention) else get(src)
    b = dst if isinstance(dst, Convention) else get(dst)
    return (a.unit_m / b.unit_m) * (b.basis() @ a.basis().T)


def matrix4(src: str, dst: str) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = matrix(src, dst)
    return m


def needs_winding_flip(src: str, dst: str) -> bool:
    return bool(np.linalg.det(matrix(src, dst)) < 0)


def convert_points(p: np.ndarray, src: str, dst: str) -> np.ndarray:
    return np.asarray(p, float) @ matrix(src, dst).T


def convert_directions(v: np.ndarray, src: str, dst: str) -> np.ndarray:
    """Directions (normals) rotate/reflect but are not scaled; result is re-normalised."""
    m = matrix(src, dst)
    m = m / abs(np.linalg.det(m)) ** (1 / 3)
    out = np.asarray(v, float) @ m.T
    n = np.linalg.norm(out, axis=-1, keepdims=True)
    return out / np.where(n == 0, 1, n)


def convert_transform(t: np.ndarray, src: str, dst: str) -> np.ndarray:
    """Similarity-transform a 4×4 node matrix: M · T · M⁻¹ (keeps it a proper local transform in `dst`)."""
    m = matrix4(src, dst)
    return m @ np.asarray(t, float) @ np.linalg.inv(m)


def convert_uv(uv: np.ndarray, src: str, dst: str) -> np.ndarray:
    a, b = get(src), get(dst)
    out = np.array(uv, float, copy=True)
    if a.uv_origin != b.uv_origin:
        out[..., 1] = 1.0 - out[..., 1]
    return out


def convert_normal_map(rgb: np.ndarray, src: str, dst: str) -> np.ndarray:
    """Flip the green channel when the normal-map Y conventions differ (uint8 tangent-space map)."""
    out = np.array(rgb, copy=True)
    if get(src).normal_map_y != get(dst).normal_map_y:
        out[..., 1] = 255 - out[..., 1]
    return out
