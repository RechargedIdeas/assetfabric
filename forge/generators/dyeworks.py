"""DyeWorks (procedural backend) — tileable palette-quantised materials.

Outputs albedo (palette-locked) + normal map. Periodic value noise guarantees
seamless wrap. Diffusion backends (SD1.5 on Vega / SDXL on 7900) are optional
later; this procedural path is the always-available GroundWeave fallback.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from forge.gates import budget_gate, dims_gate, palette_gate, seamless_gate
from forge.generators import Artifact, GeneratorOutput, register
from forge.imaging import Image


def periodic_noise(w: int, h: int, cells: int, octaves: int, seed: str) -> list[list[float]]:
    rng = random.Random(seed)
    out = [[0.0] * w for _ in range(h)]
    amp_total = 0.0
    for o in range(octaves):
        n = cells * (2 ** o)
        lattice = [[rng.random() for _ in range(n)] for _ in range(n)]
        amp = 0.5 ** o
        amp_total += amp
        for y in range(h):
            fy = y / h * n
            y0 = int(fy) % n
            y1 = (y0 + 1) % n
            ty = fy - int(fy)
            ty = ty * ty * (3 - 2 * ty)
            for x in range(w):
                fx = x / w * n
                x0 = int(fx) % n
                x1 = (x0 + 1) % n
                tx = fx - int(fx)
                tx = tx * tx * (3 - 2 * tx)
                a = lattice[y0][x0] + (lattice[y0][x1] - lattice[y0][x0]) * tx
                b = lattice[y1][x0] + (lattice[y1][x1] - lattice[y1][x0]) * tx
                out[y][x] += amp * (a + (b - a) * ty)
    return [[v / amp_total for v in row] for row in out]


def material(brief: dict[str, Any], ctx: Any) -> tuple[Image, Image, list[list[float]]]:
    s = int(brief.get("size", 16))
    pal = ctx.vault.get(brief["palette"])
    lo, hi = brief.get("ramp", [1, len(pal) - 1])
    style = brief.get("style", "stone")
    height = periodic_noise(s, s, int(brief.get("cells", 4)), int(brief.get("octaves", 2)), f"DyeWorks:{brief['id']}:{brief.get('seed', 0)}")
    if style == "brick":
        for y in range(s):
            for x in range(s):
                row = y // (s // 4)
                off = (s // 4) if row % 2 else 0
                if y % (s // 4) == 0 or (x + off) % (s // 2) == 0:
                    height[y][x] *= 0.35
    albedo = Image(s, s)
    span = hi - lo
    for y in range(s):
        for x in range(s):
            idx = lo + min(span, int(height[y][x] * (span + 1)))
            albedo.set(x, y, pal[idx])
    normal = Image(s, s)
    for y in range(s):
        for x in range(s):
            dx = height[y][(x + 1) % s] - height[y][(x - 1) % s]
            dy = height[(y + 1) % s][x] - height[(y - 1) % s][x]
            nx, ny, nz = -dx * 2.0, -dy * 2.0, 1.0
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            normal.set(x, y, (int((nx / ln * 0.5 + 0.5) * 255), int((ny / ln * 0.5 + 0.5) * 255), int((nz / ln * 0.5 + 0.5) * 255), 255))
    return albedo, normal, height


@register("material")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    albedo, normal, _ = material(brief, ctx)
    pal = ctx.vault.get(brief["palette"])
    a_png, n_png = albedo.to_png(), normal.to_png()
    elapsed = (time.perf_counter() - t0) * 1000
    s = albedo.width
    gates = [
        palette_gate(albedo, [pal]),
        dims_gate(albedo, s, s),
        seamless_gate(albedo),
        budget_gate(elapsed, len(a_png) + len(n_png), float(brief.get("budget_ms", 500)), 64 * 1024),
    ]
    return GeneratorOutput(
        [Artifact(f"{brief['id']}_albedo.png", a_png, "image/png"), Artifact(f"{brief['id']}_normal.png", n_png, "image/png")],
        gates,
        {"kind": "material", "size": s, "palette": pal.ref, "model_id": "DyeWorks", "model_version": "procedural-1"},
    )
