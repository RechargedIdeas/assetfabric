"""ForgeConsole — F8 retro / console-style path (ASSETFABRIC_SPEC §3 Layer A/D, §5.1 C1/R2, §6.1; GAME_SPEC §4.6).

Modules:
  profiles   Console Profile Registry (content/retro/profiles.yaml) + computed palettes
  colour     sRGB ↔ CIELAB, ΔE, palette LUTs (R1 Retro Render Compiler data)
  transcode  AssetTranscoder + C1 console constraint solver (sub-palettes, tile dedupe, CHR)
  asm6502    tiny two-pass 6502 assembler with a cycle table (CodeGen + C1 cycle predictor)
  rom        ROMBuilder: Fabric content → iNES NROM ROM
  emulator   EmulatorHarness: headless real-emulator boot/input/frame proofs (cynes)
  readiness  ConsoleReadiness: memory / tile / sprite / palette / cycle budgets
  validate   V1 Retro Validation Harness + Q1 pixel-stability (shimmer predictor) + R2 authenticity discriminator
"""
