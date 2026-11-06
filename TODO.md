# TODO.md — Actionable Tasks

Last updated: 2026-11-05 ~21:10 America/New_York

## Current sprint — F2 Codegen + G1-Audio

- [ ] Character / ability / stat schema (`docs/schemas/`) + YAML sources in `content/`
- [ ] Codegen: YAML → game data (`games/game-zero/data/generated/`) + GDScript ability table
- [ ] 4 base fighters, 3 starter pets, enemy tiers `[INFERENCE: names/stats pending GAME_SPEC §10]`
- [ ] Sprites for all roster entries via G1-Sprite briefs
- [ ] G1-Audio: chiptune stems (square/triangle/noise) → WAV, macro states ambient/combat
- [ ] Party combat sim: followers + pets act independently; abilities with cooldowns
- [ ] Game F2 increment: party of 4 + pets vs. enemies, headless victory
- [ ] Docs + acceptance `docs/acceptance-tests/F2.md`

## Done

- [x] F0 Foundation (accepted 2026-11-05)
- [x] F1 Content Pipeline (accepted 2026-11-05): G1-Sprite, G1-Tile, DyeWorks procedural; gates; PatternVault; SwatchStudio CLI; Godot binding; sandbox encounter
- [x] Private repo + proprietary license (D-003, D-004)

## Backlog (later milestones)

- F3 GIRT, CascadeHub, callout cache, party AI, swap overlay
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
