# TODO.md — Actionable Tasks

Last updated: 2026-11-05 ~21:20 America/New_York

## Current sprint — F3 GIRT + CascadeHub + callouts

- [ ] GIRT facade: model registry, backend selection (CPU always), per-call latency budget + telemetry
- [ ] Tiny policy format (JSON MLP weights, ONNX-exportable) evaluated in GDScript; trainer in Python (CPU)
- [ ] Behaviour trees for fighters / pets / enemies (data-driven)
- [ ] CascadeHub typed message bus (intents, callouts, dialogue) — never on the tick's critical path
- [ ] Callout cache: generated offline per character × event, safety-gated; zero LM in tick (G-AI-03)
- [ ] Time-freeze swap: pause, overlay, ranked swap recommendations via forward sim (<50 ms)
- [ ] Dialogue: templated micro-LM stand-in with LoRA-style persona tables `[INFERENCE]`
- [ ] Game F3 increment + docs

## Done

- [x] F0 Foundation (accepted 2026-11-05)
- [x] F1 Content Pipeline (accepted 2026-11-05): G1-Sprite, G1-Tile, DyeWorks procedural; gates; PatternVault; SwatchStudio CLI; Godot binding; sandbox encounter
- [x] F2 Codegen + G1-Audio (accepted 2026-11-05): roster → game data + .tres; derived sprites; chiptune stems; first combat party of 4 + pets
- [x] Private repo + proprietary license (D-003, D-004)

## Backlog (later milestones)

- F4 sandbox (process tier), hot reload, snapshots, statecharts
- F5 Monte Carlo balance, soft-lock, save migration, first boss
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
