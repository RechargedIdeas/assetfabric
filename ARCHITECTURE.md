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

## F0 code map (what exists now)

| Path | Role |
|---|---|
| `forge/` | Content Forge Python package + CLI |
| `forge.yaml` | Project manifest |
| `docs/schemas/` | JSON Schemas (manifest, telemetry) |
| `store/` | Content-addressed asset store root |
| `.fabric/` | Jobs DB + telemetry JSONL (gitignored data) |
| `games/game-zero/` | Empty Godot 4 project |
| `studio/` | PySide6 stub |
| `companions/pocketloom/` | Placeholder |
| `cluster/loomcluster/` | Placeholder |

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
