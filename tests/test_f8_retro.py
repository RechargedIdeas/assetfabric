"""F8 retro / console-style (0.8.0+f8): ForgeConsole units — profiles, palettes, LUTs, C1 solver, 6502 assembler,
ROMBuilder, EmulatorHarness, Q1 shimmer predictor, V1 frame maths, R1 generator. The end-to-end proof (Godot captures,
gamepad flow, emulator input) is `forge accept F8` (tests/test_game_increments.py)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from forge.retro import asm6502, colour, profiles, rom, transcode, validate


@pytest.fixture(scope="module")
def profs(root: Path) -> dict[str, profiles.Profile]:   # noqa: F811
    return profiles.load(root)


@pytest.fixture(scope="module")
def root() -> Path:   # module-scoped twin of the conftest fixture
    from tests.conftest import ROOT
    return ROOT


def test_registry_valid_and_integer_scaled(root: Path, profs: dict) -> None:
    raw = profiles.load_raw(root)
    assert profiles.validate(raw) == []
    assert raw["order"][0] == "off" and raw["default"] == "off"
    assert {p: profs[p].scale for p in profs} == {"gz-native": 4, "nes-style": 5, "gb-style": 8}
    for p in profs.values():
        assert p.logical[0] * p.scale == 1280 and p.logical[1] * p.scale == 720


def test_registry_rejects_non_integer_scale(root: Path) -> None:
    raw = profiles.load_raw(root)
    raw["profiles"]["nes-style"]["logical"] = [300, 169]
    assert any("integer" in e for e in profiles.validate(raw))


def test_nes_palette_is_computed_and_sane() -> None:
    pal = profiles.nes_ntsc_palette()
    assert len(pal) == 64
    r, g, b = pal[0x01]
    assert b > r and b > g                    # $01 blue
    r, g, b = pal[0x16]
    assert r > g and r > b                    # $16 red
    r, g, b = pal[0x1A]
    assert g > r and g > b                    # $1A green
    assert pal[0x30] == (255, 255, 255) and pal[0x0F] == (0, 0, 0)
    us = profiles.nes_usable()
    nums = [n for n, _ in us]
    assert len(us) == 54 and 0x0D not in nums and 0x1E not in nums and 0x0F in nums


def test_lut_pins_exact_colours(profs: dict, root: Path) -> None:
    pv = np.array([colour.hex_rgb(h) for h in profiles.patternvault_colours(root)], dtype=np.uint8)
    img, coll = colour.build_lut(profs["gz-native"].palette, pv)
    assert coll == [] and img.shape == (512, 512, 3)
    assert (colour.apply_lut(pv, img) == pv).all()          # Fabric-native: PatternVault art passes unchanged
    nes = profs["nes-style"]
    img2, _ = colour.build_lut(nes.palette, pv)
    out = colour.apply_lut(pv, img2)
    keys = {tuple(c) for c in nes.palette.tolist()}
    assert all(tuple(c) in keys for c in out.tolist())     # everything lands on the NES palette


def test_generator_gates_and_tree_in_sync(root: Path) -> None:
    from forge.accept_f8 import generator_part

    g = generator_part(root)
    assert all(g["gates"].values()), g
    assert all(g["artifacts_match_tree"].values()), "run `forge build`"
    table = json.loads((root / "games/game-zero/assets/generated/retro/retro.json").read_text())
    assert table["q1_scales"] == {"0.75": 1, "1.50": 2}


def test_signal_solver_separates_pair() -> None:
    pal = np.array([[0, 0, 0], [100, 100, 100], [200, 200, 200]], dtype=np.uint8)
    over, left = transcode.solve_signal_overrides([("#646464", "#6a6a6a", False)], pal, "lab", ["#646464", "#6a6a6a"])
    assert left == [] and len(over) == 1


def test_q1_scales_match_encounter_code(root: Path) -> None:
    src = (root / "games/game-zero/scenes/encounter.gd").read_text()
    literal = {float(x) for x in re.findall(r"s\.scale = Vector2\(([\d.]+), [\d.]+\)", src)}
    listed = set(profiles.load_raw(root)["q1"]["sprite_scales"])
    assert literal - {1.0} == listed


def test_shimmer_predictor() -> None:
    assert validate.shimmer(1.0, snap=True) == {"shimmer": 0.0, "texel_loss": 0.0}
    assert validate.shimmer(2.0, snap=True) == {"shimmer": 0.0, "texel_loss": 0.0}
    bad = validate.shimmer(0.4, snap=False)
    assert bad["shimmer"] > 0 and bad["texel_loss"] > 0.5
    assert [validate.q1_scale(s) for s in (0.75, 1.0, 1.5, 2.0)] == [1, 1, 2, 2]


def test_v1_frame_maths(profs: dict, root: Path) -> None:
    p = profs["nes-style"]
    pv = np.array([colour.hex_rgb(h) for h in profiles.patternvault_colours(root)], dtype=np.uint8)
    lut, _ = colour.build_lut(p.palette, pv)
    rng = np.random.default_rng(1)
    cells = pv[rng.integers(0, len(pv), (144, 256))]
    src = np.repeat(np.repeat(cells, 5, 0), 5, 1)
    out = validate.model_pass(src, 5, lut)
    assert validate.block_uniformity(out, 5) == 1.0
    assert validate.palette_conformance(out, p.palette) == 1.0
    assert validate.block_uniformity(src[2:, 3:], 5) < 1.0          # a misaligned frame is caught
    scan = out.astype(np.int64).copy()
    rows = (np.arange(720) % 5 + 0.5) / 5 >= 0.5
    scan[rows] = np.floor(scan[rows] * 0.65 + 0.5)
    assert validate.scanline_structure(out, scan.astype(np.uint8), 5, 0.35) == {"top_rows_unchanged": 1.0,
                                                                                 "bottom_rows_darkened": 1.0}


def test_assembler_encoding_and_cycles() -> None:
    p = asm6502.assemble("""
X0 = $10
.org $8000
start: LDA #$01
  STA $2000
  LDA (X0),Y
  LDX X0
loop: DEX
  BNE loop
  JMP start
nmi: PHA
  STA $4014
  PLA
done:
  RTI
""")
    assert p.data.hex() == "a9018d0020b110a610cad0fd4c0080488d14406840"
    assert p.cycles("nmi", "done") == 3 + 4 + 4
    with pytest.raises(asm6502.AsmError):
        p.cycles("loop", "nmi")                 # backward branch inside the window
    with pytest.raises(asm6502.AsmError):
        asm6502.assemble("LDA nowhere")


def test_transcoder_meets_nes_constraints(profs: dict, root: Path) -> None:
    gen = root / "games/game-zero/assets/generated/sprite"
    imgs = {s: transcode.load_rgba(gen / f"{s}.png") for s in ("spr_kael", "spr_nyra", "spr_bram", "spr_sola", "spr_ember_fox")}
    ts = transcode.transcode(imgs, profs["nes-style"], "sprite")
    assert len(ts.palettes) <= 4 and all(len(p) <= 3 for p in ts.palettes)
    assert all(t.max() <= 3 and t.shape == (8, 8) for t in ts.tiles)
    assert ts.fidelity["mean_de_console"] >= ts.fidelity["mean_de_quantise"] - 1e-9
    t = np.zeros((8, 8), dtype=np.uint8)
    t[0, 0], t[0, 7], t[7, 0] = 1, 2, 3
    assert transcode.chr_bytes(t) == bytes([0x80, 0, 0, 0, 0, 0, 0, 0x80, 0x01, 0, 0, 0, 0, 0, 0, 0x80])


def test_rom_build_deterministic_and_within_budgets(profs: dict, root: Path) -> None:
    from forge.retro import readiness

    p = profs["nes-style"]
    a, b = rom.build(root, p), rom.build(root, p)
    assert a.rom == b.rom and len(a.rom) == 16 + 32768 + 8192
    assert a.rom[:4] == b"NES\x1a" and a.rom[4] == 2 and a.rom[5] == 1
    vec = a.rom[16 + 0x7FFA:16 + 0x8000]
    nmi, reset, irq = (vec[i] | vec[i + 1] << 8 for i in (0, 2, 4))
    assert reset == 0x8000 and nmi == a.program.labels["nmi"] and irq == a.program.labels["irq"]
    chk = readiness.check_rom(a, p)
    assert chk["ok"], chk["errors"]
    assert rom.sprites_per_scanline(a) <= 8


def test_readiness_all_profiles(profs: dict, root: Path) -> None:
    from forge.retro import readiness

    for pid, p in profs.items():
        r = readiness.check(root, p)
        assert r["ok"], (pid, r["errors"])


def test_emulator_boots_rom(profs: dict, root: Path) -> None:
    from forge.retro import emulator

    if not emulator.available():
        pytest.skip("cynes not installed")
    import tempfile

    import cynes
    p = profs["nes-style"]
    rb = rom.build(root, p)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "g.nes"
        f.write_bytes(rb.rom)
        nes = cynes.NES(str(f))
        frame = nes.step(frames=10)
        assert not nes.has_crashed
    m = emulator.partition_match(frame, rom.render_expected(rb, p))
    assert m["match"] == 1.0 and m["bijective"]


def test_locale_keys_present(root: Path) -> None:
    loc = json.loads((root / "games/game-zero/locale/en.json").read_text())
    for pid in profiles.load_raw(root)["order"]:
        assert f"retro.profile.{pid}" in loc
    for k in ("settings.retro", "settings.retro.changed", "settings.scanlines", "settings.on", "settings.off"):
        assert k in loc
