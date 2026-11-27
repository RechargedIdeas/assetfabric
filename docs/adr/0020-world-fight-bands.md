# ADR-0020 — World fights are gated on wipe-rate and clear-time bands from a Monte Carlo replay of the slice

| Field | Value |
|---|---|
| Status | **accepted** (closes quality gap P7) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (Producer direction t59u "fix quality gaps", t61u "proceed with all"); agent implementation |

## Context

GAME_SPEC §4.4 asks for "bosses + trash mobs with tier system" and §5 proves one tier-3 boss with the balance runner
(G-BAL-01, F5). Until 0.7.14 the slice's world fights (field, tunnels, Ore Hollow, deep cave, Windward Ridge packs) were
tuned by hand: the only evidence was "0 wipes" on the 12 bot playthroughs, i.e. one sample per fight per selection, and
nothing stopped a pack from being trivial or a death trap. The spec names no wipe-rate or clear-time numbers, so the
bands are `[INFERENCE]` (C-98).

## Decision

1. The slice records, for every fight, the state it started from — party levels + pet, item/buff bonus, HP carried from
   earlier fights, the packs it pulled and the tilemap (`slice.gd::_fight_context`, diagnostics only).
2. The F5 balance worker accepts an inline `encounter_def` plus per-job `patch` (hostiles, tilemap, bonus, tick limit) and
   `start_hp`, and reports the first landed hit (`engage_tick`). Existing F5 jobs are unchanged.
3. `forge/worldfights.py` replays every recorded fight of every selection over fixed seeds (seed_base 70 000, CRN across
   selections; full 30 seeds per world fight and 100 per boss fight on 12 selections = 8 040 fights; FAST/CI 8 / 24 on
   2 selections) and checks the bands in `content/tune/worldfights.yaml` **per selection × fight**:
   trash wipe ≤ 2 %, median engaged clear 1–6 s, p90 ≤ 9 s; elite (≥ 2 tier-2 units) wipe ≤ 6 %, 2–9 s, p90 ≤ 13 s;
   slice Warden wipe ≤ 10 %, 8–30 s, p90 ≤ 40 s; time bounds scale with the number of packs pulled; P(≥ 1 wipe per
   playthrough) ≤ 30 %; no soft-locks / timeouts. `forge accept F6` gates it.
4. The slice Warden band has no wipe floor: Q5 (C-93) made it "a deliberately forgiving first boss" (level 4 + crafted
   gear); the hard tuning point stays G-BAL-01 (level 3, no gear, 0.55–0.90 win rate).
5. Tuning only touched pack composition (`content/world/areas.yaml`), never shared enemy stats, so F5 G-BAL-01 and the
   per-pair hold-out are unaffected.

## Consequences

- A pack edit that makes a fight trivial (< 1 s) or deadly fails `forge accept F6` with the offending selection × fight.
- The model plays the BT + policy party AI, not a human; human wipe rates will be higher. A GUI playtest remains the
  real proof (F6.md §Human playtest).
- Full `forge accept F6` grows by ≈ 2 min (8 040 fights on 8 workers); CI FAST adds ≈ 10 s.
