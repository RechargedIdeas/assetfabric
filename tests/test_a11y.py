"""G-A11Y-01 (0.7.10): colour-blind remap table + its distance gate, input schema coverage, no hard-coded keys."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from forge.a11y import collateral, delta_e, game_table, remap_table, report, simulate
from forge.patternvault import PatternVault


def test_cvd_simulation_sanity() -> None:
    # greys are unchanged by every deficiency; red/green collapse for deuteranopes
    for d in ("deuteranopia", "protanopia", "tritanopia"):
        r, g, b = simulate("#808080", d)
        assert abs(r - g) < 0.01 and abs(g - b) < 0.01
    assert delta_e("#e04040", "#40c060") > 100
    assert delta_e("#e04040", "#40c060", "deuteranopia") < 20


def test_shipped_variants_pass_the_gate(root: Path) -> None:
    r = report(PatternVault(root))
    assert r["ok"], r
    for rows in r["variants"].values():
        assert all(x["variant_seen"] >= r["min_delta_e"] and x["variant_seen"] >= x["default_seen"] for x in rows)
    t = game_table(PatternVault(root))
    assert t["variants"][0] == "default" and set(t["variants"][1:]) == set(PatternVault(root).variants())
    assert set(t["ui"]) == {"plot_growing", "plot_ready"}


def test_gate_catches_a_bad_variant_and_collateral(root: Path) -> None:
    v = PatternVault(root)
    bad = copy.deepcopy(v)
    bad.data["colorblind_variants"]["deuteranopia"]["ui_retro"] = list(v.data["palettes"]["ui_retro"]["colours"])
    assert not report(bad)["ok"]                      # red vs green UI collapses again
    coll = copy.deepcopy(v)
    del coll.data["colorblind_variants"]["protanopia"]["hero_amber"]   # #c2413a is also hero_amber's accent
    assert collateral(coll) and not report(coll)["ok"]


def test_world_json_carries_the_table(root: Path) -> None:
    w = json.loads((root / "games/game-zero/data/generated/world.json").read_text(encoding="utf-8"))
    assert w["a11y"] == game_table(PatternVault(root))
    assert remap_table(PatternVault(root)) == w["a11y"]["palettes"]


def test_no_hard_coded_keys_in_scenes(root: Path) -> None:
    """Every key the game reads goes through the InputMap (rebindable); only the input schema names keys."""
    game = root / "games" / "game-zero"
    for p in list((game / "scenes").glob("*.gd")) + list((game / "world").glob("*.gd")) + [game / "ui" / "settings_menu.gd"]:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"is_key_pressed|KEY_[A-Z0-9]+", text.replace("KEY_ESCAPE", "")), p.name


def test_every_action_has_keyboard_and_gamepad_or_is_typed(root: Path) -> None:
    fab = (root / "games/game-zero/autoload/fabric.gd").read_text(encoding="utf-8")
    schema = fab[fab.index("const INPUT_SCHEMA"):fab.index("## Order of the rows")]
    rows = re.findall(r'^\t"([a-z0-9_]+)": \{"keys": \[([^\]]*)\], "pad": \[([^\]]*)\]', schema, re.M)
    assert len(rows) >= 17
    for action, keys, pad in rows:
        assert keys.strip(), action
        assert pad.strip() or action == "command", action       # typing a command needs a keyboard
    order = re.search(r"const ACTION_ORDER := \[(.*?)\]", fab, re.S).group(1)
    assert set(re.findall(r'"([a-z0-9_]+)"', order)) == {a for a, _, _ in rows}
