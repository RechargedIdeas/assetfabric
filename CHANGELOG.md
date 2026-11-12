# CHANGELOG.md

All notable changes to AssetFabric. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are PEP 440 with the Fabric milestone as local label (`0.0.0+f0.0`). AssetFabric is proprietary — versions are internal milestones, not public releases.

## [Unreleased]

## [0.7.1+f7] — 2026-11-12 — Companion track C1–C6: PocketLoom (standalone offline Android companion) + LoomLink

### Added
- `companions/pocketloom/` — **PocketLoom** `0.1.0-c6` (Gradle 8.9 wrapper, AGP 8.7.3, Kotlin 2.0.21, minSdk 26 / targetSdk 35):
  - **FabricCore** (`fabriccore/`, pure Kotlin/JVM, no third-party runtime deps): `JobSpec`/`JobExecutor`, `LocalExecutor`,
    `Dispatcher` (run locally or queue), content-addressed `AssetStore` with per-asset version vectors, durable
    `OffloadQueue` (torn-line safe), `Telemetry` (JSONL, rotated), `ModelCache` (byte-budget LRU + pins), `GenBackends`
    ladder (ONNX rung = labelled stub, CPU always), **LocalForge** caves/sprites with gates + deterministic retry,
    `Captures` (JPEG/PNG/WebP sniffing + dimensions), `LoomLinkClient` (HMAC pairing, signed requests), `SyncPlan` /
    `SyncClient`, `PocketLoomCore` facade, `fabriccore-all.jar` CLI. 26 JUnit tests.
  - **App** (`app/`): Generate · Library · Capture · Link · Telemetry on platform widgets; all text in string/plural
    resources; camera intent via a private `CaptureProvider` (no CAMERA permission) + document import; `loomlink://pair`
    intent filter (QR → pre-filled Link tab); data-extraction rules exclude everything from backup/transfer.
- `forge/loomlink.py` (from `wip/f5-companions`, made self-contained): desktop pairing server + offload ops
  (`hashchain`, `gen`, `recon.capture` → store) + sync planner/store; `forge link serve` (code, `loomlink://` URI, QR if
  `qrcode` is installed).
- `forge accept C1…C6` / `forge accept C1-C6` (`forge/accept_companions.py`): one Gradle build (tests, fat jar, debug APK,
  lint), aapt/apksigner/dex checks, 2-core generation run with independent PNG palette check, manifest/string/offline
  scans, Kotlin↔Python pairing/offload/sync interop; results `docs/acceptance-tests/results/C1…C6.json`; fast mode for
  pytest. STATUS.md gains a companion table.
- `tests/test_companions.py`; shared vectors `tests/fixtures/loomlink_vectors.json` (HMAC, hashchain, canonical JSON,
  sync plans) checked by both Python and Kotlin; `tests/fixtures/capture_640x480.jpg`.
- CI job `pocketloom` (setup-java 17, Gradle cache, runner Android SDK) running `forge accept C1-C6 --no-write`.
- Docs: `docs/acceptance-tests/C1-C6.md`, `companions/pocketloom/README.md`, INFERENCES C-1…C-15, packaging/TESTING/
  ARCHITECTURE/SECURITY/tool-catalog/GLOSSARY updates.

### Changed
- Version `0.7.1+f7` (Fabric milestone stays F7). CI also runs on pushes to `feat/**`.
- LoomLink hardening vs the draft: pairing codes expire after 300 s, a `hello` issued before a code rotation cannot be
  confirmed, pending hellos capped; identical-bytes concurrent edits converge on both sides (second sync is a no-op).
- `.gitignore`: `.gradle/`, `.kotlin/`, `companions/pocketloom/**/build/`.

### Measured
- `forge accept C1-C6`: all passed (full mode) in ≈ 75 s on 8 vCPU with warm Gradle caches (build ≈ 56 s).
  Debug APK 972 815 bytes, `apksigner` v2 verified (debug key; SHA-256 per machine — see C1-C6.md).
  LocalForge on 2 cores: cave mean 13 ms / max 53 ms, sprite mean 12 ms / max 62 ms (budget 250 ms); 16/16 gates each,
  byte-identical across homes.

### Known
- Not run on a phone/emulator (no device, no KVM). ONNX rung is a stub. LoomLink: no TLS/PAKE (integrity + replay
  protection only; Tailscale for encryption), no sync of deletions, session key not Keystore-wrapped.
- LoomCluster (C7) and GroundWeave (C8) drafts stay on `wip/f5-companions` for the next run.

## [0.7.0+f7] — 2026-11-12 — F7 Packaging: Desktop / Android / Web PWA launch candidates, ShuttleLine multi, BoltPack

### Added
- `forge build --target {desktop-linux,desktop-windows,android,web,all}` (`forge/packaging.py`): toolchain discovery (Godot 4.3, templates, JDK 17, Android SDK, Chrome, bwrap, wine), hermetic Godot home (`.fabric/godot-home`, generated debug keystore), staged keep-import so runtime-loaded Fabric output ships byte-for-byte, exports, per-target verify (exported-binary boot, PE32+ headers, aapt/apksigner/apkanalyzer, PCK/APK readers), `BUILD.json` with SHA-256 of every file. `forge templates status|fetch` (sha256-pinned 4.3-stable templates).
- `games/game-zero/export_presets.cfg`: desktop-linux, desktop-windows (release), android (debug, arm64-v8a, no INTERNET), web (threads + PWA).
- **PWAPipeline** (`forge/pwa.py`): G-WEB-01 gzip-9 budget, SW cache-list check, `_headers` (COOP/COEP), URL-fragment QA hook, local server + headless-Chrome smoke (headers, isolation, SW, offline reload, header-less host).
- **ShuttleLine** `shuttleline.contract/1` (`forge shuttle contract [--check]`), verified against every shipped PCK/APK; `generic-folder` adapter (`forge shuttle export`).
- **BoltPack** (`forge/boltpack.py`): CycloneDX 1.5 SBOM from the engine's own copyright info + platform extras + game content, license allow-list audit (copyleft fails), `LICENSES/`, `dist/bolt/*.fabricbolt` (unsigned).
- Game: `--net-report` (multiplayer peer report), input remap (`profile.settings.input_remap`) applied at boot/load, `savecheck --import-b64 [--rewrite]` for cross-device saves, `Save.quit_after_persist()` (Web IndexedDB flush before quit).
- F7 increment `launch-candidates` + acceptance (`forge/accept_f7.py`, fast + full); `tests/test_f7_packaging.py`; `docs/packaging.md`; `docs/acceptance-tests/F7.md`; `results/F7.json`; inferences F7-1…F7-18.

### Changed
- Boot router default scene is `slice` (shipped builds open the game); exported builds never open the F4 live channel implicitly.
- GIRT counts over-budget policy calls as `policy_over_budget`, not fallbacks; F3 gates policy **p95 ≤ budget** (fixes a ≈ 1-in-4 F3 flake, also seen on `main`).
- `project.godot`: ETC2/ASTC import enabled (Android export requirement). `forge.yaml` declares the four platform targets. Version `0.7.0+f7`; optional extra `package` (Playwright).
- `.gitignore`: `.fabric/godot-home/`, `.fabric/cache/`, `.fabric/jdk/`, `games/game-zero/*.import` (plus existing `dist/`, `godot-bin/`, `*.keystore`).

### Measured
- `forge accept F7` full: passed, 1 min 44 s on 8 vCPU. Linux 66.1 MB binary + 1.57 MB PCK; Windows 84.2 MB exe; debug APK 25.6 MB; Web 35.9 MB raw / **9.29 MB gzip** (G-WEB-01 budget 45 MB). SHA-256 per artifact in docs/acceptance-tests/F7.md.
- G-SAVE-01: desktop → Android content → Web (IndexedDB, offline reload) → desktop, checksum identical every hop, final state == uninterrupted run. G-NET-01: slice completes in `bwrap --unshare-net`; no INTERNET permission; Web boots offline.

### Known
- Unsigned/debug only; no store listings. Windows build not executed (no Windows host/wine); Android not run on a device (no KVM); Web tested on localhost headless Chrome only.
- G-A11Y-01 partial (no rebinding UI / runtime palette toggle). Web ships threads only (D-001). Exports not byte-reproducible.
- Platform exports + full F7 acceptance are local-only; CI runs the F7 fast subset.

## [0.6.0+f6] — 2026-11-12 — F6 Vertical slice: quests, farming/craft economy, tiered loot, adaptive music, cave ↔ open world

### Added
- **Codegen-World** (`forge/generators/world.py`, `forge/world.py`): `content/world/{economy,loot,quests,music,areas}.yaml` → `games/game-zero/data/generated/world.json` — items, crops, recipes, shop, XP curve, tiered loot tables, quests compiled to one parallel statechart, adaptive-music rules, area graph. Gates: schema, cross-refs, quest-chart soft-lock (F4 analyzer), economy solvability, loot tables, music rules. Python twins (`Lcg`, `roll_loot`, `QuestLog`, guards) for GDScript parity.
- G1-Tile open-world features: farm plots, workbench, gather nodes, pinned hostile spawns; new maps `field_01`, `tunnels_01`, `cave_deep` (caves without features stay byte-identical). `music_field` stems (ambient/tension/combat).
- Game Zero world layer `games/game-zero/world/` (`world_state.gd`, `quest_log.gd`, `loot.gd`, `autopilot.gd` scripted QA agent) and `audio/music_director.gd` (biome × explore/tension/combat/boss layers with fades).
- `--scene=slice` (`scenes/slice.gd/.tscn`): character + pet select, plant/grow/harvest, gather, craft salve/tonic/gear at the bench, field ⇄ tunnels ⇄ deep cave → Warden's lair → open-world exit, quest log (main + side quest), XP/levels, checkpoints, save/quit/resume, boss-reward unlock (`vex`), freeze-swap overlay; `--autoplay`, `--leader/--pet/--seed/--resume/--quit-after-checkpoint`.
- Player State **save v4** (farm, checkpoint, quest counters, rng, world tick, depleted nodes, cleared packs, buffs, gear, unlocks, party HP); v3→v4 migration with GDScript ↔ Python parity.
- Pet↔character **affinity** (GAME_SPEC §4.2) in `content/roster/pets.yaml` (live-tune bounds 0.25–3.0) and `AFFINITY_SPACE` tuning knobs.
- F6 increment `vertical-slice` + acceptance (`forge/accept_f6.py`: slice + quit/resume in a new process + 12-selection matrix + quest/loot/migration parity + world gates + locale coverage; `FORGE_ACCEPT_FAST=1` 2-selection subset for pytest/CI); `tests/test_f6_world.py`; `docs/acceptance-tests/F6.md`; `results/F6.json`; inferences F6-1…F6-12.

### Changed
- **G-BAL-01 gates the per-pair (leader × pet) spread** (`max_combo_deviation_lt_5pp`) in addition to choice marginals; balance death-order diagnostics.
- A player-driven exploring leader is no longer shoved by follower separation; area transitions end the tick (resume parity).
- Slice salve key (H) is edge-triggered (one salve per press).
- `forge report` plan text for F6; version `0.6.0+f6` in `forge/__init__.py`, `pyproject.toml`, `forge.yaml` (`milestone: F6`, `increment: vertical-slice`), `project.godot`.

### Measured
- Vertical slice: all 8 GAME_SPEC §6.1 items met headless; 12/12 selections complete, 0 wipes / soft-locks / script errors; quit→resume final state byte-identical to an uninterrupted run.
- Slice length (bot): 2.92 game-min (matrix 2.75–3.37) vs 15–20 min human target — soft, not met by the bot.
- G-BAL-01 (seed_base 1000, 2400 fights): mean 0.718, choice 1.04 pp, **per-pair 3.21 pp** — pass. Unseen seed_base 9000: per-pair 5.25 pp (≈ 200-seed noise floor).

### Known
- Human GUI playtest pending (length, readability, controls, music mix).
- Economy / loot / quest / music content is placeholder (D-005, INFERENCE F6-3).
- Companion drafts remain on `wip/f5-companions`, unverified.

## [0.5.0+f5] — 2026-11-12 — F5 Balance: Monte Carlo, Optuna, soft-lock detection, save migration, first boss

### Added
- `forge/balance.py` + `tools/balance.gd` (`--scene=balance`): Monte Carlo runner — 12 character-select matchups (leader × starter pet) × N seeds, common random numbers, ±20 % damage rolls + crits + spawn jitter, sharded over headless Godot workers (CPU only), Wilson 95 % CIs, marginals, G-BAL-01 verdict; `forge balance run|tune` (Optuna TPE, optional extra `tune`; knobs validated against live-tune limits).
- `forge/softlock.py` + `forge softlock`: static statechart + encounter reachability report; runtime `softlock` (no damage/heal for 1200 ticks) and `timeout` outcomes in the sim; stall probe.
- `forge/save.py` + `autoload/save.gd` (`Save` autoload): Player State v3 (profile / roster / world), migrations v1→v2→v3, canonical JSON + sha256 checksum, atomic tmp→rename + `.bak` fallback, newer-version refusal; `forge save inspect|migrate`; `tools/savecheck.gd`.
- Tier-3 boss **Cave Warden** (HP-threshold phase manager: summons 2 emberlings at 66 %, enrage at 33 %), boss kit cleave / ember_bolt / quake, derived sprite, G1-Tile boss arena (`boss_room` carve, brief `content/briefs/f5/boss.yaml`), `boss_warden` encounter + `scenes/boss.tscn`, save on victory, boss music stem.
- F5 increment `first-boss` + acceptance (`forge/accept_f5.py`); `tests/test_f5_balance_save.py` (15 tests); `docs/acceptance-tests/F5.md`; `results/F5.json`, `results/F5-tune.json`.

### Changed
- Codegen validates boss phases (descending from 1.0, ability + summon refs) and exports them; roster schema adds `boss` / `phases`.
- BT: a tier-3 boss counts double for `should_taunt`; autoplay leader rallies outside an un-pulled boss's aggro ring until followers are in leash [INFERENCE F5-6].
- Starter-pet bonuses tuned (ember_fox atk 0.15→0.25, stone_tortle def 2→2.7, lumen_wisp hp 0.15→0.30); limits for `def_flat`.

### Measured
- G-BAL-01: 2400 fights, mean 0.732, max choice deviation 3.04 pp, 0 soft-locks — pass. Wall ≈ 109–135 s on 8 workers.
- Boss clear: victory in 880 ticks, all 3 phases, 2 summons.

### Known
- Per-combination spread 12.7 pp (soft metric, not met) — balance debt.
- Companion drafts (PocketLoom FabricCore, LoomCluster, GroundWeave) remain on `wip/f5-companions`, unverified.

## [0.4.0+f4] — 2026-11-12 — F4 Substrate: sandbox, hot reload, snapshots, statecharts, guardian

### Added
- `forge/sandbox.py` + `sandbox_worker.py`: tier ladder firecracker/gvisor (detected, no launcher) → bwrap (namespaces, no network, ro root) → process (rlimits, scrubbed env, audit hook); lifecycle telemetry; scratch snapshots; `forge sandbox doctor|run`; `forge build --sandbox`.
- `forge/live.py` + `autoload/live.gd`: live channel — monotonic tickets, sandboxed staging, `tune_limits` validation on both sides, two-phase commit at a tick boundary, 90-tick health probe, rollback, acks; `forge live set|sprite|push|watch|serve|status`; `content/tune/limits.yaml` exported into `game_data.json`.
- Tier-2 snapshots: `CombatSim.to_snapshot/restore/full_hash`, `Entity.to_dict/from_dict`; session WAL; on-disk restore + replay.
- Parallel statecharts: `sim/statechart.gd`, `forge/statechart.py` (soft-lock analysis), `data/statecharts/live_session.json` (combat / movement / ai / dialogue / reload).
- `forge/guardian.py`: crash/hang detection, exponential backoff, restart with `--live-resume` (session snapshot, poison-ticket quarantine, re-apply committed tickets), crash-loop give-up.
- F4 increment `live-tune` (`scenes/live.tscn`, `encounters/live_tune.json`) + two-phase acceptance (`forge/accept_f4.py`); `tests/test_f4_substrate.py` (28 tests); `docs/SUBSTRATE.md`, `docs/acceptance-tests/F4.md`.

### Changed
- `sim.leash` / `sim.separation` are per-sim (live-tunable); `EncounterBuilder.restat` re-derives stats in place; roster `ref` meta on entities.
- Replay no longer duplicates intents/swaps/callouts in reports.

### Known
- No micro-VM/gVisor launcher (no usable KVM); `process` tier is best-effort against native code.
- Swap advisor still ≈ 50–100 ms (target < 50 ms; ceiling 150 ms) — native step function not built.

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
