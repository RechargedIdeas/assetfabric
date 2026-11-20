"""ARCore capture — desktop half (C10 `lens.arcore_session`, C11 `depth.arcore`). SPEC §9 "ARCore + DepthAnything V2".

The phone (PocketLoom `ArCoreCapture`, ARCore SDK, `real_unverified_on_device`) records per-frame camera pose + intrinsics
and, where the device supports the Depth API, a DEPTH16 map (millimetres) + confidence. FabricCore packs that into a
LoomLink payload (`ArDepth.payload`, op `depth.arcore`); this module is the desktop side, bit-for-bit the same maths as
FabricCore `ArDepth` / `ArPoses` (shared vectors `tests/fixtures/arcore_vectors.json`):

* `decode` / `stats` — DEPTH16 → metres (0 = no depth), valid fraction, min / lower-median / max;
* `anchors` — deterministic grid of confident depth samples mapped into camera-image pixels → metric anchors for
  `depth.align_inverse_depth` (ARCore metric depth + DepthAnything dense relative depth = dense metric depth);
* `coverage` — pose coverage of a capture set: path length, max baseline, angular spread of view directions. This is the
  measured parallax/overlap proxy C10 previously reported as `not_measured` (only when poses exist).

Nothing here has seen a real ARCore frame: inputs are synthetic payloads with the documented layout (INFERENCES C-67)."""
from __future__ import annotations

import base64
import math
from typing import Any

import numpy as np

MIN_CONFIDENCE = 128      # ARCore raw-depth confidence 0..255; below this a sample is not used as an anchor
ANCHORS = 12


def synthetic_frame(w: int, h: int) -> dict[str, np.ndarray]:
    """Deterministic test frame shared with Kotlin (`ArDepth.synthetic`): depth in mm, confidence 0..255, holes."""
    ys, xs = np.mgrid[0:h, 0:w]
    d = 500 + (xs * 37 + ys * 91) % 4000
    d[(xs + ys) % 11 == 0] = 0
    c = (xs * 13 + ys * 7) % 256
    return {"depth_mm": d.astype(np.uint16), "confidence": c.astype(np.uint8)}


def payload(depth_mm: np.ndarray, confidence: np.ndarray | None, pose: list[float], intrinsics: dict[str, float],
            timestamp_ns: int = 0, image: bytes | None = None, media: str = "image/jpeg") -> dict[str, Any]:
    h, w = depth_mm.shape
    p: dict[str, Any] = {"width": w, "height": h, "depth_u16_b64": base64.b64encode(depth_mm.astype("<u2").tobytes()).decode(),
                         "pose": [float(v) for v in pose], "intrinsics": dict(intrinsics), "timestamp_ns": int(timestamp_ns)}
    if confidence is not None:
        p["conf_u8_b64"] = base64.b64encode(confidence.astype(np.uint8).tobytes()).decode()
    if image is not None:
        p["image_b64"] = base64.b64encode(image).decode()
        p["media"] = media
    return p


def decode(p: dict[str, Any]) -> tuple[np.ndarray, np.ndarray | None]:
    w, h = int(p["width"]), int(p["height"])
    if not (0 < w <= 4096 and 0 < h <= 4096):
        raise ValueError("depth size out of range")
    raw = base64.b64decode(p["depth_u16_b64"])
    if len(raw) != w * h * 2:
        raise ValueError("depth map size mismatch")
    d = np.frombuffer(raw, dtype="<u2").reshape(h, w)
    c = None
    if p.get("conf_u8_b64"):
        cr = base64.b64decode(p["conf_u8_b64"])
        if len(cr) != w * h:
            raise ValueError("confidence map size mismatch")
        c = np.frombuffer(cr, dtype=np.uint8).reshape(h, w)
    return d, c


def stats(depth_mm: np.ndarray) -> dict[str, Any]:
    v = np.sort(depth_mm[depth_mm > 0].astype(np.int64))
    if v.size == 0:
        return {"valid_fraction": 0.0, "min_m": None, "median_m": None, "max_m": None}
    return {"valid_fraction": round(v.size / depth_mm.size, 6), "min_m": int(v[0]) / 1000.0,
            "median_m": int(v[(v.size - 1) // 2]) / 1000.0, "max_m": int(v[-1]) / 1000.0}


def anchors(depth_mm: np.ndarray, confidence: np.ndarray | None, image_w: int, image_h: int, n: int = ANCHORS,
            min_conf: int = MIN_CONFIDENCE) -> list[dict[str, Any]]:
    """Grid of `ceil(sqrt(n))²` cells; each cell centre is an anchor if its depth > 0 and confidence ≥ `min_conf`.
    Coordinates are mapped from depth pixels to camera-image pixels (integer maths, same as Kotlin)."""
    h, w = depth_mm.shape
    g = max(1, math.isqrt(n - 1) + 1)
    out: list[dict[str, Any]] = []
    for gy in range(g):
        for gx in range(g):
            px, py = (2 * gx + 1) * w // (2 * g), (2 * gy + 1) * h // (2 * g)
            mm = int(depth_mm[py, px])
            if mm == 0 or (confidence is not None and int(confidence[py, px]) < min_conf):
                continue
            out.append({"x": (2 * px + 1) * image_w // (2 * w), "y": (2 * py + 1) * image_h // (2 * h), "depth_m": mm / 1000.0})
            if len(out) == n:
                return out
    return out


# ------------------------------------------------------------------------------------------------- poses

def _forward(q: list[float]) -> tuple[float, float, float]:
    """Camera look direction (-Z, ARCore/OpenGL camera convention) rotated by unit quaternion (qx, qy, qz, qw)."""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return (-(2 * (x * z + w * y)), -(2 * (y * z - w * x)), -(1 - 2 * (x * x + y * y)))


def coverage(poses: list[list[float]]) -> dict[str, Any]:
    """Pose coverage of a capture set. Each pose is [tx, ty, tz, qx, qy, qz, qw] (camera-to-world, metres)."""
    if not poses:
        raise ValueError("no poses")
    for p in poses:
        if len(p) != 7 or not all(math.isfinite(float(v)) for v in p):
            raise ValueError("pose must be 7 finite numbers [tx,ty,tz,qx,qy,qz,qw]")
    c = [(float(p[0]), float(p[1]), float(p[2])) for p in poses]
    f = [_forward([float(v) for v in p[3:]]) for p in poses]
    path = sum(math.dist(c[i], c[i + 1]) for i in range(len(c) - 1))
    base = max((math.dist(a, b) for i, a in enumerate(c) for b in c[i + 1:]), default=0.0)

    def ang(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        d = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
        return math.degrees(math.acos(d))
    spread = max((ang(a, b) for i, a in enumerate(f) for b in f[i + 1:]), default=0.0)
    steps = [ang(f[i], f[i + 1]) for i in range(len(f) - 1)]
    return {"views": len(poses), "path_m": round(path, 6), "max_baseline_m": round(base, 6),
            "angular_spread_deg": round(spread, 4), "max_step_deg": round(max(steps, default=0.0), 4)}


def ingest(p: dict[str, Any], estimator: Any = None) -> dict[str, Any]:
    """Desktop handling of one ARCore frame (LoomLink op `depth.arcore`). With a camera image and a dense estimator the
    DepthAnything relative map is aligned to the ARCore anchors → dense metric depth summary."""
    d, c = decode(p)
    intr = p.get("intrinsics") or {}
    iw, ih = int(intr.get("image_w") or d.shape[1]), int(intr.get("image_h") or d.shape[0])
    an = anchors(d, c, iw, ih)
    out: dict[str, Any] = {"width": d.shape[1], "height": d.shape[0], **stats(d), "anchors": an,
                           "pose": p.get("pose"), "coverage": coverage([p["pose"]]) if p.get("pose") else None}
    if not p.get("image_b64"):
        out["dense"] = {"skipped": "no_image"}
    elif estimator is None:
        out["dense"] = {"skipped": "no_estimator"}
    elif len(an) < 2:
        out["dense"] = {"skipped": "too_few_confident_anchors"}
    else:
        from forge import depth
        rel = estimator.estimate(base64.b64decode(p["image_b64"]))
        sx, sy = rel.shape[1] / iw, rel.shape[0] / ih
        al = depth.align_inverse_depth(rel, [depth.Anchor(min(rel.shape[1] - 1, int(a["x"] * sx)), min(rel.shape[0] - 1, int(a["y"] * sy)),
                                                          a["depth_m"]) for a in an])
        dm = al["depth_m"]
        out["dense"] = {"width": rel.shape[1], "height": rel.shape[0], "median_m": float(np.nanmedian(dm)),
                        "anchor_rmse_m": al["anchor_rmse_m"], "scale": al["scale"], "shift": al["shift"]}
    return out
