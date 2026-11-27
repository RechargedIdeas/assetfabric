# ADR-0018 — Economy, loot and XP numbers come from a design model, gated in Codegen-World and F6

| Field | Value |
|---|---|
| Status | **accepted** (closes D-005's *content-table* part; final names/numbers stay Game-Design sign-off) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (Producer direction t59u "fix quality gaps", t61u "proceed with all"); agent implementation |

## Context

GAME_SPEC §4.4 asks only for a "minimal gather/grow/craft loop that feeds loot/economy schema" and §10 lists "farming loop
economy numbers" as an open design decision (D-005). Until 0.7.12 every price, drop rate and XP threshold in
`content/world/economy.yaml` was a hand-typed placeholder (INFERENCE F6-3) with no target it had to meet, so nothing
stopped a dead drop, an unpayable crop or a boss reached under-levelled. This diverges from nothing in the specs; it fills
a gap the specs leave open, so the numbers are `[INFERENCE]` (C-93) until Game Design signs them off.

## Decision

1. `content/world/economy_design.yaml` holds the design decision in data: base coin-equivalent values for raw goods, a
   craft markup (1.25) and targets — crop ROI 1.25–2.25, expected loot value per kill by tier (T1 1.5–3.5, T2 5–11,
   T3 40–90), no dead materials, loot reliability (P(Flint Edge shards before boss prep) ≥ 0.95, P(Warden Charm hide by
   the end) ≥ 0.95), median end coin 32–160, and the party level at four quest stages (3 / 4 / 4 / 5).
2. Codegen-World derives every other value (seeds = shop price, crafted = Σ inputs × markup) into `world.json`
   (`items[*].value`) and gates the static targets (`economy_design` gate, `forge/economy.py`).
3. `forge accept F6` replays the recorded slice kill sequence through the loot tables with 2000 re-seeded RNGs (a Python
   twin of `world/loot.gd`) and checks the reliability and coin targets; XP pacing is checked deterministically on
   the recorded run, and the twin's predicted level-ups must equal the game's logged ones. Main run and every selection.
4. The per-pair balance gap (TODO P6) is closed the same way: an out-of-sample hold-out (1000 seeds per leader × pet cell,
   **seed_base 20 000**, never used for fitting) gated at ≤ 3.5 pp in `forge accept F5` full mode (C-94). The first
   hold-out range (9000) was spent choosing which cells to recalibrate, so it is not reused as a gate. A bounded
   per-cell Optuna study is recorded (`results/F5-tune-affinity.json`) but was too noisy to apply; three affinities
   were recalibrated with a paired common-random-number probe on fit seeds (60 000+). The 200-seed G-BAL-01 per-pair
   check becomes noise-aware (every cell's Wilson 95 % CI reaches mean ± 5 pp); its point spread is reported.

## Consequences

- Changing a price or drop rate is a data edit that either passes the targets or fails the build — no silent drift.
- The targets are ours; Game Design may change them (that is the sign-off left on D-005), but then the tables must still
  pass the gate.
- v1 has no coin sink beyond seeds, so coin accumulates (≈ 130 at the end of the slice); a sink is a Game Design item.
- The hold-out costs 12 000 fights (≈ 4 min on 8 vCPU, ≈ 15–20 min extrapolated on the 2-core node), so it runs only in
  full `forge accept F5`, not in pytest/CI; CI keeps the noise-aware 200-seed per-pair check.
- Any future affinity refit must use fit seeds (50 000+) and be confirmed on a range it has never seen; if 20 000 is
  ever used to choose values, the gate moves again (C-94).

## Alternatives considered

- **Keep hand-typed numbers until Game Design delivers:** rejected — the quality-gap plan (TODO P4) wants a gate now.
- **Simulate a full market economy:** rejected for a 15–20 min slice with one shop; out of scope for v1.
- **Fit the economy numbers to the targets with Optuna:** rejected; values are derived from a few base values, which
  keeps them explainable.

## References

GAME_SPEC §4.4, §5, §6.1, §10 · TODO P4, P6, P7 · INFERENCES C-93, C-94 · `forge/economy.py`, `forge/balance.py`
(`holdout`, `tune_affinity`) · docs/acceptance-tests/F5.md, F6.md.
