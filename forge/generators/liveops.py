"""F9 LiveOps readiness manifest — generator kind `liveops` (ASSETFABRIC_SPEC §12 "remote config / feature flags").

content/liveops/flags.yaml + content/tune/limits.yaml → `liveops.json` (flags with safe offline defaults, the balance
knob ranges a config bundle may touch, bundle format constants). Read by the game's LiveOps autoload.

Gates: `flags_manifest` (forge.liveops.validate_flags incl. locale keys), `knobs_live` (every knob range matches at
least one numeric leaf of the generated game data — a dead remote-config hook is an error), `budget`.
"""

from __future__ import annotations

import json
import time
from typing import Any

from forge.gates import GateResult, budget_gate
from forge.generators import Artifact, GeneratorOutput, register


@register("liveops")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    from forge import liveops as L
    from forge.live import GAME_DATA_REL, match_paths

    t0 = time.perf_counter()
    raw = L.load_flags(ctx.root)
    errs = L.validate_flags(raw, L.locale_en(ctx.root))
    gates = [GateResult("flags_manifest", not errs, {"errors": errs})]
    if errs:
        return GeneratorOutput([], gates, {"kind": "liveops"})
    man = L.game_manifest(ctx.root)
    gd_path = ctx.root / GAME_DATA_REL
    gd = json.loads(gd_path.read_text(encoding="utf-8")) if gd_path.exists() else {}
    dead = [k for k in man["knobs"] if not match_paths(gd, k)]
    gates.append(GateResult("knobs_live", not dead, {"knobs_matching_nothing": dead, "knobs": len(man["knobs"])}))
    data = (json.dumps(man, indent=1, sort_keys=True) + "\n").encode("utf-8")
    gates.append(budget_gate((time.perf_counter() - t0) * 1000, len(data), brief.get("max_ms", 5000), 64 * 1024))
    return GeneratorOutput([Artifact("liveops.json", data, "application/json")], gates,
                           {"kind": "liveops", "flags": sorted(man["flags"]), "knobs": len(man["knobs"])})
