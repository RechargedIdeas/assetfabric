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
| **ShuttleLine** | Shuttle | Multi-engine export | Godot@F1; multi@F7 | **Godot target real** (`fabric_assets.json`) |
| **BoltPack** | Bolt | Signed SBOM packages | F7 | deferred |
| **PatternVault** | Vault | Versioned palettes/patterns | F1 | **real** (`content/patternvault/`, colour-blind variants) |
| **WhisperWeft** | Weft | Voice-driven Studio commands | F7+ | deferred |
| **RealityLoom** | Loom | Reconstruction orchestrator | C10+ | deferred |
| **SplatForge** | — | 3DGS training | C12 / F3–F4 backdrop | deferred |
| **MeshWeaver** | — | Splat→mesh | Phase 2 | deferred |
| **LensForge** | Lens | Camera intelligence | C10–C11 | deferred |
| **LoomCluster** | Loom | Equal-node clustering | C7 | placeholder |
| **GroundWeave** | Weave | GPU→CPU fallback ladder | C8 | principle only |
| **MirrorWeave** | Mirror | Cross-device control/stream | C9 | deferred |
| **LoomLink** | Link | PocketLoom↔desktop pairing | C5 | deferred |
| **GIRT** | — | Inference runtime | F3 | **real (CPU/GDScript)** — `autoload/girt.gd`: registry, latency budgets, telemetry, LM refusal inside tick; backends `mlp-gdscript`, `persona-bigram`. ONNX Runtime GDExtension deferred |
| **CascadeHub** | — | Multi-agent bus | F3 | **real** — `autoload/cascade_hub.gd`: typed topics, drained after each tick |
| **Substrate sandbox** | — | Isolated generator/authoring execution | F4 | **real** bwrap + process tiers (`forge sandbox`); Firecracker/gVisor detected only (no KVM launcher) |
| **Live channel** | — | Atomic hot reload + live tune | F4 | **real** (`forge live set/sprite/push/watch/serve/status`) |
| **Guardian** | — | Crash/hang self-healing | F4 | **real** (backoff restart, resume, quarantine); Crash Predictor deferred |
| **Statecharts** | — | Parallel SCXML-subset + soft-lock analysis | F4 | **real** (GDScript runtime + Python twin) |
| **BalanceSchema / Monte Carlo runner** | — | Parameterized rule space + Monte Carlo runner | F5 | **real** (`forge balance run`; headless Godot workers, CPU only) |
| **Bayesian optimizer** | — | Balance tuning (Optuna/Ax) | F5 | **real, Optuna TPE on CPU** (`forge balance tune`, optional extra `tune`); surrogate model / Ax not used |
| **Soft-lock detector** | — | Static + runtime soft-lock detection | F5 | **real** (`forge softlock`; runtime stall/timeout flags in the sim) |
| **Player State save** | — | Versioned save + migration (Profile/Roster/World) | F5 | **real** (`forge save inspect/migrate`; `autoload/save.gd`); cross-device round-trip (G-SAVE-01) is F7 |
| **GodotIPC / PWAPipeline / …** | — | Platform toolkit layers | staged | deferred |

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
| `forge report` | Regenerates STATUS.md |
| `forge sandbox doctor` / `run <brief>` | Lists real tiers; runs one brief sandboxed |
| `forge build --sandbox auto` | Every generator job sandboxed; output identical |
| `forge live set k=v …` / `sprite <id>` / `push` / `watch` | Ticket acked `committed` by a running game |
| `forge live serve` | Game under guardian; crash/hang → restart + resume |
