"""Console Profile Registry (ForgeConsole, ASSETFABRIC_SPEC §6.1) — loads `content/retro/profiles.yaml`, validates it and
resolves each profile's palette and integer pixel scale.

Palettes:
  patternvault — union of every PatternVault palette colour and colour-blind variant colour (so a11y variants survive
                 quantisation exactly; G-A11Y-01 holds in retro mode).
  nes-ntsc     — the 2C02 PPU palette *computed* from its composite-video signal levels (12-phase square-wave chroma,
                 YIQ decode, as in the public NTSC-decoding write-ups). Not a copied colour table. Index = PPU colour
                 number ($00–$3F); unusable entries ($0D "blacker than black", the $xE/$xF mirrors of black) are dropped
                 so the quantiser can never pick them; the ROM writes the surviving PPU numbers.
  list         — literal colours (DMG four-shade green).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from forge.paths import find_repo_root
from forge.retro.colour import hex_rgb, rgb_hex

REGISTRY = Path("content/retro/profiles.yaml")
FAMILIES = {"fabric", "nes", "gb"}

# 2C02 composite levels (volts, normalised as in the common decoders): low signal for luma rows 0..3, then high.
_NES_LEVELS = (0.350, 0.518, 0.962, 1.550, 1.094, 1.506, 1.962, 1.962)
_BLACK, _WHITE = 0.518, 1.962


def nes_ntsc_palette() -> list[tuple[int, int, int]]:
    """64 RGB colours, index = PPU colour number."""
    out = []
    for n in range(64):
        colour, level = n & 0x0F, n >> 4
        if colour >= 0x0E:
            level = 1
        lo = _NES_LEVELS[level + 4 * (colour == 0x0)]
        hi = _NES_LEVELS[level + 4 * (colour < 0x0D)]
        y = i = q = 0.0
        for p in range(12):
            v = ((hi if (colour + p) % 12 < 6 else lo) - _BLACK) / (_WHITE - _BLACK)
            y += v
            i += v * math.cos(math.pi / 6 * (p + 4))   # +4 phases: colour burst reference ($x1 = blue)
            q += v * math.sin(math.pi / 6 * (p + 4))
        y, i, q = y / 12, i / 12, q / 12
        rgb = (y + 0.946882 * i + 0.623557 * q, y - 0.274788 * i - 0.635691 * q, y - 1.108545 * i + 1.709007 * q)
        out.append(tuple(int(round(255 * min(1.0, max(0.0, c)) ** (1 / 1.13))) for c in rgb))   # mild display gamma
    return out  # type: ignore[return-value]


def nes_usable() -> list[tuple[int, tuple[int, int, int]]]:
    """(PPU number, rgb) for the colours a ROM may use: drops $0D and the $xE/$xF black mirrors, keeps $0F as black,
    and keeps the first PPU number of any duplicate RGB."""
    pal = nes_ntsc_palette()
    seen: dict[tuple[int, int, int], int] = {}
    for n, c in enumerate(pal):
        if n == 0x0D or (n & 0x0F) in (0x0E, 0x0F) and n != 0x0F:
            continue
        seen.setdefault(c, n)
    return sorted(((n, c) for c, n in seen.items()), key=lambda t: t[0])


def patternvault_colours(root: Path) -> list[str]:
    from forge.patternvault import PatternVault

    v = PatternVault(root)
    cols: list[str] = []
    for spec in v.data["palettes"].values():
        cols += [c.lower() for c in spec["colours"]]
    for pals in v.data.get("colorblind_variants", {}).values():
        for cs in pals.values():
            cols += [c.lower() for c in cs]
    return sorted(set(cols))



@dataclass
class Profile:
    id: str
    family: str
    label_key: str
    logical: tuple[int, int]
    palette_hex: list[str]
    scale: int
    scanlines: float = 0.0
    constraints: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    rom: dict[str, Any] | None = None
    ppu_numbers: list[int] | None = None        # nes: PPU colour number per palette entry
    match: str = "lab"                           # nearest-colour metric (colour.nearest)

    @property
    def palette(self) -> np.ndarray:
        return np.array([hex_rgb(h) for h in self.palette_hex], dtype=np.uint8)

    def table(self) -> dict[str, Any]:
        """What the game reads (assets/generated/retro/retro.json)."""
        return {"family": self.family, "label_key": self.label_key, "logical": list(self.logical), "scale": self.scale,
                "scanlines": self.scanlines, "palette_size": len(self.palette_hex), "match": self.match, "lut": f"{self.id}_lut.png"}


def load_raw(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    return yaml.safe_load((root / REGISTRY).read_text(encoding="utf-8"))


def validate(raw: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    bw, bh = raw.get("base_viewport", [0, 0])
    order = raw.get("order", [])
    if raw.get("default") not in order:
        errs.append("default profile not in order")
    if not order or order[0] != "off":
        errs.append("order must start with 'off' (modern presentation)")
    for pid in order[1:]:
        p = raw.get("profiles", {}).get(pid)
        if p is None:
            errs.append(f"{pid}: listed in order but not defined")
            continue
        if p.get("family") not in FAMILIES:
            errs.append(f"{pid}: unknown family {p.get('family')!r}")
        lw, lh = p.get("logical", [0, 0])
        if not lw or bw % lw or bh % lh or bw // lw != bh // lh:
            errs.append(f"{pid}: logical {lw}x{lh} is not an integer, uniform downscale of {bw}x{bh}")
        if not str(p.get("label_key", "")).startswith("retro.profile."):
            errs.append(f"{pid}: label_key must be a locale key retro.profile.*")
        if p.get("rom") and p.get("family") != "nes":
            errs.append(f"{pid}: ROMBuilder supports family nes only")
    for pid in raw.get("profiles", {}):
        if pid not in order:
            errs.append(f"{pid}: defined but not in order")
    return errs


def load(root: Path | None = None) -> dict[str, Profile]:
    root = root or find_repo_root()
    raw = load_raw(root)
    errs = validate(raw)
    if errs:
        raise ValueError("; ".join(errs))
    bw = raw["base_viewport"][0]
    out: dict[str, Profile] = {}
    for pid in raw["order"][1:]:
        p = raw["profiles"][pid]
        src = p["palette"]["source"]
        ppu = None
        if src == "patternvault":
            pal = patternvault_colours(root)
        elif src == "nes-ntsc":
            us = nes_usable()
            pal = [rgb_hex(c) for _, c in us]
            ppu = [n for n, _ in us]
        elif src == "list":
            pal = [c.lower() for c in p["palette"]["colours"]]
        else:
            raise ValueError(f"{pid}: unknown palette source {src}")
        out[pid] = Profile(pid, p["family"], p["label_key"], tuple(p["logical"]), pal, bw // p["logical"][0],
                           float(p.get("scanlines", 0.0)), p.get("constraints", {}), p.get("memory", {}),
                           p.get("timing", {}), p.get("rom"), ppu, str(p["palette"].get("match", "lab")))
    return out


def order(root: Path | None = None) -> list[str]:
    return list(load_raw(root)["order"])
