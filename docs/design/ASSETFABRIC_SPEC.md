# ASSETFABRIC_SPEC.md — Production Build Spec

> **Source of truth:** DeepSeek share https://chat.deepseek.com/share/g90tn4mss3265u0xm3 (ChatGrabber high fidelity, 56 messages).  
> **Prefer chat content over invention.** Items marked `[INFERENCE]` are reasonable extrapolations not stated verbatim.  
> **Rename:** Asset Factory → **AssetFabric** (name collision with existing AssetFactory products; fabric metaphor chosen in chat).  
> **First product / MVP test:** Game Zero (see `GAME_SPEC.md`). AssetFabric is built in game-dependency order, proven by playable increments.

---

## 1. Purpose

AssetFabric is a **universal content fabric and execution substrate** for producing games and assets end-to-end: generation, validation, packaging, AI runtime, sandboxed execution, reconstruction, clustering, and companion tooling. It is not a conventional asset packager alone.

**Governing principle (chat):** A Factory/Fabric milestone is not complete until a **game increment that depends on it ships, is playable, and passes its acceptance test.**

**What AssetFabric is:**
- Unified generation toolkit (GUI + CLI + REST + MCP + ACP + in-Studio terminal)
- Godot 4 production toolkit (plugins, bridges, import contracts)
- ML model mesh + metamodels + training/telemetry
- Universal emulation / console-style layer + micro-VM sandbox + hot reload / snapshots
- Android Kotlin companion (**PocketLoom**): standalone offline + optional desktop pairing
- Heterogeneous compute clustering (**LoomCluster**) with CPU software fallbacks (**GroundWeave**)
- Cross-device control/streaming (**MirrorWeave**) and capture/reconstruction (**LensForge / RealityLoom / SplatForge / MeshWeaver**)

**What it is not (v1 hard deferrals):** quantum *hardware* backend (simulation OK), fantasy consoles (PICO-8/TIC-80), modern console CertPacks, community mod marketplace, P2P mesh beyond 2 players, dedicated servers, full M1-Architect discovery as a ship gate.

---

## 2. Architecture Overview

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
│ Substrate (UEF): sandbox · micro-VMs · hot reload · snapshots   │
│ Guardian · Parallel statecharts · Emulator harness              │
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

### Core technical decisions (from chat)

| Subsystem | Decision |
|---|---|
| Engine | Godot 4, Compatibility renderer for 2D / mobile / Web |
| Android (game) | Thin Kotlin plugins (`@UsedByGodot`); game logic not primarily Kotlin |
| Desktop Studio | Python + PySide6; WebSocket/TCP or shared SQLite/DuckDB to Godot |
| Inference | ONNX Runtime (NNAPI / WASM SIMD128 / CPU / DirectML / Vulkan); AMD fleet: DirectML or ROCm, not CUDA-first |
| RL training | PyTorch + Ray RLlib / CleanRL consuming headless Godot via gRPC |
| Micro LM | Shared backbone (Qwen2.5-0.5B or TinyLlama) + per-character LoRA |
| STT | Vosk primary; whisper.cpp optional high-accuracy fallback |
| P2P | Godot `WebRTCMultiplayerPeer` + STUN; **TURN mandatory** for NAT failure mode |
| Balance | Parameterized schema + Monte Carlo / Bayesian optimizer (Optuna/Ax) |
| Telemetry | Structured events → SQLite/DuckDB + live WebSocket to Studio |
| Data stores | SQLite (jobs/telemetry/registry cache/Player State); content-addressed blob store; MLflow lineage; DuckDB analytics |

### Hard runtime constraints

1. **No LLM in the combat tick loop.**
2. **No untrusted code without sandbox during authoring.**
3. **No client-authoritative multiplayer state.**
4. **No hard-coded strings or paths** (locale keys + manifests).
5. **Every GPU capability has a CPU software path** (or declared GPU requirement routed by LoomCluster).
6. **Weakest acceptance node: 2 cores, no GPU** (Ryzen 5 1600 with GPUs disabled used as contract hardware in chat).

---

## 3. Godot Tooling / Plugins

Godot is directionally capable but has structural gaps. AssetFabric ships a layered toolkit:

### Layer A — Platform & Export
| Tool | Role |
|---|---|
| **GodotIPC** | Reliable Android data-plane bridge (replace fragile plugin IPC for STT/ONNX/sensors) |
| **PWAPipeline** | Web export orchestrator: size budgets, COOP/COEP, offline SW, smoke tests |
| **ConsoleReadiness** | Porting gate / memory budget validator (modern consoles deferred; gate still useful) |

### Layer B — AI & Inference
| Tool | Role |
|---|---|
| **GIRT** | Godot Inference Runtime — unified ONNX/policy/LM serving with latency budgets |
| **LoRAManager** | Adapter residency, hot-swap, callout pre-generation |
| **VoiceBridge** | Offline STT (Vosk) with grammar-constrained intents |

### Layer C — Gameplay & Simulation
| Tool | Role |
|---|---|
| **CascadeHub** | Multi-agent typed message bus (JSON/MessagePack); semantic intents, not LLM-on-critical-path |
| **HeadlessSim** | Deterministic simulation harness + fidelity gates for RL / balance |
| **BalanceSchema** | Parameterized rule space + Monte Carlo runner |

### Layer D — Performance & Rendering
| Tool | Role |
|---|---|
| **NativeHotPath** | Coarse-grained GDExtension for hot paths (GDScript is interpreter) |
| **UI Toolkit** | Performance-safe UI patterns |
| **StreamWorld** | Chunk streaming + LOD for caves/open world |
| **SpatialAudioBridge** | Spatial audio with occlusion |
| **R1 Retro Render Compiler** | Shader foundry, scene templates, camera rigs, render contract schema |
| **Q1 Pixel Stability Solver** | Offline UV/geometry quantization, shimmer predictor, camera policy |
| **V1 Retro Validation Harness** | Authenticity / fidelity gates |

### Layer E — Observability
| Tool | Role |
|---|---|
| **TelemetryStream** | Structured event schema + backpressure |
| **ThoughtStreamViewer** | Real-time agent introspection |
| **ProfilerBridge** | Native/extension profiling |

**Language note (chat):** C# is **not** the primary game language for this project; GDScript + Rust/C++ GDExtension for hot paths. Hot-reload references to C# plugins are Substrate options, not a mandate to rewrite game logic in C#.

---

## 4. Universal Asset Generation Toolkit (Content Forge)

### 4.1 Surfaces (all first-class)

| Surface | Purpose |
|---|---|
| **GUI (Studio)** | Visual builder, SwatchStudio, dashboards, sandbox |
| **CLI (`forge`)** | Human + agent scripting |
| **REST API** | CI, remote agents |
| **MCP** | Model Context Protocol — tool discovery for AI agents |
| **ACP** | Agent Client Protocol — editor-to-agent sessions |
| **WebSocket** | Live telemetry, MirrorWeave, LoomLink |
| **gRPC** | Training / bulk transfer |
| **In-Studio terminal** | Shared-state REPL with slash commands |

### 4.2 Terminal slash commands (chat catalog)

| Command | Description |
|---|---|
| `/help [command]` | Catalog or detailed help |
| `/generate <type> <brief>` | Start generation job |
| `/preview <type> [options]` | Dry-run without commit |
| `/commit [job_id]` | Promote preview to canonical |
| `/validate [asset]` | Run validation gates |
| `/export <target>` | Export for Godot/Unity/Unreal |
| `/generators` | List generators, schemas, budgets |
| `/assets` | Browse/filter asset catalog |
| `/budget` | Spend / remaining / cost per generator |
| `/session save\|load\|list` | Session management |
| `/mcp status\|start\|stop` | Embedded MCP server |
| `/acp status\|start\|stop` | Embedded ACP agent |
| `/sandbox <agent_id>` | Isolated sandbox + thought stream |
| `/clear`, `/quit`, `/history` | REPL controls |

Prefixes: `/` local slash; `$` sandboxed shell; bare text → core API / agent.

GUI and terminal are **bidirectional views of the same state** (command echo from sliders; shared job progress; dual permission prompts).

### 4.3 Budget & permission engine

Every generation job is gated: resource budgets (tri count, texture size, tile count, audio channels, memory, latency), permissions (destructive actions need consent), and content safety for LM outputs.

### 4.4 Godot runtime binding

GDExtension + GDScript `ContentForge` API allows **runtime generation during play** under stricter budgets; imports emit presets so bundles land with zero manual wiring. Runtime generation must stay off combat-critical paths unless deterministic fallbacks exist.

### 4.5 AssetFabric tool catalog (fabric-themed names)

| Tool | Metaphor | Purpose | Milestone (approx.) |
|---|---|---|---|
| **DyeWorks** | Dyeing | PBR materials (albedo/normal/roughness/metalness/height/AO); backends: procedural / internal diffusion / optional AssetFactory API | F1 |
| **G1-Sprite** | — | 8-bit palette-constrained sprites + anim sheets | F1 |
| **G1-Tile** | — | NCA tilemaps / caves with solvability | F1 |
| **G1-Audio** | — | Chiptune stems (ambient/tension/combat/boss) | F2 |
| **Codegen** | — | Stats, abilities, characters, loot, dialogue templates → GDScript/`.tres` | F2 |
| **SwatchStudio** | Swatch | Live material/parameter tuning with CLI echo | F1 |
| **ShuttleLine** | Shuttle | Multi-engine export (Godot first; Unity/Unreal adapters) | Godot@F1; multi@F7 |
| **BoltPack** | Bolt | Signed, SBOM-audited publish packages (`.fabricbolt`) | F7 |
| **PatternVault** | Vault | Versioned palettes/patterns/capture profiles | F1 |
| **WhisperWeft** | Weft | Voice-driven Studio commands (Vosk → grammar → CascadeHub) | F7+ |
| **RealityLoom** | Loom | Reconstruction orchestrator (splat vs mesh routing) | C10+ |
| **SplatForge** | — | 3DGS training from capture | C12 / F3–F4 backdrop path |
| **MeshWeaver** | — | Splat→mesh conversion | Phase 2 reconstruction |
| **LensForge** | Lens | Camera intelligence, depth, capture telemetry | C10–C11 |
| **LoomCluster** | Loom | Equal-node compute clustering | C7 |
| **GroundWeave** | Weave | GPU→CPU software fallback ladder | C8 |
| **MirrorWeave** | Mirror | Bidirectional cross-device control + screen stream | C9 |
| **LoomLink** | Link | Pairing (QR / codes / Tailscale) between PocketLoom and desktop | C5 |

**First-party procedural generators** (runtime-capable) vs **adapter plugins** (authoring-only) vs **code generators** — as designed in Content Forge gap analysis.

Optional later: integrate useful **AssetFactory** (third-party) features as backends where licensing allows; prefer internal/procedural offline paths for v1 offline guarantee.

---

## 5. ML Models, Metamodels, Training, Telemetry

### 5.1 Model family mesh

| Family | Purpose | Runtime notes |
|---|---|---|
| **G1** | Asset generators (sprite, tile, texture, audio) | Authoring 50–500 ms; runtime <100 ms where claimed |
| **D1** | Data optimizers (active learning, synth, augment) | Offline |
| **S1** | Upscale / downscale / cycle-consistency | Mobile upscale <5 ms target |
| **H1** | Hardware NAS, compression, per-device adapters | Offline → deploy |
| **M1** | Meta-models: architecture discovery + Bayesian/NSGA tuning | Hours; **M1-Architect deferred for v1 ship** |
| **C1** | Console constraint solvers / palette / cycle predictors | Console-style path |
| **R2** | Retro authenticity (constraint, fidelity delta, discriminator) | Retro render packs |
| **O1** | Observers (telemetry thought streams, dashboards) | Always-on observability |
| **R1 Reality Capture** `[INFERENCE: named R1 in reconstruction msg; avoid clash with Retro R1 — treat as RealityCapture / RC family in implementation]` | Capture quality, splat params, compression | Reconstruction path |
| **S-series Substrate** | Backend selector, snapshot policy, crash predictor, sandbox allocator, quantum circuit optimizer | Execution layer |

### 5.2 Notable concrete models (chat)

- **G1-Sprite:** Tiny (2–4 MB ONNX) + Medium (5–6 MB), CPU-capable
- **G1-Tile:** NCA (~2 MB), CMA-ME diversity, A* solvability gate
- **G1-Texture / DyeWorks diffusion:** SD1.5-class on Vega; SDXL-class on 7900 XTX when GPU available; procedural fallback always
- **S1-Up / S1-Down:** mobile real-time upscaler + learned downscaler + joint consistency trainer
- **H1-Compress / H1-NAS / H1-Registry:** prune → distill → quantize; device adapter registry
- **D1-Active / D1-Synth / D1-Augment:** curator, synthetic factory, augmentation policy learner
- **M1-Architect / M1-Tuner:** LLM-agent architecture search + Optuna/NSGA-II (Architect out of v1 DoD)
- **Game AI:** Behavior Tree + ONNX RL policy (PPO); hierarchical RL for bosses; shared LM + LoRA; Vosk STT
- **Depth:** DepthAnything V2 (+ ARCore where available) for LensForge

### 5.3 Training pipelines

1. **Automated self-training:** headless Godot self-play → experience via gRPC → PyTorch/RLlib → ONNX INT8 → hot-swap; continual learning with replay + regularization
2. **Manual training workspace:** Studio UI to train, test, talk to, sandbox-interact with models
3. **Character creator path:** save emits `.tres` + LoRA fine-tune job + policy warm-start
4. **MLOps:** model registry with lineage; MLflow tracking; drift detector + retraining gate (gap-fill)

### 5.4 Telemetry dashboards & thought streams

Structured event fields (minimum): `timestamp`, `agent_id`, `agent_type`, `event_type`, `state_before`/`after`, `action_taken`, `action_source` (BT/policy/LLM/player), `inference_latency_ms`, `model_id`/`version`, `thought_stream`, plus sandbox fields (`sandbox_id`, `profile`, `sim_tick`, `state_hash`).

Dashboard panels: fleet overview, pipeline flow diagram, thought-stream viewer, quality heatmap, compression Pareto frontier, training curves, anomaly flags. Tiered telemetry with **backpressure**.

**Thought streams for non-LLM models:** expose intermediate decisions / feature attributions / policy logits summaries — not only token monologues.

---

## 6. Console-Style / Emulator Layer + Sandbox / Micro-VMs + Hot Reload

### 6.1 Universal Emulation Fabric (UEF / Substrate)

| Backend | Covers | Isolation |
|---|---|---|
| libretro / WASM | NES→PS1, GBA, Genesis, N64, arcade | WASM sandbox |
| Native emulators | PS2, GC/Wii, PSP, Dreamcast | Process / micro-VM |
| wasmcart | Fantasy / custom retro carts | Fixed ABI WASM |
| QEMU / MicroVM | Full OS / legacy software | KVM / Hypervisor |
| Quantum simulators | Gate circuits | State-vector / tensor-network (sim-only in v1) |

**Product stance (chat pivot):** Prefer **emulator targets + console-style authenticity in Godot** over shipping licensed console binaries. Modern console CertPacks are post-v1. Retro ROM path (F8) is optional/confirm-before-build.

**ForgeConsole** (when enabled): Console Profile Registry, ConstraintCompiler, AssetTranscoder, CodeGen, ROMBuilder, EmulatorHarness, CertPack (deferred).

Three paths unified: (1) real ROMs in emulators, (2) console-style Godot authenticity profiles/shaders, (3) fantasy consoles (deferred).

### 6.2 Micro-VM sandbox kernel

| Isolation | When |
|---|---|
| **Firecracker** | Long-running / untrusted / stateful (games session, emulator, training env) |
| **gVisor** | Short trusted jobs (single asset gen, quick test) |
| **Microsandbox** | Interactive Studio sandboxes; disk snapshots |

Lifecycle: `CREATED → PROVISIONING → RUNNING → SNAPSHOTTING → RESTORING → TERMINATED` under **Sandbox Orchestrator** (quotas, timeouts, snapshot policies, audit).

### 6.3 Atomic hot reload, parallel states, snapshots

- **Atomic reload:** monotonic version ticket → stage/validate in isolation → two-phase commit → health probe → rollback on failure
- **Parallel statecharts:** combat / movement / AI / dialogue concurrent (StateCharts / SCXML semantics)
- **Snapshots:** Tier1 micro-VM; Tier2 application/ECS; Tier3 CRIU; WAL between snapshots
- **Failover:** in-sandbox rollback → sandbox restore → session host migration
- **Guardian:** crash detect, auto-restart with backoff, resource anomaly, predictive crash model `[chat: Crash Predictor]`

---

## 7. Gaussian Splatting / Photogrammetry Integration Map

Treat 3DGS as a **parallel asset class**, not a mesh replacement.

| Method | Role in AssetFabric |
|---|---|
| Photogrammetry (COLMAP/Meshroom) | Hero props/characters needing collision/topology |
| 3D Gaussian Splatting | Photoreal backdrops / set pieces; real-time friendly |
| NeRF | Reference / research; not primary realtime path |
| Neural SDF | Future mesh extraction path |

**Tools:** RealityLoom (orchestrator), SplatForge (train splat), MeshWeaver (splat→mesh, e.g. SuGaR / GOF), ShuttleLine Godot 3DGS adapter (GDGS plugin), PatternVault capture profiles, BoltPack license/SBOM for COLMAP/Nerfstudio deps.

**Phased:**
1. **Backdrop pipeline:** COLMAP + Nerfstudio/OpenSplat → `.ply`/`.splat` → Godot GDGS Raster backend
2. **Hybrid:** RealityLoom routes `backdrop`→splat, `hero_prop`→photogrammetry or MeshWeaver
3. **Large scenes:** LOD/streaming (LODGE/MobileSplat principles), GDGS relighting

**AMD honesty (chat):** Dominant 3DGS trainers are CUDA-centric. Paths: OpenSplat+ROCm on Linux 7900; CPU COLMAP + burst GPU; photogrammetry-only Meshroom CPU. Always show honest ETAs (CPU room capture can be hours).

---

## 8. Android Kotlin Companion (PocketLoom)

**Corrected model (chat):** Two **equal editions**, not phone-as-peripheral.

### Standalone (offline, required)
- LocalForge on-device generation (procedural + small ONNX)
- Local asset store, telemetry UI, generate screen
- Capture for later offload
- Works with **nothing else connected**

### When paired (enhancement)
- LoomLink: pairing codes, **QR**, **Tailscale**
- Bidirectional: phone can drive desktop Studio; desktop can drive phone
- Offload heavy jobs; sync with conflict resolution
- LensForge capture → RealityLoom/SplatForge on desktop/cluster

### Shared
- **FabricCore** Kotlin Multiplatform shared module
- JobExecutor contract; OffloadQueue for deferred work
- Model cache + eviction on device

### Security
- Pairing handshake, capability model, permission gates, no ambient authority over host without consent

---

## 9. Resource Clustering / Equal Nodes / CPU Fallback

### LoomCluster
- Every connected device is an **equal node** that **advertises and negotiates** resources
- User-set allocation caps per device
- Distributed job queue, work stealing, checkpointing
- Coordinator can be elected; not master-slave with PocketLoom

### GroundWeave
- **Fallback ladder** for every GPU op → software/CPU backends
- **Two-core, no-GPU guarantee:** tools must complete within declared budgets on acceptance hardware (or declare GPU-required and LoomCluster must route)

### MirrorWeave
- Android screen stream → desktop
- Desktop remote control of Android; Android remote control of desktop
- Camera video/stills/focus/telemetry streaming

### LensForge
- Capture modes; ARCore + DepthAnything V2; monocular distance estimates; offload path for reconstruction

---

## 10. Hardware Notes (from chat — authoritative inventory)

| Node | Specs | Tier / Role |
|---|---|---|
| **main** | Ryzen 9 5900X, RX 7900 XFX 24GB, 64GB RAM (~32GB free typical) | T1 — Studio host, heavy gen/train |
| **secondary** | Ryzen 5 1600, Vega 64 + Vega 56 (8GB each), 32GB RAM | T2 — batch gen, parallel inference; GPUs do **not** pool |
| **redmi** | Redmi Note 12 Pro 5G, Dimensity 1080, Mali-G68, 8GB | T3 — PocketLoom reference device |
| **lemur** | System76 Lemur Pro 9 (Clevo L140CU), i7-10510U, UHD 620, **40GB RAM**, Windows (WSL2 optional) | T4 — portable Studio, warm model cache, light inference |
| **nokia** | Nokia 7.2 | T5 — QR/client/review |
| **kindle-1/2** | Kindle Fire tablets | T5 — second-screen dashboards |

**AMD-critical:** No NVIDIA in fleet. Prefer DirectML on Windows; ROCm 6.x if Linux on 7900; Vulkan (llama.cpp) universal path; disable OpenVINO-on-UHD620 as primary (often slower than CPU). Vega: DirectML/Vulkan only (not ROCm 6).

---

## 11. Documentation Suite the Chat Required

Build agents must maintain (content specified in final chat messages):

| Doc | Role |
|---|---|
| **README.md** | Humans + agents: what AssetFabric / Game Zero are, quick start, doc map |
| **AGENTS.md** | Rules of engagement, read order, scope discipline, one-milestone offset, testing, commits, blockers, governance |
| **BUILD_ORDER.md** | Authoritative F0–F7 + C1–C12 sequence |
| **HANDOVER.md** | Current state snapshot for next agent |
| **PLAN.md** | Vision, pillars, DoD, milestones, fleet, out-of-scope, failure modes |
| **TODO.md** | Sprint tasks, backlog, blockers, bugs, decisions needed |
| **ARCHITECTURE.md** | Systems, tools, models, stores, protocols, constraints |
| **DECISIONS.md** / ADRs | Indexed ADRs |
| **docs/tool-catalog.md** | Per-tool purpose, CLI, acceptance |
| **docs/hardware-fleet.md** | Node config |
| **TESTING.md** | QA pyramid, acceptance, CI gates, performance/fidelity contracts |
| **SECURITY.md** | Threat model, privacy, compliance, SBOM, console NDA |
| **CONTRIBUTING.md** | Setup, PR checklist |
| **GLOSSARY.md** | Terms |
| **CHANGELOG.md** | Unreleased / versions |

This `ASSETFABRIC_SPEC.md` is the **condensed production build spec** derived from that suite + prior design turns; implementers should expand into the full doc tree as F0.

---

## 12. Gap-Fill Expectations (must be implemented, not waved)

From successive gap analyses + final fill pass:

| Gap area | Expectation |
|---|---|
| Android IPC | GodotIPC production bridge |
| ONNX portability | Per-device profiles + GroundWeave; never assume CUDA |
| LoRA memory | Residency manager + callout cache |
| PWA size/threading | PWAPipeline + hard size budget (<45 MB compressed game web target in chat) |
| WebRTC NAT | TURN always available |
| RL collapse | Pool-based opponents + fidelity gates |
| Balance | Parameterized schema + surrogate optimizer |
| Multi-agent | Cascade architecture, not per-agent prompting in tick |
| Voice CPU budget | Shared Vosk; grammar constraints; don’t dual full STT+TTS without budget |
| Telemetry | Schema + backpressure (not ad-hoc logs) |
| Optimal swap | Forward simulation <50 ms, not pure heuristic |
| 3D/PBR/rigging | DyeWorks + Forge3D-class tools + MeshWeaver |
| MLOps | Registry, experiments, drift monitor |
| Agentic orchestration | MCP/ACP first-class |
| Runtime LLM safety | Governance LLM gate |
| Compliance | Age gates / disclosure / moderation hooks (EU AI Act, COPPA awareness) |
| Anti-cheat | Server-authoritative validation for MP |
| LiveOps readiness | Remote config / feature flags (launch content deferred) |
| Hybrid QA | AI agents + human playtesters |
| L10n / a11y | Generated keys; colorblind palettes; remapping |
| SBOM | License audit in CI |
| Milestone discipline | CI-enforced one-milestone offset + scope guard |

---

## 13. Phased Build Order (agent-executable)

**Parallel contract:** Fabric always **one milestone ahead** of game. Fabric cannot start F(n+1) until F(n)’s game increment ships. Companion track C* runs parallel as specified.

### Fabric + Game Zero

| ID | Weeks (indicative) | Fabric delivers | Game proves |
|---|---|---|---|
| **F0** | 1–4 | Manifest, `forge` CLI, asset store, orchestrator, telemetry schema | Empty Godot boots; `forge status` healthy |
| **F1** | 5–10 | Sprite/tile/DyeWorks procedural, gates, Godot presets, PatternVault, SwatchStudio | Playable sandbox: 1 char, 1 tilemap, 1 enemy, 1 attack |
| **F2** | 11–14 | Codegen (chars/abilities/stats), G1-Audio | First combat: party of 4 + pets + enemies |
| **F3** | 15–20 | GIRT, CascadeHub, micro LM, callouts | Party AI, swap, dialogue, callouts |
| **F4** | 21–25 | Sandbox/micro-VM, hot reload, snapshots, statecharts | Live tune without full rebuild |
| **F5** | 26–29 | Monte Carlo balance, soft-lock, save migration | First boss |
| **F6** | 30–33 | Quest SM, farming, loot, adaptive music | **Vertical slice 15–20 min** |
| **F7** | 34–38 | Desktop/Android/Web PWA packaging, ShuttleLine multi, BoltPack | Tier1+Tier2 launches |
| **F8** | optional | Retro/console-style | Confirm scope first |
| **F9** | post | LiveOps foundation | Readiness only |

### Companion / Cluster (parallel)

| ID | Focus |
|---|---|
| C1 | PocketLoom / FabricCore |
| C2 | On-device generation |
| C3 | Standalone UI |
| C4 | Local capture |
| C5 | Pairing (QR/codes/Tailscale) |
| C6 | Offload + sync |
| C7 | LoomCluster |
| C8 | GroundWeave |
| C9 | MirrorWeave |
| C10 | LensForge capture |
| C11 | Metric depth |
| C12 | Cluster reconstruction (SplatForge path) |

### Cross-cutting
Governance pipeline continuous (LLM gate, compliance, SBOM, drift, milestone/scope guards).

### Suggested agent first session
1. Read README → AGENTS → PLAN → BUILD_ORDER → HANDOVER → TODO  
2. Implement **F0 only** until acceptance green  
3. Do not start F1 generators until F0 game/env gate passes  
4. Keep HANDOVER/TODO current every session  

---

## 14. Definition of Done — AssetFabric v1 (summary)

See chat Part 1 / PLAN DoD. Headline: content gen + validation + Godot bridge + AI runtime + substrate + balance/QA + player state + l10n/a11y + platform targets + observability + PocketLoom C1–C6 minimum for “two editions” + LoomCluster/GroundWeave for fleet — each with **executable acceptance tests**. Anything not on the DoD list is out of scope without a formal trade.

---

*End of ASSETFABRIC_SPEC.md*
