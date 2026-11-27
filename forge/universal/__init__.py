# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Universal 2D / 2.5D / 3D graphics + parametric engine layer (Milestone U1).

Modules (docs/architecture/universal-engine.md is the normative description):

* `ir`         — Universal Scene & Asset IR (2D sprites/atlases + normal/depth/emission maps, 2.5D layered scenes,
                 3D meshes, PBR materials, skins, point clouds, 3D Gaussian splats); canonical JSON + digest.
* `coords`     — coordinate conventions (handedness, up axis, units) and exact basis changes between them.
* `mesh`       — triangle-mesh utilities: primitives, STL/OBJ/OFF I/O, manifold/watertight/volume checks.
* `csg`        — pure-Python (NumPy) parametric CSG: SDF evaluation + marching tetrahedra (OpenSCAD fallback).
* `openscad`   — parameter schemas, deterministic `.scad` emission, OpenSCAD CLI compile, validation, GLB.
* `gltf`       — glTF 2.0 / GLB writer + structural validator (no third-party deps).
* `png`        — NumPy PNG encode/decode (8-bit gray/RGB/RGBA).
* `maps2d`     — height → tangent-space normal / depth / AO maps, lighting profiles, photometric normal recovery.
* `exporters/` — engine/tool adapters (Unreal, Unity, Blender, RPG Maker, Sprite Lamp, …) behind one contract.
* `registry`   — the Engine & Tool Adapter Catalog (`content/universal/engines_catalog.yaml`).
* `evolution`  — benchmark-gated self-improvement of generator recipes (promotion only on strict improvement).
* `plugins`    — self-expansion SDK: gap detector, plugin scaffold, contract + security gate, versioned hot-loader.
"""

from __future__ import annotations

IR_VERSION = "1.0.0"
ADAPTER_API_VERSION = "1.0"
TIERS = ("native_verified", "cli_bridge", "interchange_pack", "descriptor_only")
