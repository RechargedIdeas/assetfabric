"""LensForge capture intelligence (C10) — SPEC §4 / §9 "Capture modes; ARCore + DepthAnything V2; monocular distance
estimates; offload path for reconstruction". Depth lives in `forge/depth.py` (C11).

REAL (CPU, deterministic; pure-integer pixel math so FabricCore (Kotlin) reproduces the numbers bit-for-bit):
  * capture **modes** + advisory **profiles** (content/patternvault/capture_profiles.json — a PatternVault capture profile),
  * per-image quality: sharpness (Laplacian variance), exposure (mean luma + clipping), resolution,
  * capture-set assessment against a mode (view count, per-view verdicts, exact duplicates, best-of-burst),
  * `CaptureTelemetry` — the typed telemetry contract (device, optics, exposure) incl. EXIF read (Pillow),
  * wired into LoomLink: a `recon.capture` offload is assessed on the desktop and the verdict is stored in provenance.

STUB (refuses with `StubError`): ARCore session (Android-only SDK), continuous video capture, camera focus control.

NOT measured: view overlap / pose coverage (needs feature matching = COLMAP, C12) — reported as `overlap: "not_measured"`,
never guessed. Decoding: PNG with the built-in decoder; JPEG/WebP via Pillow (extra `lens`, part of `dev`) — without Pillow a
JPEG is refused with a locale-keyed reason rather than approximated.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from forge.i18n import t
from forge.paths import find_repo_root
from forge.stubs import refuse

MILESTONE = "C10"
PROFILES_PATH = Path("content") / "patternvault" / "capture_profiles.json"
MAX_PIXELS = 64_000_000


def load_profiles(root: Path | None = None) -> dict[str, Any]:
    return json.loads(((root or find_repo_root()) / PROFILES_PATH).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ decoding

class DecodeError(ValueError):
    pass


def _png_gray(data: bytes) -> tuple[np.ndarray, int, int]:
    """Minimal PNG → gray int32 (8-bit RGB/RGBA/gray/gray-alpha, non-interlaced). Anything else → DecodeError."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise DecodeError("not a PNG")
    pos, ihdr, idat = 8, None, bytearray()
    while pos + 8 <= len(data):
        n, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
    if ihdr is None:
        raise DecodeError("PNG without IHDR")
    w, h, depth, ctype, _c, _f, interlace = ihdr
    if depth != 8 or interlace != 0 or ctype not in (0, 2, 4, 6):
        raise DecodeError(f"unsupported PNG variant (depth {depth}, colour type {ctype}, interlace {interlace})")
    if w * h > MAX_PIXELS:
        raise DecodeError("image too large")
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    stride = w * ch
    raw = zlib.decompress(bytes(idat))
    if len(raw) != h * (stride + 1):
        raise DecodeError("truncated PNG")
    buf = np.frombuffer(raw, dtype=np.uint8).reshape(h, stride + 1)
    out = np.zeros((h, stride), dtype=np.int32)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(h):
        f, line = int(buf[y, 0]), buf[y, 1:].astype(np.int32)
        if f == 0:
            cur = line
        elif f == 1:
            cur = line.copy()
            for x in range(ch, stride):
                cur[x] = (cur[x] + cur[x - ch]) & 255
        elif f == 2:
            cur = (line + prev) & 255
        elif f == 3:
            cur = line.copy()
            for x in range(stride):
                left = cur[x - ch] if x >= ch else 0
                cur[x] = (cur[x] + ((left + prev[x]) >> 1)) & 255
        elif f == 4:
            cur = line.copy()
            for x in range(stride):
                a = cur[x - ch] if x >= ch else 0
                b = prev[x]
                c = prev[x - ch] if x >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[x] = (cur[x] + pr) & 255
        else:
            raise DecodeError("bad PNG filter")
        out[y], prev = cur, cur
    px = out.reshape(h, w, ch)
    if ch >= 3:
        gray = (299 * px[:, :, 0] + 587 * px[:, :, 1] + 114 * px[:, :, 2]) // 1000
    else:
        gray = px[:, :, 0]
    return gray.astype(np.int64), w, h


def decode_gray(data: bytes) -> tuple[np.ndarray, int, int, str]:
    """Bytes → (gray[h,w] int64, width, height, media). PNG built-in; JPEG/WebP need Pillow."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        g, w, h = _png_gray(data)
        return g, w, h, "image/png"
    media = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else ("image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None)
    if media is None:
        raise DecodeError(t("lens.not_an_image"))
    try:
        from PIL import Image
    except ImportError:
        raise DecodeError(t("lens.pillow_missing")) from None
    import io
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise DecodeError(f"{type(e).__name__}: {e}") from None
    if im.width * im.height > MAX_PIXELS:
        raise DecodeError("image too large")
    rgb = np.asarray(im.convert("RGB"), dtype=np.int64)
    gray = (299 * rgb[:, :, 0] + 587 * rgb[:, :, 1] + 114 * rgb[:, :, 2]) // 1000
    return gray, im.width, im.height, media


# ------------------------------------------------------------------------------------------------ quality

def gray_metrics(gray: np.ndarray) -> dict[str, float]:
    """Pure function of an int gray image — the Kotlin twin `fabric.core.Quality.assessGray` must match (shared vectors)."""
    g = gray.astype(np.int64)
    h, w = g.shape
    n = h * w
    total = int(g.sum())
    out: dict[str, float] = {"mean_luma": total / n,
                             "dark_clip": float((g <= 5).sum()) / n, "bright_clip": float((g >= 250).sum()) / n}
    if h >= 3 and w >= 3:
        lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
        m = lap.size
        s, ss = int(lap.sum()), int((lap * lap).sum())
        out["sharpness"] = ss / m - (s / m) ** 2
    else:
        out["sharpness"] = 0.0
    return out


def assess(data: bytes, mode: str = "still", root: Path | None = None) -> dict[str, Any]:
    """Quality of one image against a capture profile. Raises DecodeError for unreadable input; StubError for stub modes."""
    prof = load_profiles(root)
    mode_p = _mode(prof, mode)
    gray, w, h, media = decode_gray(data)
    m = gray_metrics(gray)
    th = prof["thresholds"]
    reasons = []
    if m["sharpness"] < th["min_sharpness"]:
        reasons.append("blurry")
    if not (th["mean_luma"][0] <= m["mean_luma"] <= th["mean_luma"][1]):
        reasons.append("too_dark" if m["mean_luma"] < th["mean_luma"][0] else "too_bright")
    if max(m["dark_clip"], m["bright_clip"]) > th["max_clip_fraction"]:
        reasons.append("clipped")
    if max(w, h) < mode_p["min_long_edge_px"]:
        reasons.append("low_resolution")
    return {"sha256": hashlib.sha256(data).hexdigest(), "media": media, "width": w, "height": h,
            "sharpness": round(m["sharpness"], 3), "mean_luma": round(m["mean_luma"], 3),
            "dark_clip": round(m["dark_clip"], 5), "bright_clip": round(m["bright_clip"], 5),
            "mode": mode, "verdict": "pass" if not reasons else "warn", "reasons": reasons,
            "advisory": True}


def assess_or_reason(data: bytes, mode: str = "still") -> dict[str, Any]:
    """Never raises: used where a bad/unsupported image must not break the surrounding flow (LoomLink offload)."""
    try:
        return assess(data, mode)
    except DecodeError as e:
        return {"verdict": "unassessed", "reason": str(e), "advisory": True}


def _mode(prof: dict[str, Any], mode: str) -> dict[str, Any]:
    m = prof["modes"].get(mode)
    if m is None:
        raise ValueError(f"unknown capture mode {mode!r}; known: {sorted(prof['modes'])}")
    if m["status"] == "stub":
        refuse(f"lens.mode.{mode}", m["reason_key"], MILESTONE)
    return m


def assess_set(images: list[bytes], mode: str, root: Path | None = None) -> dict[str, Any]:
    """Capture-set check: enough views, per-view quality, exact duplicates, best-of-burst. Overlap is NOT measured."""
    prof = load_profiles(root)
    mp = _mode(prof, mode)
    per, seen, dups = [], {}, []
    for i, b in enumerate(images):
        try:
            a = assess(b, mode, root)
        except DecodeError as e:
            per.append({"index": i, "verdict": "unreadable", "reason": str(e)})
            continue
        a["index"] = i
        if a["sha256"] in seen:
            dups.append({"index": i, "duplicate_of": seen[a["sha256"]]})
        else:
            seen[a["sha256"]] = i
        per.append(a)
    usable = [p for p in per if p.get("verdict") == "pass" and p["index"] not in {d["index"] for d in dups}]
    best = max((p for p in per if "sharpness" in p), key=lambda p: (p["sharpness"], -p["index"]), default=None)
    reasons = []
    if len(usable) < mp["min_views"]:
        reasons.append("too_few_usable_views")
    return {"mode": mode, "route_hint": mp["route_hint"], "views": len(images), "usable_views": len(usable),
            "min_views": mp["min_views"], "duplicates": dups, "best_index": best["index"] if best else None,
            "overlap": "not_measured", "verdict": "pass" if not reasons else "warn", "reasons": reasons,
            "per_view": per, "advisory": True}


# ------------------------------------------------------------------------------------------------ telemetry contract

_TELEMETRY_FIELDS: dict[str, tuple[type | tuple[type, ...], float | None, float | None]] = {
    "focal_length_mm": ((int, float), 0.5, 2000.0),
    "focal_length_35mm": ((int, float), 5.0, 2000.0),
    "sensor_width_mm": ((int, float), 0.5, 100.0),
    "exposure_s": ((int, float), 1e-6, 3600.0),
    "iso": ((int, float), 1.0, 10_000_000.0),
    "focus_distance_m": ((int, float), 0.0, 1e6),
    "captured_at_ms": (int, 0, None),
}


@dataclass(frozen=True)
class CaptureTelemetry:
    """Typed capture telemetry (SPEC §9 'telemetry streaming'; also the MirrorWeave `telemetry` frame payload)."""

    device: str = ""
    focal_length_mm: float | None = None
    focal_length_35mm: float | None = None
    sensor_width_mm: float | None = None
    exposure_s: float | None = None
    iso: float | None = None
    focus_distance_m: float | None = None
    orientation: int | None = None          # EXIF orientation 1..8
    captured_at_ms: int | None = None
    source: str = ""

    def __post_init__(self) -> None:
        for k, (typ, lo, hi) in _TELEMETRY_FIELDS.items():
            v = getattr(self, k)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, typ):
                raise ValueError(f"{k}: wrong type")
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                raise ValueError(f"{k}: out of range")
        if self.orientation is not None and not (isinstance(self.orientation, int) and 1 <= self.orientation <= 8):
            raise ValueError("orientation: 1..8")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CaptureTelemetry":
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown telemetry fields {sorted(unknown)}")
        return cls(**d)


def read_exif(data: bytes) -> CaptureTelemetry:
    """Optics/exposure from EXIF (Pillow). Missing tags stay None — never defaulted."""
    try:
        from PIL import Image
    except ImportError:
        raise DecodeError(t("lens.pillow_missing")) from None
    import io
    ex = Image.open(io.BytesIO(data)).getexif()
    sub = ex.get_ifd(0x8769)

    def num(v: Any) -> float | None:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    iso = sub.get(0x8827)
    if isinstance(iso, (tuple, list)):
        iso = iso[0] if iso else None
    return CaptureTelemetry(
        device=" ".join(str(x) for x in (ex.get(0x010F), ex.get(0x0110)) if x),
        focal_length_mm=num(sub.get(0x920A)), focal_length_35mm=num(sub.get(0xA405)) or None,
        exposure_s=num(sub.get(0x829A)), iso=num(iso), focus_distance_m=num(sub.get(0x9206)),
        orientation=int(ex.get(0x0112)) if ex.get(0x0112) else None, source="exif")


# ------------------------------------------------------------------------------------------------ stubs

class ARCoreSession:
    """STUB: ARCore depth/pose-assisted capture — Android-only SDK, not in FabricCore."""

    def start(self) -> None:
        refuse("lens.arcore_session", "stub.lens.arcore_session", MILESTONE)


class VideoCapture:
    """STUB: continuous video capture + keyframe extraction."""

    def start(self) -> None:
        refuse("lens.video_capture", "stub.lens.video_capture", MILESTONE)


class FocusController:
    """STUB: camera focus control (also reachable remotely via MirrorWeave `focus`)."""

    def set_focus(self, distance_m: float) -> None:
        refuse("lens.focus_control", "stub.mirror.camera_focus", MILESTONE)


STUB_PROBES = {
    "lens.arcore_session": lambda: ARCoreSession().start(),
    "lens.video_capture": lambda: VideoCapture().start(),
    "lens.focus_control": lambda: FocusController().set_focus(1.0),
}


# ------------------------------------------------------------------------------------------------ GroundWeave probe

def synthetic_gray(w: int = 64, h: int = 48, seed: int = 1) -> np.ndarray:
    """Deterministic integer test pattern (also the shared Kotlin vector generator: see tests/fixtures/lens_vectors.json)."""
    ys, xs = np.mgrid[0:h, 0:w]
    return ((xs * 7 + ys * 13 + (xs * ys) % 17 + seed * 31) % 256).astype(np.int64)


def probe() -> dict[str, Any]:
    """`lens.assess` CPU-rung probe for GroundWeave verify: deterministic, no files."""
    return {m: gray_metrics(synthetic_gray(64, 48, s)) for m, s in (("a", 1), ("b", 2))}


__all__ = ["CaptureTelemetry", "assess", "assess_set", "assess_or_reason", "read_exif", "gray_metrics", "load_profiles",
           "DecodeError", "ARCoreSession", "VideoCapture", "FocusController"]
