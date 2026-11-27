"""EmulatorHarness (ForgeConsole, ASSETFABRIC_SPEC §6.1) — boots a forge-built ROM in a real, independent NES emulator
headless and proves it against the ROMBuilder's own reference renderer.

Emulator: **cynes** (MIT, C++ cycle-level NES core with Python bindings, `pip install cynes`; a dev/acceptance tool, never
shipped with the game). Its palette is its own, so frames are compared by **colour-class partition**: every reference
PPU colour number must map to exactly one emulator RGB and no two numbers to the same RGB (a bijection), on every pixel.

Proofs: boots without a CPU jam; the settled frame equals the reference; holding Right/Left/Down/Up moves the party by
the expected number of pixels with the walk animation and facing flip; two fresh boots give byte-identical frames
(determinism); the CPU never jams over the whole run.
"""

from __future__ import annotations

import collections
import hashlib
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from forge.retro import rom as R
from forge.retro.profiles import Profile


def available() -> bool:
    try:
        import cynes  # noqa: F401
    except ImportError:
        return False
    return True


def partition_match(frame: np.ndarray, expected: np.ndarray) -> dict[str, Any]:
    a = expected.reshape(-1).tolist()
    b = frame.reshape(-1, 3).astype(np.int64)
    bk = ((b[:, 0] << 16) | (b[:, 1] << 8) | b[:, 2]).tolist()
    pairs = collections.Counter(zip(a, bk))
    best: dict[int, tuple[int, int]] = {}
    for (x, y), n in pairs.items():
        if n > best.get(x, (0, 0))[0]:
            best[x] = (n, y)
    good = sum(v[0] for v in best.values())
    inj = len({v[1] for v in best.values()}) == len(best)
    return {"match": good / len(a), "bijective": inj, "classes": len(best)}


def _locate(rb: R.RomBuild, profile: Profile, frame: np.ndarray, x0: int, y0: int, dx: tuple[int, int],
            dy: tuple[int, int], facing: int) -> dict[str, Any]:
    best: dict[str, Any] = {"match": -1.0}
    for x in range(x0 + dx[0], x0 + dx[1] + 1):
        for y in range(y0 + dy[0], y0 + dy[1] + 1):
            for fr in range(3):
                m = partition_match(frame, R.render_expected(rb, profile, x, y, fr, facing))
                if m["match"] > best["match"]:
                    best = m | {"x": x, "y": y, "frame": fr}
                if best["match"] == 1.0 and best["bijective"]:
                    return best
    return best


def run(rb: R.RomBuild, profile: Profile, hold: int = 30) -> dict[str, Any]:
    import cynes

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "game.nes"
        p.write_bytes(rb.rom)
        out: dict[str, Any] = {"emulator": f"cynes {getattr(cynes, '__version__', '?')}", "rom_sha256": rb.sha256}
        nes = cynes.NES(str(p))
        f0 = nes.step(frames=10)
        out["boot"] = partition_match(f0, R.render_expected(rb, profile)) | {"crashed": bool(nes.has_crashed)}
        moves = []
        x, y = R.START
        frames_seen = set()
        for name, mask, vec, facing in (("right", cynes.NES_INPUT_RIGHT, (1, 0), 0), ("down", cynes.NES_INPUT_DOWN, (0, 1), 0),
                                        ("left", cynes.NES_INPUT_LEFT, (-1, 0), 1), ("up", cynes.NES_INPUT_UP, (0, -1), 1)):
            nes.controller = mask
            fr = nes.step(frames=hold)
            # the displayed frame lags the game state by up to a frame, so allow ±2 px around the expected travel
            def rng(v: int) -> tuple[int, int]:
                return (-2, 2) if v == 0 else ((hold - 4, hold + 2) if v > 0 else (-hold - 2, -hold + 4))
            dxr, dyr = rng(vec[0]), rng(vec[1])
            loc = _locate(rb, profile, fr, x, y, dxr, dyr, facing)
            moved = (loc.get("x", x) - x, loc.get("y", y) - y)
            frames_seen.add(loc.get("frame"))
            moves.append({"input": name, "moved": list(moved), "match": loc["match"], "bijective": loc.get("bijective"),
                          "anim_frame": loc.get("frame")})
            x, y = loc.get("x", x), loc.get("y", y)
        nes.controller = 0
        still = nes.step(frames=20)
        rel = _locate(rb, profile, still, x, y, (-2, 2), (-2, 2), 1)
        out["release"] = {k: rel.get(k) for k in ("match", "bijective", "frame")}
        out["moves"] = moves
        out["walk_frames_seen"] = sorted(f for f in frames_seen if f is not None)
        out["crashed"] = bool(nes.has_crashed)
        # determinism: two fresh boots, same inputs → identical frame bytes
        hashes = []
        for _ in range(2):
            n2 = cynes.NES(str(p))
            n2.step(frames=10)
            n2.controller = cynes.NES_INPUT_RIGHT | cynes.NES_INPUT_DOWN
            hashes.append(hashlib.sha256(n2.step(frames=45).tobytes()).hexdigest())
        out["deterministic"] = hashes[0] == hashes[1]
        out["frame_sha256"] = hashes[0]
        out["frame0"] = f0
    return out
