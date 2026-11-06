# ADR-0003 — Game language: GDScript + GDExtension (not C#)

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

GDScript is interpreted and can be slow on hot paths; C# in Godot 4 lacks Web export and adds a runtime on Android.

## Decision

Primary game language is **GDScript**. Hot paths move to coarse-grained **GDExtension** (Rust or C++) via NativeHotPath. C# is not used for game logic; C# hot-reload mentions in the chat are Substrate options only.

## Consequences

- Web export remains possible.
- Performance-critical code (sim, pathing) needs native builds per platform in CI.

## Alternatives considered

- **C# primary:** rejected (Web export, mobile size).
- **All-native:** rejected (iteration speed).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
