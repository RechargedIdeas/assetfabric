# ADR-0014 — AMD-first backends: DirectML / ROCm / Vulkan (not CUDA-first)

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

The fleet has no NVIDIA GPUs (RX 7900, Vega 64/56, Mali, UHD 620).

## Decision

Prefer **DirectML** on Windows, **ROCm 6.x** on Linux for the 7900, **Vulkan** universally; Vegas use DirectML/Vulkan only. No feature may require CUDA; CUDA-only trainers need an honest alternative with real ETAs.

## Consequences

- Every GPU path has a CPU (GroundWeave) fallback.

## Alternatives considered

- **CUDA-first:** rejected (no hardware).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
