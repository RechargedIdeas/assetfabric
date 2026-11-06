# ADR-0004 — Inference runtime: GIRT over ONNX Runtime + llama.cpp

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Game AI needs policies (ONNX), small LMs, and STT across desktop, Android (NNAPI) and Web (WASM SIMD128) on an AMD-only fleet.

## Decision

Build **GIRT** (Godot Inference Runtime) as a unified serving layer with latency budgets. Backends: ONNX Runtime (CPU / DirectML / NNAPI / WASM) for policies and generators, llama.cpp (Vulkan/CPU) for the micro LM. Every model has a CPU path (GroundWeave).

## Consequences

- One API for game code; per-device profiles selected by H1 adapters.
- GIRT is an F3 deliverable; F0–F2 must not depend on it.

## Alternatives considered

- **Per-feature ad-hoc runtimes:** rejected (budget control impossible).
- **CUDA-first stacks:** rejected (ADR-0014).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
