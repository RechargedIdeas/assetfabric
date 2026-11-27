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
| `forge/voice.py`, `forge/cli_voice.py` | VoiceBridge: Vosk STT constrained to the intent grammar (`VERBS` read from `intent_grammar.gd`), confidence gate, `forge voice` | F3 / 0.7.8 |
| `forge/microlm.py` | Persona micro-LM: Qwen2.5-0.5B int8 ONNX (onnxruntime CPU), persona cards, review-gated drafts (`forge persona author`) merged into the callout cache | F3 / 0.7.8 |
| `forge/splattrain.py` | SplatForge CPU rung: tiny-scene isotropic 3DGS trainer (NumPy, analytic gradients) | C12 / 0.7.7 |
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
| `forge/worldfights.py`, `content/tune/worldfights.yaml` | World-fight Monte Carlo: replays each recorded slice fight (start state from `slice.gd::_fight_context`) in the balance worker; wipe-rate / clear-time bands per selection × fight (ADR-0020) | P7 (0.7.15) |
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
| `content/retro/profiles.yaml`, `forge/retro/` (`profiles`, `colour`, `transcode`, `asm6502`, `rom`, `emulator`, `readiness`, `validate`), `forge/generators/retro.py`, `forge/cli_retro.py`, `forge/accept_f8.py` | F8 ForgeConsole: Console Profile Registry, C1 palette + sub-palette + a11y signal solver, R1 LUT generator, ConsoleReadiness, own 6502 assembler + cycle predictor, iNES ROMBuilder, cynes EmulatorHarness, V1 frame gates + R2 discriminator, F8 acceptance | F8 |
| `games/game-zero/autoload/retro.gd`, `ui/retro_post.gdshader`, `tools/retrocheck.gd` | F8 R1 pass (CanvasLayer 1 between world and HUD), Q1 camera/sprite policy, settings, acceptance flows | F8 |
| `forge/accept_f7.py` | F7 acceptance: builds, desktop slice in a network-less namespace, Android content run, G-SAVE-01 ring, G-WEB-01, G-NET-01, remap | F7 |
| `companions/pocketloom/` | PocketLoom: `fabriccore/` (pure Kotlin/JVM runtime: JobExecutor, Dispatcher, AssetStore + version vectors, OffloadQueue, Telemetry, LocalForge, ModelCache, Captures, LoomLink client, SyncClient, CLI) + `app/` (Android UI, platform widgets) | real (C1–C6, debug APK) |
| `forge/loomlink.py` | Desktop side of LoomLink: pairing server (HMAC proofs, caps, signed requests), offload ops, sync planner + store (`forge link serve`) | real (C5/C6) |
| `forge/mirrorweave.py`, `forge/lensforge.py`, `forge/depth.py`, `forge/realityloom.py`, `forge/stubs.py`, `forge/registry.py`, `content/companions/c9_c12.yaml`, `content/patternvault/capture_profiles.json` | C9–C12: MirrorWeave frame hub + LoomLink routes, LensForge quality/modes/telemetry, pinhole depth + alignment, RealityLoom route/bundle/plan + `.ply` validator; the register marks each capability real / stub / deferred and is cross-checked against code, locales, Kotlin and the ladder (Kotlin: `fabric/core/{Stubs,MirrorWeave,LensForge,Depth,Recon}.kt`) | real CPU paths + labelled stubs (see §C9–C12) |
| `studio/` | Studio GUI (PySide6): Status, Mirror, Console (read-only `/` commands), Swatches, Voice, Persona | real, minimal (0.7.4–0.7.8) |
| `forge/loomcluster.py`, `cluster/loomcluster/` | LoomCluster (C7) equal-node scheduler | real, loopback-proven (see §LoomCluster / GroundWeave) |
| `forge/groundweave.py`, `content/groundweave/ladder.yaml` | GroundWeave (C8) GPU→CPU ladder | real; all GPU rungs `planned` |

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
   ─► godot --export-{release,debug} <preset> ─► dist/<target>/ (Linux · Windows · debug APK · Web PWA · Web single-thread fallback `web-nothreads`, ADR-0019)
   ─► verify (exported binary / PE / aapt+apksigner / PWAPipeline + headless Chrome)
   ─► ShuttleLine contract vs shipped PCK/APK ─► BoltPack SBOM + license audit ─► dist/bolt/*.fabricbolt
```

### Retro flow (F8, ADR-0021)

```
profiles.yaml + PatternVault ─► gen retro (C1 LUT, a11y signal solver, Q1 table) ─► assets/generated/retro/*_lut.png + retro.json
   ─► Godot: world (canvas 0) ─► Retro CanvasLayer 1: sample cell centre → a11y remap → LUT → scanlines ─► HUD CanvasLayer 2
sprites + tilemaps ─► AssetTranscoder (C1 sub-palettes, 8×8 CHR) ─► ROMBuilder (6502 asm + cycle predictor) ─► .nes ─► cynes EmulatorHarness ─► V1 match
```

### PocketLoom flow (C1–C6)

```
PocketLoom (standalone, offline)                          desktop (optional, paired)
 Generate ─► Dispatcher ─► LocalExecutor (LocalForge CPU) ─► AssetStore (sha256 blobs + version vectors)
 Capture (camera intent / import) ─► AssetStore + OffloadQueue[recon.capture]
 Link: code / loomlink:// QR / Tailscale IP ─► HMAC pairing ─► session key ─► signed requests
 OffloadQueue.drain ───────────────────────────────────────► forge/loomlink.py /offload (hashchain · gen · recon.capture→store)
 SyncClient ─► /sync/manifest (plan) ─► /sync/push · /sync/blob ◄──► SyncStore (same format; conflicts keep both)
```

FabricCore (Kotlin) and `forge/loomlink.py` (Python) are wire-compatible; shared vectors in `tests/fixtures/loomlink_vectors.json`.

The sim is separated from rendering so it can run headless (acceptance, balance, RL) at thousands of ticks per second and stay deterministic (state hash).

## Core technical decisions

| Subsystem | Decision |
|---|---|
| Engine | Godot 4, Compatibility renderer |
| Android (game) | Thin Kotlin plugins; game logic not primarily Kotlin |
| Android (companion) | PocketLoom: Kotlin, platform widgets (no AndroidX), FabricCore JVM module shared with a desktop CLI; LoomLink = HTTP + HMAC (Tailscale for encryption) |
| Desktop Studio | Python + PySide6 |
| Inference | ONNX Runtime (NNAPI / WASM SIMD128 / CPU / DirectML / Vulkan); AMD: DirectML or ROCm, not CUDA-first |
| RL training | PyTorch + Ray RLlib / CleanRL ↔ headless Godot gRPC |
| Micro LM | Shared backbone (Qwen2.5-0.5B or TinyLlama) + per-character LoRA |
| STT | Vosk primary (real on desktop since 0.7.8, grammar-constrained); whisper.cpp optional (not built) |
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
- ~~GroundWeave CPU fallbacks / 2-core acceptance~~ — done in C8 (CPU paths proven; no GPU backends exist yet).  

## LoomCluster / GroundWeave (C7 / C8)

```
 any node ──POST /submit──▶ Node (queue · slots=max(1,cores×cap%) · journal.jsonl)
   ▲  gossip /hello (adverts: cores, devices, slots, load) ◀──▶ peers          (equal nodes; coordinator = lowest id, reporting only)
   │  idle slot ──POST /steal──▶ busiest peer's queue TAIL (only jobs the thief can run; owner moves with the job)
   └─ POST /result ──▶ origin (parked + redelivered if the origin is down); origin lease re-queues work whose owner vanished
 job op ─▶ GroundWeave ladder (content/groundweave/ladder.yaml): rocm → directml → vulkan → cpu   (cpu rung is real and last)
```

- **Execution semantics:** at-least-once; ops are deterministic functions of their payload, so duplicates and placement do not change results (the first result wins). Failing jobs retry (`cluster.protocol.max_attempts`). `gen` runs in a child process whose device set is the node's advert.
- **Auth + artifacts (0.7.14):** every request/response is HMAC-SHA256 signed with the fleet secret (`X-Loom-Ts/Nonce/Sig`, `X-Loom-RSig`; ±120 s, nonce replay guard → 401; no secret → node refuses to start). Results carry `{sha256,size}`; the origin pulls signed `GET /blob/<sha256>` and verifies the digest before accepting. Not encrypted (C-95, C-96).
- **Placement:** `requires.device` is matched against adverts; unmatched → HTTP 400. GPU-required GroundWeave ops (`recon.splat`) are routed this way.
- **PocketLoom:** `forge link serve --cluster URL` plugs a `ClusterBridge` into LoomLink's `/offload`; the phone is a client of the fleet (a Kotlin peer node is future work).
- **GroundWeave rules:** every generator kind must have a `gen.<kind>` op; the last rung is a real CPU backend (or the op is `gpu_required` + `route: loomcluster`); `run_brief` refuses undeclared generators; `planned` rungs are never selected; `groundweave.execute` demotes a rung that raises. Transport is HTTP/JSON on loopback — see SECURITY.md for what that does not cover.

## C9–C12 companion interfaces (MirrorWeave · LensForge · depth · SplatForge path)

```
PocketLoom ──signed LoomLink──▶ /mirror/frame (stills · telemetry; seq-ordered ring, ≤ 8 MiB)      real
                                /mirror/control (forge.status · groundweave.show · mirror.stats)    real (read-only)
                                /mirror/frame screen_video|camera_video (VP8/VP9/H.264, keyframe-checked, GOP resync)  real
                                /mirror/ws/hello · /mirror/ws/frame (WebSocket, per-message HMAC)  real
                                /mirror/control input ─▶ Studio spool ─▶ Qt events                   real
                                /mirror/input/poll ◀─ desktop operator outbox (per-event MAC)       real (desktop) /
                                  └─ phone: AccessibilityService · Camera2Focus · MediaProjection    real_unverified_on_device
 desktop: x11grab ─▶ libvpx (system ffmpeg, separate process) ─▶ hub / WS                            real
 capture (still/burst/orbit/sweep) ─▶ LensForge.assess (integer luma · Laplacian var · clip %)       real, Kotlin = Python
 metres ◀─ Depth: pinhole + inverse-depth alignment ◀─ DepthAnything V2 Small (onnxruntime CPU)      real
          ◀─ ARCore DEPTH16 anchors + poses (desktop ingest real; phone ArCoreCapture)           real / real_unverified_on_device
 recon.capture ─▶ RealityLoom: route (backdrop→splat · hero_prop→photogrammetry→MeshWeaver) · bundle · plan  real
                  ├─ Photogrammetry: OpenCV SIFT SfM (CPU, sparse) ─▶ sfm/sparse.ply + cameras.json        real
                  ├─ splat .ply ─▶ MeshWeaver (density → surface nets → OBJ) · GDGS (Godot MultiMesh)      real
                  ├─ SplatForgeCPU: SfM poses ─▶ tiny isotropic 3DGS (NumPy, ≤2k splats/96 px) ─▶ splat/*.ply real
                  └─ submit: cluster placement check (rocm node?) ─▶ SplatForge full-scale [STUB, GPU] — nothing is queued
```

Rules: a stub raises `StubError`/`StubException` (`[STUB <id> <Cn>]`, locale key), never returns data; every capability is
a row in `content/companions/c9_c12.yaml` and `forge.registry.check` verifies the row against code, locales
(`stub.*` / Android `stub_*`), Kotlin symbols and GroundWeave ops. Ladder ops: real CPU `mirror.encode`, `lens.assess`,
`depth.distance`, `depth.estimate`, `recon.plan`, `recon.sfm`, `recon.mesh`, `shuttle.gdgs` (since 0.7.5–0.7.7);
`recon.splat_cpu` (bounded tiny-scene 3DGS, 0.7.7); `gpu_required` + `route: loomcluster`: `recon.splat` (full-scale). Inferences C-32…C-50; batch 1 (C9 real) C-51…C-59; batch 2/2b C-60…C-70; batch 3 (C12) C-71…C-77. A `real_unverified_on_device`
row must name an `android_impl` class that exists in the app module (`forge.registry.check`).
