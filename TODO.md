# TODO.md — Actionable Tasks

Last updated: 2026-11-12 America/New_York

## Current sprint — F7 packaging (next)

- [ ] **Human GUI playtest of the vertical slice** (F6 carry-over): measure real length vs 15–20 min; HUD/quest/overlay readability; controls (E interact, H salve, Tab freeze, `/` command); music mix and fades; art legibility of plots/bench/nodes. Checklist: docs/acceptance-tests/F6.md §Human playtest
- [ ] Slice length: if humans also finish well under 15 min, add content (more field/tunnel areas, a second crop cycle, side quests) rather than slowing the bot
- [ ] F7: Desktop / Android / Web PWA packaging (export must ship `assets/generated/` + `data/generated/` as non-resources), ShuttleLine multi, BoltPack

## Balance (F6)

- [x] Per-pair (leader × pet) spread < 5 pp: pet↔character affinity → 3.21 pp on the gate seeds, now gated (INFERENCE F6-1/F6-2)
- [ ] Per-pair spread on *unseen* seeds is 5.25 pp ≈ noise floor at 200 seeds/cell; an out-of-sample per-cell gate needs ~800 seeds/cell (faster worker first)
- [ ] Longer Optuna study (≥ 100 seeds/matchup per trial) once the runner is faster; consider Ax/surrogate
- [ ] Faster balance worker (native step function would also fix swap advisor)
- [ ] Balance the slice's world fights (tunnels/cave packs, buffs, levels) with the Monte Carlo runner — currently tuned by hand; 0 wipes over the 12-selection matrix

## Perf debt

- [ ] Swap advisor < 50 ms (now ≈ 50–100 ms; F4 re-measured 66–104 ms): native step function (GDExtension) or reduced candidate set; keep serial/threaded parity test
## Done

- [x] F0 Foundation (accepted 2026-11-05)
- [x] F1 Content Pipeline (accepted 2026-11-05): G1-Sprite, G1-Tile, DyeWorks procedural; gates; PatternVault; SwatchStudio CLI; Godot binding; sandbox encounter
- [x] F2 Codegen + G1-Audio (accepted 2026-11-05): roster → game data + .tres; derived sprites; chiptune stems; first combat party of 4 + pets
- [x] F3 GIRT + CascadeHub + callouts (accepted 2026-11-05): policy BC, callout cache, persona LM stand-in, BT party AI, time-freeze swap, intents, dialogue
- [x] F4 Substrate (accepted 2026-11-12): bwrap/process sandbox, live channel (2PC + probe + rollback), snapshots + WAL, parallel statecharts, guardian
- [x] F5 Balance (accepted 2026-11-12): Monte Carlo runner (G-BAL-01 pass), Optuna TPE tuning, soft-lock detection, save v3 + migrations; first tier-3 boss
- [x] F6 Vertical slice (accepted 2026-11-12): quest statechart, farming/gather/craft economy, tiered loot, adaptive music, field ⇄ tunnels ⇄ cave ⇄ lair, save v4 + quit/reload parity, QA autopilot, 12-selection matrix; per-pair balance gate
- [x] Private repo + proprietary license (D-003, D-004)

## Backlog (later milestones)

- Firecracker / gVisor launchers (need usable KVM + guest image)
- Hot reload of GDScript code, tilemaps, audio; remote (WS/gRPC) live transport for Studio
- Session host migration (failover tier 3); Crash Predictor model
- Studio PySide6 shell; SwatchStudio GUI
- ONNX G1-Sprite Tiny, NCA G1-Tile, diffusion DyeWorks backends

## Companion / cluster (parallel)

- [ ] C1 PocketLoom FabricCore (Kotlin) — JobExecutor contract, local store (unverified draft on `wip/f5-companions`)
- [ ] C7 LoomCluster node registry + scheduler; C8 GroundWeave fallback ladder (unverified draft on `wip/f5-companions`)

## Blockers

| ID | Description | Owner | Status |
|---|---|---|---|
| — | none | — | — |

## Bugs

| ID | Description | Severity | Notes |
|---|---|---|---|
| — | none filed | — | — |

## Decisions needed

| ID | Question | Owner | By |
|---|---|---|---|
| D-001 | Web export single-threaded fallback strategy? | Factory Lead | before F7 |
| D-002 | Confirm Android reference = Redmi Note 12 Pro 5G | Producer | F7 |
| D-005 | Final names/stats of 4 fighters + 3 starter pets (GAME_SPEC §10); F6 economy/loot/quest content | Game Design | before content lock |

## Infrastructure

- [x] CI on GitHub Actions with Godot 4.3 headless
- [ ] Windows runner (DirectML) — later
- [ ] Model artifact storage backend beyond local `store/`
