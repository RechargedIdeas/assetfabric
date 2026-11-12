# TODO.md — Actionable Tasks

Last updated: 2026-11-12 America/New_York

## Current sprint — F5 balance + boss

- [ ] Monte Carlo balance runner (headless batch, G-BAL-01: 1k encounters, win-rate deviation < 5 % across matchups)
- [ ] Bayesian / Optuna tuning on CPU against the balance objective
- [ ] Soft-lock detection (statechart static analysis + runtime stall detector)
- [ ] Save system + versioned migration (Player State Profile / Roster / World)
- [ ] Game F5 increment: first tier-3 boss cleared, proven by the balance runner

## Perf debt

- [ ] Swap advisor < 50 ms (now ≈ 50–100 ms; F4 re-measured 66–104 ms): native step function (GDExtension) or reduced candidate set; keep serial/threaded parity test
## Done

- [x] F0 Foundation (accepted 2026-11-05)
- [x] F1 Content Pipeline (accepted 2026-11-05): G1-Sprite, G1-Tile, DyeWorks procedural; gates; PatternVault; SwatchStudio CLI; Godot binding; sandbox encounter
- [x] F2 Codegen + G1-Audio (accepted 2026-11-05): roster → game data + .tres; derived sprites; chiptune stems; first combat party of 4 + pets
- [x] F3 GIRT + CascadeHub + callouts (accepted 2026-11-05): policy BC, callout cache, persona LM stand-in, BT party AI, time-freeze swap, intents, dialogue
- [x] F4 Substrate (accepted 2026-11-12): bwrap/process sandbox, live channel (2PC + probe + rollback), snapshots + WAL, parallel statecharts, guardian
- [x] Private repo + proprietary license (D-003, D-004)

## Backlog (later milestones)

- Firecracker / gVisor launchers (need usable KVM + guest image)
- Hot reload of GDScript code, tilemaps, audio; remote (WS/gRPC) live transport for Studio
- Session host migration (failover tier 3); Crash Predictor model
- F6 quest SM, farming, loot, adaptive music, vertical slice
- F7 packaging (desktop/Android/Web), ShuttleLine multi, BoltPack
- Studio PySide6 shell; SwatchStudio GUI
- ONNX G1-Sprite Tiny, NCA G1-Tile, diffusion DyeWorks backends

## Companion / cluster (parallel)

- [ ] C1 PocketLoom FabricCore (Kotlin) — JobExecutor contract, local store
- [ ] C7 LoomCluster node registry + scheduler; C8 GroundWeave fallback ladder

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
| D-005 | Final names/stats of 4 fighters + 3 starter pets (GAME_SPEC §10) | Game Design | before content lock |

## Infrastructure

- [x] CI on GitHub Actions with Godot 4.3 headless
- [ ] Windows runner (DirectML) — later
- [ ] Model artifact storage backend beyond local `store/`
