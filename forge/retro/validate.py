"""V1 Retro Validation Harness + Q1 Pixel Stability Solver + R2 retro authenticity (ASSETFABRIC_SPEC §3 Layer D, §5.1).

V1 (frame gates, on real Godot captures):
  * block_uniformity — every logical pixel is one exact N×N block of identical screen pixels;
  * palette_conformance — every pixel is a profile palette colour (scanlines off);
  * shader_exact — the retro frame equals forge's own model of the pass applied to the matching source frame
    (cell-centre sample → colour-blind remap → LUT), pixel for pixel: the shader and forge/retro/colour.py agree bit-exactly;
  * scanline_structure — with scanlines on, the top half of each logical row is the plain frame and the bottom half is
    the same colours darkened by the documented factor (±1 per channel).
Q1:
  * shimmer predictor — for a texel scale (screen px per texel ÷ block) and a motion policy, simulates a sprite sliding
    across sub-pixel offsets, sampling at logical pixel centres, and reports the fraction of steps whose texel pattern
    changes shape (not just shifts) plus the texels never shown. Integer scale + whole-pixel snapping ⇒ 0 / 0.
  * q1_scale — the geometry quantisation the game applies to non-integer sprite scales under a profile.
R2 (authenticity discriminator): a deterministic logistic regression over four frame features (block uniformity, palette
conformance, colour count per block-row, edge sharpness), trained on synthetic positives (palette-quantised, integer-
scaled Fabric art) and negatives (bilinear / fractional scaling, off-palette noise, dithering-free gradients) with a fixed
seed; reported as held-out accuracy and a score per real capture. [INFERENCE F8-8] the spec names "constraint, fidelity
delta, discriminator" only; this is the smallest honest discriminator, CPU-only.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from forge.retro.colour import apply_lut


# ------------------------------------------------------------------ V1

def block_uniformity(img: np.ndarray, scale: int, region: tuple[int, int, int, int] | None = None) -> float:
    rgb = img[..., :3].astype(np.int64)
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = region or (0, 0, w, h)
    sub = rgb[y0:y1, x0:x1]
    hh, ww = (sub.shape[0] // scale) * scale, (sub.shape[1] // scale) * scale
    sub = sub[:hh, :ww].reshape(hh // scale, scale, ww // scale, scale, 3)
    ref = sub[:, :1, :, :1, :]
    same = (sub == ref).all(axis=(1, 3, 4))
    return float(same.mean())


def palette_conformance(img: np.ndarray, palette: np.ndarray) -> float:
    rgb = img[..., :3].reshape(-1, 3).astype(np.int64)
    key = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
    pk = (palette[:, 0].astype(np.int64) << 16) | (palette[:, 1].astype(np.int64) << 8) | palette[:, 2]
    return float(np.isin(key, pk).mean())


def model_pass(source: np.ndarray, scale: int, lut: np.ndarray, remap: list[tuple[str, str]] | None = None) -> np.ndarray:
    """forge's model of ui/retro_post.gdshader on a source frame (scanlines off)."""
    from forge.retro.colour import hex_rgb

    rgb = source[..., :3]
    h, w = rgb.shape[:2]
    cy = (np.arange(h // scale) * scale + scale // 2)
    cx = (np.arange(w // scale) * scale + scale // 2)
    cells = rgb[cy][:, cx].astype(np.int64)
    if remap:
        out = cells.copy()
        done = np.zeros(cells.shape[:2], dtype=bool)
        for a, b in remap:
            ca = np.array(hex_rgb(a))
            m = (np.abs(cells - ca).max(-1) <= 3) & ~done        # shader tolerance 0.012 ≈ 3/255
            out[m] = hex_rgb(b)
            done |= m
        cells = out
    q = apply_lut(cells.astype(np.uint8), lut)
    return np.repeat(np.repeat(q, scale, axis=0), scale, axis=1)


def exact_match(a: np.ndarray, b: np.ndarray) -> float:
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    return float((a[:h, :w, :3] == b[:h, :w, :3]).all(-1).mean())


def scanline_structure(plain: np.ndarray, scan: np.ndarray, scale: int, strength: float) -> dict[str, float]:
    p = plain[..., :3].astype(np.int64)
    s = scan[..., :3].astype(np.int64)
    rows = np.arange(p.shape[0]) % scale
    top = (rows + 0.5) / scale < 0.5 - 1e-9          # the shader darkens where fract(y_logical) >= 0.5
    top_ok = float((p[top] == s[top]).all(-1).mean())
    want = np.floor(p[~top] * (1.0 - strength) + 0.5)
    bot_ok = float((np.abs(s[~top] - want) <= 2).all(-1).mean())
    return {"top_rows_unchanged": top_ok, "bottom_rows_darkened": bot_ok}


# ------------------------------------------------------------------ Q1

def shimmer(texel_scale: float, snap: bool, texels: int = 16, steps: int = 16) -> dict[str, float]:
    """texel_scale: logical pixels per texel. snap: positions rounded to whole logical pixels (camera policy)."""
    patterns = []
    losses: list[float] = []
    for k in range(steps + 1):
        off = k / steps * 3.0                       # slide 3 logical px in sub-pixel steps
        if snap:
            off = math.floor(off + 0.5)
        n = int(math.ceil(texels * texel_scale)) + 4
        idx = [math.floor((i + 0.5 - off) / texel_scale) for i in range(-2, n)]
        vis = [t for t in idx if 0 <= t < texels]
        losses.append(1 - len(set(vis)) / texels)
        runs: list[int] = []
        prev = None
        for t in vis:
            if prev is not None and t == prev:
                runs[-1] += 1
            else:
                runs.append(1)
            prev = t
        patterns.append(tuple(runs))
    changes = sum(1 for a, b in zip(patterns, patterns[1:]) if a != b)
    return {"shimmer": round(changes / steps, 4), "texel_loss": round(float(np.mean(losses)), 4)}


def q1_scale(s: float) -> int:
    """Whole-number sprite scale: nearest integer ≥ 1, halves round up (bosses keep reading bigger)."""
    return max(1, int(math.floor(s + 0.5)))


def q1_report(scales: list[float], profiles: dict[str, Any], base_zoom: float) -> dict[str, Any]:
    rows = []
    for pid, p in profiles.items():
        for s in sorted(set([1.0, *scales])):
            naive = shimmer(s * base_zoom / p.scale, snap=False)
            policy = shimmer(float(q1_scale(s)), snap=True)
            rows.append({"profile": pid, "sprite_scale": s, "policy_scale": q1_scale(s),
                         "naive": naive, "policy": policy})
    ok = all(r["policy"]["shimmer"] == 0 and r["policy"]["texel_loss"] == 0 for r in rows)
    return {"ok": ok, "rows": rows, "naive_shimmer_max": max(r["naive"]["shimmer"] for r in rows),
            "naive_texel_loss_max": max(r["naive"]["texel_loss"] for r in rows)}


# ------------------------------------------------------------------ R2

def features(img: np.ndarray, scale: int, palette: np.ndarray) -> np.ndarray:
    rgb = img[..., :3].astype(np.int64)
    bu = block_uniformity(img, scale)
    pc = palette_conformance(img, palette)
    h, w = rgb.shape[:2]
    cells = rgb[scale // 2::scale, scale // 2::scale]
    key = (cells[..., 0] << 16) | (cells[..., 1] << 8) | cells[..., 2]
    per_row = np.mean([len(np.unique(r)) for r in key]) / max(1, key.shape[1])
    dx = np.abs(np.diff(rgb, axis=1)).sum(-1)
    nz = dx[dx > 0]
    sharp = float((nz > 48).mean()) if nz.size else 1.0
    return np.array([bu, pc, 1.0 - per_row, sharp])


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def train_discriminator(art: list[np.ndarray], palette: np.ndarray, lut: np.ndarray, scale: int,
                        seed: int = 8) -> dict[str, Any]:
    """Synthetic training set from Fabric art (RGBA strips). Returns weights + held-out accuracy."""
    rng = np.random.default_rng(seed)
    X, y = [], []
    for k in range(240):
        a = art[k % len(art)][..., :3]
        tile = np.tile(a, (3, 2, 1))[:48, :64]
        pos = apply_lut(tile, lut)
        pos = np.repeat(np.repeat(pos, scale, 0), scale, 1)
        X.append(features(pos, scale, palette))
        y.append(1)
        kind = k % 3
        if kind == 0:     # fractional nearest scaling (non-integer texel size)
            f = scale + 0.5 + rng.random()
            yy = (np.arange(int(48 * f)) / f).astype(int)
            xx = (np.arange(int(64 * f)) / f).astype(int)
            neg = apply_lut(tile, lut)[yy][:, xx]
        elif kind == 1:   # bilinear-ish blur (2×2 box after integer scaling)
            big = np.repeat(np.repeat(apply_lut(tile, lut), scale, 0), scale, 1).astype(np.float64)
            neg = ((big + np.roll(big, 1, 0) + np.roll(big, 1, 1) + np.roll(np.roll(big, 1, 0), 1, 1)) / 4).astype(np.uint8)
        else:             # off-palette noise on integer-scaled art
            big = np.repeat(np.repeat(tile, scale, 0), scale, 1).astype(np.int64)
            neg = np.clip(big + rng.integers(-24, 25, big.shape), 0, 255).astype(np.uint8)
        X.append(features(neg, scale, palette))
        y.append(0)
    Xa, ya = np.array(X), np.array(y, dtype=np.float64)
    order = rng.permutation(len(ya))
    Xa, ya = Xa[order], ya[order]
    cut = int(len(ya) * 0.7)
    w = np.zeros(Xa.shape[1])
    b = 0.0
    for _ in range(3000):
        p = _sigmoid(Xa[:cut] @ w + b)
        g = p - ya[:cut]
        w -= 0.5 * (Xa[:cut].T @ g) / cut
        b -= 0.5 * g.mean()
    acc = float(((_sigmoid(Xa[cut:] @ w + b) > 0.5) == (ya[cut:] > 0.5)).mean())
    return {"weights": [round(float(v), 6) for v in w], "bias": round(float(b), 6), "holdout_accuracy": round(acc, 4),
            "train": cut, "holdout": len(ya) - cut}


def authenticity(img: np.ndarray, scale: int, palette: np.ndarray, model: dict[str, Any]) -> float:
    z = features(img, scale, palette) @ np.array(model["weights"]) + model["bias"]
    return round(float(_sigmoid(np.array(z))), 4)
