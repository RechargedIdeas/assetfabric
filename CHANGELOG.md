# CHANGELOG.md

All notable changes to AssetFabric. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are PEP 440 with the Fabric milestone as local label (`0.0.0+f0.0`). AssetFabric is proprietary — versions are internal milestones, not public releases.

## [Unreleased]

## [0.3.0+f3] — 2026-11-05 — F3 GIRT + CascadeHub + callouts

### Added
- Generators: `policy` (P-TargetSelect MLP via NumPy behaviour cloning, holdout-accuracy gate, parity probe), `callouts` (persona × event cache with coverage + safety gates), `persona_lm` (bigram tables + deterministic LCG sampler with repetition guard). `content/personas/personas.yaml`, `content/briefs/f3/ai.yaml`.
- Game Zero: `GIRT` autoload (registry, latency budgets, telemetry, refuses LM inside the tick), `CascadeHub` autoload (typed bus drained after each tick), `ai/brain.gd` (data-driven BTs compiled to int opcodes + policy targeting), `ai/swap_advisor.gd` (forward-sim swap ranking, threaded with serial parity), `ai/intent_grammar.gd`, `data/ai/behaviour_trees.json`, `party_ai` encounter + `party.tscn`, freeze overlay, command box, callouts and dialogue HUD, demo-mode script playback.
- F3 increment `party-ai` + acceptance (with GDScript↔Python MLP and LM parity, perf block); `tests/test_f3_ai.py`; `tools/profile.gd` dev profiler.

### Changed
- Grid: wall mask + all-pairs BFS path table (O(1), allocation-free pathing), `fork()` for worker threads; flow fields as `PackedInt32Array`.
- Combat sim: leader swap, `clone()`, `forward` mode (no global writes), think LOD, battle_start/low_hp/victory/swap events, allocation-free hot paths. F2 first-combat now wins in 561 ticks (was 563) because paths are always fresh.
- numpy added to dependencies.

### Known
- Swap advisor ≈ 50–80 ms on the reference box vs. GAME_SPEC target < 50 ms (hard ceiling 150 ms enforced; target tracked in `results/F3.json` `perf`).

## [0.2.0+f2] — 2026-11-05 — F2 Codegen + G1-Audio

### Added
- `content/roster/` (abilities, fighters, pets, enemies) + `docs/schemas/roster.schema.json`.
- Codegen generator: schema, cross-ref, roster-shape, stat-sanity gates → `data/generated/game_data.json` + 14 ability `.tres` Resources; one derived G1-Sprite brief per roster unit (13 sprites); new `pet` sprite archetype; 3 new hero palettes.
- G1-Audio generator: NES-style pulse/triangle/noise stems for ambient/tension/combat/boss + 4 SFX; no-clipping, duration and loop-seam gates.
- Game Zero: `combat_sim.gd` (abilities: melee/ranged/aoe/heal/taunt, cooldowns/windups, follower + pet brains, separation), `encounter_builder.gd` (roster refs, pet bonuses with diminishing returns), generic `encounter.gd` scene, `combat.tscn`, runtime WAV loader, `skill` input.
- F2 increment `first-combat` + acceptance; tests for codegen/audio (29 total).

### Changed
- Sandbox encounter now built from roster refs through the same combat sim.
- Pipeline supports `export_base` (codegen writes to `data/generated/`) and brief expansion.

## [0.1.0+f1] — 2026-11-05 — F1 Content Pipeline

### Added
- `forge/imaging.py` dependency-free PNG codec; `forge/patternvault.py` + `content/patternvault/palettes.json` (5 palettes, colour-blind variants).
- Generators: G1-Sprite (procedural humanoid/beast, 6-frame sheets), G1-Tile (cellular-automata caves with entry/exit/spawns), DyeWorks (seamless albedo + normal).
- Gates: palette, dims, seamless, solvability, floor ratio, BudgetGate.
- `forge/pipeline.py`: briefs (`content/briefs/`) → orchestrator → generators → gates → store → `games/game-zero/assets/generated/` + `fabric_assets.json`.
- CLI: `forge build`, `forge gen`, `forge palette`, `forge accept`, `forge report`.
- `forge/milestones.py`: increment registry, headless acceptance, offset guard in `forge status`; `STATUS.md` generator.
- Game Zero: `Fabric` autoload (registry, runtime loading, input schema, locales, headless watchdog), deterministic sim (`sim/`), playable sandbox scene, autoplay acceptance.
- Tests: pipeline, gates, determinism gate, headless Godot increments (23 total).
- CI: `.github/workflows/ci.yml` with Godot 4.3 download/cache; `scripts/capture.sh` (Movie Maker frames).
- Docs: F1 acceptance, INFERENCES §F1, STATUS.md, screenshot.

### Changed
- `docs/F0_INFERENCES.md` → `docs/INFERENCES.md` (per-milestone sections).
- `scripts/smoke_godot.sh` uses `--boot-only`.
- AGENTS/BUILD_ORDER offset rules generalised to "accept F(n) before F(n+1)".

## [0.0.1+f0] — 2026-11-05 — Private repository setup

### Added
- Private GitHub repository `RechargedIdeas/assetfabric` and first push of `main`.
- Root `LICENSE` (proprietary, All Rights Reserved) and `THIRD_PARTY_NOTICES.md`.
- `docs/design/`: imported authoritative specs (ASSETFABRIC_SPEC, GAME_SPEC, ASSETFABRIC_ML_AI_FEATURES, CHAT_SUMMARY_ASSETFABRIC) with index.
- ADRs 0004–0010 and 0012 written out (previously index-only); all ADRs expanded to full Context/Decision/Consequences/Alternatives prose.
- GitHub hygiene: `CODEOWNERS`, issue templates (bug, task, scope change), PR template.

### Changed
- ADR-0001 License: **proposed → accepted** (proprietary).
- `pyproject.toml` license `LicenseRef-TBD` → `LicenseRef-Proprietary`; `Private :: Do Not Upload` classifier.
- README, SECURITY, CONTRIBUTING, TESTING, HANDOVER, TODO, GLOSSARY, setup and acceptance docs rewritten for a cloned private repo (no box-only paths).

## [0.0.0+f0.0] — 2026-11-05 — F0 Foundation

### Added
- Repository scaffold and documentation suite (SPEC §11).
- Content Forge: `forge` CLI (`status`, `doctor`, `validate`, `job`, `store`).
- `forge.yaml` + JSON Schemas (project manifest, telemetry events).
- Content-addressed asset store + SQLite job orchestrator stubs.
- Telemetry JSONL emitter.
- Empty Godot 4 Game Zero project (Compatibility renderer); headless boot verified with Godot 4.3.
- Studio / PocketLoom / LoomCluster placeholders.
- Pytest suite (12 tests) for schemas, status, store, orchestrator, Godot structure.
- Minimal GitHub Actions CI.
