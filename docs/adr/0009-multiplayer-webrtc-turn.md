# ADR-0009 — Multiplayer: WebRTC + STUN with mandatory self-hosted TURN

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

v1 multiplayer is host/client co-op for 2 players, including LAN/self-host, and must survive NAT failure.

## Decision

Use Godot `WebRTCMultiplayerPeer` with STUN; **TURN is always available** (self-hosted). The host is authoritative (anti-cheat); clients send inputs only.

## Consequences

- Mesh >2 players and dedicated servers are deferred.

## Alternatives considered

- **Dedicated servers:** deferred. **ENet only:** rejected (Web).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
