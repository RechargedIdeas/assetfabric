# ADR-0008 — Web target: WebGL 2.0 Compatibility; WebGPU out of v1

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

The PWA must run broadly and stay under a size budget (<45 MB compressed in chat).

## Decision

Web export uses Godot's **Compatibility renderer on WebGL 2.0**, packaged by PWAPipeline (COOP/COEP, offline service worker, size budget, smoke tests). WebGPU is out of scope for v1.

## Consequences

- Threads need COOP/COEP; single-thread fallback is decision D-001.

## Alternatives considered

- **WebGPU:** rejected for v1 (support/maturity).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
