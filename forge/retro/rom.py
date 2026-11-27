"""ROMBuilder (ForgeConsole, ASSETFABRIC_SPEC §6.1 path 1 "real ROMs in emulators") — Fabric content → iNES NROM ROM.

What the ROM is: a **Game Zero field demo** for the `nes-style` profile. It shows a 16×15-metatile window of the Fabric
tilemap named in the profile (`rom.area`, centred on its spawn), and the four base fighters + a pet as 16×16 metasprites
in formation. Controller 1's d-pad moves the party (1 px / frame, clamped to the screen), the leader plays its idle/walk
frames and faces the way it moves. Everything visible comes out of AssetFabric: CHR tiles and sub-palettes from the
AssetTranscoder + C1 solver, the nametable/attribute table from the tilemap brief's layout, metasprite tables from the
sprite strips. The 6502 program is assembled here (forge/retro/asm6502.py) — no external toolchain.

[INFERENCE F8-6] The spec says only "ROMBuilder" / "real ROMs in emulators" (F8 optional). A playable field demo is the
smallest ROM that exercises every console constraint we validate (CHR, sub-palettes, attributes, OAM, per-scanline
sprites, vblank budget, controller). Porting the full combat sim to 6502 is out of scope (and the spec forbids nothing
here: the combat tick stays in Godot, no LLM anywhere near it).

Memory map: CHR table 0 ($0000) = background tiles, table 1 ($1000) = sprite tiles. PRG at $8000 (32 KiB, vectors at
$FFFA). Zero page holds the game state; OAM shadow at $0200 (DMA'd every vblank).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from forge.retro import transcode as T
from forge.retro.asm6502 import Program, assemble
from forge.retro.profiles import Profile

WALK_FRAMES = (0, 2, 3)        # FRAME_NAMES idle0, walk0, walk1 (games/game-zero/scenes/encounter.gd)
FORMATION = ((0, 0), (-20, -12), (-20, 12), (-38, 0), (18, 8))   # leader, 3 followers, pet (dx, dy) [INFERENCE F8-6]
START = (128, 112)
BOUNDS = (44, 230, 24, 200)    # leader x min/max, y min/max (keeps the formation on screen)
WIN_W, WIN_H = 16, 15          # metatiles (256×240)

SRC = r"""
PPUCTRL = $2000
PPUMASK = $2001
PPUSTATUS = $2002
OAMADDR = $2003
PPUSCROLL = $2005
PPUADDR = $2006
PPUDATA = $2007
OAMDMA = $4014
JOY1 = $4016
nmi_flag = $00
buttons = $01
lx = $02
ly = $03
facing = $04
frame = $05
ticks = $06
moving = $07
ptr = $08
mptr = $0A
ent = $0C
ex = $0D
ey = $0E
oamx = $0F

.org $8000
reset:
  SEI
  CLD
  LDX #$40
  STX $4017
  LDX #$FF
  TXS
  INX
  STX PPUCTRL
  STX PPUMASK
  STX $4010
vb1:
  BIT PPUSTATUS
  BPL vb1
  LDA #$00
clr:
  STA $0000,X
  STA $0100,X
  STA $0300,X
  STA $0400,X
  STA $0500,X
  STA $0600,X
  STA $0700,X
  INX
  BNE clr
  LDA #$FF
hide:
  STA $0200,X
  INX
  BNE hide
vb2:
  BIT PPUSTATUS
  BPL vb2
  LDA PPUSTATUS
  LDA #$3F
  STA PPUADDR
  LDA #$00
  STA PPUADDR
  LDX #$00
pal:
  LDA palettes,X
  STA PPUDATA
  INX
  CPX #32
  BNE pal
  LDA PPUSTATUS
  LDA #$20
  STA PPUADDR
  LDA #$00
  STA PPUADDR
  LDA #<nametable
  STA ptr
  LDA #>nametable
  STA ptr+1
  LDX #4
  LDY #0
nt:
  LDA (ptr),Y
  STA PPUDATA
  INY
  BNE nt
  INC ptr+1
  DEX
  BNE nt
  LDA #START_X
  STA lx
  LDA #START_Y
  STA ly
  JSR build_oam
vb3:
  BIT PPUSTATUS
  BPL vb3
  LDA #$00
  STA OAMADDR
  LDA #$02
  STA OAMDMA
  LDA #$00
  STA PPUSCROLL
  STA PPUSCROLL
  LDA #%10001000
  STA PPUCTRL
  LDA #%00011110
  STA PPUMASK

main:
  LDA nmi_flag
  BEQ main
  LDA #$00
  STA nmi_flag
  INC ticks
  LDA #$01
  STA JOY1
  LDA #$00
  STA JOY1
  LDX #8
joy:
  LDA JOY1
  LSR A
  ROL buttons
  DEX
  BNE joy
  LDA #$00
  STA moving
  LDA buttons
  AND #$01
  BEQ no_right
  LDA lx
  CMP #MAX_X
  BCS no_right
  INC lx
  LDA #$00
  STA facing
  INC moving
no_right:
  LDA buttons
  AND #$02
  BEQ no_left
  LDA lx
  CMP #MIN_X+1
  BCC no_left
  DEC lx
  LDA #$01
  STA facing
  INC moving
no_left:
  LDA buttons
  AND #$04
  BEQ no_down
  LDA ly
  CMP #MAX_Y
  BCS no_down
  INC ly
  INC moving
no_down:
  LDA buttons
  AND #$08
  BEQ no_up
  LDA ly
  CMP #MIN_Y+1
  BCC no_up
  DEC ly
  INC moving
no_up:
  LDA #$00
  STA frame
  LDA moving
  BEQ still
  LDA ticks
  LSR A
  LSR A
  LSR A
  AND #$01
  CLC
  ADC #$01
  STA frame
still:
  JSR build_oam
  JMP main

build_oam:
  LDX #$00
  STX oamx
  LDA #$00
  STA ent
ent_loop:
  LDY ent
  LDA lx
  CLC
  ADC form_dx,Y
  STA ex
  LDA ly
  CLC
  ADC form_dy,Y
  STA ey
  TYA
  ASL A
  STA mptr
  ASL A
  CLC
  ADC mptr
  STA mptr
  CPY #$00
  BNE fol
  LDA frame
  ASL A
  CLC
  ADC mptr
  STA mptr
fol:
  LDA mptr
  CLC
  ADC facing
  TAY
  LDA meta_lo,Y
  STA ptr
  LDA meta_hi,Y
  STA ptr+1
  LDY #$00
  LDX oamx
spr:
  LDA (ptr),Y
  CLC
  ADC ey
  STA $0200,X
  INY
  INX
  LDA (ptr),Y
  STA $0200,X
  INY
  INX
  LDA (ptr),Y
  STA $0200,X
  INY
  INX
  LDA (ptr),Y
  CLC
  ADC ex
  STA $0200,X
  INY
  INX
  CPY #16
  BNE spr
  STX oamx
  INC ent
  LDA ent
  CMP #ENTITIES
  BNE ent_loop
  RTS

nmi:
  PHA
  LDA #$00
  STA OAMADDR
  LDA #$02
  STA OAMDMA
  LDA #$00
  STA PPUSCROLL
  STA PPUSCROLL
  LDA #%10001000
  STA PPUCTRL
  INC nmi_flag
  PLA
nmi_end:
  RTI
irq:
  RTI
"""


@dataclass
class RomBuild:
    rom: bytes
    program: Program
    sprites: T.TileSet
    background: T.TileSet
    nametable: bytes            # 960 tile bytes + 64 attribute bytes
    palettes: list[int]         # 32 PPU colour numbers
    metasprites: list[list[tuple[int, int, int, int]]]   # [(dy, tile, attr, dx)] × 4, index (entity*3+frame)*2+facing
    window: tuple[int, int]     # metatile origin in the area layout
    report: dict[str, Any]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.rom).hexdigest()


def _signed(v: int) -> int:
    return v & 0xFF


def _window(layout: dict[str, Any]) -> tuple[int, int]:
    w, h = int(layout["width"]), int(layout["height"])
    sx, sy = 0, 0
    for y, row in enumerate(layout["rows"]):
        if "S" in row:
            sx, sy = row.index("S"), y
    return max(0, min(w - WIN_W, sx - WIN_W // 2)), max(0, min(h - WIN_H, sy - WIN_H // 2))


def _asm_source(tables: str) -> str:
    consts = (f"START_X = {START[0]}\nSTART_Y = {START[1]}\nMIN_X = {BOUNDS[0]}\nMAX_X = {BOUNDS[1]}\n"
              f"MIN_Y = {BOUNDS[2]}\nMAX_Y = {BOUNDS[3]}\nENTITIES = {len(FORMATION)}\n")
    return consts + SRC + tables


def build(root: Path, profile: Profile) -> RomBuild:
    if not profile.rom or profile.family != "nes" or profile.ppu_numbers is None:
        raise ValueError(f"{profile.id}: no NES rom block")
    gen = root / "games" / "game-zero" / "assets" / "generated"
    spec = profile.rom
    area = spec["area"]
    layout = json.loads((gen / "tilemap" / f"{area}.json").read_text(encoding="utf-8"))
    tileset_img = T.load_rgba(gen / "tilemap" / f"{area}_tiles.png")
    ids = list(spec["party"]) + [spec["pet"]]
    strips = {i: T.load_rgba(gen / "sprite" / f"{i}.png") for i in ids}
    # only the frames the ROM shows are transcoded (CHR budget)
    frames = {}
    for i in ids:
        for f in (WALK_FRAMES if i == ids[0] else (0,)):
            frames[f"{i}#{f}"] = strips[i][:, f * 16:(f + 1) * 16]
    spr = T.transcode(frames, profile, "sprite")
    bg = T.transcode({area: tileset_img}, profile, "bg")
    ts = int(layout["tile_size"])
    legend = layout["legend"]
    wx, wy = _window(layout)
    # metatile index -> (TL, TR, BL, BR tile, sub-palette)
    meta: dict[int, tuple[list[int], int]] = {}
    for m in bg.maps[area]:
        mi = m["x"] // ts
        tl = meta.setdefault(mi, ([0, 0, 0, 0], m["pal"]))
        q = (1 if (m["x"] % ts) >= 8 else 0) + (2 if (m["y"] % ts) >= 8 else 0)
        tl[0][q] = m["tile"]
    names = bytearray(32 * 30)
    attr_pal = np.zeros((WIN_H + 1, WIN_W), dtype=np.int64)
    for my in range(WIN_H):
        for mx in range(WIN_W):
            g = layout["rows"][wy + my][wx + mx]
            mi = int(legend.get(g, 0))
            tiles, p = meta[mi]
            for q, t in enumerate(tiles):
                tx, ty = mx * 2 + (q & 1), my * 2 + (q >> 1)
                names[ty * 32 + tx] = t
            attr_pal[my, mx] = p
    attrs = bytearray(64)
    for ay in range(8):
        for ax in range(8):
            v = 0
            for q, (ox, oy) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
                my, mx = ay * 2 + oy, ax * 2 + ox
                if my < WIN_H + 1 and mx < WIN_W:
                    v |= int(attr_pal[my, mx]) << (2 * q)
            attrs[ay * 8 + ax] = v
    nametable = bytes(names + attrs)
    ppu = profile.ppu_numbers
    uni = ppu[bg.universal or 0]
    pals: list[int] = []
    for layer in (bg.palettes, spr.palettes):
        for i in range(4):
            sub = layer[i] if i < len(layer) else []
            pals += [uni] + [ppu[c] for c in (sub + [sub[-1] if sub else bg.universal or 0] * 3)[:3]]
    # metasprite tables: (entity, frame, facing)
    metas: list[list[tuple[int, int, int, int]]] = []
    for e, i in enumerate(ids):
        for fi in range(3):
            f = WALK_FRAMES[fi] if e == 0 else 0
            pl = spr.maps[f"{i}#{f}"]
            for facing in (0, 1):
                rows = []
                for m in pl:
                    dx, dy = m["x"] - 8, m["y"] - 8 - 1           # centred; OAM Y is scanline - 1
                    attr = m["pal"] | (0x40 if m["hflip"] else 0) | (0x80 if m["vflip"] else 0)
                    if facing:
                        dx = -dx - 8
                        attr ^= 0x40
                    rows.append((_signed(dy), m["tile"], attr, _signed(dx)))
                metas.append(rows)
    lines = ["palettes:", ".byte " + ", ".join(f"${p:02X}" for p in pals), "form_dx:",
             ".byte " + ", ".join(str(_signed(d[0])) for d in FORMATION), "form_dy:",
             ".byte " + ", ".join(str(_signed(d[1])) for d in FORMATION)]
    for k, rows in enumerate(metas):
        lines.append(f"meta{k}:")
        lines.append(".byte " + ", ".join(str(v) for r in rows for v in r))
    lines.append("meta_lo:")
    lines.append(".byte " + ", ".join(f"<meta{k}" for k in range(len(metas))))
    lines.append("meta_hi:")
    lines.append(".byte " + ", ".join(f">meta{k}" for k in range(len(metas))))
    lines.append("nametable:")
    for s in range(0, 1024, 32):
        lines.append(".byte " + ", ".join(f"${b:02X}" for b in nametable[s:s + 32]))
    lines += ["prg_end:", ".org $FFFA", ".word nmi, reset, irq"]
    prog = assemble(_asm_source("\n".join(lines) + "\n"), 0x8000)
    prg = bytes(prog.data)
    mem = profile.memory
    if len(prg) != int(mem["prg_rom"]):
        raise ValueError(f"PRG is {len(prg)} bytes, expected {mem['prg_rom']}")
    chr_ = bytearray(int(mem["chr_rom"]))
    for k, t in enumerate(bg.tiles[:256]):
        chr_[k * 16:(k + 1) * 16] = T.chr_bytes(t)
    for k, t in enumerate(spr.tiles[:256]):
        chr_[0x1000 + k * 16:0x1000 + (k + 1) * 16] = T.chr_bytes(t)
    mirroring = 1 if spec.get("mirroring") == "vertical" else 0
    header = b"NES\x1a" + bytes([len(prg) // 16384, len(chr_) // 8192, mirroring | ((int(spec.get("mapper", 0)) & 0x0F) << 4),
                                 int(spec.get("mapper", 0)) & 0xF0]) + bytes(8)
    rom = header + prg + bytes(chr_)
    code_end = prog.labels["palettes"] - 0x8000
    rep = {"window": [wx, wy], "prg_used": prog.labels["prg_end"] - 0x8000 + 6, "code_bytes": code_end,
           "chr_bg_tiles": len(bg.tiles), "chr_sprite_tiles": len(spr.tiles),
           "bg_sub_palettes": len(bg.palettes), "sprite_sub_palettes": len(spr.palettes),
           "nmi_cycles": prog.cycles("nmi", "nmi_end") + 514, "zero_page_bytes": 0x10, "oam_shadow_bytes": 256,
           "fidelity": {"sprites": spr.fidelity, "background": bg.fidelity}}
    return RomBuild(rom, prog, spr, bg, nametable, pals, metas, (wx, wy), rep)


def nes_rgb(profile: Profile) -> dict[int, tuple[int, int, int]]:
    from forge.retro.profiles import nes_ntsc_palette

    return dict(enumerate(nes_ntsc_palette()))


def render_expected(rb: RomBuild, profile: Profile, lx: int = START[0], ly: int = START[1], frame: int = 0,
                    facing: int = 0) -> np.ndarray:
    """Reference frame (240×256 PPU colour numbers) for a party position — what a correct PPU shows."""
    out = np.zeros((240, 256), dtype=np.int64)
    pals = rb.palettes
    nt, at = rb.nametable[:960], rb.nametable[960:]
    for ty in range(30):
        for tx in range(32):
            t = rb.background.tiles[nt[ty * 32 + tx]]
            a = at[(ty // 4) * 8 + tx // 4]
            sh = ((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2
            p = (a >> sh) & 3
            for y in range(8):
                for x in range(8):
                    v = int(t[y, x])
                    out[ty * 8 + y, tx * 8 + x] = pals[p * 4 + v] if v else pals[0]
    sprites = []
    for e, (dx, dy) in enumerate(FORMATION):
        fi = frame if e == 0 else 0
        rows = rb.metasprites[(e * 3 + fi) * 2 + facing]
        for (sdy, tile, attr, sdx) in rows:
            sdy = sdy - 256 if sdy >= 128 else sdy
            sdx = sdx - 256 if sdx >= 128 else sdx
            sprites.append((((ly + dy) + sdy) & 0xFF, tile, attr, ((lx + dx) + sdx) & 0xFF))
    line_count = np.zeros(240, dtype=np.int64)
    drawn = np.zeros((240, 256), dtype=bool)
    for (oy, tile, attr, ox) in sprites:          # OAM order: lower index wins
        t = rb.sprites.tiles[tile]
        if attr & 0x40:
            t = t[:, ::-1]
        if attr & 0x80:
            t = t[::-1, :]
        for y in range(8):
            sy = oy + 1 + y
            if sy >= 240:
                continue
            line_count[sy] += 1
            if line_count[sy] > 8:
                continue
            for x in range(8):
                sx = ox + x
                v = int(t[y, x])
                if sx < 256 and v and not drawn[sy, sx]:
                    out[sy, sx] = pals[16 + (attr & 3) * 4 + v]
                    drawn[sy, sx] = True
    return out


def sprites_per_scanline(rb: RomBuild) -> int:
    """Worst case over every reachable leader position (the formation is rigid, so it is position-independent
    while fully on screen)."""
    rows: dict[int, int] = {}
    for e, (dx, dy) in enumerate(FORMATION):
        for (sdy, _t, _a, _x) in rb.metasprites[e * 6]:
            sdy = sdy - 256 if sdy >= 128 else sdy
            for y in range(8):
                rows[dy + sdy + y] = rows.get(dy + sdy + y, 0) + 1
    return max(rows.values())
