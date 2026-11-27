<!-- AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE. -->
# Universal 2D / 2.5D / 3D engine (Milestone U1)

User request **t65u** asks for AssetFabric to act as an adaptive, self-improving, production-grade universal graphics
engine. It should do parametric generation with OpenSCAD, integrate with Unreal, Unity, Blender, RPG Maker, Sprite Lamp,
Sprite Pro, GameGuru, Clickteam Fusion, Construct 2, CopperCube 6, Esenthel, ePic Character Generator, AGFPRO 3,
AppGameKit, RaySupreme 3D, Fuse, Flipside Studio, Creative Engine and every engine on Wikipedia's *List of game
engines*, and handle photogrammetry and Gaussian splats. It should also grow new capabilities over time.

U1 delivers the substrate for that. It is honest about what each integration proves.

* **The integrations**:
  * one scene IR;
  * a tiered adapter SDK with 23 built-in adapters;
  * a Wikipedia-derived engines catalog;
  * parametric templates that compile through the **real OpenSCAD CLI** and also through an own NumPy CSG fallback.
* **Self-improvement**: a benchmark-gated loop with rollback.
* **Growing new capabilities**:
  * a sandboxed plugin system;
  * a live gap report that tells you what to build next.

Proof: `forge accept U1` → `docs/acceptance-tests/U1.md`, `results/U1.json`.

```
             ┌──────────── content/universal/parametric/*.yaml  (templates: params, ranges, tri budget, CSG tree)
             │                     │ bind + whitelist-checked expressions
             │          ┌──────────┴───────────┐
             │   emit_scad → OpenSCAD CLI    csg.py SDF + marching tetrahedra (CPU, deterministic)
             │   (cli_bridge, real binary)   (GroundWeave gen.parametric CPU rung)
             │          └──────────┬───────────┘  cross-check volumes (tol 4 %)
             ▼                     ▼
reference scenes ──► forge.universal.ir.Scene  (meshes, skins, materials, textures, sprites, 2.5D layers,
 (2d / 2.5d / 3d)         point clouds, Gaussian splats, cameras, node tree; convention-tagged; JSON + digest)
                               │ coords.convert (glTF RH Y-up m ↔ Unity LH ↔ Unreal LH Z-up cm ↔ Blender RH Z-up …)
                               ▼
          exporters.REGISTRY  (built-ins + sandboxed plugin proxies)  ──►  Pack (deterministic files + manifest SHA-256)
             │ native_verified: Godot GLTFDocument, Blender bridge (headless)      │ verify(): own readers re-check
             │ cli_bridge:      OpenSCAD render of the exported assembly            ▼
             │ interchange_pack / descriptor_only: documented import formats   engine/tool imports the pack
             ▼
     registry (engines_catalog.yaml: 178 Wikipedia rows + 28 curated tools) → adapter_for(engine id)
```

## Modules (`forge/universal/`)

| Module | Role |
|---|---|
| `ir.py` | Scene IR v1.0.0, which covers `Texture`, `Material` (PBR), `Skeleton`, `MeshAsset` (+ joints/weights), `Sprite` (atlas frames, pivot, fps), `Layer25D` (parallax/isometric), `PointCloud`, `SplatSet` (3DGS), `Camera` and `Node`. It provides deterministic JSON (`digest()`), `converted(dst)` and `validate()`. A major-version mismatch is refused. |
| `coords.py` | 10 named conventions (gltf, godot, unity, unreal, blender, opengl-yup, directx-yup, zup-rh, source, zup-rh-yfwd). Change-of-basis is built from semantic axes. It also handles winding flips, UV origin, and normal-map green-channel conversion. |
| `mesh.py`, `png.py` | TriMesh plus manifold/watertight/orientation validation. STL/OBJ/OFF I/O and a NumPy PNG codec. No third-party mesh libraries. |
| `csg.py` | Whitelisted expression language and a CSG tree evaluated as an SDF. Marching tetrahedra run with optional Newton projection, and the triangle order is sorted so output is deterministic. |
| `openscad.py` | Template load/bind and deterministic `.scad` emission. Calls the OpenSCAD CLI (`--export-format binstl`) and falls back to `csg-sdf-cpu`. `build()` writes `.scad/.stl/.obj/.off/.glb` + `report.json` with a cross-check and format round-trips. |
| `gltf.py` | Own glTF 2.0/GLB writer and reader. It covers materials, textures, skins, sprite cards, point clouds (POINTS) and cameras. Splats go in `extras`. |
| `maps2d.py` | Silhouette → height → normal/depth/AO maps plus Sprite Lamp lighting profiles. The production normal path is `normals_for_silhouette`, which uses the active self-improvement recipe. |
| `exporters/` | Adapter SDK (`base.py`) plus 23 adapters: 3D (`three_d.py`), 2D/2.5D (`two_d.py`), capture/photogrammetry/3DGS (`capture.py`) and catalog-generic (`generic.py`). See the tier table below. |
| `native/` | Headless runs of real tools: Godot (`--headless`, temp project, `GLTFDocument`) and Blender (`--background` bridge script). |
| `registry.py`, `catalog_build.py` | Builds the catalog from Wikipedia wikitext (pinned revision) plus `named_tools.yaml`, then handles search/resolve and integrity. |
| `engine.py` | Facade: `adapter_for(target)`, `load_scene(ref:… / parametric:… / IR JSON)`, `export`, `demo`. |
| `evolution.py` | Benchmark suites, gating, promotion, rollback and telemetry (ADR-0025). |
| `plugins.py`, `plugin_worker.py` | Plugin manifest, static policy, sandboxed contract suite, register/rollback/hot-load, scaffold and gap report (ADR-0026). |

## Adapter tiers (what each integration proves; ADR-0023)

| Tier | Meaning | Built-ins |
|---|---|---|
| `native_verified` | The tool's own binary loads our output headlessly in `forge accept U1` when installed. Skipped and recorded otherwise. | `godot` (Godot 4.3 `GLTFDocument`: meshes/skins/materials/images counted), `blender` (bridge script in Blender 4.3: objects, materials, armature, custom-property tags) |
| `cli_bridge` | We drive the tool's real CLI. | `openscad` (exported `assembly.scad` rendered by OpenSCAD 2021.01; templates compiled by it) |
| `interchange_pack` | We write the tool's **documented** import formats plus a manifest, and re-validate them with our own readers. The (closed-source / non-Linux) tool itself is **not** run. | `gltf`, `unreal` (GLB + Paper2D TexturePacker JSON + DirectX normals + editor-Python import script with an API allow-list), `unity` (UPM package, deterministic GUID `.meta`, `.unitypackage`), `rpgmaker` (MV/MZ 48 px and VX Ace 32 px sheet layouts), `spritelamp` (Sprite Lamp / Sprite Pro maps, also import), `construct`, `clickteam`, `appgamekit`, `atlas2d`, 5 mesh packs (GameGuru `.x`+`.fpe`, CopperCube `.x`, Esenthel, AGFPRO, RaySupreme), `colmap`, `splats` (3DGS PLY + nerfstudio transforms + COLMAP), `recon-import`, `fuse`, `epic-chargen`, `catalog-generic` |
| `descriptor_only` | Catalog record plus a generic pack. The engine's import formats are not confirmed. | catalog entries only |

FBX is **not** written: there is no verified writer, and the SDK is proprietary. `forge universal gaps` reports FBX and
USD as high-severity gaps.

## Catalog (`content/universal/engines_catalog.yaml`)

The catalog was generated from Wikipedia *List of game engines*, revision **1388112807** (2026-11-26 12:27 EST). Only
factual fields are kept (name, language, year, platforms, orientation, licence class). The Wikipedia text is CC BY-SA,
so no prose is copied; see THIRD_PARTY_NOTICES.

**Counts:**

| Figure | Count |
|---|---|
| Wikipedia rows | **178**, all unique |
| Curated named tools (`named_tools.yaml`) | **28**; 7 of them match a Wikipedia row and are merged into it |
| Catalog entries | **199** |
| By tier | native_verified 2 · cli_bridge 1 · interchange_pack 120 · descriptor_only 76 |

**How Wikipedia rows get their tier:**
* `interchange_pack`: a public toolchain plus modern import formats.
* `descriptor_only`: in-house/non-public, legacy, or no 2D/3D orientation listed.
* Coordinate conventions are curated for 30 engines. The others use glTF and let the engine's importer convert
  ([INFERENCE U1-1]).

Regenerate the catalog with `python -m forge.universal.catalog_build fetch` and then `forge universal catalog-build
/tmp/wiki_engines.txt`.

## Parametric generation (ADR-0024)

There are four templates: `crate`, `pillar`, `barrel` and `cog` (the cog is in mm, with `unit_m: 0.001`).
* Parameters have ranges and defaults.
* Expressions are AST-whitelisted: arithmetic, comparisons, and `min/max/abs/sqrt/floor/ceil/sin/cos/…`.
* Every template has a triangle budget.

**Backends:**

| Backend | Status |
|---|---|
| `openscad-cli` | The real OpenSCAD. Results are cross-checked against the fallback volume. |
| `csg-sdf-cpu` | Pure NumPy and always available. This is the GroundWeave rung for `gen.parametric`; a planned Vulkan compute rung sits above it. |

Box results with OpenSCAD 2021.01 (relative volume difference between OpenSCAD and the fallback):

| crate | pillar | barrel | cog |
|---|---|---|---|
| 0.23 % | 0.47 % | 0.32 % | 0.39 % |

All are manifold, watertight and within budget.

## Self-improvement (ADR-0025)

Recipe families are `parametric.csg` (cell fraction, Newton steps) and `maps2d.normal` (blur, relief, dome).

**How a run works:**
1. Each run proposes neighbours of the active recipe plus a pairwise combination.
2. Each candidate is benchmarked on **exactly the production code path** against ground truth:
   * `parametric.csg` uses OpenSCAD `$fn=128` volumes;
   * `maps2d.normal` uses analytic hemisphere/ellipsoid normals.
3. A candidate is promoted only if it is strictly better **and** passes every gate:
   * `parametric.csg`: manifold/watertight, within the triangle budget, volume error ≤ 5 %, suite time ≤ 60 s;
   * `maps2d.normal`: finite, unit length, mean error ≤ 45°.

**Where state lives:**
* Promotions are local (`.fabric/universal/evolution/state.json`, git-ignored), with telemetry in JSONL.
* `forge universal evolve-rollback` restores any version.
* Production (`openscad.default_recipe`, the Sprite Lamp exporter) always reads `evolution.active_recipe`, so an
  improvement is used immediately and a rollback is immediate too.

**Measured in `forge accept U1`:**
* **Normals:** 25.36° → 19.37° → 11.61° → 4.04° mean angular error.
* **CSG:** objective 0.01838 → 0.01697 (cell 1/51.2, 2 Newton steps).
* **Rejections:**
  * an injected regression was rejected ("no strict improvement");
  * an injected coarse recipe was rejected by the volume gate.

## Plugins and the gap report (ADR-0026)

**Gap report.** `forge universal gaps` compares `content/universal/capabilities.yaml` with live state:
* the formats advertised by built-ins and active plugins;
* descriptor-only and inference-flagged catalog entries;
* adapters without a native check;
* GroundWeave rungs that are still `planned`.

At U1 it lists 9 of 16 formats as covered. The gaps are fbx, usd, 3mf, dae, spz, vrm and x3d, plus features
(LOD chain, UV unwrap, retargeting), 76 descriptor-only engines and planned GPU rungs.

**Plugin lifecycle:**
1. `plugin-scaffold`: the skeleton fails until it is implemented.
2. `plugin-verify` runs three checks:
   * a manifest check;
   * a static AST policy: import allow-list, no `eval/exec/open/getattr/__import__`, no dunder access, no direct
     filesystem writes, no binary files;
   * a contract suite run **inside the forge sandbox** (bwrap: no network, read-only root; process tier: audit
     hooks). The reference scenes are exported twice and must be byte-identical, then verified, then the manifest is
     checked for honesty.
3. `plugin-register`: re-verifies, refuses non-increasing versions and built-in ids, and stores the tree hash.
4. `plugin-rollback`.
5. Hot-load: registered plugins become sandboxed **proxies** in the adapter registry, so plugin code never runs in the
   host process. A tampered install is refused.

Plugins are limited to `interchange_pack` / `descriptor_only`, because they cannot spawn tools.

The example `content/universal/plugins/x3d-export` closes the x3d gap. Three hostile fixtures
(`tests/fixtures/universal_plugins/`) are rejected:
* the network-exfiltration fixture, by the static policy;
* the hidden-state fixture, by the determinism gate;
* the sandbox-escape fixture, by the static policy **and**, with that gate bypassed, by both sandbox tiers.

## CLI

```
forge parametric list | scad <tpl> [--set k=v] | build <tpl> --out DIR [--backend auto|openscad-cli|csg-sdf-cpu]
forge universal catalog [--summary|--tier|--dims] | search <q> | adapters | native
forge universal export <adapter|engine|tool> --scene ref:3d|ref:2d|ref:2.5d|parametric:cog?teeth=16|ir.json --out DIR [--native]
forge universal verify <adapter> <pack> | demo --out DIR [--native]
forge universal gaps | evolve <family> [--rounds N] | evolve-history <family> | evolve-rollback <family> <version>
forge universal plugin-scaffold <id> --format F --dims 3d | plugin-verify DIR | plugin-register DIR | plugin-rollback ID | plugins
forge accept U1
```

## Rules kept

* **Zero fake claims.** Every integration has a tier, and nothing above `interchange_pack` is claimed without a real
  binary run.
* **AMD-first with a CPU fallback.** All U1 paths are CPU NumPy. GroundWeave carries `gen.parametric` (planned Vulkan
  rung) and `universal.export`. Both are verified pinned to 2 cores and byte-identical unpinned.
* **Deterministic outputs.** Packs, `.scad`, STL, GLB and catalog generation are all deterministic.
* **Locale keys.** Template titles and plugin/evolution messages are in `locales/en.json`.
* **Proprietary header** on new sources.
