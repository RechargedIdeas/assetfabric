"""Callout cache + persona micro-LM stand-in (F3).

`kind: callouts` expands persona templates for every character × event into a
pre-generated cache (GAME_SPEC §4.3: combat callouts come from a cache — zero LM
in the combat loop, G-AI-03). Every line passes the content-safety gateway.

`kind: persona_lm` trains a per-character bigram model from the persona corpus.
`[INFERENCE]` It is the CPU stand-in for the shared Qwen2.5-0.5B + per-character
LoRA backbone (ADR-0005): same GIRT interface (`lm` kind), out-of-tick, budgeted.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from forge.gates import GateResult, budget_gate
from forge.generators import Artifact, GeneratorOutput, register


def load_personas(root: Path, src: str = "content/personas/personas.yaml") -> dict[str, Any]:
    return yaml.safe_load((root / src).read_text(encoding="utf-8"))


def safety_check(line: str, safety: dict[str, Any]) -> list[str]:
    """Content-safety gateway: length, blocklist, unresolved slots."""
    problems = []
    if len(line) > int(safety.get("max_chars", 80)):
        problems.append("too_long")
    low = line.lower()
    problems += [f"blocked:{w}" for w in safety.get("blocklist", []) if w in low]
    if "{" in line or "}" in line:
        problems.append("unresolved_slot")
    return problems


@register("callouts")
def generate_callouts(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    src = load_personas(ctx.root, brief.get("source", "content/personas/personas.yaml"))
    safety = src["safety"]
    cache: dict[str, dict[str, list[str]]] = {}
    rejected: list[str] = []
    missing: list[str] = []
    for pid, p in sorted(src["personas"].items()):
        cache[pid] = {}
        for ev in src["events"]:
            templates = p["callouts"].get(ev, [])
            if brief.get("include_reviewed_lm_drafts", True):     # human-reviewed micro-LM drafts (forge persona author)
                from forge.microlm import reviewed_lines
                templates = templates + [x for x in reviewed_lines(ctx.root, pid, ev) if x not in templates]
            if not templates:
                missing.append(f"{pid}:{ev}")
            lines = []
            for tpl in templates:
                for ally in p["words"]["ally"][:2]:
                    for foe in p["words"]["foe"][:2]:
                        # {ally_name} is resolved at runtime from the roster; keep a token for it
                        line = tpl.replace("{ally}", ally).replace("{foe}", foe).replace("{ally_name}", "%ALLY%")
                        if line in lines:
                            continue
                        bad = safety_check(line.replace("%ALLY%", "Ally"), safety)
                        if bad:
                            rejected.append(f"{pid}:{ev}:{bad}")
                        else:
                            lines.append(line)
            cache[pid][ev] = lines
    data = {"schema_version": "1.0", "events": src["events"], "callouts": cache}
    blob = (json.dumps(data, indent=1, sort_keys=True) + "\n").encode()
    elapsed = (time.perf_counter() - t0) * 1000
    gates = [
        GateResult("coverage", not missing, {"missing": missing}),
        GateResult("safety", not rejected, {"rejected": rejected}),
        budget_gate(elapsed, len(blob), float(brief.get("budget_ms", 500)), 256 * 1024),
    ]
    n = sum(len(v) for c in cache.values() for v in c.values())
    return GeneratorOutput([Artifact("callouts.json", blob, "application/json")], gates,
                           {"kind": "callouts", "lines": n, "model_id": "CalloutCache", "model_version": "1"})


def train_bigram(corpus: list[str]) -> dict[str, dict[str, int]]:
    table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for line in corpus:
        toks = ["<s>", *line.lower().split(), "</s>"]
        for a, b in zip(toks, toks[1:]):
            table[a][b] += 1
    return {a: dict(sorted(nx.items())) for a, nx in sorted(table.items())}


def sample(table: dict[str, dict[str, int]], seed: int, max_tokens: int = 14, start: str = "<s>") -> str:
    """Deterministic sampler (LCG) — mirrored exactly in girt.gd."""
    state = seed & 0x7FFFFFFF
    out: list[str] = [] if start == "<s>" else [start]
    cur = start
    seen: set[tuple[str, str]] = set()
    for _ in range(max_tokens):
        nxt = table.get(cur)
        if not nxt:
            break
        total = sum(nxt.values())
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        r = state % total
        acc = 0
        for tok, c in nxt.items():
            acc += c
            if r < acc:
                cur = tok
                break
        if cur == "</s>":
            break
        pair = (out[-1] if out else "<s>", cur)
        if pair in seen:  # repetition guard (mirrored in girt.gd)
            break
        seen.add(pair)
        out.append(cur)
    return " ".join(out)


@register("persona_lm")
def generate_lm(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    src = load_personas(ctx.root, brief.get("source", "content/personas/personas.yaml"))
    models = {pid: {"traits": p["traits"], "bigram": train_bigram(p["corpus"])} for pid, p in sorted(src["personas"].items())}
    probes = {pid: [sample(m["bigram"], s) for s in range(1, 6)] for pid, m in models.items()}
    unsafe = [f"{pid}:{t}" for pid, ts in probes.items() for t in ts if safety_check(t, src["safety"])]
    empty = [pid for pid, ts in probes.items() if not any(ts)]
    data = {"schema_version": "1.0", "backend": "persona-bigram", "sampler": "lcg-1103515245",
            "max_tokens": 14, "models": models, "probes": probes}
    blob = (json.dumps(data, indent=1, sort_keys=True) + "\n").encode()
    elapsed = (time.perf_counter() - t0) * 1000
    gates = [GateResult("safety", not unsafe, {"unsafe": unsafe}), GateResult("non_empty", not empty, {"empty": empty}),
             budget_gate(elapsed, len(blob), float(brief.get("budget_ms", 500)), 256 * 1024)]
    return GeneratorOutput([Artifact("persona_lm.json", blob, "application/json")], gates,
                           {"kind": "persona_lm", "model_id": "M-PersonaLM", "model_version": "bigram-1"})
