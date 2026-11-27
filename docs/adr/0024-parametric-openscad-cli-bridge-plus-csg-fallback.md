# ADR-0024 — Parametric generation: OpenSCAD as a CLI bridge, own NumPy CSG/SDF fallback

| Field | Value |
|---|---|
| Status | **accepted** (U1) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (user request t65u: universal 2D/2.5D/3D engine); agent implementation |

## Context

t65u asks for "parametric generation with custom OpenSCAD integration".

* OpenSCAD is GPL-2 and an optional external binary. We cannot vendor it into proprietary code.
* CI and user machines may not have it installed.
* Its CGAL path is slow for some models.

## Decision

1. Templates are YAML (`content/universal/parametric/`). Each has parameters with ranges, a triangle budget, units,
   a locale title key, and a CSG tree. Expressions are AST-whitelisted, with no names beyond the parameters and a
   small math allow-list.
2. `emit_scad` writes deterministic OpenSCAD source (repeats become `for/let`). `forge parametric build` runs the
   **real OpenSCAD CLI** in a subprocess when it is present (tier `cli_bridge`). We only exchange files with it; we
   never link to it.
3. `csg.py` evaluates the same tree as a signed-distance field and polygonises it with marching tetrahedra (Newton
   projection, sorted output). This is always available, deterministic, and the GroundWeave `gen.parametric` CPU rung.
   The triangle budget is enforced by coarsening.
4. When both backends run, volumes are cross-checked: tolerance 4 %, measured 0.2–0.5 %.
5. Every build writes `.scad/.stl/.obj/.off/.glb` plus `report.json`, and re-reads every interchange file.

## Consequences

* Parametric output works on every machine. OpenSCAD just adds exact CGAL CSG.
* The template language is a subset of OpenSCAD: primitives, transforms, booleans and rotational repeats. Arbitrary
  OpenSCAD code is not accepted, which is also the security boundary.
