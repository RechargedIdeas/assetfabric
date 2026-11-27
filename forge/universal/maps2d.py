# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""2D / 2.5D map synthesis on CPU (NumPy): height → tangent-space normal, depth, ambient occlusion; Sprite Lamp style
lighting profiles; photometric normal recovery from profiles; and a deterministic procedural demo character used by
the sprite-sheet exporters.

Conventions: images are (h, w, c) uint8, top-left origin. Tangent-space normals are encoded OpenGL-style (+Y = up in
the image, i.e. green increases toward the top) unless `y_down=True` (DirectX-style, green flipped)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NormalRecipe:
    """Tunable normal-map recipe (evolved by `evolution`)."""
    blur: int = 1            # box-blur radius applied to the height field
    strength: float = 2.0    # height-gradient gain
    dome: float = 1.0        # 1 = circular profile bulge, 0 = linear ramp


def _erode4(m: np.ndarray) -> np.ndarray:
    p = np.pad(m, 1)
    return p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]


def _box_blur(a: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return a
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def height_from_alpha(alpha: np.ndarray, recipe: NormalRecipe = NormalRecipe()) -> np.ndarray:
    """Inflate a silhouette into a height field in [0, 1] (distance-to-edge by repeated 4-erosion, dome profile)."""
    m = alpha > 0
    d = np.zeros(m.shape, float)
    cur = m.copy()
    while cur.any():
        d += cur
        cur = _erode4(cur)
    dmax = max(float(d.max()), 1.0)
    t = d / dmax
    h = recipe.dome * np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1)) + (1 - recipe.dome) * t
    h = _box_blur(h, recipe.blur)
    return np.where(m, h, 0.0)


def inscribed_radius(alpha: np.ndarray) -> float:
    """Largest 4-erosion depth of the silhouette in pixels (the same metric height_from_alpha uses)."""
    cur, d = alpha > 0, 0.0
    while cur.any():
        d += 1
        cur = _erode4(cur)
    return d


def normals_for_silhouette(alpha: np.ndarray, recipe: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Production 2D normal pipeline: silhouette → height → normals with relief relative to the inscribed radius.
    `recipe` = {blur, relief, dome}; default: the active self-improvement recipe (baseline when none promoted)."""
    if recipe is None:
        from forge.universal import evolution
        recipe = evolution.active_recipe("maps2d.normal")
    rec = NormalRecipe(blur=int(recipe["blur"]), strength=1.0, dome=float(recipe["dome"]))
    h = height_from_alpha(alpha, rec)
    return normals_from_height(h, float(recipe["relief"]) * max(inscribed_radius(alpha), 1.0)), h


def normals_from_height(h: np.ndarray, strength: float = 2.0) -> np.ndarray:
    """Unit normals (h, w, 3) as float (x right, y up, z out of the image) via central differences."""
    gx = np.zeros_like(h)
    gy = np.zeros_like(h)
    gx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) / 2
    gy[1:-1, :] = (h[2:, :] - h[:-2, :]) / 2      # +row = down the image
    n = np.stack([-gx * strength, gy * strength, np.ones_like(h)], -1)   # image-down gradient → +Y up flips sign
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def encode_normals(n: np.ndarray, alpha: np.ndarray | None = None, y_down: bool = False) -> np.ndarray:
    v = n.copy()
    if y_down:
        v[..., 1] = -v[..., 1]
    rgb = np.clip(np.round((v * 0.5 + 0.5) * 255), 0, 255).astype(np.uint8)
    if alpha is not None:
        rgb[alpha == 0] = (128, 128, 255)
        return np.dstack([rgb, alpha.astype(np.uint8)])
    return rgb


def decode_normals(rgb: np.ndarray, y_down: bool = False) -> np.ndarray:
    v = rgb[..., :3].astype(float) / 255 * 2 - 1
    if y_down:
        v[..., 1] = -v[..., 1]
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def depth_map(h: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Sprite Lamp depth convention: brighter = closer to the viewer; transparent pixels black."""
    d = np.clip(np.round(h * 255), 0, 255).astype(np.uint8)
    return np.dstack([d, d, d, alpha.astype(np.uint8)])


def ambient_occlusion(h: np.ndarray, alpha: np.ndarray, radius: int = 3) -> np.ndarray:
    """Cheap height-based AO: pixels lower than their neighbourhood mean get darker."""
    occ = np.clip(1.0 - 2.0 * np.maximum(_box_blur(h, radius) - h, 0), 0, 1)
    a = np.clip(np.round(occ * 255), 0, 255).astype(np.uint8)
    return np.dstack([a, a, a, alpha.astype(np.uint8)])


PROFILE_DIRS = {"Left": (-1.0, 0.0, 0.35), "Right": (1.0, 0.0, 0.35), "Top": (0.0, 1.0, 0.35),
                "Bottom": (0.0, -1.0, 0.35), "Front": (0.0, 0.0, 1.0)}


def lighting_profiles(n: np.ndarray, alpha: np.ndarray, albedo: float = 0.9) -> dict[str, np.ndarray]:
    """Render the five Sprite Lamp lighting profiles (Lambert, greyscale) from a normal field."""
    out = {}
    for name, d in PROFILE_DIRS.items():
        L = np.array(d) / np.linalg.norm(d)
        v = np.clip((n @ L) * albedo, 0, 1)
        g = np.clip(np.round(v * 255), 0, 255).astype(np.uint8)
        out[name] = np.dstack([g, g, g, alpha.astype(np.uint8)])
    return out


def normals_from_profiles(profiles: dict[str, np.ndarray]) -> np.ndarray:
    """Photometric-stereo recovery (least squares over the 5 known light directions) — what Sprite Lamp does with
    hand-painted profiles; used here to prove the generated profiles and normal map are mutually consistent."""
    names = list(PROFILE_DIRS)
    L = np.array([np.array(PROFILE_DIRS[k]) / np.linalg.norm(PROFILE_DIRS[k]) for k in names])     # (5, 3)
    I = np.stack([profiles[k][..., 0].astype(float) / 255 for k in names], -1)                     # (h, w, 5)
    g = I @ np.linalg.pinv(L).T
    return g / np.maximum(np.linalg.norm(g, axis=-1, keepdims=True), 1e-9)


def angular_error_deg(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    cos = np.clip((a * b).sum(-1), -1, 1)
    ang = np.degrees(np.arccos(cos))[mask]
    return {"mean": float(ang.mean()) if ang.size else 0.0, "p95": float(np.percentile(ang, 95)) if ang.size else 0.0}


# ----------------------------------------------------------------------------- procedural demo character

PALETTE = {"skin": (241, 194, 150), "hair": (92, 58, 33), "tunic": (46, 110, 168), "belt": (120, 78, 40),
           "boots": (60, 44, 36), "eye": (24, 24, 32), "outline": (20, 16, 24)}
DIRECTIONS = ("down", "left", "right", "up")          # RPG Maker MV/MZ row order


def character_frame(size: int, direction: str, step: int) -> np.ndarray:
    """A deterministic chibi walker frame (RGBA uint8, size×size). step ∈ {0,1,2}: 0/2 = stride, 1 = idle."""
    s = size
    img = np.zeros((s, s, 4), np.uint8)
    yy, xx = np.mgrid[0:s, 0:s].astype(float) / s

    def fill(mask: np.ndarray, col: tuple[int, int, int]) -> None:
        img[mask] = (*col, 255)
    bob = 0.0 if step == 1 else 0.02
    legsw = {0: 0.06, 1: 0.0, 2: -0.06}[step]
    # legs
    for side, sw in ((-1, legsw), (1, -legsw)):
        lx = 0.5 + side * 0.09
        fill((np.abs(xx - lx) < 0.06) & (yy > 0.70 + bob + max(sw, 0)) & (yy < 0.94 + min(sw, 0) * 0.5), PALETTE["boots"])
    # body
    fill(((xx - 0.5) / 0.20) ** 2 + ((yy - 0.62 - bob) / 0.16) ** 2 < 1, PALETTE["tunic"])
    fill((np.abs(yy - 0.68 - bob) < 0.025) & (np.abs(xx - 0.5) < 0.19), PALETTE["belt"])
    # head
    head = ((xx - 0.5) / 0.22) ** 2 + ((yy - 0.32 - bob) / 0.21) ** 2 < 1
    fill(head, PALETTE["skin"])
    hair = head & (yy < 0.24 - bob * 0 + bob)
    if direction == "up":
        hair = head & (yy < 0.44 + bob)
    elif direction == "left":
        hair = hair | (head & (xx > 0.58))
    elif direction == "right":
        hair = hair | (head & (xx < 0.42))
    fill(hair, PALETTE["hair"])
    if direction != "up":
        ex = {"down": (0.42, 0.58), "left": (0.36, 0.46), "right": (0.54, 0.64)}[direction]
        for x0 in ex:
            fill((np.abs(xx - x0) < 0.025) & (np.abs(yy - 0.34 - bob) < 0.035), PALETTE["eye"])
    # 1-px outline
    a = img[..., 3] > 0
    p = np.pad(a, 1)
    edge = ~a & (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:])
    img[edge] = (*PALETTE["outline"], 255)
    return img


def tile(size: int, kind: str, variant: int = 0) -> np.ndarray:
    """Deterministic 2D tiles (grass / stone / water / dirt) for tileset exporters (RGBA, opaque)."""
    yy, xx = np.mgrid[0:size, 0:size]
    h = ((xx * 73856093) ^ (yy * 19349663) ^ (variant * 83492791)) % 97 / 96.0     # integer hash noise
    base = {"grass": (76, 140, 60), "stone": (128, 128, 136), "water": (52, 104, 180), "dirt": (134, 96, 60)}[kind]
    k = 0.85 + 0.3 * h
    if kind == "stone":
        k = np.where(((xx % (size // 2)) == 0) | ((yy % (size // 2)) == 0), 0.6, k)
    if kind == "water":
        k = 0.9 + 0.2 * (np.sin((xx + 2 * yy + variant * 5) * 2 * np.pi / size) > 0.6)
    rgb = np.clip(np.array(base)[None, None, :] * k[..., None], 0, 255).astype(np.uint8)
    return np.dstack([rgb, np.full((size, size), 255, np.uint8)])
