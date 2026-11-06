# DECISIONS.md — Architecture Decision Records (index)

Full ADR text: `docs/adr/NNNN-<title>.md`. Never delete ADRs — supersede.

## Format

Status: proposed | accepted | superseded | deprecated.

## Index

| ID | Title | Status |
|---|---|---|
| 0001 | License for the project | proposed |
| 0002 | Engine: Godot 4 Compatibility renderer | accepted |
| 0003 | Primary game language: GDScript + GDExtension (not C#) | accepted |
| 0004 | Inference runtime: GIRT over ONNX Runtime + llama.cpp | accepted |
| 0005 | Micro LM backbone: Qwen2.5-0.5B INT4 + LoRA | accepted |
| 0006 | STT: Vosk primary (+ whisper.cpp optional) | accepted |
| 0007 | Sandbox backends: gVisor (trusted) + Firecracker (untrusted) | accepted |
| 0008 | Web target: WebGL 2.0 Compatibility; WebGPU out of v1 | accepted |
| 0009 | Multiplayer: WebRTC + self-hosted TURN | accepted |
| 0010 | Model families: G1/D1/S1/H1/M1/C1/R2/O1 (+RC/Substrate) | accepted |
| 0011 | No LLM in combat tick loop | accepted |
| 0012 | Content-addressed asset store with provenance | accepted |
| 0013 | Product name: AssetFabric (not Asset Factory) | accepted |
| 0014 | AMD-first backends: DirectML / ROCm / Vulkan (not CUDA-first) | accepted |
| 0015 | Studio: Python + PySide6 (not embedded in Godot) | accepted |
| 0016 | One-milestone offset Fabric↔Game | accepted |

## Adding an ADR

1. Draft `docs/adr/NNNN-<title>.md`.  
2. PR; scope-affecting needs Producer + Factory Lead.  
3. Index here on merge.
