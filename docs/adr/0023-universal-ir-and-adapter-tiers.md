# ADR-0023 — One scene IR + tiered adapters; a tier is a claim we can prove

| Field | Value |
|---|---|
| Status | **accepted** (U1) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (user request t65u: universal 2D/2.5D/3D engine); agent implementation |

## Context

t65u names about 20 engines and tools, every engine on Wikipedia's *List of game engines* (178 rows), and
photogrammetry and Gaussian-splat tools. Most of them are closed-source, Windows-only, or have no headless mode, so
AssetFabric cannot run them on Linux CI. Claiming "integration" without running the tool would break the project's
zero-fake-claims rule.

## Decision

1. **One IR** (`forge.universal.ir`, v1.0.0) covers 2D (sprites/atlases), 2.5D (parallax/isometric layers and cards)
   and 3D (meshes, skins, PBR materials, cameras, point clouds, 3DGS splats).
   * Every scene carries a coordinate convention.
   * `coords.py` converts between 10 named conventions using semantic axes (right/up/forward with handedness).
   * Conversions round-trip to below 1e-9.
2. **Adapters** implement `export/verify` (and `import_/sample_input` where they import). Every pack is deterministic
   and carries `assetfabric_manifest.json` (file SHA-256, adapter id/tier/API version, convention, source IR digest).
3. **Every adapter, and every catalog entry, has exactly one tier:**
   * `native_verified`: the tool's own binary loads our output headlessly (Godot 4.3, Blender 4.3).
   * `cli_bridge`: we drive the tool's real CLI (OpenSCAD).
   * `interchange_pack`: we write the tool's documented import formats and re-validate them with our own readers.
     The tool itself is not run.
   * `descriptor_only`: the import path is unconfirmed. We provide a catalog record plus a generic glTF/OBJ/atlas pack.
4. **Formats without a verified writer are not emitted.** FBX is the main example. They are reported as gaps instead.
5. **Facts that are extrapolated rather than documented** are flagged `inference: true` / `[INFERENCE U1-n]`
   (docs/INFERENCES.md §U1).

## Consequences

* Users can see exactly which integrations are proven, and how.
* Promoting a tool to `native_verified` means adding a headless check (`native_check`) and a CI/box run. It is never
  done by editing YAML.
* glTF is the hub format. Engines without a curated convention get glTF axes and rely on their importer
  ([INFERENCE U1-1]).
