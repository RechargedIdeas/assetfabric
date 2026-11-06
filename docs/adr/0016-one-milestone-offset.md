# ADR-0016 — One-milestone offset between Fabric and Game

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Platform work tends to outrun the product. The chat made the game the Fabric's proof.

## Decision

Fabric may be **at most one milestone ahead** of Game Zero. Fabric milestone F(n) is incomplete until the Game increment that depends on it ships, is playable, and passes its acceptance test. F(n+1) generator code may not merge before that.

## Consequences

- `forge.yaml` tracks `fabric.milestone` and `game.increment`; CI/agents enforce the gate.

## Alternatives considered

- **Platform-first:** rejected. **Game-first with ad-hoc tools:** rejected.

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
