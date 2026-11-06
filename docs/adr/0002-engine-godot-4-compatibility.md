# ADR-0002 — Engine: Godot 4 with the Compatibility renderer

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Game Zero targets desktop, Android (mid-range Mali GPUs) and a Web PWA. The fleet is AMD-only and the weakest acceptance node is 2 cores with no GPU. The chat evaluated Godot's structural gaps and chose to close them with Fabric tooling rather than switch engines or fork Godot.

## Decision

Use **Godot 4** (4.3 pinned for F0) with `renderer/rendering_method="gl_compatibility"` for 2D, mobile and Web. Forward+/Mobile renderers are not the project default. Pixel stability and retro looks are achieved by Fabric tooling (R1/Q1/V1), **not** an engine fork.

## Consequences

- WebGL 2.0 export path is available (see ADR-0008).
- Some modern rendering features are unavailable; 3D content must respect Compatibility limits.
- Engine gaps (Android IPC, inference, multi-agent bus) are owned by Fabric layers A–E.

## Alternatives considered

- **Unity / Unreal:** rejected in chat (licensing, Web/mobile weight, openness).
- **Forward+ default:** rejected — excludes Web and low-end Android.
- **Fork Godot for pixel stability:** rejected — maintenance burden.

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
