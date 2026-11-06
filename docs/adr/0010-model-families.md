# ADR-0010 — Model families: G1/D1/S1/H1/M1/C1/R2/O1 (+RC, Substrate)

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

The chat defined a mesh of model families with distinct roles, budgets and training loops.

## Decision

Adopt the family taxonomy in `docs/design/ASSETFABRIC_SPEC.md` §5.1. Reality-capture models are named **RC** in code to avoid clashing with the R1 Retro Render Compiler `[INFERENCE]`. M1-Architect is excluded from the v1 ship gate. New families require an ADR.

## Consequences

- Model IDs in telemetry/registry use `<family>-<name>` (e.g. `G1-Sprite`).

## Alternatives considered

- **Flat model list:** rejected (no budget/ownership structure).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
