"""G1-Sprite (procedural backend) — palette-locked 8-bit sprite sheets.

Frames (left→right): idle0 idle1 walk0 walk1 attack0 attack1, each `size`×`size`.
Deterministic for a given seed. `[INFERENCE]` template-based procedural backend
stands in for the chat's 2–4 MB ONNX Tiny model until that model is trained.
"""

from __future__ import annotations

import random
import time
from typing import Any

from forge.gates import budget_gate, dims_gate, palette_gate
from forge.generators import Artifact, GeneratorOutput, register
from forge.imaging import Image
from forge.patternvault import Palette

FRAMES = ["idle0", "idle1", "walk0", "walk1", "attack0", "attack1"]
OUT, SHADOW, BASE, HI, SKIN, ACCENT = range(6)


def _humanoid(rng: random.Random, s: int) -> dict[str, Any]:
    return {
        "head_w": rng.choice([2, 3]),
        "body_w": rng.choice([3, 4]),
        "leg_gap": rng.choice([0, 1]),
        "hair": rng.random() < 0.7,
        "belt": rng.random() < 0.6,
        "weapon_len": rng.choice([3, 4, 5]),
    }


def _draw_humanoid(p: dict[str, Any], pose: str, s: int) -> dict[tuple[int, int], int]:
    c = s // 2
    px: dict[tuple[int, int], int] = {}
    bob = 1 if pose == "idle1" else 0

    def sym(x: int, y: int, col: int) -> None:
        px[(c - 1 - x, y)] = col
        px[(c + x, y)] = col

    # head
    for y in range(2 + bob, 6 + bob):
        for x in range(p["head_w"]):
            sym(x, y, SKIN)
    if p["hair"]:
        for x in range(p["head_w"]):
            sym(x, 2 + bob, BASE)
    px[(c - 1, 4 + bob)] = OUT  # eyes
    px[(c, 4 + bob)] = OUT
    # body
    for y in range(6 + bob, 11):
        for x in range(p["body_w"] - (1 if y == 6 + bob else 0)):
            sym(x, y, BASE if x < p["body_w"] - 1 else SHADOW)
        sym(0, y, HI)
    if p["belt"]:
        for x in range(p["body_w"] - 1):
            sym(x, 10, ACCENT)
    # legs
    for y in range(11, s - 1):
        step = (y - 11) % 2
        lx = 1 + p["leg_gap"]
        if pose == "walk0":
            px[(c - 1 - lx, y)] = SHADOW
            px[(c + lx - (1 if y > 12 else 0), y)] = SHADOW
        elif pose == "walk1":
            px[(c - 1 - lx + (1 if y > 12 else 0), y)] = SHADOW
            px[(c + lx, y)] = SHADOW
        else:
            sym(lx, y, SHADOW)
        _ = step
    # arms / weapon (facing right)
    arm_y = 7 + bob
    if pose == "attack0":
        for i in range(3):
            px[(c + p["body_w"] + 0, arm_y - 1 - i)] = SKIN
    elif pose == "attack1":
        for i in range(2):
            px[(c + p["body_w"] + i, arm_y)] = SKIN
        for i in range(p["weapon_len"]):
            px[(c + p["body_w"] + 2 + i, arm_y)] = ACCENT
    else:
        sym(p["body_w"], arm_y, SKIN)
        sym(p["body_w"], arm_y + 1, SKIN)
    return px


def _beast(rng: random.Random, s: int) -> dict[str, Any]:
    return {"rx": rng.choice([4, 5, 6]), "ry": rng.choice([3, 4]), "spikes": rng.randint(1, 3), "eye_gap": rng.choice([1, 2])}


def _pet(rng: random.Random, s: int) -> dict[str, Any]:
    return {"rx": rng.choice([3, 4]), "ry": rng.choice([2, 3]), "spikes": rng.randint(0, 2), "eye_gap": 1, "ears": rng.random() < 0.6}


def _draw_pet(p: dict[str, Any], pose: str, s: int) -> dict[tuple[int, int], int]:
    px = _draw_beast(p, pose, s)
    if p.get("ears"):
        top = min(y for (_, y) in px) if px else 0
        c = s // 2
        for dx in (-p["rx"] + 1, p["rx"] - 2):
            px[(c + dx, top - 1)] = SHADOW
    return px


def _draw_beast(p: dict[str, Any], pose: str, s: int) -> dict[tuple[int, int], int]:
    c = s // 2
    px: dict[tuple[int, int], int] = {}
    rx, ry = p["rx"], p["ry"]
    squash = 1 if pose in ("idle1", "walk1") else 0
    lunge = 2 if pose == "attack1" else (1 if pose == "attack0" else 0)
    cy = s - 2 - ry + squash
    for y in range(cy - ry + squash, cy + ry + 1):
        for x in range(-rx - squash, rx + squash):
            dx = (x + 0.5) / (rx + squash)
            dy = (y - cy) / (ry + 0.5)
            if dx * dx + dy * dy <= 1.0:
                col = HI if dy < -0.4 else (SHADOW if dy > 0.45 else BASE)
                px[(c + x + lunge, y)] = col
    top = cy - ry + squash
    for i in range(p["spikes"]):
        sx = c - p["spikes"] + 2 * i + lunge
        px[(sx, top - 1)] = SHADOW
    eg = p["eye_gap"]
    px[(c - eg - 1 + lunge + 1, cy - 1)] = ACCENT
    px[(c + eg + lunge, cy - 1)] = ACCENT
    if pose == "attack1":
        for i in range(2):
            px[(c + rx + lunge + i, cy + 1)] = SKIN  # teeth / claw
    # feet
    if pose == "walk0":
        px[(c - 2 + lunge, s - 1)] = SHADOW
    elif pose == "walk1":
        px[(c + 1 + lunge, s - 1)] = SHADOW
    return px


def _outline(px: dict[tuple[int, int], int], s: int) -> dict[tuple[int, int], int]:
    out = dict(px)
    for (x, y) in px:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) not in px and 0 <= nx < s and 0 <= ny < s:
                out[(nx, ny)] = OUT
    return {k: v for k, v in out.items() if 0 <= k[0] < s and 0 <= k[1] < s}


@register("sprite")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    s = int(brief.get("size", 16))
    seed = int(brief.get("seed", 0))
    archetype = brief.get("archetype", "humanoid")
    palette: Palette = ctx.vault.get(brief["palette"])
    rng = random.Random(f"G1-Sprite:{archetype}:{seed}")
    makers = {"humanoid": (_humanoid, _draw_humanoid), "beast": (_beast, _draw_beast), "pet": (_pet, _draw_pet)}
    if archetype not in makers:
        raise ValueError(f"unknown sprite archetype {archetype!r}")
    make, draw = makers[archetype]
    params = make(rng, s)
    sheet = Image(s * len(FRAMES), s)
    for i, pose in enumerate(FRAMES):
        frame = _outline(draw(params, pose, s), s)
        for (x, y), idx in frame.items():
            sheet.set(i * s + x, y, palette[min(idx, len(palette) - 1)])
    png = sheet.to_png()
    elapsed = (time.perf_counter() - t0) * 1000
    gates = [
        palette_gate(sheet, [palette]),
        dims_gate(sheet, s * len(FRAMES), s),
        budget_gate(elapsed, len(png), max_ms=float(brief.get("budget_ms", 500)), max_bytes=64 * 1024),
    ]
    return GeneratorOutput(
        [Artifact(f"{brief['id']}.png", png, "image/png")],
        gates,
        {"kind": "sprite", "frame_size": s, "frames": FRAMES, "params": params, "palette": palette.ref,
         "model_id": "G1-Sprite", "model_version": "procedural-1"},
    )
