# ADR-0015 — Studio: Python + PySide6, outside Godot

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Authoring, training and telemetry UIs need the Python ML ecosystem and must not bloat the game.

## Decision

Desktop **Studio** is Python + PySide6, talking to Godot via WebSocket/TCP or shared SQLite/DuckDB. It hosts the embedded slash-command terminal, MCP host and ACP agent.

## Consequences

- PySide6 is an optional extra (`.[studio]`); F0 does not require it.

## Alternatives considered

- **Godot editor plugin as Studio:** rejected (ML ecosystem, coupling).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
