# docs/tool-catalog.md — Fabric tools

Fabric-themed names from ASSETFABRIC_SPEC §4.5. Status column reflects what is implemented on `main`; see STATUS.md for milestone acceptance.

| Tool | Metaphor | Purpose | Milestone | F0 status |
|---|---|---|---|---|
| **forge CLI** | — | Human + agent scripting | F0 | **real** (`status`/`doctor`/…) |
| **Content Forge core** | — | Orchestrator, store, schemas | F0 | **skeleton** |
| **DyeWorks** | Dyeing | PBR materials; procedural / diffusion / optional API | F1 | **procedural real** (`kind: material`, albedo+normal, seamless gate); diffusion later |
| **G1-Sprite** | — | 8-bit palette sprites + anim sheets | F1 | **procedural real** (`kind: sprite`, 6-frame sheets); ONNX Tiny later |
| **G1-Tile** | — | NCA tilemaps / caves + solvability | F1 | **CA real** (`kind: tilemap`, solvability + floor-ratio gates); NCA later |
| **G1-Audio** | — | Chiptune stems | F2 | deferred |
| **Codegen** | — | Stats/abilities/chars → GDScript/`.tres` | F2 | deferred |
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
| **GIRT** | — | Inference runtime | F3 | deferred |
| **CascadeHub** | — | Multi-agent bus | F3 | deferred |
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
