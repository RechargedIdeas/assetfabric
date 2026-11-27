"""Colour maths for the retro path: sRGB ↔ CIELAB (D65), CIE76 ΔE, nearest-palette LUTs (numpy, deterministic)."""

from __future__ import annotations

import numpy as np

LUT_LEVELS = 64          # per channel: index = value >> 2 (exact integer maths in the shader)
LUT_SIDE = 512           # 64 slices of 64×64 laid out 8×8


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_hex(c: tuple[int, int, int] | np.ndarray) -> str:
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb: (..., 3) uint8/float 0..255 → (..., 3) float64 L*a*b*."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    d = 6 / 29
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def delta_e(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.linalg.norm(srgb_to_lab(a) - srgb_to_lab(b), axis=-1)


def nearest(rgb: np.ndarray, palette: np.ndarray, match: str = "lab") -> np.ndarray:
    """Index of the perceptually nearest palette colour for every pixel. rgb (..., 3), palette (P, 3) → (...) int.
    match="lab": CIE76 in L*a*b*. match="lightness": L* only, with the input's 0..100 range stretched onto the
    palette's L* range (a monochrome LCD keeps luminance order, not hue)."""
    lab = srgb_to_lab(rgb.reshape(-1, 3))
    pl = srgb_to_lab(palette)
    if match == "lightness":
        lo, hi = pl[:, 0].min(), pl[:, 0].max()
        lab = np.stack([lo + lab[:, 0] / 100.0 * (hi - lo), np.zeros(len(lab)), np.zeros(len(lab))], -1)
        pl = np.stack([pl[:, 0], np.zeros(len(pl)), np.zeros(len(pl))], -1)
    out = np.empty(lab.shape[0], dtype=np.int64)
    for s in range(0, lab.shape[0], 65536):       # bounded memory on the 2-core node
        d = ((lab[s:s + 65536, None, :] - pl[None, :, :]) ** 2).sum(-1)
        out[s:s + 65536] = d.argmin(1)
    return out.reshape(rgb.shape[:-1])


def build_lut(palette: np.ndarray, exact: np.ndarray | None = None, match: str = "lab") -> tuple[np.ndarray, list[str]]:
    """64³ nearest-colour LUT as a 512×512 RGB image (slice b at (b%8, b//8), texel (r, g) inside it).

    Bin centres map to their nearest palette colour (CIELAB). Then every colour in `exact` (and every palette colour)
    is pinned so an *exact* input colour maps to its own nearest palette colour — palette art round-trips unchanged.
    Returns (image, collisions): a collision is two pinned colours that share a bin but want different outputs."""
    q = np.arange(LUT_LEVELS) * 4 + 2
    r, g, b = np.meshgrid(q, q, q, indexing="ij")
    centres = np.stack([r, g, b], -1).reshape(-1, 3)
    idx = nearest(centres, palette, match).reshape(LUT_LEVELS, LUT_LEVELS, LUT_LEVELS)
    pins: dict[tuple[int, int, int], int] = {}
    collisions: list[str] = []
    pinned = [palette] + ([exact] if exact is not None and len(exact) else [])
    for arr in pinned:
        want = nearest(arr, palette, match)
        for c, w in zip(arr, want):
            key = (int(c[0]) >> 2, int(c[1]) >> 2, int(c[2]) >> 2)
            if key in pins and pins[key] != int(w):
                collisions.append(f"{rgb_hex(c)} shares LUT bin {key} with a colour that maps elsewhere")
                continue
            pins[key] = int(w)
            idx[key] = int(w)
    img = np.zeros((LUT_SIDE, LUT_SIDE, 3), dtype=np.uint8)
    for bb in range(LUT_LEVELS):
        ox, oy = (bb % 8) * LUT_LEVELS, (bb // 8) * LUT_LEVELS
        # image[y, x] with x = r, y = g
        img[oy:oy + LUT_LEVELS, ox:ox + LUT_LEVELS] = palette[idx[:, :, bb].T]
    return img, collisions


def apply_lut(img_rgb: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """What the R1 shader does per pixel (bit-exact): q = v >> 2 → LUT texel."""
    q = img_rgb.astype(np.int64) >> 2
    x = (q[..., 2] % 8) * LUT_LEVELS + q[..., 0]
    y = (q[..., 2] // 8) * LUT_LEVELS + q[..., 1]
    return lut[y, x]
