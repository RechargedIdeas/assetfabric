"""R1 Retro Render Compiler data (F8, ASSETFABRIC_SPEC §3 Layer D; GAME_SPEC §4.6) — generator kind `retro`.

From the Console Profile Registry (content/retro/profiles.yaml) + PatternVault it writes, per profile, the 64³
nearest-colour LUT the game's post-process samples (`<profile>_lut.png`, 512×512) and one `retro.json` the game's Retro
autoload reads (order, default, logical resolution, integer scale, scanline option, locale label keys, LUT file).

Gates:
- `registry` — profiles.yaml validates (integer uniform downscale of the base viewport, locale label keys, families).
- `lut_exact` — every palette colour and every PatternVault colour (incl. colour-blind variants) has its own LUT bin, so
  exact art colours quantise deterministically; for `gz-native` every PatternVault colour maps to itself.
- `a11y_signals` — every PatternVault signal pair (a11y_checks) stays two different colours after a11y remap + profile
  quantisation, for every variant, unless the pair is listed in `a11y_shape_cues` (the game also shows it by shape).
- `budget`.

C1 signal separation: before the LUT is built, `transcode.solve_signal_overrides` moves single PatternVault colours to
another palette entry (cheapest perceptual error first) when that un-collapses a signal pair — e.g. on the 4-shade DMG
the ember enemy body and the moss floor share a shade by lightness, so the enemy moves one shade. Moves are recorded in
the registry meta (`c1_overrides`).
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np

from forge.gates import GateResult, budget_gate
from forge.generators import Artifact, GeneratorOutput, register


def signal_report(root: Any, profiles: dict[str, Any], luts: dict[str, np.ndarray], cues: list[str]) -> dict[str, Any]:
    from forge.a11y import _colour, delta_e
    from forge.patternvault import PatternVault
    from forge.retro.colour import apply_lut, hex_rgb, rgb_hex

    vault = PatternVault(root)
    checks = vault.data.get("a11y_checks", {}).get("pairs", [])
    rows = []
    ok = True
    for pid in profiles:
        for v in [None, *vault.variants()]:
            for c in checks:
                a, b = (_colour(vault, r, v) for r in c["pair"])
                qa, qb = (rgb_hex(apply_lut(np.array([hex_rgb(x)], dtype=np.uint8), luts[pid])[0]) for x in (a, b))
                distinct = qa != qb
                cue = c["what"] in cues
                good = distinct or cue
                ok &= good
                rows.append({"profile": pid, "variant": v or "default", "what": c["what"], "shown": [qa, qb],
                             "distinct": distinct, "shape_cue": cue, "de_seen": round(delta_e(qa, qb, v), 1), "ok": good})
    return {"ok": ok, "rows": rows}


@register("retro")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    from forge.retro import profiles as P
    from forge.retro.colour import build_lut, hex_rgb
    from forge.retro.png import encode

    t0 = time.perf_counter()
    gates: list[GateResult] = []
    raw = P.load_raw(ctx.root)
    errs = P.validate(raw)
    gates.append(GateResult("registry", not errs, {"errors": errs}))
    if errs:
        return GeneratorOutput([], gates, {"kind": "retro"})
    profs = P.load(ctx.root)
    pv = np.array([hex_rgb(h) for h in P.patternvault_colours(ctx.root)], dtype=np.uint8)
    arts: list[Artifact] = []
    luts: dict[str, np.ndarray] = {}
    collisions: dict[str, list[str]] = {}
    identity_misses: list[str] = []
    from forge.a11y import _colour
    from forge.patternvault import PatternVault
    from forge.retro.transcode import solve_signal_overrides

    vault = PatternVault(ctx.root)
    cues = set(raw.get("a11y_shape_cues", []))
    pairs = [(_colour(vault, c["pair"][0], v).lower(), _colour(vault, c["pair"][1], v).lower(), c["what"] in cues)
             for v in [None, *vault.variants()] for c in vault.data.get("a11y_checks", {}).get("pairs", [])]
    overrides: dict[str, dict[str, int]] = {}
    for pid, p in profs.items():
        over, _left = solve_signal_overrides(pairs, p.palette, p.match, P.patternvault_colours(ctx.root)) \
            if p.family != "fabric" else ({}, [])
        if over:
            overrides[pid] = over
        img, coll = build_lut(p.palette, pv, p.match, over)
        luts[pid] = img
        if coll:
            collisions[pid] = coll
        if p.family == "fabric":
            from forge.retro.colour import apply_lut

            back = apply_lut(pv, img)
            identity_misses += [f"{pid}: {tuple(a)} -> {tuple(b)}" for a, b in zip(pv.tolist(), back.tolist()) if a != b]
        arts.append(Artifact(f"{pid}_lut.png", encode(img), "image/png"))
    gates.append(GateResult("lut_exact", not collisions and not identity_misses,
                            {"collisions": collisions, "identity_misses": identity_misses[:10]}))
    sig = signal_report(ctx.root, profs, luts, list(raw.get("a11y_shape_cues", [])))
    gates.append(GateResult("a11y_signals", sig["ok"], {"failing": [r for r in sig["rows"] if not r["ok"]][:10],
                                                         "collapsed_with_cue": [r for r in sig["rows"] if not r["distinct"]][:10]}))
    table = {"schema_version": "1.0", "default": raw["default"], "order": raw["order"],
             "base_viewport": raw["base_viewport"], "profiles": {pid: p.table() for pid, p in profs.items()}}
    data = json.dumps(table, indent=1, sort_keys=True).encode() + b"\n"
    arts.append(Artifact("retro.json", data, "application/json"))
    elapsed = (time.perf_counter() - t0) * 1000
    gates.append(budget_gate(elapsed, sum(len(a.data) for a in arts), float(brief.get("max_ms", 20000)), 4_000_000))
    return GeneratorOutput(arts, gates, {"kind": "retro", "profiles": list(profs),
                                         "signal_pairs_checked": len(sig["rows"]),
                                         "collapsed_with_shape_cue": sorted({f"{r['profile']}: {r['what']}" for r in sig["rows"]
                                                                             if not r["distinct"]}),
                                         "c1_overrides": {k: dict(sorted(v.items())) for k, v in sorted(overrides.items())}})
