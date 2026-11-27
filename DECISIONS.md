# DECISIONS.md — Architecture Decision Records (index)

Full ADR text lives in `docs/adr/NNNN-<slug>.md`. ADRs are never deleted — they are **superseded** by a later ADR that links back.

## Status values

`proposed` → `accepted` → (`superseded` | `deprecated`)

## Index

| ID | Title | Status |
|---|---|---|
| [0001](docs/adr/0001-license.md) | License: proprietary, All Rights Reserved | accepted |
| [0002](docs/adr/0002-engine-godot-4-compatibility.md) | Engine: Godot 4 with the Compatibility renderer | accepted |
| [0003](docs/adr/0003-gdscript-plus-gdextension.md) | Game language: GDScript + GDExtension (not C#) | accepted |
| [0004](docs/adr/0004-girt-inference-runtime.md) | Inference runtime: GIRT over ONNX Runtime + llama.cpp | accepted |
| [0005](docs/adr/0005-micro-lm-backbone.md) | Micro LM: shared small backbone + per-character LoRA | accepted |
| [0006](docs/adr/0006-stt-vosk.md) | Speech-to-text: Vosk primary, whisper.cpp optional | accepted |
| [0007](docs/adr/0007-sandbox-backends.md) | Sandbox backends: gVisor (short trusted) + Firecracker (untrusted/long) | accepted |
| [0008](docs/adr/0008-web-target-webgl2.md) | Web target: WebGL 2.0 Compatibility; WebGPU out of v1 | accepted |
| [0009](docs/adr/0009-multiplayer-webrtc-turn.md) | Multiplayer: WebRTC + STUN with mandatory self-hosted TURN | accepted |
| [0010](docs/adr/0010-model-families.md) | Model families: G1/D1/S1/H1/M1/C1/R2/O1 (+RC, Substrate) | accepted |
| [0011](docs/adr/0011-no-llm-in-combat-tick.md) | No LLM in the combat tick loop | accepted |
| [0012](docs/adr/0012-content-addressed-store.md) | Content-addressed asset store with provenance | accepted |
| [0013](docs/adr/0013-rename-to-assetfabric.md) | Product name: AssetFabric (not Asset Factory) | accepted |
| [0014](docs/adr/0014-amd-first-inference.md) | AMD-first backends: DirectML / ROCm / Vulkan (not CUDA-first) | accepted |
| [0015](docs/adr/0015-studio-pyside6.md) | Studio: Python + PySide6, outside Godot | accepted |
| [0016](docs/adr/0016-one-milestone-offset.md) | One-milestone offset between Fabric and Game | accepted |
| [0017](docs/adr/0017-slice-length-human-pace-gate.md) | Vertical-slice length gated on a human-pace estimate (until a playtest) | accepted |

## Open decisions (not ADRs yet)

Tracked in [TODO.md §Decisions needed](TODO.md#decisions-needed): **D-001** Web single-thread fallback (resume item e), **D-002** Android reference device, **D-005** final roster + economy/loot/quest content (Game Design; resume items a/b). F8 scope was confirmed by the Producer on 2026-11-20 (t59u, INFERENCE C-85). The swap-advisor native path (quality gap P3 follow-up) would use the GDExtension half of ADR-0003 — no new ADR needed unless it changes the GDScript-fallback rule.

## Adding an ADR

1. Copy the structure of an existing ADR (Context / Decision / Consequences / Alternatives / References) into `docs/adr/NNNN-<slug>.md` using the next free number.
2. Open a PR. Scope-affecting ADRs need **Producer + Factory Lead** approval (see `AGENTS.md` §3.3).
3. Add the row to this index in the same PR.
4. If the ADR diverges from `docs/design/` specs, say so explicitly in its Context section.
