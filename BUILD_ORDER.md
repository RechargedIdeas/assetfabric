# BUILD_ORDER.md — Authoritative sequence

Source: `docs/design/ASSETFABRIC_SPEC.md` §13 + design chat. Weeks are indicative.

## Parallel contract

**Fabric is always one milestone ahead of the game.**  
Fabric **must not** start implementing F(n+1) deliverables until F(n)’s **game increment** ships and passes acceptance.

Companion track **C\*** runs in parallel and is **not** a Fabric F-gate unless noted.

---

## Fabric + Game Zero

| ID | Weeks (indicative) | Fabric delivers | Game proves | Gate |
|---|---|---|---|---|
| **F0** | 1–4 | Manifest, `forge` CLI, asset store, orchestrator, telemetry schema | Empty Godot boots; `forge status` healthy | ✅ |
| **F1** | 5–10 | Sprite/tile/DyeWorks procedural, gates, Godot presets, PatternVault, SwatchStudio | Playable sandbox: 1 char, 1 tilemap, 1 enemy, 1 attack | ✅ |
| **F2** | 11–14 | Codegen (chars/abilities/stats), G1-Audio | First combat: party of 4 + pets + enemies | |
| **F3** | 15–20 | GIRT, CascadeHub, micro LM, callouts | Party AI, swap, dialogue, callouts | |
| **F4** | 21–25 | Sandbox/micro-VM, hot reload, snapshots, statecharts | Live tune without full rebuild | |
| **F5** | 26–29 | Monte Carlo balance, soft-lock, save migration | First boss | |
| **F6** | 30–33 | Quest SM, farming, loot, adaptive music | **Vertical slice 15–20 min** | |
| **F7** | 34–38 | Desktop/Android/Web PWA packaging, ShuttleLine multi, BoltPack | Tier1+Tier2 launches | |
| **F8** | optional | Retro/console-style | Confirm scope first | |
| **F9** | post | LiveOps foundation | Readiness only | |

### Progress

Live status per milestone: [STATUS.md](STATUS.md) (generated). Acceptance checklists: `docs/acceptance-tests/F*.md`.

- **F0** ✅ accepted 2026-11-05.
- **F1** ✅ accepted 2026-11-05 — procedural G1-Sprite / G1-Tile / DyeWorks, gates, Godot binding, PatternVault, SwatchStudio CLI; sandbox encounter playable and headless-proven.
- **F2** ✅ accepted 2026-11-05 — codegen (roster → game data + ability `.tres`), derived sprites, G1-Audio stems; first combat with party of 4 + pets.
- **F3** ✅ accepted 2026-11-05 — GIRT (CPU/GDScript backends), CascadeHub, policy + callout cache + persona LM stand-in; party AI (BT + policy), time-freeze swap with forward-sim ranking, intents, dialogue. Swap < 50 ms target tracked as soft (measured ≈ 50–80 ms).

### Entry criteria for any F(n+1)

1. `forge accept F(n)` passes and `docs/acceptance-tests/results/F(n).json` is committed.
2. `pytest` green, `forge status` exit 0 (offset guard ok).
3. HANDOVER/TODO/CHANGELOG/STATUS updated.
4. Milestone bump commit: `forge.yaml` (`fabric.milestone`, `game.increment`) + `forge.__milestone__`.

---

## Companion / Cluster (parallel)

| ID | Focus | F0 depth |
|---|---|---|
| C1 | PocketLoom / FabricCore | placeholder README |
| C2 | On-device generation | deferred |
| C3 | Standalone UI | deferred |
| C4 | Local capture | deferred |
| C5 | Pairing (QR/codes/Tailscale) | deferred |
| C6 | Offload + sync | deferred |
| C7 | LoomCluster | fleet in `forge.yaml` only |
| C8 | GroundWeave | principle documented; ladder later |
| C9 | MirrorWeave | deferred |
| C10–C12 | LensForge / depth / SplatForge path | deferred |

---

## Cross-cutting (continuous later)

Governance pipeline: LLM safety gate, compliance hooks, SBOM, drift, milestone/scope guards.
