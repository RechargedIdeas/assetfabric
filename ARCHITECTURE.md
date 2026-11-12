# ARCHITECTURE.md — Technical System Map

Normative map for AssetFabric. Design specs live in `docs/design/`; ADRs + this file supersede them where they conflict.

## High-level

```
┌─────────────────────────────────────────────────────────────────┐
│ Studio (Python / PySide6)  — authoring, training, telemetry UI  │
│  + embedded terminal (slash cmds) + MCP host + ACP agent        │
└───────────────┬───────────────────────────┬─────────────────────┘
                │ REST/CLI/WS/gRPC          │ LoomLink / Tailscale
┌───────────────▼──────────────┐   ┌────────▼─────────────────────┐
│ Content Forge core           │   │ PocketLoom (Android Kotlin)  │
│ Generators · Validators ·    │   │ Standalone LocalForge +      │
│ Orchestrator · BudgetGate    │   │ optional peer with desktop   │
└───────────────┬──────────────┘   └────────┬─────────────────────┘
                │                           │
┌───────────────▼───────────────────────────▼─────────────────────┐
│ Substrate (UEF): sandbox · hot reload · snapshots · guardian    │
└───────────────┬─────────────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────────┐
│ Godot 4 game runtime (Compatibility renderer)                   │
│ GIRT · CascadeHub · ShuttleLine imports · Retro render packs    │
└─────────────────────────────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────────┐
│ LoomCluster: equal nodes · negotiate resources · GroundWeave    │
└─────────────────────────────────────────────────────────────────┘
```

## Code map (current)

| Path | Role | Since |
|---|---|---|
| `forge/cli.py` | `forge` CLI: status, doctor, validate, job, store, build, gen, palette, accept, report | F0/F1 |
| `forge/manifest.py`, `forge.yaml` | Project manifest + schema validation | F0 |
| `forge/store.py` | Content-addressed blob store + provenance manifests (ADR-0012) | F0 |
| `forge/orchestrator.py` | SQLite job queue + in-order worker (`run_pending`) | F0/F1 |
| `forge/telemetry.py` | Telemetry schema + JSONL emitter | F0 |
| `forge/imaging.py` | Dependency-free RGBA/PNG codec | F1 |
| `forge/patternvault.py`, `content/patternvault/` | Versioned palettes + colour-blind variants | F1 |
| `forge/gates.py` | palette / dims / seamless / solvability / floor-ratio / BudgetGate | F1 |
| `forge/generators/` | Generator registry: `sprite` (G1-Sprite), `tilemap` (G1-Tile), `material` (DyeWorks) | F1 |
| `forge/pipeline.py`, `content/briefs/` | brief → generator → gates → store → Godot export + `fabric_assets.json` | F1 |
| `forge/generators/codegen.py`, `content/roster/` | Roster YAML → `game_data.json` + ability `.tres`; derived sprite briefs | F2 |
| `forge/generators/audio.py` | G1-Audio chiptune stems + SFX (WAV) | F2 |
| `forge/generators/policy.py` | P-TargetSelect: NumPy behaviour cloning → JSON MLP + parity probe | F3 |
| `forge/generators/callouts.py`, `content/personas/` | Safety-gated callout cache; persona bigram LM stand-in + mirrored sampler | F3 |
| `forge/milestones.py` | Milestone ↔ increment registry, headless acceptance, offset guard | F1 |
| `forge/report.py` | STATUS.md generator | F1 |
| `games/game-zero/autoload/fabric.gd` | Runtime binding: registry, runtime asset loading, input schema, locales, watchdog | F1 |
| `games/game-zero/sim/` | Deterministic fixed-step sim: grid, entity, `combat_sim` (abilities, party, pets, taunt), `encounter_builder` (roster refs → entities, pet bonuses) | F1/F2 |
| `games/game-zero/data/` | `ability.gd` Resource, encounters, `generated/` (codegen output) | F2 |
| `games/game-zero/scenes/` | boot (router), `encounter.gd` (render, input, music, freeze overlay, command box, dialogue) used by sandbox/combat/party scenes | F0–F3 |
| `games/game-zero/autoload/girt.gd` | GIRT: model registry, budgets, telemetry, policy + LM backends; refuses LM inside tick | F3 |
| `games/game-zero/autoload/cascade_hub.gd` | CascadeHub typed bus, drained after each tick | F3 |
| `games/game-zero/ai/` | `brain.gd` (compiled BTs + policy targeting), `swap_advisor.gd` (threaded forward sim), `intent_grammar.gd` | F3 |
| `forge/sandbox.py`, `forge/sandbox_worker.py` | Substrate sandbox tiers (firecracker/gvisor detected; bwrap + process real), lifecycle, scratch snapshots, worker protocol | F4 |
| `forge/live.py`, `content/tune/limits.yaml` | Live channel (Forge side): tickets, staging, validation, `forge live` | F4 |
| `forge/statechart.py` | Statechart runtime twin + static soft-lock analysis | F4 |
| `forge/guardian.py` | Crash/hang supervisor, backoff, restart with `--live-resume` | F4 |
| `forge/accept_f4.py` | F4 two-phase acceptance (backlog run + live process under guardian) | F4 |
| `games/game-zero/autoload/live.gd` | Live channel (game side): poll, validate, overlay, acks, in-flight marker, quarantine, WAL | F4 |
| `games/game-zero/sim/statechart.gd`, `data/statecharts/` | Parallel statechart runtime (combat / movement / ai / dialogue / reload) | F4 |
| `forge/balance.py`, `games/game-zero/tools/balance.gd` | Monte Carlo balance runner (sharded headless Godot workers, CRN seeds, Wilson CIs, G-BAL-01 verdict) + Optuna TPE tuner | F5 |
| `forge/softlock.py` | Static soft-lock report (statecharts + encounter reachability) + stall-probe overrides; runtime detector lives in `sim/combat_sim.gd` | F5 |
| `forge/save.py`, `games/game-zero/autoload/save.gd` | Player State save (Profile / Roster / World), v1→v2→v3→v4 migrations (v4: farm, checkpoint, quest counters, buffs, gear — F6), canonical JSON + sha256, atomic write + `.bak` fallback (Python twin ↔ GDScript) | F5 |
| `forge/accept_f5.py`, `scenes/boss.tscn`, `data/encounters/boss_warden.json` | F5 acceptance (boss clear ×2, save round-trip, G-BAL-01, soft-lock probe); tier-3 boss with HP-phase manager | F5 |
| `content/world/*.yaml`, `forge/generators/world.py`, `forge/world.py` | **Codegen-World**: economy (items, crops, recipes, shop, XP), tiered loot tables, quests (compiled to one parallel statechart), adaptive-music rules, area graph → `data/generated/world.json`; gates schema / cross-refs / quest-chart soft-lock / economy solvability / loot / music; Python twins (Lcg, roll_loot, QuestLog, guards) for parity | F6 |
| `forge/generators/tile.py` (features) | G1-Tile open-world features: farm plots `P`, workbench `W`, gather nodes `G`, pinned hostile spawns (`spawn_at`); caves without features stay byte-identical | F6 |
| `games/game-zero/world/` | `world_state.gd` (inventory, farm, nodes, packs, buffs, gear, XP, quest counters, save ↔ state), `quest_log.gd` (statechart + guards), `loot.gd`, `autopilot.gd` (scripted QA agent) | F6 |
| `games/game-zero/audio/music_director.gd` | Adaptive music: per-biome stem sets, explore / tension / combat / boss layer maps with fades | F6 |
| `forge/accept_f6.py`, `scenes/slice.tscn` | F6 vertical slice (select → farm → tunnels → cave → craft → boss → open world → save) + quit/reload parity, 12-selection matrix, quest/loot/save parity, locale coverage | F6 |
| `forge/packaging.py`, `games/game-zero/export_presets.cfg` | F7 packaging: toolchain discovery (Godot, pinned 4.3 templates, JDK 17, Android SDK), hermetic Godot home (`.fabric/godot-home`), stage with keep-import, exports, per-target verify (PE, aapt/apksigner, exported-binary smoke), PCK/APK readers, `BUILD.json` | F7 |
| `forge/pwa.py` | PWAPipeline: G-WEB-01 budget, SW cache list, `_headers`, fragment-args hook, local server + headless Chrome harness (`WebHarness`) | F7 |
| `forge/shuttleline.py` | ShuttleLine `shuttleline.contract/1`, per-target shipped-content verification, `generic-folder` adapter | F7 |
| `forge/boltpack.py` | BoltPack: CycloneDX SBOM (engine copyright info + platform extras + content), license audit, `LICENSES/`, `.fabricbolt` | F7 |
| `forge/accept_f7.py` | F7 acceptance: builds, desktop slice in a network-less namespace, Android content run, G-SAVE-01 ring, G-WEB-01, G-NET-01, remap | F7 |
| `studio/`, `companions/pocketloom/`, `cluster/loomcluster/` | Studio / companion / cluster tracks | stub |

### Content flow (F1)

```
content/briefs/*.yaml ─► forge build ─► JobOrchestrator ─► generator (CPU procedural)
        ─► gates (palette, seamless, solvability, budget) ─► AssetStore (sha256 + provenance)
        ─► games/game-zero/assets/generated/<kind>/ + fabric_assets.json
        ─► Fabric autoload (runtime load) ─► sim + scenes
```

### Live flow (F4)

```
forge live set/sprite/push ─► stage (sandbox regen) + validate (tune_limits) ─► ticket n + HEAD (atomic)
   ─► game polls HEAD at a tick boundary ─► re-validate (limits + sha256) ─► inflight marker ─► snapshot
   ─► apply + restat ─► health probe (90-tick clone) ─► commit | rollback ─► ack n ─► session snapshot + WAL
guardian: crash/hang ─► kill ─► backoff ─► restart --live-resume (snapshot + quarantine + re-apply)
```

### Packaging flow (F7)

```
games/game-zero ─► dist/.stage (no .gdignore; PNG/WAV importer="keep") ─► godot --import
   ─► godot --export-{release,debug} <preset> ─► dist/<target>/ (Linux · Windows · debug APK · Web PWA)
   ─► verify (exported binary / PE / aapt+apksigner / PWAPipeline + headless Chrome)
   ─► ShuttleLine contract vs shipped PCK/APK ─► BoltPack SBOM + license audit ─► dist/bolt/*.fabricbolt
```

The sim is separated from rendering so it can run headless (acceptance, balance, RL) at thousands of ticks per second and stay deterministic (state hash).

## Core technical decisions

| Subsystem | Decision |
|---|---|
| Engine | Godot 4, Compatibility renderer |
| Android (game) | Thin Kotlin plugins; game logic not primarily Kotlin |
| Desktop Studio | Python + PySide6 |
| Inference | ONNX Runtime (NNAPI / WASM SIMD128 / CPU / DirectML / Vulkan); AMD: DirectML or ROCm, not CUDA-first |
| RL training | PyTorch + Ray RLlib / CleanRL ↔ headless Godot gRPC |
| Micro LM | Shared backbone (Qwen2.5-0.5B or TinyLlama) + per-character LoRA |
| STT | Vosk primary; whisper.cpp optional |
| P2P | Godot WebRTCMultiplayerPeer + STUN; **TURN mandatory** |
| Telemetry | Structured events → SQLite/DuckDB + WS to Studio |
| Data stores | SQLite; content-addressed blobs; MLflow; DuckDB analytics |

## Model families

G1, D1, S1, H1, M1 (Architect deferred), C1, R2, O1, RealityCapture/RC, Substrate S-series.  
New families require an ADR. See `docs/design/ASSETFABRIC_ML_AI_FEATURES.md`.

## Protocol surfaces

REST · CLI (`forge`) · MCP · ACP · WebSocket · gRPC · in-Studio terminal.

## Key constraints

- No LLM in combat tick loop.  
- No unsandboxed untrusted authoring code.  
- No client-authoritative MP state.  
- No hard-coded strings/paths.  
- GroundWeave CPU fallbacks / 2-core acceptance.  
