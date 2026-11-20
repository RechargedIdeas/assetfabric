"""Metric depth (C11) — SPEC §5.2 "Depth: DepthAnything V2 (+ ARCore where available) for LensForge" and §9 "monocular
distance estimates".

REAL (CPU, numpy, deterministic):
  * `focal_px` — pixel focal length from EXIF-style optics (focal+sensor width, or 35 mm-equivalent, or horizontal FOV),
  * `distance_to_object` — classic pinhole monocular distance from an object of KNOWN real size (z = f·S/s) with an
    uncertainty band from ±`size_px_err` pixels of measurement error,
  * `align_inverse_depth` — turns ANY relative inverse-depth map (DepthAnything V2 convention: larger = nearer) into a metric
    depth map from ≥2 metric anchors, by least squares on inverse depth (the standard scale/shift alignment).

REAL since 0.7.5 (CPU, onnxruntime): `DepthAnythingV2.estimate` — DepthAnything V2 **Small** (Apache-2.0; the Base/Large/
Giant checkpoints are CC-BY-NC-4.0 and are never used) as ONNX on the onnxruntime CPU execution provider. Weights are not in
git: `forge models fetch depth-anything-v2-small` (SHA-256 pinned in content/models/models.yaml). `estimate_metric` chains
it with `align_inverse_depth`. `render_scene` draws an analytic perspective scene (textured ground, wall, box) with exact
per-pixel depth — the ground truth used by tests and `forge accept C11`.

STUB (refuses, never fabricates a map): `ARCoreDepth.estimate` (Android-only SDK, see INFERENCES C-6x).
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


MODEL_ID = "depth-anything-v2-small"


class DepthAnythingV2:
    """DepthAnything V2 Small on onnxruntime (CPU EP). `estimate(image)` → relative inverse depth float32[h, w] at the input
    resolution (larger = nearer). `threads=1` (default) makes the output bit-reproducible across hosts/core counts with
    the same onnxruntime build; more threads are faster but may differ in the last float bits."""

    def __init__(self, model_path: str | None = None, input_size: int | None = None, threads: int = 1,
                 providers: list[str] | None = None) -> None:
        from forge import models
        spec = models.registry()[MODEL_ID]
        self.pre = spec["preprocess"]
        self.input_size = int(input_size or self.pre["size"])
        self.model_path = model_path or str(models.require(MODEL_ID))
        self.threads = threads
        self.providers = providers or ["CPUExecutionProvider"]
        self._sess = None

    @property
    def session(self):
        if self._sess is None:
            try:
                import onnxruntime as ort
            except ImportError as e:   # optional extra `depth`
                raise RuntimeError(t("depth.ort_missing")) from e
            so = ort.SessionOptions()
            so.intra_op_num_threads = self.threads
            so.inter_op_num_threads = 1
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            so.log_severity_level = 3
            self._sess = ort.InferenceSession(self.model_path, so, providers=self.providers)
        return self._sess

    def target_size(self, w: int, h: int) -> tuple[int, int]:
        """DPT 'keep aspect ratio, multiple of 14' resize (the scale closer to 1 wins, like the reference processor)."""
        m = int(self.pre["multiple_of"])
        sw, sh = self.input_size / w, self.input_size / h
        if abs(1 - sw) < abs(1 - sh):
            sh = sw
        else:
            sw = sh
        return max(m, int(round(w * sw / m)) * m), max(m, int(round(h * sh / m)) * m)

    def preprocess(self, rgb: np.ndarray) -> np.ndarray:
        from PIL import Image
        h, w = rgb.shape[:2]
        tw, th = self.target_size(w, h)
        im = Image.fromarray(rgb.astype(np.uint8)).resize((tw, th), Image.BICUBIC)
        x = np.asarray(im, dtype=np.float32) / 255.0
        x = (x - np.array(self.pre["mean"], np.float32)) / np.array(self.pre["std"], np.float32)
        return np.ascontiguousarray(x.transpose(2, 0, 1)[None])

    def estimate_rgb(self, rgb: np.ndarray) -> np.ndarray:
        from PIL import Image
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("expected an RGB image array [h, w, 3]")
        out = self.session.run(None, {"pixel_values": self.preprocess(rgb)})[0][0].astype(np.float32)
        h, w = rgb.shape[:2]
        return np.asarray(Image.fromarray(out, mode="F").resize((w, h), Image.BILINEAR), dtype=np.float32)

    def estimate(self, image: bytes) -> np.ndarray:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(image)) as im:
            rgb = np.asarray(im.convert("RGB"))
        return self.estimate_rgb(rgb)


def estimate_metric(rgb: np.ndarray, anchors: list[Anchor], estimator: RelativeDepthEstimator | None = None) -> dict[str, Any]:
    """Dense metric depth = DepthAnything V2 relative map + inverse-depth alignment on ≥ 2 metric anchors."""
    est = estimator or DepthAnythingV2()
    rel = est.estimate_rgb(rgb) if hasattr(est, "estimate_rgb") else est.estimate(rgb)
    out = align_inverse_depth(rel, anchors)
    out["relative"] = rel
    out["model"] = MODEL_ID
    return out


MAX_OFFLOAD_SIDE = 1024


def offload_estimate(payload: dict[str, Any], estimator: RelativeDepthEstimator | None = None) -> dict[str, Any]:
    """LoomLink `depth.estimate` offload (phone → desktop). Payload: `data_b64` (JPEG/PNG/WebP), optional `anchors`
    [{x, y, depth_m}] in image pixels, optional `max_side` (≤ 1024). Returns the relative map as little-endian uint16
    (`rel_u16_b64`, 0..65535 over [rel_min, rel_max]) at the (possibly downscaled) size, plus the metric alignment when
    ≥ 2 anchors are given — no image codec needed on the phone."""
    import base64
    import io

    from PIL import Image
    data = base64.b64decode(payload["data_b64"])
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        w0, h0 = im.size
        side = max(16, min(int(payload.get("max_side", 512)), MAX_OFFLOAD_SIDE))
        s = min(1.0, side / max(w0, h0))
        if s < 1.0:
            im = im.resize((max(1, round(w0 * s)), max(1, round(h0 * s))), Image.BICUBIC)
        rgb = np.asarray(im)
    est = estimator or DepthAnythingV2()
    rel = est.estimate_rgb(rgb) if hasattr(est, "estimate_rgb") else est.estimate(data)
    lo, hi = float(rel.min()), float(rel.max())
    q = np.round((rel - lo) / max(hi - lo, EPS) * 65535).astype("<u2")
    out: dict[str, Any] = {"model": MODEL_ID, "width": int(rel.shape[1]), "height": int(rel.shape[0]), "scale_from_input": s,
                           "rel_min": lo, "rel_max": hi, "rel_u16_b64": base64.b64encode(q.tobytes()).decode(),
                           "convention": "relative inverse depth, larger = nearer"}
    anchors = payload.get("anchors") or []
    if len(anchors) >= 2:
        al = align_inverse_depth(rel, [Anchor(int(round(a["x"] * s)), int(round(a["y"] * s)), float(a["depth_m"]))
                                       for a in anchors])
        d = al["depth_m"]
        out["metric"] = {"scale": al["scale"], "shift": al["shift"], "anchor_rmse_m": al["anchor_rmse_m"],
                         "invalid_fraction": al["invalid_fraction"], "median_m": float(np.nanmedian(d)),
                         "min_m": float(np.nanmin(d)), "max_m": float(np.nanmax(d))}
    return out


def render_scene(w: int = 256, h: int = 192, fov_deg: float = 60.0, cam_h: float = 1.5, pitch_deg: float = 8.0,
                 wall_z: float = 9.0, seed: int = 7) -> dict[str, Any]:
    """Analytic ray-cast scene with exact camera-space depth: checker+noise ground (y=0), brick wall (z=wall_z), a crate.

    Returns rgb uint8[h,w,3], depth_m float64[h,w] (camera z, NaN for sky) and the focal length in px."""
    rng = np.random.default_rng(seed)
    f = 0.5 * w / math.tan(math.radians(fov_deg) / 2)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    dx, dy = (xs + 0.5 - w / 2) / f, -(ys + 0.5 - h / 2) / f     # camera ray (z = 1), y up
    p = math.radians(pitch_deg)                                    # camera pitched down by p
    wy = dy * math.cos(p) - math.sin(p)                            # world-space ray (x right, y up, z forward)
    wz = dy * math.sin(p) + math.cos(p)
    wx = dx
    inf = np.full((h, w), np.inf)
    t_ground = np.where(wy < -1e-9, cam_h / np.maximum(-wy, 1e-9), inf)
    t_wall = np.where(wz > 1e-9, wall_z / np.maximum(wz, 1e-9), inf)
    # crate: axis-aligned box x∈[-0.9,0.1], y∈[0,0.8], z∈[3.0,4.0]
    lo, hi = np.array([-0.9, 0.0, 3.0]), np.array([0.1, 0.8, 4.0])
    o = np.array([0.0, cam_h, 0.0])
    with np.errstate(divide="ignore", invalid="ignore"):
        dirs = [wx, wy, wz]
        t1 = [(lo[i] - o[i]) / dirs[i] for i in range(3)]
        t2 = [(hi[i] - o[i]) / dirs[i] for i in range(3)]
        tmin = np.maximum.reduce([np.minimum(a, b) for a, b in zip(t1, t2)])
        tmax = np.minimum.reduce([np.maximum(a, b) for a, b in zip(t1, t2)])
    t_box = np.where((tmax >= tmin) & (tmin > 0), tmin, inf)
    t = np.minimum.reduce([t_ground, t_wall, t_box])
    hit = np.isfinite(t)
    px, py, pz = wx * t, cam_h + wy * t, wz * t
    rgb = np.zeros((h, w, 3))
    sky = np.stack([0.55 + 0.3 * (ys / h), 0.7 + 0.2 * (ys / h), np.full_like(ys, 0.95)], -1)
    rgb[:] = sky
    g = (t == t_ground) & hit
    chk = ((np.floor(px[g] / 0.5) + np.floor(pz[g] / 0.5)) % 2)
    base = np.stack([0.35 + 0.25 * chk, 0.42 + 0.2 * chk, 0.25 + 0.1 * chk], -1)
    rgb[g] = base * (0.85 + 0.3 * rng.random((g.sum(), 1)))
    wm = (t == t_wall) & hit & ~g
    row = np.floor(py[wm] / 0.25)
    mortar = ((py[wm] % 0.25) < 0.03) | (((px[wm] + 0.25 * (row % 2)) % 0.5) < 0.03)
    brick = np.stack([np.full(wm.sum(), 0.62), np.full(wm.sum(), 0.3), np.full(wm.sum(), 0.22)], -1)
    brick = brick * (0.85 + 0.3 * rng.random((wm.sum(), 1)))
    brick[mortar] = [0.8, 0.78, 0.74]
    rgb[wm] = brick
    bm = (t == t_box) & hit & ~g & ~wm
    face = np.where(np.isclose(pz[bm], 3.0, atol=1e-6), 1.0, 0.75)
    plank = (np.floor(py[bm] / 0.2) % 2)
    rgb[bm] = np.stack([0.55 + 0.1 * plank, 0.38 + 0.08 * plank, 0.18 + 0.0 * plank], -1) * face[:, None]
    # camera-space depth (z along the optical axis) = t * (ray z in camera frame) where camera ray has z=1 → depth = t
    depth = np.where(hit, t, np.nan)        # world ray = R·(dx, dy, 1) (a rotation), so the ray parameter IS camera z
    return {"rgb": (np.clip(rgb, 0, 1) * 255).astype(np.uint8), "depth_m": depth, "focal_px": f}


def depth_metrics(pred: np.ndarray, gt: np.ndarray) -> dict[str, float]:
    """Standard monocular-depth metrics on pixels where both are finite: AbsRel, δ<1.25, Spearman of inverse depth."""
    m = np.isfinite(pred) & np.isfinite(gt) & (gt > 0) & (pred > 0)
    p, g = pred[m], gt[m]
    ratio = np.maximum(p / g, g / p)

    def rank(v: np.ndarray) -> np.ndarray:
        r = np.empty(len(v))
        r[np.argsort(v, kind="stable")] = np.arange(len(v))
        return r
    ra, rb = rank(1 / p), rank(1 / g)
    sp = float(np.corrcoef(ra, rb)[0, 1])
    return {"abs_rel": float(np.mean(np.abs(p - g) / g)), "delta1": float(np.mean(ratio < 1.25)), "spearman": sp,
            "pixels": int(m.sum())}


class ARCoreDepth:
    """STUB: ARCore Depth API (Android only) — rung of `depth.estimate` on the phone."""

    def estimate(self, image: bytes) -> np.ndarray:
        refuse("depth.arcore", "stub.depth.arcore", MILESTONE)


STUB_PROBES = {
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
           "RelativeDepthEstimator", "estimate_metric", "render_scene", "depth_metrics", "MODEL_ID"]
