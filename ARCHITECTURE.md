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
│ Substrate (UEF): sandbox · micro-VMs · hot reload · snapshots   │
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
| `forge/milestones.py` | Milestone ↔ increment registry, headless acceptance, offset guard | F1 |
| `forge/report.py` | STATUS.md generator | F1 |
| `games/game-zero/autoload/fabric.gd` | Runtime binding: registry, runtime asset loading, input schema, locales, watchdog | F1 |
| `games/game-zero/sim/` | Deterministic fixed-step sim (grid, entity, sandbox) | F1 |
| `games/game-zero/scenes/` | boot (router), sandbox (render + input) | F0/F1 |
| `studio/`, `companions/pocketloom/`, `cluster/loomcluster/` | Studio / companion / cluster tracks | stub |

### Content flow (F1)

```
content/briefs/*.yaml ─► forge build ─► JobOrchestrator ─► generator (CPU procedural)
        ─► gates (palette, seamless, solvability, budget) ─► AssetStore (sha256 + provenance)
        ─► games/game-zero/assets/generated/<kind>/ + fabric_assets.json
        ─► Fabric autoload (runtime load) ─► sim + scenes
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
