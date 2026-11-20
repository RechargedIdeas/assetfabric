# docs/tool-catalog.md — Fabric tools

Fabric-themed names from ASSETFABRIC_SPEC §4.5. Status column reflects what is implemented on `main`; see STATUS.md for milestone acceptance.

| Tool | Metaphor | Purpose | Milestone | F0 status |
|---|---|---|---|---|
| **forge CLI** | — | Human + agent scripting | F0 | **real** (`status`/`doctor`/…) |
| **Content Forge core** | — | Orchestrator, store, schemas | F0 | **skeleton** |
| **DyeWorks** | Dyeing | PBR materials; procedural / diffusion / optional API | F1 | **procedural real** (`kind: material`, albedo+normal, seamless gate); diffusion later |
| **G1-Sprite** | — | 8-bit palette sprites + anim sheets | F1 | **procedural real** (`kind: sprite`, 6-frame sheets); ONNX Tiny later |
| **G1-Tile** | — | NCA tilemaps / caves + solvability | F1 | **CA real** (`kind: tilemap`, solvability + floor-ratio gates); NCA later |
| **G1-Audio** | — | Chiptune stems | F2 | **procedural real** (`kind: audio`, 4 macro-state stems + SFX, WAV) |
| **Codegen** | — | Stats/abilities/chars → GDScript/`.tres` | F2 | **real** (`kind: codegen`, game_data.json + ability `.tres`, derived sprite briefs) |
| **SwatchStudio** | Swatch | Live material tuning + CLI echo | F1 | **CLI** (`forge palette`, `forge gen --seed`); GUI with Studio |
| **ShuttleLine** | Shuttle | Multi-engine export | Godot@F1; multi@F7 | **real (F7)**: `shuttleline.contract/1` (`forge shuttle contract [--check]`), verified against every shipped PCK/APK (`dist/<target>/shuttle.json`); adapters `godot` + `generic-folder` (`forge shuttle export`) real, Unity/Unreal not built |
| **BoltPack** | Bolt | Signed SBOM packages | F7 | **real, unsigned (F7)**: CycloneDX 1.5 SBOM from the engine's own copyright info + platform extras + game content, license allow-list audit (copyleft fails), `LICENSES/`, `dist/bolt/*.fabricbolt`; release signing TODO |
| **PatternVault** | Vault | Versioned palettes/patterns | F1 | **real** (`content/patternvault/`, colour-blind variants) |
| **WhisperWeft** | Weft | Voice-driven Studio commands | F7+ | deferred |
| **RealityLoom** | Loom | Reconstruction orchestrator | C12 | interface + plan real; stages are stubs |
| **SplatForge** | — | 3DGS training | C12 / F3–F4 backdrop | **stub** (refuses; `recon.splat` gpu_required → loomcluster) |
| **MeshWeaver** | — | Splat→mesh | Phase 2 | **stub** (`recon.mesh` planned) |
| **LensForge** | Lens | Camera intelligence | C10–C11 | quality/modes/telemetry real (CPU); ARCore/video/focus + dense depth stubs |
| **LoomCluster** | Loom | Equal-node clustering | C7 | **real (C7), loopback-proven**: `forge/loomcluster.py`, `forge cluster …`; negotiation, stealing, leases, retry, journal recovery, device placement, LoomLink bridge. No LAN run, no auth |
| **GroundWeave** | Weave | GPU→CPU fallback ladder | C8 | **real (C8)**: `content/groundweave/ladder.yaml`, `forge/groundweave.py`, `forge groundweave …`; CPU rungs real, every GPU rung `planned` (no GPU backend built); enforced by the pipeline. PocketLoom applies the rule locally (C2) |
| **MirrorWeave** | Mirror | Cross-device control/stream | C9 | stills, CPU VP8/VP9 video, X11 capture, signed WS, Studio input real; Android capture/H.264/input/focus `real_unverified_on_device` |
| **LoomLink** | Link | PocketLoom↔desktop pairing | C5 | **real (C5/C6)**: one-time code + `loomlink://` QR URI + Tailscale address, HMAC-SHA256 mutual proof, capability ∩, signed requests; offload + version-vector sync (`forge link serve`, `forge/loomlink.py`, `fabric.core.LoomLinkClient`). No TLS/PAKE yet |
| **PocketLoom** | — | Standalone Android companion | C1–C6 | **real, debug APK (C1–C6)**: Generate · Library · Capture · Link · Telemetry; offline-first; not yet run on a device |
| **FabricCore** | — | Shared Kotlin runtime (JobExecutor, store, queue, telemetry) | C1 | **real, JVM-only** (KMP targets later); also a desktop CLI jar |
| **LocalForge** | — | On-device generation | C2 | **CPU procedural real** (caves, sprites, gates + retry); ONNX rung = labelled stub |
| **OffloadQueue** | — | Deferred heavy work until paired | C6 | **real** (durable JSONL journal, torn-line safe, drains via LoomLink) |
| **GIRT** | — | Inference runtime | F3 | **real (CPU/GDScript)** — `autoload/girt.gd`: registry, latency budgets, telemetry, LM refusal inside tick; backends `mlp-gdscript`, `persona-bigram`. ONNX Runtime GDExtension deferred |
| **CascadeHub** | — | Multi-agent bus | F3 | **real** — `autoload/cascade_hub.gd`: typed topics, drained after each tick |
| **Substrate sandbox** | — | Isolated generator/authoring execution | F4 | **real** bwrap + process tiers (`forge sandbox`); Firecracker/gVisor detected only (no KVM launcher) |
| **Live channel** | — | Atomic hot reload + live tune | F4 | **real** (`forge live set/sprite/push/watch/serve/status`) |
| **Guardian** | — | Crash/hang self-healing | F4 | **real** (backoff restart, resume, quarantine); Crash Predictor deferred |
| **Statecharts** | — | Parallel SCXML-subset + soft-lock analysis | F4 | **real** (GDScript runtime + Python twin) |
| **BalanceSchema / Monte Carlo runner** | — | Parameterized rule space + Monte Carlo runner | F5 | **real** (`forge balance run`; headless Godot workers, CPU only) |
| **Bayesian optimizer** | — | Balance tuning (Optuna/Ax) | F5 | **real, Optuna TPE on CPU** (`forge balance tune`, optional extra `tune`); surrogate model / Ax not used |
| **Soft-lock detector** | — | Static + runtime soft-lock detection | F5 | **real** (`forge softlock`; runtime stall/timeout flags in the sim) |
| **Player State save** | — | Versioned save + migration (Profile/Roster/World) | F5 | **real** (`forge save inspect/migrate`; `autoload/save.gd`; v4 world layer at F6); cross-device round-trip **G-SAVE-01 proven at F7** (desktop → Android → Web → desktop) |
| **Quest state machine** | — | Quest SM | F6 | **real** (quests compiled to a parallel statechart by Codegen-World; `world/quest_log.gd` + Python twin; static soft-lock analysis) |
| **Farming / economy** | — | Farm, gather, grow, craft feeding economy + combat | F6 | **real** (`content/world/economy.yaml`; plots, crops, gather nodes, recipes, buffs, gear; economy-solvability gate) — content placeholders (D-005) |
| **Loot tables** | — | Loot tied to tiers | F6 | **real** (`content/world/loot.yaml`; deterministic LCG rolls, GDScript ↔ Python parity, EV in registry) |
| **Adaptive music** | — | Stems layered by biome/state | F6 | **real** (`audio/music_director.gd` + `content/world/music.yaml`; G1-Audio stems `music_field`, `music_cave`) |
| **QA autopilot** | — | AI agent playtests (hybrid QA) | F6 | **scripted** deterministic agent (`world/autopilot.gd`), not learned; humans still needed for length/feel |
| **PWAPipeline** | — | Web export orchestrator: size budgets, COOP/COEP, offline SW, smoke tests | F7 | **real** (`forge/pwa.py`): G-WEB-01 gzip budget, SW cache-list check, `_headers`, URL-fragment arg hook, headless-Chrome smoke (headers, isolation, SW, offline reload, header-less host) |
| **Packaging (`forge build --target`)** | — | Desktop / Android / Web exports | F7 | **real** (`forge/packaging.py`): hermetic Godot home, pinned 4.3 templates (`forge templates`), staged keep-import, Linux/Windows/debug APK/Web PWA, per-target verify, `BUILD.json` |
| **GodotIPC / ConsoleReadiness** | — | Android data-plane bridge / console porting gate | staged | deferred |

### CLI acceptance

| Command | Acceptance |
|---|---|
| `forge status` | Exit 0 when env healthy; JSON with `healthy: true` |
| `forge doctor` | Exit 0 when required deps present |
| `forge validate manifest` | Exit 0 on valid `forge.yaml` |
| `forge build [--brief GLOB]` | All briefs pass gates; assets exported + registry written |
| `forge gen <id> [--seed N]` | One brief; exit 1 on gate failure |
| `forge palette [name] [--variant]` | Lists/echoes PatternVault swatches |
| `forge accept <F>` | Headless Godot increment passes; result recorded |
| `forge accept C1-C6` / `C<n>` | PocketLoom Gradle build + APK verify + Kotlin↔Python interop pass; `results/C<n>.json` recorded |
| `forge accept C9-C12` / `C<n>` | MirrorWeave / LensForge / depth / SplatForge-path contracts verified, every stub refuses with a `[STUB …]` label, real CPU paths exact on 2 cores; `results/C<n>.json` |
| `forge mirror info/push/latest/stream/control` | stills/telemetry real; `stream --source screen` / `camera-video`, `control --target android` exit 3 (stub) |
| `forge lens modes/assess/exif/session` | modes/quality/EXIF real; `session --kind arcore` / `focus` / `video` exit 3 |
| `forge depth distance/estimate` | `distance` real (pinhole); `estimate` exit 3 (stub) |
| `forge recon route/tools/bundle/plan/submit/check-splat/train` | all real except `train` (exit 3) and `submit` (placement check, then SplatForge stub; nothing queued) |
| `forge link serve` | Prints one-time code + `loomlink://` URI (QR if `qrcode` installed); serves pairing/offload/sync |
| `forge report` | Regenerates STATUS.md |
| `forge sandbox doctor` / `run <brief>` | Lists real tiers; runs one brief sandboxed |
| `forge build --sandbox auto` | Every generator job sandboxed; output identical |
| `forge live set k=v …` / `sprite <id>` / `push` / `watch` | Ticket acked `committed` by a running game |
| `forge live serve` | Game under guardian; crash/hang → restart + resume |
