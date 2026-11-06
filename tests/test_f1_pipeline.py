"""F1 Content Pipeline: imaging, PatternVault, gates, generators, determinism."""

from __future__ import annotations

import json
from pathlib import Path

from forge.gates import palette_gate, seamless_gate, solvability_gate
from forge.generators.tile import make_cave
from forge.imaging import Image
from forge.patternvault import PatternVault
from forge.pipeline import Context, load_briefs, run_brief


def test_png_roundtrip() -> None:
    img = Image(3, 2)
    img.set(0, 0, (255, 0, 0, 255))
    img.set(2, 1, (1, 2, 3, 128))
    back = Image.from_png(img.to_png())
    assert back.pixels == img.pixels


def test_patternvault_palettes_and_variants(root: Path) -> None:
    v = PatternVault(root)
    assert {"hero_teal", "enemy_ember", "cave_stone"} <= set(v.names())
    base, cb = v.get("enemy_ember"), v.get("enemy_ember", "deuteranopia")
    assert len(base) == len(cb) and base.colours != cb.colours


def test_palette_gate_rejects_stray_colour(root: Path) -> None:
    pal = PatternVault(root).get("hero_teal")
    img = Image(2, 1)
    img.set(0, 0, pal[0])
    assert palette_gate(img, [pal]).ok
    img.set(1, 0, (1, 2, 3, 255))
    assert not palette_gate(img, [pal]).ok


def test_solvability_gate() -> None:
    assert solvability_gate(["#####", "#S.E#", "#####"]).ok
    assert not solvability_gate(["#####", "#S#E#", "#####"]).ok


def test_cave_is_solvable_and_deterministic() -> None:
    c = {"width": 40, "height": 22, "min_path": 30}
    rows1, info1 = make_cave(c, 11)
    rows2, _ = make_cave(c, 11)
    assert rows1 == rows2
    assert solvability_gate(rows1).ok and info1["path_len"] >= 30
    assert make_cave(c, 12)[0] != rows1


def test_seamless_gate_on_dyeworks(root: Path) -> None:
    ctx = Context.create(root)
    from forge.generators.dyeworks import material
    albedo, normal, _ = material({"id": "t", "palette": "cave_stone", "size": 32, "seed": 5}, ctx)
    assert seamless_gate(albedo).ok
    # A hard vertical split is not seamless.
    bad = Image(16, 16)
    for y in range(16):
        for x in range(16):
            bad.set(x, y, (0, 0, 0, 255) if x < 8 else (255, 255, 255, 255))
    assert not seamless_gate(bad).ok


def test_all_briefs_pass_gates_and_match_committed_registry(root: Path) -> None:
    """Determinism gate: regenerating briefs reproduces the committed game assets byte-for-byte."""
    ctx = Context.create(root)
    reg = json.loads((ctx.export_root / "fabric_assets.json").read_text())
    for brief in load_briefs(root):
        out = run_brief(brief, ctx, export=False)
        assert out.ok, (brief["id"], [g for g in out.gates if not g.ok])
        for art in out.artifacts:
            committed = reg["assets"][brief["id"]]["files"][art.name]["sha256"]
            assert ctx.store.digest_bytes(art.data) == committed, f"{brief['id']}/{art.name} drifted"
            on_disk = root / "games/game-zero" / reg["assets"][brief["id"]]["files"][art.name]["res"].removeprefix("res://")
            assert on_disk.read_bytes() == art.data


def test_generators_within_budget(root: Path) -> None:
    ctx = Context.create(root)
    for brief in load_briefs(root):
        out = run_brief(brief, ctx, export=False)
        budget = [g for g in out.gates if g.gate == "budget"][0]
        assert budget.ok, budget.detail
