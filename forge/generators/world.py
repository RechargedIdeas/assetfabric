"""Codegen-World (F6) — `content/world/*.yaml` → `data/generated/world.json`.

One artifact the game loads at runtime (no hand wiring): items, crops, recipes, shop, XP curve,
tier loot tables, quests (+ compiled parallel statechart), adaptive-music rules and the slice
world graph (areas, links, gather nodes, packs).
Gates:
- `schema` — required sections / fields present.
- `cross_refs` — every item, crop, recipe, enemy, fighter, tilemap and music track referenced exists;
  loot tables cover every enemy tier in the roster.
- `quest_chart` — static soft-lock analysis of the compiled quest statechart (forge/statechart.py).
- `economy_solvable` — main-quest guards are satisfiable from deterministic sources only
  (forge/world.py `solvability`), so a bad loot roll can never soft-lock the slice.
- `loot_tables` — positive weights, valid qty ranges.
- `music_rules` — every macro state names ≥ 1 audible stem that each biome track generates.
- `budget`.
"""

from __future__ import annotations

import json
import time
from typing import Any

import yaml

from forge.gates import GateResult, budget_gate
from forge.generators import Artifact, GeneratorOutput, register

SECTIONS = ("economy", "loot", "quests", "music", "areas")


def load_world_sources(root: Any, src: str = "content/world") -> dict[str, Any]:
    d = root / src
    return {name: yaml.safe_load((d / f"{name}.yaml").read_text(encoding="utf-8")) for name in SECTIONS}


def build_world(raw: dict[str, Any]) -> dict[str, Any]:
    from forge.world import compile_quests

    eco, loot, q, mus, ar = (raw[k] for k in SECTIONS)
    return {
        "schema_version": "1.0",
        "items": {i["id"]: {**i, "name_key": f"item.{i['id']}"} for i in eco["items"]},
        "crops": {c["id"]: c for c in eco["crops"]},
        "recipes": {r["id"]: r for r in eco["recipes"]},
        "shop": eco.get("shop", {}),
        "start_kit": eco.get("start_kit", {}),
        "farm": eco.get("farm", {"plots": 4}),
        "xp": eco["xp"],
        "loot": {"tiers": {str(k): v for k, v in loot["tiers"].items()}, "enemies": loot.get("enemies", {})},
        "quests": q["quests"],
        "quest_chart": compile_quests(q["quests"]),
        "music": mus,
        "start_area": ar["start_area"],
        "areas": {a["id"]: a for a in ar["areas"]},
    }


@register("world")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    from forge.generators.codegen import load_roster
    from forge.pipeline import load_briefs
    from forge.statechart import analyze
    from forge.world import loot_ev, solvability

    t0 = time.perf_counter()
    gates: list[GateResult] = []
    try:
        raw = load_world_sources(ctx.root, brief.get("source", "content/world"))
        world = build_world(raw)
        gates.append(GateResult("schema", True))
    except (KeyError, TypeError, OSError, yaml.YAMLError) as exc:
        return GeneratorOutput([], [GateResult("schema", False, {"error": repr(exc)})], {"kind": "world"})

    roster = load_roster(ctx.root, brief.get("roster", "content/roster"))
    enemies = {e["id"]: e for e in roster["enemies"]["enemies"]}
    fighters = {f["id"]: f for f in roster["fighters"]["fighters"]}
    briefs = {b["id"]: b for b in load_briefs(ctx.root) if b.get("kind") in ("tilemap", "audio")}
    items = world["items"]
    miss: list[str] = []

    def need_item(i: str, where: str) -> None:
        if i != "none" and i not in items:
            miss.append(f"{where}→item:{i}")

    for c in world["crops"].values():
        need_item(c["id"], f"crop {c['id']}")
        need_item(c["seed"], f"crop {c['id']}")
    for r in world["recipes"].values():
        for i in list(r["in"]) + list(r["out"]):
            need_item(i, f"recipe {r['id']}")
    for i in list(world["shop"]) + list(world["start_kit"]):
        need_item(i, "shop/start_kit")
    for i in items.values():
        if i["kind"] == "seed" and i.get("crop") not in world["crops"]:
            miss.append(f"seed {i['id']}→crop:{i.get('crop')}")
    for tier, t in world["loot"]["tiers"].items():
        for e in t["table"] + t.get("guaranteed", []):
            need_item(e["item"], f"loot tier {tier}")
    for ref, t in world["loot"]["enemies"].items():
        if ref not in enemies:
            miss.append(f"loot extra→enemy:{ref}")
        for e in t["table"]:
            need_item(e["item"], f"loot {ref}")
    tiers_needed = {str(e["tier"]) for e in enemies.values()}
    miss += [f"loot: no table for tier {t}" for t in sorted(tiers_needed - set(world["loot"]["tiers"]))]
    node_counts: dict[str, int] = {}
    for a in world["areas"].values():
        tb = briefs.get(a["tilemap"])
        if not tb:
            miss.append(f"area {a['id']}→tilemap:{a['tilemap']}")
            continue
        for glyph, item in a.get("nodes", {}).items():
            need_item(item, f"area {a['id']} node")
            node_counts[item] = node_counts.get(item, 0) + int(tb.get("constraints", {}).get("nodes", 0))
        for link in a.get("links", {}).values():
            if link["to"] not in world["areas"]:
                miss.append(f"area {a['id']}→link:{link['to']}")
        for p in a.get("packs", []):
            for u in p["units"]:
                if u["ref"] not in enemies:
                    miss.append(f"area {a['id']}→enemy:{u['ref']}")
            if int(p["spawn"]) >= int(tb.get("constraints", {}).get("enemies", 1)):
                miss.append(f"area {a['id']}→spawn index {p['spawn']} ≥ tilemap spawns")
    for q in world["quests"]:
        for st in q["stages"]:
            r = st.get("reward", {})
            if r.get("unlock") and (r["unlock"] not in fighters or fighters[r["unlock"]].get("base")):
                miss.append(f"quest {q['id']}.{st['id']}→unlock:{r['unlock']}")
            for i in r.get("item", {}):
                need_item(i, f"quest {q['id']} reward")
    mus = world["music"]
    stems_by_track: dict[str, set[str]] = {}
    for b, spec in mus["biomes"].items():
        tb = briefs.get(spec["track"])
        if not tb:
            miss.append(f"music biome {b}→track:{spec['track']}")
        else:
            stems_by_track[spec["track"]] = set(tb.get("stems", ["ambient", "tension", "combat", "boss"]))
    gates.append(GateResult("cross_refs", not miss, {"missing": miss}))

    qa = analyze(world["quest_chart"])
    gates.append(GateResult("quest_chart", bool(qa["ok"]), {"regions": {k: v for k, v in qa["regions"].items()}}))
    sol = solvability(world, node_counts)
    gates.append(GateResult("economy_solvable", sol["ok"], {"missing": sol["missing"], "node_counts": node_counts}))
    bad_loot = []
    for tier, t in world["loot"]["tiers"].items():
        for e in t["table"] + t.get("guaranteed", []):
            if "weight" in e and float(e["weight"]) <= 0:
                bad_loot.append(f"tier {tier} {e['item']} weight")
            if "qty" in e and not (0 < e["qty"][0] <= e["qty"][1]):
                bad_loot.append(f"tier {tier} {e['item']} qty {e['qty']}")
    gates.append(GateResult("loot_tables", not bad_loot, {"bad": bad_loot}))
    bad_mus = []
    for state, vols in mus["states"].items():
        audible = [s for s, v in vols.items() if float(v) > -60]
        if not audible:
            bad_mus.append(f"state {state} silent")
        for track, stems in stems_by_track.items():
            if not any(s in stems for s in audible):
                bad_mus.append(f"state {state}: track {track} has none of {audible}")
    gates.append(GateResult("music_rules", not bad_mus and int(mus.get("fade_ticks", 0)) > 0, {"bad": bad_mus}))
    data = (json.dumps(world, indent=1, sort_keys=True) + "\n").encode()
    elapsed = (time.perf_counter() - t0) * 1000
    gates.append(budget_gate(elapsed, len(data), float(brief.get("budget_ms", 2000)), 256 * 1024))
    return GeneratorOutput([Artifact("world.json", data, "application/json")], gates,
                           {"kind": "world", "loot_ev": loot_ev(world), "supply": sol["supply"], "node_counts": node_counts,
                            "quests": [q["id"] for q in world["quests"]], "model_id": "Codegen-World", "model_version": "1"})
