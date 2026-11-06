# TODO.md — Actionable Tasks

Last updated: 2026-11-05 ~20:45 America/New_York

## Current sprint (F0 — Foundation) — closing

- [x] **F0.1** `forge.yaml` project manifest schema (`docs/schemas/forge.project.schema.json`)
- [x] **F0.2** Telemetry event schema v1 (`docs/schemas/telemetry.event.schema.json`)
- [x] **F0.3** Empty Godot project + `forge status` healthy
- [x] **F0.4** `forge doctor` environment checks
- [x] **F0.5** Job orchestrator + asset store scaffolding (build target skeleton deferred — status/store/job cover F0)
- [x] **F0.6** Test harness (`pytest`) for status / schema / store / godot structure
- [x] **F0.7** Doc suite per SPEC §11
- [x] **F0.8** Hardware fleet registered in `forge.yaml` cluster + `docs/hardware-fleet.md`
- [x] **F0.9** Optional: install Godot binary on box and run true headless smoke (`REQUIRE_GODOT=1`)

## Acceptance checklist (F0)

- [x] Doc suite present
- [x] `forge status` healthy
- [x] One-milestone offset documented; F1 blocked
- [x] Tests green
- [ ] Human / Producer sign-off on F0 acceptance (this session stops for acceptance)

## Backlog (F1-ready — DO NOT START until F0 accepted)

- [ ] G1-Sprite Tiny procedural/ONNX path + palette gate
- [ ] G1-Tile NCA + solvability gate
- [ ] DyeWorks procedural backend + SwatchStudio stub
- [ ] PatternVault
- [ ] Godot import presets / EditorImportPlugin
- [ ] Playable sandbox: 1 char, 1 tilemap, 1 enemy, 1 attack
- [ ] `forge build --target godot-desktop` real pipeline
- [ ] Studio PySide6 shell (beyond stub)

## Blockers

| ID | Description | Filed by | Owner | Status |
|---|---|---|---|---|
| — | none open for F0 core | — | — | — |

## Bugs

| ID | Description | Severity | Notes |
|---|---|---|---|
| — | none filed | — | WSL2 doctor false-warning from chat template N/A on this Linux box |

## Decisions needed

| ID | Question | Owner | By |
|---|---|---|---|
| D-001 | Web export single-threaded fallback strategy? | Factory Lead | before F7 |
| D-002 | Confirm Android reference = Redmi Note 12 Pro 5G | Producer | F1 |

## Done (repo setup)

- [x] D-003 License → proprietary (ADR-0001 accepted)
- [x] D-004 Private remote `RechargedIdeas/assetfabric` created and pushed

## Infrastructure

- [ ] Provision CI runners (Linux primary; Windows for DirectML later)
- [ ] Model artifact storage backend (content-addressed — local `store/` for now)
- [ ] Optional Godot 4.3+ binary cache under `godot-bin/` (gitignored)

## Deferred (see PLAN.md §Out-of-Scope)

Do not open implementation tasks for deferred items without a scope change.
