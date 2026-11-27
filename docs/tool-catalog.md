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
| **SwatchStudio** | Swatch | Live material tuning + CLI echo | F1 | **CLI** (`forge palette`, `forge gen --seed`) + Studio Swatches tab (0.7.8, read-only palette/colour-blind view) |
| **ShuttleLine** | Shuttle | Multi-engine export | Godot@F1; multi@F7 | **real (F7)**: `shuttleline.contract/1` (`forge shuttle contract [--check]`), verified against every shipped PCK/APK (`dist/<target>/shuttle.json`); adapters `godot` + `generic-folder` (`forge shuttle export`) real; Unity/Unreal **interchange packs** (not run in the editors) via `forge universal export` since U1 |
| **BoltPack** | Bolt | Signed SBOM packages | F7 | **real, unsigned (F7)**: CycloneDX 1.5 SBOM from the engine's own copyright info + platform extras + game content, license allow-list audit (copyleft fails), `LICENSES/`, `dist/bolt/*.fabricbolt`; release signing TODO |
| **PatternVault** | Vault | Versioned palettes/patterns | F1 | **real** (`content/patternvault/`, colour-blind variants) |
| **WhisperWeft** | Weft | Voice-driven Studio commands | F7+ | VoiceBridge real (0.7.8: Vosk → closed grammar → intent; Studio Voice tab); voice → Studio command routing not built |
| **RealityLoom** | Loom | Reconstruction orchestrator | C12 | route/bundle/plan/placement real; CPU photogrammetry (OpenCV SfM) real (0.7.7); GPU splat stage stub |
| **SplatForge** | — | 3DGS training | C12 / F3–F4 backdrop | tiny-scene CPU trainer **real** (0.7.7, `recon.splat_cpu`, own NumPy isotropic 3DGS, ≤ 2k splats); full-scale **stub** (`recon.splat` gpu_required → loomcluster) |
| **MeshWeaver** | — | Splat→mesh | Phase 2 | **real** CPU rung (0.7.7: density → surface nets → OBJ); SuGaR rung planned (GPU) |
| **LensForge** | Lens | Camera intelligence | C10–C11 | quality/modes/telemetry, video keyframe ingest, ARCore pose coverage/DEPTH16 ingest, dense depth (DepthAnything V2 Small, CPU) real; phone Camera2 video/focus + ARCore capture `real_unverified_on_device` |
| **LoomCluster** | Loom | Equal-node clustering | C7 | **real (C7), loopback-proven**: `forge/loomcluster.py`, `forge cluster …`; negotiation, stealing, leases, retry, journal recovery, device placement, LoomLink bridge; **HMAC-signed node requests/responses + content-addressed `/blob/<sha256>` transfer since 0.7.14** (`forge cluster keygen`). No LAN run, no encryption |
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
| **BalanceSchema / Monte Carlo runner** | — | Parameterized rule space + Monte Carlo runner | F5 | **real** (`forge balance run`; headless Godot workers, CPU only; `forge balance holdout` — per-pair spread on 1000 unseen seeds/cell, gated ≤ 3.5 pp in full `forge accept F5` since 0.7.13; world-fight wipe-rate / clear-time bands over every slice fight, `forge/worldfights.py`, gated in `forge accept F6` since 0.7.15) |
| **Bayesian optimizer** | — | Balance tuning (Optuna/Ax) | F5 | **real, Optuna TPE on CPU** (`forge balance tune`; `forge balance tune-affinity` = 12 per-cell studies, 0.7.13; optional extra `tune`); surrogate model / Ax not used |
| **Soft-lock detector** | — | Static + runtime soft-lock detection | F5 | **real** (`forge softlock`; runtime stall/timeout flags in the sim) |
| **Player State save** | — | Versioned save + migration (Profile/Roster/World) | F5 | **real** (`forge save inspect/migrate`; `autoload/save.gd`; v4 world layer at F6); cross-device round-trip **G-SAVE-01 proven at F7** (desktop → Android → Web → desktop) |
| **Quest state machine** | — | Quest SM | F6 | **real** (quests compiled to a parallel statechart by Codegen-World; `world/quest_log.gd` + Python twin; static soft-lock analysis) |
| **Farming / economy** | — | Farm, gather, grow, craft feeding economy + combat | F6 | **real** (`content/world/economy.yaml`; plots, crops, gather nodes, recipes, buffs, gear; economy-solvability gate) + **economy design model** since 0.7.13 (`content/world/economy_design.yaml`, `forge/economy.py`: derived values, `economy_design` gate, slice loot MC + XP pacing in F6; ADR-0018) — numbers await Game-Design sign-off (D-005) |
| **Loot tables** | — | Loot tied to tiers | F6 | **real** (`content/world/loot.yaml`; deterministic LCG rolls, GDScript ↔ Python parity, EV in registry) |
| **Adaptive music** | — | Stems layered by biome/state | F6 | **real** (`audio/music_director.gd` + `content/world/music.yaml`; G1-Audio stems `music_field`, `music_cave`) |
| **QA autopilot** | — | AI agent playtests (hybrid QA) | F6 | **scripted** deterministic agent (`world/autopilot.gd`), not learned; humans still needed for length/feel |
| **PWAPipeline** | — | Web export orchestrator: size budgets, COOP/COEP, offline SW, smoke tests | F7 | **real** (`forge/pwa.py`): G-WEB-01 gzip budget, SW cache-list check, `_headers`, URL-fragment arg hook, headless-Chrome smoke (headers, isolation, SW, offline reload, header-less host); `web-nothreads` single-thread fallback + `patch_sw` stale-entry fix since 0.7.14 (ADR-0019) |
| **Packaging (`forge build --target`)** | — | Desktop / Android / Web exports | F7 | **real** (`forge/packaging.py`): hermetic Godot home, pinned 4.3 templates (`forge templates`), staged keep-import, Linux/Windows/debug APK/Web PWA + `web-nothreads` (0.7.14), per-target verify, `BUILD.json` |
| **GodotIPC** | — | Android data-plane bridge | staged | deferred |
| **ConsoleReadiness** | — | Console porting gate (memory / palette / tile budgets) | F8 | **real** (`forge/retro/readiness.py`, `forge retro readiness`): per-profile budgets over every sprite + area, fidelity ΔE/dL*, ROM budgets |
| **ForgeConsole** | — | Console Profile Registry → ConstraintCompiler → AssetTranscoder → CodeGen → ROMBuilder → EmulatorHarness → CertPack | F8 | **real** except CertPack + fantasy consoles (deferred): `content/retro/profiles.yaml`, `forge/retro/` (C1 solver, transcoder, own 6502 assembler + cycle predictor, iNES NROM field-demo ROM, cynes harness), `forge retro rom|emulate` |
| **R1 Retro Render Compiler** | — | Console-style post-process | F8 | **real**: generator kind `retro` → 64³ LUTs + `retro.json`; `ui/retro_post.gdshader` + `autoload/retro.gd` |
| **Q1 Pixel Stability Solver** | — | Integer camera / sprite policy, shimmer | F8 | **real** (policy + shimmer predictor, `forge retro shimmer`) |
| **V1 Retro Validation Harness / R2** | — | Frame gates, fidelity delta, discriminator | F8 | **real** (`forge/retro/validate.py`; R2 = NumPy logistic regression, not a learned image model) |
| **LiveOps readiness (remote config / feature flags)** | — | SPEC §12 "LiveOps readiness: remote config / feature flags (launch content deferred)"; GAME_SPEC §8 remote config hooks for balance knobs | F9 | **real, readiness only**: `content/liveops/flags.yaml` → generator kind `liveops`; `forge liveops manifest|keygen|bundle|verify|install|rollback|status|diag-export|readiness`; game `autoload/liveops.gd` (signed local bundles, crash-loop quarantine, tamper → defaults). No service / endpoint (ADR-0022) |
| **Diagnostics export** | — | SPEC §12 compliance / privacy; SECURITY §6 "telemetry stays on-device unless the user opts in to export" | F9 | **real, local**: consent flag default off, `forge liveops diag-export --consent` PII scrub + `diag_bundle.schema.json`; never uploads |
| **Universal IR + adapters** | Shuttle (generalised) | One scene IR for 2D/2.5D/3D (sprites, layers, meshes, skins, PBR, cameras, point clouds, 3DGS) + 10 coordinate conventions + tiered adapters | U1 | **real**: `forge/universal/` (ir, coords, gltf, exporters/), `forge universal export|verify|demo|adapters|native`; 23 adapters — **native_verified** Godot 4.3 + Blender 4.3 (headless runs), **cli_bridge** OpenSCAD, **interchange_pack** Unreal (GLB + Paper2D + editor-Python import), Unity (UPM + .meta + .unitypackage), RPG Maker MV/MZ/VX Ace, Sprite Lamp/Pro, Construct, Clickteam, AppGameKit, GameGuru/CopperCube/Esenthel/AGFPRO/RaySupreme mesh packs, COLMAP, 3DGS PLY/nerfstudio, Fuse/ePic/recon importers — those tools themselves are **not run** (ADR-0023). No FBX/USD writer |
| **Engines catalog** | — | Every engine on Wikipedia's *List of game engines* + named tools | U1 | **real**: `content/universal/engines_catalog.yaml` (178 Wikipedia rows, rev 1388112807 + 28 curated tools = 199 entries; tiers 2/1/120/76), `forge universal catalog|search|catalog-build` |
| **Parametric (OpenSCAD bridge + CSG fallback)** | — | Parametric templates → `.scad/.stl/.obj/.off/.glb` | U1 | **real**: `content/universal/parametric/`, `forge parametric list|scad|build`; real OpenSCAD CLI when installed + own NumPy SDF/marching-tetrahedra fallback (GroundWeave `gen.parametric` CPU rung), volume cross-check (ADR-0024) |
| **Self-improvement loop** | — | Benchmark-gated recipe promotion + rollback | U1 | **real**: `forge/universal/evolution.py`, `forge universal evolve|evolve-history|evolve-rollback`; families `parametric.csg`, `maps2d.normal`; production reads the active recipe (ADR-0025) |
| **Plugins + gap detector** | — | Grow new formats safely; report what is missing | U1 | **real**: `forge universal gaps|plugin-scaffold|plugin-verify|plugin-register|plugin-rollback|plugins`; static AST policy + sandboxed (bwrap) contract suite + sandboxed proxies; example `content/universal/plugins/x3d-export` (ADR-0026) |

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
| `godot --headless --path games/game-zero -- --scene=swapbench [--reps=N]` | Swap-advisor benchmark + LOD fidelity (Q3); `forge accept F3` runs it pinned to 2 physical cores and gates p95 < 50 ms on the reference node |
| `forge accept C1-C6` / `C<n>` | PocketLoom Gradle build + APK verify + Kotlin↔Python interop pass; `results/C<n>.json` recorded |
| `forge accept C9-C12` / `C<n>` | MirrorWeave / LensForge / depth / SplatForge-path contracts verified, every stub refuses with a `[STUB …]` label, real CPU paths exact on 2 cores; `results/C<n>.json` |
| `forge accept U1` | Universal engine: OpenSCAD + CSG parametric, IR round-trips, 23 adapters × reference scenes (+ Godot/Blender/OpenSCAD native when installed), catalog integrity, evolution promote/reject/rollback, plugin register/hot-load/hostile rejection; `results/U1.json` |
| `forge parametric build <tpl> --out DIR` / `forge universal export <engine> --scene … --out DIR` | Mesh/pack written + re-verified; exit 1 on a failed gate/verify |
| `forge universal gaps` / `plugin-verify DIR` | Live gap report / manifest + static policy + sandboxed contract; exit 1 when rejected |
| `forge mirror info/push/latest/stream/control` | all real (0.7.4): stills/telemetry, `stream --source desktop|desktop-video` (X11 capture, CPU VP8/VP9), `control --action query|input` (Studio input); the phone halves are `real_unverified_on_device` |
| `forge lens modes/assess/exif/session/focus/video` | all real on the desktop (0.7.5–0.7.6): `video` keyframe ingest (system ffmpeg), `session --kind arcore` pose coverage, `focus` queues a request for a paired phone (phone Camera2 side `real_unverified_on_device`) |
| `forge depth distance/estimate` | real: `distance` (pinhole), `estimate` (DepthAnything V2 Small on onnxruntime CPU — needs `forge models fetch`; `--backend arcore` DEPTH16 ingest) |
| `forge recon route/tools/bundle/plan/submit/check-splat/train/photogrammetry/mesh/godot-import` | all real except `train --stage splat` (full-scale GPU, exit 3) and `submit` (placement check, then SplatForge stub; nothing queued); `train --stage splat-cpu BUNDLE` is real (tiny scenes) |
| `forge voice grammar/transcribe/intent/eval` | real (0.7.8): Vosk small en-us constrained to the intent grammar; needs `forge models fetch vosk-small-en-us-0.15` |
| `forge persona author` | real (0.7.8): Qwen2.5-0.5B int8 ONNX drafts persona lines (safety + meta filter); `--write` queues them `reviewed: false` |
| `forge link serve` | Prints one-time code + `loomlink://` URI (QR if `qrcode` installed); serves pairing/offload/sync |
| `forge report` | Regenerates STATUS.md |
| `forge sandbox doctor` / `run <brief>` | Lists real tiers; runs one brief sandboxed |
| `forge build --sandbox auto` | Every generator job sandboxed; output identical |
| `forge live set k=v …` / `sprite <id>` / `push` / `watch` | Ticket acked `committed` by a running game |
| `forge live serve` | Game under guardian; crash/hang → restart + resume |
