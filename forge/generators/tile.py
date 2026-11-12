"""G1-Tile (procedural backend) — cave layouts + tileset with solvability gate.

Cellular-automata caves (`[INFERENCE]` classic CA stands in for the chat's
~2 MB NCA model), largest region kept, entry `S` / exit `E` placed far apart,
optional enemy spawn `X`. Tileset = DyeWorks materials + entry/exit markers.
Narrative constraint vector (brief `constraints`) controls size/density/rooms.
"""

from __future__ import annotations

import json
import random
import time
from collections import deque
from typing import Any

from forge.gates import bfs_path, budget_gate, floor_ratio_gate, palette_gate, solvability_gate
from forge.generators import Artifact, GeneratorOutput, register
from forge.generators.dyeworks import material
from forge.imaging import Image

TILE_INDEX = {"#": 0, ".": 1, "S": 2, "E": 3}
# F6 feature glyphs (passable): G gather node · P farm plot · W workbench / stall. Only layouts that
# use them get the extra tileset columns, so F1–F5 caves stay byte-identical.
FEATURE_INDEX = {"G": 4, "P": 5, "W": 6}


def _ca(w: int, h: int, fill: float, steps: int, rng: random.Random) -> list[list[bool]]:
    g = [[(x in (0, w - 1) or y in (0, h - 1)) or rng.random() < fill for x in range(w)] for y in range(h)]
    for _ in range(steps):
        n = [[False] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                if x in (0, w - 1) or y in (0, h - 1):
                    n[y][x] = True
                    continue
                walls = sum(g[y + dy][x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
                n[y][x] = walls >= 5 or (walls >= 4 and g[y][x])
        g = n
    return g


def _largest_region(g: list[list[bool]]) -> set[tuple[int, int]]:
    h, w = len(g), len(g[0])
    seen: set[tuple[int, int]] = set()
    best: set[tuple[int, int]] = set()
    for y in range(h):
        for x in range(w):
            if g[y][x] or (x, y) in seen:
                continue
            region = set()
            q = deque([(x, y)])
            seen.add((x, y))
            while q:
                cx, cy = q.popleft()
                region.add((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not g[ny][nx] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        q.append((nx, ny))
            if len(region) > len(best):
                best = region
    return best


def _farthest(grid: list[list[str]], start: tuple[int, int]) -> tuple[tuple[int, int], dict[tuple[int, int], int]]:
    h, w = len(grid), len(grid[0])
    dist = {start: 0}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] != "#" and (nx, ny) not in dist:
                dist[(nx, ny)] = dist[(x, y)] + 1
                q.append((nx, ny))
    far = max(dist, key=lambda k: (dist[k], -k[1], -k[0]))
    return far, dist


def _place_features(grid: list[list[str]], dist: dict[tuple[int, int], int], c: dict[str, Any], spawns: list[tuple[int, int]],
                    rng: random.Random) -> dict[str, Any]:
    """F6: gather nodes (G) spread along the route, farm plots (P) + workbench (W) near the entry.
    Features only replace plain floor that is not a spawn and keep 4-neighbour access."""
    out: dict[str, Any] = {}
    taken = set(spawns)
    far = max(dist.values())

    def free(p: tuple[int, int]) -> bool:
        x, y = p
        if grid[y][x] != "." or p in taken:
            return False
        open_n = sum(1 for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if grid[ny][nx] == ".")
        return open_n >= 2

    plots = int(c.get("plots", 0))
    if plots or c.get("bench"):
        near = sorted((d, p[1], p[0]) for p, d in dist.items() if 2 <= d <= 8)
        got: list[tuple[int, int]] = []
        for d, y, x in near:
            if len(got) >= plots + (1 if c.get("bench") else 0):
                break
            if free((x, y)):
                got.append((x, y))
                taken.add((x, y))
        if c.get("bench") and got:
            bx, by = got[0]
            grid[by][bx] = "W"
            out["bench"] = [bx, by]
            got = got[1:]
        for x, y in got:
            grid[y][x] = "P"
        out["plots"] = [[x, y] for x, y in got]
    n = int(c.get("nodes", 0))
    if n:
        nodes = []
        for i in range(n):
            target = far * (0.15 + 0.75 * (i + 0.5) / n)
            cands = sorted((abs(d - target), p[1], p[0]) for p, d in dist.items() if free(p))[:6]
            if not cands:
                break
            _, y, x = cands[rng.randrange(len(cands))]
            grid[y][x] = "G"
            taken.add((x, y))
            nodes.append([x, y])
        out["nodes"] = nodes
    return out


def make_cave(constraints: dict[str, Any], seed: int, attempts: int = 20) -> tuple[list[str], dict[str, Any]]:
    w = int(constraints.get("width", 40))
    h = int(constraints.get("height", 22))
    fill = float(constraints.get("density", 0.45))
    steps = int(constraints.get("smoothing", 5))
    min_path = int(constraints.get("min_path", (w + h) // 2))
    enemies = int(constraints.get("enemies", 1))
    for attempt in range(attempts):
        rng = random.Random(f"G1-Tile:{seed}:{attempt}")
        g = _ca(w, h, fill, steps, rng)
        region = _largest_region(g)
        grid = [["#" if (x, y) not in region else "." for x in range(w)] for y in range(h)]
        if not region:
            continue
        leftmost = min(region, key=lambda p: (p[0], p[1]))
        start, _ = _farthest(grid, leftmost)
        end, dist = _farthest(grid, start)
        if dist[end] < min_path:
            continue
        sx, sy = start
        ex, ey = end
        boss_info: dict[str, Any] = {}
        room = constraints.get("boss_room")
        if room:   # F5: carve a round arena around the cell ~85% of the way to the exit
            r = int(room.get("radius", 4))
            at = float(room.get("at", 0.85))
            cx, cy = min(dist, key=lambda p: (abs(dist[p] - dist[end] * at), p[1], p[0]))
            for yy in range(max(1, cy - r), min(h - 1, cy + r + 1)):
                for xx in range(max(1, cx - r), min(w - 1, cx + r + 1)):
                    if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r + 1 and grid[yy][xx] == "#":
                        grid[yy][xx] = "."
            end, dist = _farthest(grid, start)   # carving can only shorten/extend reach; recompute
            ex, ey = end
            boss_info = {"boss_room": {"center": [cx, cy], "radius": r}}
        grid[sy][sx] = "S"
        grid[ey][ex] = "E"
        spawn_at = constraints.get("spawn_at")
        if spawn_at:   # F6: one spawn per path fraction (packs spread along the route)
            spawns = []
            for f in spawn_at:
                cands = sorted((abs(d - dist[end] * float(f)), p[1], p[0]) for p, d in dist.items()
                               if grid[p[1]][p[0]] == "." and p not in spawns)
                spawns.append((cands[0][2], cands[0][1]))
        else:
            # enemy spawns: floor cells ~60% of the way along entry->exit distance
            target = dist[end] * 0.6
            cands = sorted((abs(d - target), p) for p, d in dist.items() if grid[p[1]][p[0]] == ".")
            spawns = [p for _, p in cands[:enemies]]
        feats = _place_features(grid, dist, constraints, spawns, rng)
        rows = ["".join(r) for r in grid]
        return rows, {"start": list(start), "exit": list(end), "spawns": [list(p) for p in spawns], "attempt": attempt, "path_len": dist[end], **boss_info, **feats}
    raise RuntimeError("G1-Tile: no layout satisfied constraints")


@register("tilemap")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    seed = int(brief.get("seed", 0))
    rows, info = make_cave(brief.get("constraints", {}), seed)
    ts = int(brief.get("tile_size", 16))
    wall_b = {"id": f"{brief['id']}_wall", "palette": brief.get("wall_palette", "cave_stone"), "size": ts, "style": "brick", "ramp": [1, 4], "seed": seed}
    floor_b = {"id": f"{brief['id']}_floor", "palette": brief.get("floor_palette", "cave_stone"), "size": ts, "style": "stone", "ramp": [2, 4], "cells": 2, "seed": seed}
    wall, _, _ = material(wall_b, ctx)
    floor, _, _ = material(floor_b, ctx)
    marker = ctx.vault.get(brief.get("marker_palette", "cave_moss"))
    used = [g for g in FEATURE_INDEX if any(g in r for r in rows)]
    legend = dict(TILE_INDEX) | {g: FEATURE_INDEX[g] for g in used}
    tileset = Image(ts * (4 + (len(FEATURE_INDEX) if used else 0)), ts)
    tileset.blit(wall, 0, 0)
    tileset.blit(floor, ts, 0)
    for i, col in ((2, marker[4]), (3, marker[3])):
        tileset.blit(floor, ts * i, 0)
        for y in range(3, ts - 3):
            for x in range(3, ts - 3):
                if (x in (3, ts - 4)) or (y in (3, ts - 4)) or (i == 3 and x == y):
                    tileset.set(ts * i + x, y, col)
    if used:   # F6 feature tiles drawn over floor with marker/wall ramps (palette-safe)
        wall_pal = ctx.vault.get(brief.get("wall_palette", "cave_stone"))
        for g, i in FEATURE_INDEX.items():
            tileset.blit(floor, ts * i, 0)
            for y in range(ts):
                for x in range(ts):
                    if g == "G" and abs(x - ts // 2) + abs(y - ts // 2) <= ts // 4:
                        tileset.set(ts * i + x, y, marker[4] if (x + y) % 3 else marker[2])
                    elif g == "P" and 2 <= x < ts - 2 and 2 <= y < ts - 2:
                        tileset.set(ts * i + x, y, wall_pal[1] if y % 4 < 2 else wall_pal[2])
                    elif g == "W" and 2 <= x < ts - 2 and 4 <= y < ts - 4:
                        tileset.set(ts * i + x, y, wall_pal[3] if y in (4, ts - 5) or x in (2, ts - 3) else wall_pal[2])
    layout = {"schema_version": "1.0", "tile_size": ts, "width": len(rows[0]), "height": len(rows), "legend": legend, "rows": rows, **info}
    layout_bytes = (json.dumps(layout, indent=1) + "\n").encode()
    ts_png = tileset.to_png()
    elapsed = (time.perf_counter() - t0) * 1000
    path = bfs_path(rows, tuple(info["start"]), tuple(info["exit"]), passable=".SEGPW")
    gates = [
        solvability_gate(rows),
        floor_ratio_gate(rows, *brief.get("constraints", {}).get("floor_ratio", (0.3, 0.7))),
        palette_gate(tileset, [ctx.vault.get("cave_stone"), ctx.vault.get(brief.get("wall_palette", "cave_stone")),
                               ctx.vault.get(brief.get("floor_palette", "cave_stone")), marker]),
        budget_gate(elapsed, len(ts_png) + len(layout_bytes), float(brief.get("budget_ms", 2000)), 256 * 1024),
    ]
    return GeneratorOutput(
        [Artifact(f"{brief['id']}_tiles.png", ts_png, "image/png"), Artifact(f"{brief['id']}.json", layout_bytes, "application/json")],
        gates,
        {"kind": "tilemap", "tile_size": ts, "tiles": list(TILE_INDEX), "path_len": len(path) if path else None,
         "model_id": "G1-Tile", "model_version": "ca-1"},
    )
