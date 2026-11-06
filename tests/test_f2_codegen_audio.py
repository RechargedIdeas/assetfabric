"""F2: codegen (roster → game data + .tres) and G1-Audio stems."""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

from forge.generators.codegen import diminishing, load_roster, sprite_briefs
from forge.pipeline import Context, load_briefs, run_brief


def _brief(root: Path, bid: str) -> dict:
    return {b["id"]: b for b in load_briefs(root)}[bid]


def test_codegen_gates_and_outputs(root: Path) -> None:
    ctx = Context.create(root)
    out = run_brief(_brief(root, "roster"), ctx, export=False)
    assert out.ok, [g for g in out.gates if not g.ok]
    names = {a.name for a in out.artifacts}
    assert "game_data.json" in names
    data = json.loads(next(a.data for a in out.artifacts if a.name == "game_data.json"))
    assert sum(1 for f in data["fighters"].values() if f["base"]) == 4
    assert sum(1 for p in data["pets"].values() if p["starter"]) == 3
    for ab in data["abilities"]:
        assert f"abilities/{ab}.tres" in names
    kael = data["fighters"]["kael"]["levels"]
    assert len(kael) == 10 and kael[9]["hp"] > kael[0]["hp"]
    brute = data["enemies"]["rock_brute"]
    assert brute["tier"] == 2 and brute["stats"]["hp"] == 64  # 40 * tier-2 scale 1.6


def test_codegen_rejects_bad_ability_ref(root: Path, tmp_path: Path) -> None:
    import shutil

    from forge.generators.codegen import generate

    src = tmp_path / "roster"
    shutil.copytree(root / "content/roster", src)
    f = src / "fighters.yaml"
    f.write_text(f.read_text().replace("[shield_bash, slash]", "[no_such_move, slash]"))
    res = generate({"id": "roster_bad", "source": str(src)}, Context.create(root))
    assert not res.ok
    assert any(g.gate == "cross_refs" and not g.ok for g in res.gates)


def test_diminishing_returns_cap() -> None:
    assert diminishing(0, 0.3) == 0
    assert diminishing(0.15, 0.3) < 0.15
    assert diminishing(10, 0.3) <= 0.3
    assert diminishing(0.3, 0.3) > diminishing(0.15, 0.3)


def test_sprite_briefs_derived_for_every_unit(root: Path) -> None:
    roster = load_roster(root)
    n = sum(len(roster[g][g]) for g in ("fighters", "pets", "enemies"))
    briefs = sprite_briefs(root)
    assert len(briefs) == n and all(b["kind"] == "sprite" for b in briefs)


def test_audio_stems_valid_wav(root: Path) -> None:
    ctx = Context.create(root)
    out = run_brief(_brief(root, "music_cave"), ctx, export=False)
    assert out.ok, [g for g in out.gates if not g.ok]
    stems = [a for a in out.artifacts if "_" in a.name and not a.name.startswith("sfx_")]
    assert {a.name.rsplit("_", 1)[1] for a in stems} == {"ambient.wav", "tension.wav", "combat.wav", "boss.wav"}
    with wave.open(io.BytesIO(stems[0].data)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == 22050
        assert w.getnframes() == 22050 * 4
