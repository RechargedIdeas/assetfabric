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
| **F0** | 1–4 | Manifest, `forge` CLI, asset store, orchestrator, telemetry schema | Empty Godot boots; `forge status` healthy | CLI + schema + env |
| **F1** | 5–10 | Sprite/tile/DyeWorks procedural, gates, Godot presets, PatternVault, SwatchStudio | Playable sandbox: 1 char, 1 tilemap, 1 enemy, 1 attack | **Blocked until F0 green** |
| **F2** | 11–14 | Codegen (chars/abilities/stats), G1-Audio | First combat: party of 4 + pets + enemies | |
| **F3** | 15–20 | GIRT, CascadeHub, micro LM, callouts | Party AI, swap, dialogue, callouts | |
| **F4** | 21–25 | Sandbox/micro-VM, hot reload, snapshots, statecharts | Live tune without full rebuild | |
| **F5** | 26–29 | Monte Carlo balance, soft-lock, save migration | First boss | |
| **F6** | 30–33 | Quest SM, farming, loot, adaptive music | **Vertical slice 15–20 min** | |
| **F7** | 34–38 | Desktop/Android/Web PWA packaging, ShuttleLine multi, BoltPack | Tier1+Tier2 launches | |
| **F8** | optional | Retro/console-style | Confirm scope first | |
| **F9** | post | LiveOps foundation | Readiness only | |

### F0 detail (this session)

- [x] Doc suite  
- [x] `forge.yaml` + JSON Schema  
- [x] Telemetry event schema v1  
- [x] `forge status` / `forge doctor` / validate / store / job stubs  
- [x] Asset store scaffolding  
- [x] Job orchestrator stub  
- [x] Empty Godot 4 Compatibility project  
- [x] Tests green  
- [x] Godot 4.3 headless smoke (structure smoke always in CI)

### F1 entry criteria (do not start early)

1. `forge status` exits 0 on acceptance hardware class (≥2 cores, no GPU required for F0 tools).  
2. `pytest` green.  
3. Godot project structure smoke green (`scripts/smoke_godot.sh`).  
4. `HANDOVER.md` records F0 acceptance.  
5. Milestone bump PR: `fabric.milestone: F1` only after game increment advances past `env-boots` **or** Producer explicitly opens F1 Fabric prep with Game still proving F0 — still **no generator implementation** until env gate signed off.

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
