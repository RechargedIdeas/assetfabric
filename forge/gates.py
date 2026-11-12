"""Validation gates run before an asset is promoted to the store / game (F1).

Each gate returns a GateResult; BudgetGate enforces time/size budgets.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from forge.imaging import Image
from forge.patternvault import Palette


@dataclass
class GateResult:
    gate: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)


def palette_gate(img: Image, palettes: list[Palette]) -> GateResult:
    allowed = {c for p in palettes for c in p.colours}
    used = img.colours()
    stray = sorted(used - allowed)
    return GateResult("palette", not stray, {"used": len(used), "allowed": len(allowed), "stray": [list(s) for s in stray[:8]]})


def dims_gate(img: Image, width: int, height: int) -> GateResult:
    ok = img.width == width and img.height == height
    return GateResult("dims", ok, {"expected": [width, height], "actual": [img.width, img.height]})


def _lum(c: tuple[int, int, int, int]) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def seamless_gate(img: Image, tolerance: float = 1.75) -> GateResult:
    """Wrap-around seam difference must be comparable to interior neighbour difference."""
    w, h = img.width, img.height
    inner, n_inner = 0.0, 0
    for y in range(h):
        for x in range(w - 1):
            inner += abs(_lum(img.get(x, y)) - _lum(img.get(x + 1, y)))
            n_inner += 1
    for y in range(h - 1):
        for x in range(w):
            inner += abs(_lum(img.get(x, y)) - _lum(img.get(x, y + 1)))
            n_inner += 1
    seam = sum(abs(_lum(img.get(w - 1, y)) - _lum(img.get(0, y))) for y in range(h))
    seam += sum(abs(_lum(img.get(x, h - 1)) - _lum(img.get(x, 0))) for x in range(w))
    inner_avg = inner / max(n_inner, 1)
    seam_avg = seam / (w + h)
    ok = seam_avg <= max(inner_avg * tolerance, 1.0)
    return GateResult("seamless", ok, {"seam_avg": round(seam_avg, 3), "inner_avg": round(inner_avg, 3)})


def bfs_path(grid: list[str], start: tuple[int, int], goal: tuple[int, int], passable: str = ".SE") -> list[tuple[int, int]] | None:
    h, w = len(grid), len(grid[0])
    prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            path = []
            node: tuple[int, int] | None = cur
            while node is not None:
                path.append(node)
                node = prev[node]
            return path[::-1]
        x, y = cur
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in prev and grid[ny][nx] in passable:
                prev[(nx, ny)] = cur
                q.append((nx, ny))
    return None


def solvability_gate(grid: list[str]) -> GateResult:
    """A* / BFS: entry `S` must reach exit `E` (SPEC §5.2 G1-Tile solvability gate)."""
    starts = [(x, y) for y, row in enumerate(grid) for x, ch in enumerate(row) if ch == "S"]
    ends = [(x, y) for y, row in enumerate(grid) for x, ch in enumerate(row) if ch == "E"]
    if len(starts) != 1 or len(ends) != 1:
        return GateResult("solvability", False, {"error": "need exactly one S and one E"})
    path = bfs_path(grid, starts[0], ends[0], passable=".SEGPW")   # F6 feature glyphs are walkable
    return GateResult("solvability", path is not None, {"path_len": len(path) if path else None})


def floor_ratio_gate(grid: list[str], lo: float = 0.3, hi: float = 0.7) -> GateResult:
    cells = sum(len(r) for r in grid)
    floor = sum(len(r) - r.count("#") for r in grid)   # every non-wall glyph is floor
    ratio = floor / cells
    return GateResult("floor_ratio", lo <= ratio <= hi, {"ratio": round(ratio, 3), "range": [lo, hi]})


def budget_gate(elapsed_ms: float, size_bytes: int, max_ms: float, max_bytes: int) -> GateResult:
    """BudgetGate: authoring budget (SPEC §5.1: 50–500 ms class) + size budget."""
    ok = elapsed_ms <= max_ms and size_bytes <= max_bytes
    return GateResult("budget", ok, {"elapsed_ms": round(elapsed_ms, 2), "max_ms": max_ms, "bytes": size_bytes, "max_bytes": max_bytes})
