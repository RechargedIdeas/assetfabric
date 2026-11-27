# ADR-0025 — Self-improvement = benchmark-gated recipe promotion with rollback

| Field | Value |
|---|---|
| Status | **accepted** (U1) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (user request t65u: universal 2D/2.5D/3D engine); agent implementation |

## Context

t65u asks for an engine that "learns, adapts … and improves itself". If changes were applied without a measurable
objective and hard gates, quality would regress silently and the "self-improving" claim would be unfalsifiable.

## Decision

1. Tunable behaviour is held in **recipe families** with committed baselines (`content/universal/recipes/baseline.yaml`):
   * `parametric.csg` (cell fraction, Newton steps);
   * `maps2d.normal` (blur, relief, dome).
2. Each family has a **benchmark suite that runs the production code path** against ground truth:
   * `parametric.csg`: OpenSCAD `$fn=128` reference volumes, cached and committed with their source, cross-checked
     by a test;
   * `maps2d.normal`: analytic hemisphere/ellipsoid normals.
3. `evolve` proposes neighbours plus one pairwise combination. A candidate is promoted only when it is strictly better
   **and** passes every gate. Every evaluation is written to telemetry, and every rejection is kept with its reason.
4. Promotions are local state (`.fabric/universal/evolution/`). Production code always reads
   `evolution.active_recipe` (the baseline when nothing has been promoted). `evolve-rollback` restores any version.

## Consequences

* Improvements are measurable. U1 recorded:
  * normals 25.4° → 4.0° mean error;
  * CSG objective 0.0184 → 0.0170;
  * a regression and a gate violation, both rejected.
* Learned parameters stay small and inspectable. New families (e.g. a learned model, when an AMD GPU rung exists) plug
  into the same gates.
* Promotions are per machine. Shipping a promoted recipe as the new baseline is a reviewed commit.
