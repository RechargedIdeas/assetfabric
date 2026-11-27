# ADR-0017 — Gate the vertical-slice length on a human-pace estimate

| Field | Value |
|---|---|
| Status | **accepted** (until a human GUI playtest exists) |
| Date | 2026-11-26 |
| Deciders | Recharged Ideas (Producer direction t59u "fix quality gaps"); agent implementation |

## Context

GAME_SPEC §6.1 requires "15–20 minutes of continuous playable content". The only player we can run headless is the
QA autopilot, which plays at machine efficiency (no reading, detours or menu time). Its game time is a floor, not the
length a person experiences. Until 0.7.11 the length was reported as a soft metric (bot ≈ 3 min). Slowing the bot or
adding idle timers would game the number without adding content.

## Decision

1. Add real content until the length target is met (INFERENCE C-91: Ore Hollow, patrol beat, q_smith, Windward Ridge,
   second crop cycle).
2. `forge accept F6` hard-gates a **human-pace estimate** (`forge/pace.py`, constants in `content/tune/pace.yaml`,
   INFERENCE C-92) computed from what each autopilot run actually did; every leader × pet selection must land inside
   15–20 min. Bot game time is reported unchanged beside it.
3. Crop waiting is counted per wait segment minus the slack a slower human already spent since planting; it is never
   multiplied.
4. The model constants are fixed. Changing one needs a new entry here, with the reason.

## Consequences

- The length gate is reproducible and runs in CI (FAST: 2 selections; full: 12).
- It is a model, not a measurement. A human GUI playtest (docs/acceptance-tests/F6.md §Human playtest) supersedes it; if
  people finish well under 15 min, add content (TODO), do not retune the constants to pass.
- Sensitivity is recorded in C-92 (1.3 / 1.2 factors → 15.5 min; 1.0 / 1.0 → 13.8 min).

## Alternatives considered

- **Slow the bot / add idle waits:** rejected (games the metric).
- **Keep length soft until a playtest:** rejected by the quality-gap plan (TODO P5 wants a gate).
- **Fit constants to the target:** rejected; constants were written before the gate and are unchanged.

## References

docs/design/GAME_SPEC.md §5, §6.1; docs/INFERENCES.md C-91, C-92; forge/pace.py; content/tune/pace.yaml.
