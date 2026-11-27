# ADR-0021 — Retro is a presentation-only profile pass in Godot, plus a real-ROM path built from Fabric content

| Field | Value |
|---|---|
| Status | **accepted** (F8, `0.8.0+f8`) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (Producer direction t59u "then do F8 and F9", C-85); agent implementation |

## Context

SPEC §13 F8 is optional, "Retro/console-style", and §6.1 ForgeConsole names three paths: real ROMs in emulators,
console-style Godot authenticity profiles/shaders, fantasy consoles. The game must stay deterministic, a11y-complete
(G-A11Y-01) and shippable on Desktop/Android/Web (F7), and the combat tick must never depend on presentation (ADR-0011).

## Decision

1. **Path 2 is the product.** A Console Profile Registry (`content/retro/profiles.yaml`) defines profiles; the game
   applies one as a single full-screen CanvasLayer pass (layer 1, between the world and the HUD on layer 2):
   one sample per logical-pixel centre (`textureLod` 0, integer scale), the a11y palette remap first, then a forge-built
   64³ LUT (512×512 PNG) onto the console palette, optional scanlines. Q1: camera zoom = profile scale, camera on
   whole pixels, non-integer sprite scales snapped, integer window stretch. Default `off`; a player setting saved in
   the profile. The sim never reads it (state hash identical in every profile).
2. **Path 1 is proof, not product.** ForgeConsole builds a real iNES NROM ROM from the same Fabric sprites/tiles
   (C1 sub-palette solver, AssetTranscoder, own 6502 assembler with a cycle predictor) and boots it in cynes (MIT,
   dev-only, never shipped). Scope: field demo [INFERENCE F8-6].
3. **Path 3 and CertPack are deferred** (SPEC §1 v1 hard deferrals).
4. Colour fidelity, a11y signal separation, block uniformity and an R2 discriminator are gated in `forge accept F8`.

## Consequences

- One shader + one LUT per profile: no per-asset retro variants, so new art is retro-ready automatically (gated by
  ConsoleReadiness).
- The HUD is not pixel-quantised (readability first) [F8-10].
- Adding a console family = a registry entry + palette source; a ROM path for another family needs its own
  ROMBuilder/assembler.
