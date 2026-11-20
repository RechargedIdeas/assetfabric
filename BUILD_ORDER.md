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
| **F2** | 11–14 | Codegen (chars/abilities/stats), G1-Audio | First combat: party of 4 + pets + enemies | ✅ |
| **F3** | 15–20 | GIRT, CascadeHub, micro LM, callouts | Party AI, swap, dialogue, callouts | ✅ |
| **F4** | 21–25 | Sandbox/micro-VM, hot reload, snapshots, statecharts | Live tune without full rebuild | ✅ |
| **F5** | 26–29 | Monte Carlo balance, soft-lock, save migration | First boss | ✅ |
| **F6** | 30–33 | Quest SM, farming, loot, adaptive music | **Vertical slice 15–20 min** | ✅ |
| **F7** | 34–38 | Desktop/Android/Web PWA packaging, ShuttleLine multi, BoltPack | Tier1+Tier2 launches | ✅ |
| **F8** | optional | Retro/console-style | Confirm scope first | |
| **F9** | post | LiveOps foundation | Readiness only | |

### Progress

Live status per milestone: [STATUS.md](STATUS.md) (generated). Acceptance checklists: `docs/acceptance-tests/F*.md`.

- **F0** ✅ accepted 2026-11-05.
- **F1** ✅ accepted 2026-11-05 — procedural G1-Sprite / G1-Tile / DyeWorks, gates, Godot binding, PatternVault, SwatchStudio CLI; sandbox encounter playable and headless-proven.
- **F2** ✅ accepted 2026-11-05 — codegen (roster → game data + ability `.tres`), derived sprites, G1-Audio stems; first combat with party of 4 + pets.
- **F3** ✅ accepted 2026-11-05 — GIRT (CPU/GDScript backends), CascadeHub, policy + callout cache + persona LM stand-in; party AI (BT + policy), time-freeze swap with forward-sim ranking, intents, dialogue. Swap < 50 ms target tracked as soft (measured ≈ 50–100 ms).
- **F4** ✅ accepted 2026-11-12 — Substrate sandbox (bwrap / process tiers; Firecracker + gVisor detected, no launcher — no usable KVM), live channel with atomic hot reload (ticket → stage/validate → 2PC → probe → rollback), Tier-2 snapshots + WAL replay, parallel statecharts with soft-lock analysis, Guardian (crash/hang → backoff restart → resume + poison-ticket quarantine). Game: `live-tune`. See [docs/SUBSTRATE.md](docs/SUBSTRATE.md).
- **F5** ✅ accepted 2026-11-12 — Monte Carlo balance runner (headless Godot workers, CRN seeds, Wilson CIs; G-BAL-01 2400 fights, choice deviation 3.0 pp, mean 0.73), Optuna TPE tuning on CPU, soft-lock detection (static statecharts + encounter reachability + runtime stall detector with probe), versioned Player State save v1→v2→v3 with GDScript↔Python parity and `.bak` recovery. Game: `first-boss` (tier-3 Cave Warden). Per-combination spread 12.7 pp is open balance debt. See [docs/acceptance-tests/F5.md](docs/acceptance-tests/F5.md).
- **F6** ✅ accepted 2026-11-12 — Codegen-World (economy, crops, recipes, tiered loot tables, quest statechart compiled from `content/world/quests.yaml`, adaptive-music rules, area graph) with schema / cross-ref / quest soft-lock / economy-solvability / loot / music gates; G1-Tile open-world features (farm plots, workbench, gather nodes) for field + tunnels + deep cave; Player State save v4 (farm, checkpoint, counters, buffs, gear). Game: `vertical-slice` (GAME_SPEC §6.1, all 8 items) played headless by a scripted QA autopilot for all 12 leader × pet selections; save/quit/reload in a new process is byte-identical to an uninterrupted run. Step 0: pet↔character affinity brought the per-pair spread to 3.2 pp (gated). Bot length ≈ 3 game-min vs the 15–20 min human target — needs a GUI playtest. See [docs/acceptance-tests/F6.md](docs/acceptance-tests/F6.md).
- **F7** ✅ accepted 2026-11-12 — `forge build --target` (Linux, Windows, debug APK, Web PWA) with hermetic Godot home + pinned 4.3 templates, PWAPipeline (G-WEB-01: 9.3 MB gzip of 45 MB, offline SW, COOP/COEP), ShuttleLine `shuttleline.contract/1` verified against every shipped PCK/APK + `generic-folder` adapter, BoltPack CycloneDX SBOM + license audit (unsigned). Game: `launch-candidates` — G-SAVE-01 ring desktop → Android → Web → desktop, G-NET-01 offline solo, G-A11Y-01 partial. Unsigned/debug only; Windows and Android verified without a Windows host or device. See [docs/acceptance-tests/F7.md](docs/acceptance-tests/F7.md).

### Entry criteria for any F(n+1)

1. `forge accept F(n)` passes and `docs/acceptance-tests/results/F(n).json` is committed.
2. `pytest` green, `forge status` exit 0 (offset guard ok).
3. HANDOVER/TODO/CHANGELOG/STATUS updated.
4. Milestone bump commit: `forge.yaml` (`fabric.milestone`, `game.increment`) + `forge.__milestone__`.

---

## Companion / Cluster (parallel)

C1–C6 acceptance: `forge accept C1-C6` → `docs/acceptance-tests/results/C*.json`, checklist [docs/acceptance-tests/C1-C6.md](docs/acceptance-tests/C1-C6.md).

| ID | Focus | State |
|---|---|---|
| C1 | PocketLoom / FabricCore | ✅ accepted 2026-11-12 — Kotlin core + debug APK |
| C2 | On-device generation | ✅ accepted — LocalForge CPU (ONNX rung stub) |
| C3 | Standalone UI | ✅ accepted — 5 tabs, string resources, lint clean (no device run yet) |
| C4 | Local capture | ✅ accepted — camera intent / import → store + queued recon offload |
| C5 | Pairing (QR/codes/Tailscale) | ✅ accepted — LoomLink HMAC pairing, `forge link serve` |
| C6 | Offload + sync | ✅ accepted — OffloadQueue drain, version-vector sync (keep both) |
| C7 | LoomCluster | ✅ accepted 2026-11-19 — equal nodes (HTTP/JSON, loopback-proven), negotiation, work stealing, leases/retry, journal recovery, device placement, LoomLink bridge; `forge accept C7` |
| C8 | GroundWeave | ✅ accepted 2026-11-19 — ladder for every generator + runtime/GIRT/balance probes; CPU path byte-identical on 2 pinned cores, GPUs hidden; pipeline refuses undeclared generators; `forge accept C8` |
| C9 | MirrorWeave | ✅ accepted 2026-11-19 (interfaces + stubs) — signed stills/telemetry stream + allow-listed read-only control are real; screen capture, video, input injection are labelled stubs; `forge accept C9` |
| C10 | LensForge | ✅ accepted (interfaces + stubs) — capture modes/profiles, integer-exact quality, telemetry, set assessment real; since 0.7.5–0.7.6 video ingest + ARCore pose coverage real, phone Camera2 video/focus + ARCore capture `real_unverified_on_device` |
| C11 | Metric depth | ✅ accepted (interfaces + stubs) — pinhole distance + inverse-depth alignment real; since 0.7.5–0.7.6 DepthAnything V2 Small (CPU) real, ARCore DEPTH16 ingest real / phone capture `real_unverified_on_device` |
| C12 | SplatForge path | ✅ accepted (interfaces + stubs) — RealityLoom routing/bundle/plan, placement check, `.ply` validator real; since 0.7.7 CPU photogrammetry (OpenCV SfM), MeshWeaver and GDGS Godot import real; SplatForge training stays a stub (GPU) |
| F8 | Retro/console-style | optional per SPEC §13 — confirm scope first |
| F9 | Post | LiveOps readiness only |

---

## Cross-cutting (continuous later)

Governance pipeline: LLM safety gate, compliance hooks, SBOM, drift, milestone/scope guards.
