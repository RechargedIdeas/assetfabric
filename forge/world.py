"""F6 world rules — Python twin of `games/game-zero/world/*.gd` (quests, farming, loot, music).

Loads `games/game-zero/data/generated/world.json` (written by the `world` codegen generator from
`content/world/*.yaml`). Everything here is deterministic and mirrored in GDScript:

- **Loot** — tier tables + per-enemy extras, seeded 31-bit LCG (same constants as CombatSim);
  `roll_loot` must produce the same drops as `world/loot.gd` for the same rng state (parity-checked
  by `forge accept F6`).
- **Quests** — each quest is one region of a parallel statechart (forge/statechart.py semantics);
  guards read world counters: ``have:<item>>=n`` · ``total:<counter>>=n`` · ``flag:<name>``,
  joined with ``&``. `compile_quests` emits the chart; `eval_guard` is the shared guard language.
- **Farming** — plot growth in world ticks; `crop_ready`.
- **Economy solvability** — every item a main-quest guard demands has a deterministic source
  (start kit, crop from an obtainable seed, gather node, guaranteed boss drop, or a recipe whose
  inputs are deterministic) in sufficient quantity, so no quest can soft-lock on a bad loot roll.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge.paths import find_repo_root

WORLD_REL = "games/game-zero/data/generated/world.json"
LCG_A, LCG_C, LCG_M = 1103515245, 12345, 0x7FFFFFFF
DONE = "done"


def load_world(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    return json.loads((root / WORLD_REL).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- rng / loot

class Lcg:
    """31-bit LCG, identical to CombatSim.rand01 and world/loot.gd."""

    def __init__(self, state: int) -> None:
        self.state = int(state) & LCG_M

    def rand01(self) -> float:
        self.state = (self.state * LCG_A + LCG_C) & LCG_M
        return self.state / 2147483648.0


def _qty(rng: Lcg, q: list[int]) -> int:
    lo, hi = int(q[0]), int(q[1])
    return min(hi, lo + int(rng.rand01() * (hi - lo + 1)))


def _pick(rng: Lcg, table: list[dict[str, Any]]) -> dict[str, Any] | None:
    total = sum(float(e["weight"]) for e in table)
    if total <= 0:
        return None
    r = rng.rand01() * total
    acc = 0.0
    for e in table:
        acc += float(e["weight"])
        if r < acc:
            return e
    return table[-1]


def roll_loot(world: dict[str, Any], tier: int, ref: str, rng: Lcg) -> list[list[Any]]:
    """Drops for one defeated hostile: [[item, qty], ...] in roll order ("none" slots omitted)."""
    out: list[list[Any]] = []
    t = world["loot"]["tiers"].get(str(tier))
    if t:
        for g in t.get("guaranteed", []):
            out.append([g["item"], _qty(rng, g["qty"])])
        for _ in range(int(t.get("rolls", 1))):
            e = _pick(rng, t["table"])
            if e and e["item"] != "none":
                out.append([e["item"], _qty(rng, e["qty"])])
    extra = world["loot"]["enemies"].get(ref)
    if extra:
        e = _pick(rng, extra["table"])
        if e and e["item"] != "none":
            out.append([e["item"], _qty(rng, e["qty"])])
    return out


def loot_ev(world: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Expected drops per kill, per tier (designer report; also in the generator meta)."""
    ev: dict[str, dict[str, float]] = {}
    for tier, t in world["loot"]["tiers"].items():
        d: dict[str, float] = {}
        for g in t.get("guaranteed", []):
            d[g["item"]] = d.get(g["item"], 0) + (g["qty"][0] + g["qty"][1]) / 2
        total = sum(float(e["weight"]) for e in t["table"])
        for e in t["table"]:
            if e["item"] != "none":
                d[e["item"]] = d.get(e["item"], 0) + int(t.get("rolls", 1)) * e["weight"] / total * (e["qty"][0] + e["qty"][1]) / 2
        ev[tier] = {k: round(v, 3) for k, v in sorted(d.items())}
    return ev


# ----------------------------------------------------------------------------- quests

def eval_guard(expr: str, counters: dict[str, Any]) -> bool:
    """Guard language shared with world/quest_log.gd. `counters` = {"have": {...}, "total": {...}, "flag": {...}}."""
    if not expr:
        return True
    for part in expr.split("&"):
        part = part.strip()
        kind, _, rest = part.partition(":")
        if kind == "flag":
            if not counters.get("flag", {}).get(rest):
                return False
            continue
        name, _, n = rest.partition(">=")
        if float(counters.get(kind, {}).get(name, 0)) < float(n or 1):
            return False
    return True


def compile_quests(quests: list[dict[str, Any]]) -> dict[str, Any]:
    """Quest list → parallel statechart JSON (one region per quest; guards are the raw expressions)."""
    regions: dict[str, Any] = {}
    for q in quests:
        stages = q["stages"]
        states: dict[str, Any] = {}
        for i, st in enumerate(stages):
            nxt = stages[i + 1]["id"] if i + 1 < len(stages) else DONE
            tr: Any = {"target": nxt, "guard": st["guard"]} if st.get("guard") else nxt
            states[st["id"]] = {"on": {st["when"]: tr}}
        states[DONE] = {"final": True}
        regions[q["id"]] = {"initial": stages[0]["id"], "states": states}
    return {"id": "quests", "regions": regions}


class QuestLog:
    """Python twin of world/quest_log.gd (used for parity replays and tests)."""

    def __init__(self, world: dict[str, Any]) -> None:
        from forge.statechart import StateChart

        self.world = world
        self.counters: dict[str, Any] = {"have": {}, "total": {}, "flag": {}}
        self.chart = StateChart(world["quest_chart"], guard=lambda g, _r, _s: eval_guard(g, self.counters))

    def send(self, event: str, counters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if counters is not None:
            self.counters = counters
        return self.chart.send(event)

    def stage(self, quest: str) -> str:
        return self.chart.active[quest]


def stage_index(world: dict[str, Any], quest: str, stage: str) -> int:
    for q in world["quests"]:
        if q["id"] == quest:
            ids = [s["id"] for s in q["stages"]] + [DONE]
            return ids.index(stage) if stage in ids else -1
    return -1


# ----------------------------------------------------------------------------- farming

def crop_ready(world: dict[str, Any], plot: dict[str, Any], tick: int) -> bool:
    crop = world["crops"].get(plot.get("crop", ""))
    return bool(crop) and tick - int(plot["planted"]) >= int(crop["grow_ticks"])


# ----------------------------------------------------------------------------- solvability

def deterministic_supply(world: dict[str, Any], node_counts: dict[str, int]) -> dict[str, float]:
    """Upper bound of each item obtainable *without* random drops (∞ for shop-buyable via guaranteed coin)."""
    sup: dict[str, float] = {k: float(v) for k, v in world["start_kit"].items()}
    for item, n in node_counts.items():
        sup[item] = sup.get(item, 0) + n
    for t in world["loot"]["tiers"].values():
        for g in t.get("guaranteed", []):
            sup[g["item"]] = sup.get(g["item"], 0) + g["qty"][0]
    for q in world["quests"]:
        for st in q["stages"]:
            r = st.get("reward", {})
            for k, v in r.get("item", {}).items():
                sup[k] = sup.get(k, 0) + v
            if r.get("coin"):
                sup["coin"] = sup.get("coin", 0) + r["coin"]
    # seeds: start kit + whatever guaranteed coin can buy; crops: seeds × yield (one harvest each)
    coin = sup.get("coin", 0)
    for seed, price in sorted(world["shop"].items(), key=lambda kv: kv[1]):
        sup[seed] = sup.get(seed, 0)
    for c in world["crops"].values():
        sup[c["id"]] = sup.get(c["id"], 0) + sup.get(c["seed"], 0) * c["yield"]
    sup["coin"] = coin
    for _ in range(3):   # recipes (inputs deterministic → output deterministic)
        for r in world["recipes"].values():
            n = min((sup.get(i, 0) // q for i, q in r["in"].items()), default=0)
            for o, q in r["out"].items():
                sup[o] = max(sup.get(o, 0), n * q)
    return sup


def solvability(world: dict[str, Any], node_counts: dict[str, int]) -> dict[str, Any]:
    sup = deterministic_supply(world, node_counts)
    missing = []
    for q in world["quests"]:
        for st in q["stages"]:
            for part in (st.get("guard") or "").split("&"):
                if part.startswith("have:"):
                    name, _, n = part[5:].partition(">=")
                    if sup.get(name, 0) < float(n):
                        missing.append(f"{q['id']}.{st['id']}: {name} needs {n}, deterministic supply {sup.get(name, 0)}")
                elif part.startswith("total:"):
                    name, _, n = part[6:].partition(">=")
                    cap = {"planted": sum(sup.get(c["seed"], 0) for c in world["crops"].values()),
                           "harvested": sum(sup.get(c["seed"], 0) * c["yield"] for c in world["crops"].values()),
                           "gathered": float(sum(node_counts.values()))}.get(name, float("inf"))
                    if cap < float(n):
                        missing.append(f"{q['id']}.{st['id']}: total {name} needs {n}, deterministic cap {cap}")
    return {"ok": not missing, "missing": missing, "supply": {k: v for k, v in sorted(sup.items())}}
