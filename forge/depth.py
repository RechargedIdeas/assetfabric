"""Metric depth (C11) — SPEC §5.2 "Depth: DepthAnything V2 (+ ARCore where available) for LensForge" and §9 "monocular
distance estimates".

REAL (CPU, numpy, deterministic):
  * `focal_px` — pixel focal length from EXIF-style optics (focal+sensor width, or 35 mm-equivalent, or horizontal FOV),
  * `distance_to_object` — classic pinhole monocular distance from an object of KNOWN real size (z = f·S/s) with an
    uncertainty band from ±`size_px_err` pixels of measurement error,
  * `align_inverse_depth` — turns ANY relative inverse-depth map (DepthAnything V2 convention: larger = nearer) into a metric
    depth map from ≥2 metric anchors, by least squares on inverse depth (the standard scale/shift alignment).

STUB (refuses, never fabricates a map): `DepthAnythingV2.estimate` (no weights/runtime bundled; licence of the larger
checkpoints must be checked before BoltPack — see INFERENCES), `ARCoreDepth.estimate` (Android-only SDK).
So today a metric depth map needs a relative map from somewhere else; this module can scale it but cannot produce it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from forge.i18n import t
from forge.stubs import refuse

MILESTONE = "C11"
FULL_FRAME_WIDTH_MM = 36.0        # 35 mm-equivalent focal length is defined against a 36 mm wide frame
EPS = 1e-9


def focal_px(image_width_px: int, focal_length_mm: float | None = None, sensor_width_mm: float | None = None,
             focal_length_35mm: float | None = None, hfov_deg: float | None = None) -> float:
    """Focal length in pixels, from the best available optics (priority: mm+sensor, 35 mm-equiv, FOV)."""
    if image_width_px <= 0:
        raise ValueError("image width must be positive")
    if focal_length_mm and sensor_width_mm:
        return focal_length_mm / sensor_width_mm * image_width_px
    if focal_length_35mm:
        return focal_length_35mm / FULL_FRAME_WIDTH_MM * image_width_px
    if hfov_deg and 0 < hfov_deg < 180:
        return (image_width_px / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    raise ValueError(t("depth.no_intrinsics"))


def distance_to_object(real_size_m: float, size_px: float, focal_length_px: float, size_px_err: float = 1.0) -> dict[str, Any]:
    """Pinhole distance to an object of known size, facing the camera (fronto-parallel): z = f·S/s."""
    if real_size_m <= 0 or size_px <= 0 or focal_length_px <= 0:
        raise ValueError("size, pixel extent and focal length must be positive")
    z = focal_length_px * real_size_m / size_px
    lo = focal_length_px * real_size_m / (size_px + size_px_err)
    hi = focal_length_px * real_size_m / max(EPS, size_px - size_px_err) if size_px > size_px_err else math.inf
    return {"distance_m": round(z, 6), "lo_m": round(lo, 6), "hi_m": None if math.isinf(hi) else round(hi, 6),
            "method": "pinhole", "assumptions": ["object faces the camera", "known real size", "no lens distortion"],
            "size_px_err": size_px_err}


@dataclass(frozen=True)
class Anchor:
    x: int
    y: int
    depth_m: float


def align_inverse_depth(rel: np.ndarray, anchors: list[Anchor]) -> dict[str, Any]:
    """Relative inverse depth (larger = nearer) → metric depth (m): fit 1/depth ≈ a·rel + b on the anchors (least squares)."""
    if rel.ndim != 2:
        raise ValueError("relative depth must be a 2-D map")
    h, w = rel.shape
    pts = [(int(a.x), int(a.y), float(a.depth_m)) for a in anchors]
    if len(pts) < 2 or any(d <= 0 or not (0 <= x < w and 0 <= y < h) for x, y, d in pts):
        raise ValueError(t("depth.bad_anchors"))
    r = np.array([float(rel[y, x]) for x, y, _ in pts])
    inv = np.array([1.0 / d for _, _, d in pts])
    if float(r.max() - r.min()) < EPS:
        raise ValueError(t("depth.bad_anchors"))
    A = np.stack([r, np.ones_like(r)], axis=1)
    (a, b), *_ = np.linalg.lstsq(A, inv, rcond=None)
    if a <= 0:
        raise ValueError(t("depth.non_monotone"))
    metric_inv = a * rel.astype(np.float64) + b
    bad = metric_inv <= EPS
    depth = 1.0 / np.maximum(metric_inv, EPS)
    depth[bad] = np.nan                      # beyond the fitted range: unknown, not invented
    pred = 1.0 / np.maximum(a * r + b, EPS)
    rmse = float(np.sqrt(np.mean((pred - 1.0 / inv) ** 2)))
    return {"depth_m": depth, "scale": float(a), "shift": float(b), "anchors": len(pts),
            "anchor_rmse_m": rmse, "invalid_fraction": float(bad.mean()), "method": "inverse-depth-lstsq"}


# ------------------------------------------------------------------------------------------------ stubs

class RelativeDepthEstimator(Protocol):
    """Contract for a dense relative-depth backend: image bytes → relative inverse-depth map float32[h,w] (larger = nearer)."""

    def estimate(self, image: bytes) -> np.ndarray: ...


class DepthAnythingV2:
    """STUB: DepthAnything V2 (ONNX) — the planned ladder rungs `depth.estimate` rocm / cpu are both `planned`."""

    def estimate(self, image: bytes) -> np.ndarray:
        refuse("depth.dense_estimate", "stub.depth.model_missing", MILESTONE)


class ARCoreDepth:
    """STUB: ARCore Depth API (Android only) — rung of `depth.estimate` on the phone."""

    def estimate(self, image: bytes) -> np.ndarray:
        refuse("depth.arcore", "stub.depth.arcore", MILESTONE)


STUB_PROBES = {
    "depth.dense_estimate": lambda: DepthAnythingV2().estimate(b""),
    "depth.arcore": lambda: ARCoreDepth().estimate(b""),
}


def probe() -> dict[str, Any]:
    """`depth.distance` CPU-rung probe for GroundWeave verify: deterministic synthetic scene, no files."""
    f = focal_px(4000, 6.9, 9.6)
    d = distance_to_object(0.30, 120.0, f)
    ys, xs = np.mgrid[0:48, 0:64]
    rel = (0.2 + xs / 64.0 + ys / 96.0).astype(np.float64)
    al = align_inverse_depth(rel, [Anchor(2, 2, 3.0), Anchor(60, 40, 1.2), Anchor(30, 20, 1.9)])
    dm = np.round(al["depth_m"], 6)
    return {"focal_px": round(f, 6), "distance": d, "scale": round(al["scale"], 9), "shift": round(al["shift"], 9),
            "depth_sum": float(np.nansum(dm)), "anchor_rmse_m": round(al["anchor_rmse_m"], 9)}


__all__ = ["focal_px", "distance_to_object", "align_inverse_depth", "Anchor", "DepthAnythingV2", "ARCoreDepth",
           "RelativeDepthEstimator"]
