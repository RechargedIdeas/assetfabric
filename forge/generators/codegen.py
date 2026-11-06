"""Codegen — roster YAML (fighters / pets / enemies / abilities) → Game Zero data.

Outputs (GAME_SPEC §7 "Ability YAML → GDScript Ability + .tres"):
- `game_data.json`: resolved stats per level, tier-scaled enemies, pet rules.
- `abilities/<id>.tres`: Godot Resources using `res://data/ability.gd`.
Gates: JSON Schema, cross-references (abilities, palettes), roster shape
(4 base fighters, 3 starter pets), stat sanity.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from forge.gates import GateResult, budget_gate
from forge.generators import Artifact, GeneratorOutput, register

LEVELS = 10


def load_roster(root: Path, src_dir: str = "content/roster") -> dict[str, Any]:
    d = Path(src_dir) if Path(src_dir).is_absolute() else root / src_dir
    merged: dict[str, Any] = {}
    for name in ("abilities", "fighters", "pets", "enemies"):
        merged[name] = yaml.safe_load((d / f"{name}.yaml").read_text(encoding="utf-8"))
    return merged


def diminishing(total: float, cap: float) -> float:
    """Diminishing-returns stacking with a hard cap: cap * (1 - e^(-total/cap))."""
    if cap <= 0:
        return 0.0
    return round(cap * (1 - math.exp(-total / cap)), 4)


def _level_table(stats: dict[str, Any], growth: float) -> list[dict[str, float]]:
    out = []
    for lv in range(1, LEVELS + 1):
        m = 1 + growth * (lv - 1)
        out.append({
            "level": lv, "hp": round(stats["hp"] * m), "atk": round(stats["atk"] * m, 2),
            "def": round(stats["def"] * (1 + growth * 0.5 * (lv - 1)), 2), "speed": stats["speed"],
        })
    return out


def _tres(ab: dict[str, Any]) -> bytes:
    lines = [
        '[gd_resource type="Resource" script_class="FabricAbility" load_steps=2 format=3]',
        "",
        '[ext_resource type="Script" path="res://data/ability.gd" id="1_ab"]',
        "",
        "[resource]",
        'script = ExtResource("1_ab")',
        f'id = "{ab["id"]}"',
        f'kind = "{ab["type"]}"',
        f'target = "{ab["target"]}"',
        f'power = {float(ab["power"])}',
        f'range = {float(ab["range"])}',
        f'radius = {float(ab.get("radius", 0))}',
        f'cooldown = {int(ab["cooldown"])}',
        f'windup = {int(ab["windup"])}',
        f'duration = {int(ab.get("duration", 0))}',
        f'threshold = {float(ab.get("threshold", 0))}',
        f'name_key = "ability.{ab["id"]}"',
        "",
    ]
    return "\n".join(lines).encode()


@register("codegen")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    raw = load_roster(ctx.root, brief.get("source", "content/roster"))
    flat = {"abilities": raw["abilities"]["abilities"], "fighters": raw["fighters"]["fighters"],
            "pets": raw["pets"]["pets"], "enemies": raw["enemies"]["enemies"]}
    schema = json.loads((ctx.root / "docs/schemas/roster.schema.json").read_text())
    gates: list[GateResult] = []
    try:
        jsonschema.validate(flat, schema)
        gates.append(GateResult("schema", True))
    except jsonschema.ValidationError as exc:
        gates.append(GateResult("schema", False, {"error": exc.message}))
        return GeneratorOutput([], gates, {"kind": "codegen"})

    ab_ids = {a["id"] for a in flat["abilities"]}
    missing: list[str] = []
    palettes = set(ctx.vault.names())
    for group in ("fighters", "pets", "enemies"):
        for u in flat[group]:
            missing += [f"{u['id']}→{a}" for a in u["abilities"] if a not in ab_ids]
            if u["sprite"]["palette"] not in palettes:
                missing.append(f"{u['id']}→palette:{u['sprite']['palette']}")
    gates.append(GateResult("cross_refs", not missing, {"missing": missing}))
    base = [f for f in flat["fighters"] if f.get("base")]
    starters = [p for p in flat["pets"] if p.get("starter")]
    gates.append(GateResult("roster_shape", len(base) == 4 and len(starters) == 3 and len(flat["fighters"]) > 4,
                            {"base_fighters": len(base), "starter_pets": len(starters), "fighters": len(flat["fighters"])}))

    growth = float(raw["fighters"].get("growth_default", 0.1))
    tier_scale = {int(k): float(v) for k, v in raw["enemies"]["tier_scale"].items()}
    pet_rules = {"max_pets_per_character": raw["pets"]["max_pets_per_character"],
                 "bonus_caps": raw["pets"]["bonus_caps"], "ally_share": raw["pets"]["ally_share"]}
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "abilities": {a["id"]: {**a, "name_key": f"ability.{a['id']}", "tres": f"res://data/generated/abilities/{a['id']}.tres"} for a in flat["abilities"]},
        "fighters": {f["id"]: {"role": f["role"], "base": bool(f.get("base")), "unlock": f.get("unlock"),
                               "abilities": f["abilities"], "sprite_id": f"spr_{f['id']}", "levels": _level_table(f["stats"], growth)}
                     for f in flat["fighters"]},
        "pets": {p["id"]: {"style": p["style"], "starter": bool(p.get("starter")), "abilities": p["abilities"],
                           "bonus": p["bonus"], "sprite_id": f"spr_{p['id']}", "stats": p["stats"]} for p in flat["pets"]},
        "enemies": {e["id"]: {"tier": e["tier"], "weakness": e.get("weakness"), "abilities": e["abilities"], "sprite_id": f"spr_{e['id']}",
                              "stats": {k: (round(v * tier_scale[e["tier"]], 2) if k in ("hp", "atk", "def") else v) for k, v in e["stats"].items()}}
                    for e in flat["enemies"]},
        "pet_rules": pet_rules,
    }
    sanity = [f"{gid}:{uid}" for gid in ("fighters",) for uid, u in data[gid].items() if u["levels"][0]["hp"] <= 0]
    gates.append(GateResult("stat_sanity", not sanity, {"bad": sanity}))
    arts = [Artifact("game_data.json", (json.dumps(data, indent=1, sort_keys=True) + "\n").encode(), "application/json")]
    arts += [Artifact(f"abilities/{a['id']}.tres", _tres(a), "application/x-godot-resource") for a in flat["abilities"]]
    elapsed = (time.perf_counter() - t0) * 1000
    gates.append(budget_gate(elapsed, sum(len(a.data) for a in arts), float(brief.get("budget_ms", 1000)), 512 * 1024))
    return GeneratorOutput(arts, gates, {"kind": "codegen", "counts": {k: len(v) for k, v in flat.items()},
                                         "model_id": "Codegen", "model_version": "1"})


def sprite_briefs(root: Path, src_dir: str = "content/roster") -> list[dict[str, Any]]:
    """Derive one G1-Sprite brief per roster unit (zero manual wiring)."""
    raw = load_roster(root, src_dir)
    out = []
    for group, tag in (("fighters", "character"), ("pets", "pet"), ("enemies", "enemy")):
        for u in raw[group][group]:
            sp = u["sprite"]
            out.append({"id": f"spr_{u['id']}", "kind": "sprite", "archetype": sp["archetype"], "palette": sp["palette"],
                        "seed": sp["seed"], "size": 16, "tags": [tag, f"roster:{u['id']}"], "_source": f"{src_dir}/{group}.yaml"})
    return out
