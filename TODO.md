# TODO.md — Actionable Tasks

Last updated: 2026-11-12 America/New_York

## Current sprint — companion track (next: C9–C12 interfaces + stubs)

- [x] PocketLoom C1–C6: standalone offline debug APK (FabricCore JobExecutor + local store, on-device generation, UI, capture, pairing, offload/sync) — accepted 2026-11-12 (`forge accept C1-C6`)
- [x] LoomCluster C7 + GroundWeave C8 (drafts from `wip/f5-companions` reviewed, hardened, verified) — accepted 2026-11-19 (`forge accept C7-C8`, 0.7.2+f7)
- [ ] C7 follow-ups: LAN/Tailscale run across two real machines; cluster auth (reuse LoomLink HMAC) before binding off loopback; PocketLoom (Kotlin) as a cluster *peer* node; blob transfer for large artifacts; origin election/hand-off when the origin never returns
- [ ] C8 follow-ups: first real GPU rung (ROCm/DirectML/Vulkan ONNX for G1-Sprite/Tile) wired through `groundweave.execute`; re-time the full 2400-fight balance on a 2-core node
- [ ] C9–C12 (MirrorWeave, LensForge, depth, SplatForge): interfaces + clearly labelled stubs
- [ ] **Human GUI playtest of the vertical slice** (F6 carry-over): measure real length vs 15–20 min; HUD/quest/overlay readability; controls (E interact, H salve, Tab freeze, `/` command); music mix and fades; art legibility of plots/bench/nodes. Checklist: docs/acceptance-tests/F6.md §Human playtest
- [ ] Slice length: if humans also finish well under 15 min, add content (more field/tunnel areas, a second crop cycle, side quests) rather than slowing the bot

## PocketLoom follow-ups (C1–C6)

- [ ] On-device run (Redmi Note 12 Pro 5G, D-002): install the debug APK; Generate/Library/Capture/Link/Telemetry by hand; QR → intent → pair; drain + sync with `forge link serve`; record on-device generation timings
- [ ] ONNX rung for LocalForge (onnxruntime-android + small sprite/tile models, NNAPI → CPU) behind the existing ladder + ModelCache
- [ ] LoomLink security: PAKE (SPAKE2) or TLS with pinned desktop fingerprint; persist desktop `last_ts` across restarts; Android Keystore-wrapped session key
- [ ] Sync deletions (tombstones) and a conflict-resolution UI (today: keep both, shown as "sync conflict copy")
- [ ] In-app QR scanner (today: system camera app opens `loomlink://`); `forge link serve` QR needs the optional `qrcode` package
- [ ] Translations (strings are resources; only `values/` English exists); fix lint `DataExtractionRules` warning (legacy `allowBackup` for API 26–30)
- [ ] Kotlin Multiplatform targets for FabricCore (desktop-native / iOS) if needed (INFERENCE C-1)
- [ ] Release signing + AAB + Play listing (Producer keys)

## Packaging follow-ups (F7)

- [ ] Run `GameZero.console.exe --headless -- --net-report` + the slice on a real Windows host (or add wine to the build box) — Windows is statically verified only (INFERENCE F7-18)
- [ ] On-device Android run on the Redmi Note 12 Pro 5G (D-002): install the debug APK, play the slice, G-SAVE-01 hop on hardware
- [ ] Real-browser Web test on a public HTTPS host (Chrome, Firefox, Safari) with COOP/COEP; decide `nothreads` fallback (D-001)
- [ ] **Signing**: Windows Authenticode (+ rcedit icon/version), Linux AppImage/Flatpak signature, Android release keystore (env only, never committed) + AAB, BoltPack detached signature over `bolt.json`
- [ ] **Store listings** (Producer): itch.io / own web host, Google Play (copy, screenshots, content rating, privacy), Steam later
- [ ] G-A11Y-01 full: in-game input rebinding UI + runtime colour-blind palette toggle
- [ ] Cached CI `package` job (templates + SDK cache) running `forge accept F7` full on `main` (INFERENCE F7-16)
- [ ] Reproducible exports (pin GDScript tokenisation / compare by content) if byte-identical rebuilds are required

## Balance (F6)

- [x] Per-pair (leader × pet) spread < 5 pp: pet↔character affinity → 3.21 pp on the gate seeds, now gated (INFERENCE F6-1/F6-2)
- [ ] Per-pair spread on *unseen* seeds is 5.25 pp ≈ noise floor at 200 seeds/cell; an out-of-sample per-cell gate needs ~800 seeds/cell (faster worker first)
- [ ] Longer Optuna study (≥ 100 seeds/matchup per trial) once the runner is faster; consider Ax/surrogate
- [ ] Faster balance worker (native step function would also fix swap advisor)
- [ ] Balance the slice's world fights (tunnels/cave packs, buffs, levels) with the Monte Carlo runner — currently tuned by hand; 0 wipes over the 12-selection matrix

## Perf debt

- [ ] Swap advisor < 50 ms (now ≈ 50–100 ms; F4 re-measured 66–104 ms): native step function (GDExtension) or reduced candidate set; keep serial/threaded parity test
## Done

- [x] F0 Foundation (accepted 2026-11-05)
- [x] F1 Content Pipeline (accepted 2026-11-05): G1-Sprite, G1-Tile, DyeWorks procedural; gates; PatternVault; SwatchStudio CLI; Godot binding; sandbox encounter
- [x] F2 Codegen + G1-Audio (accepted 2026-11-05): roster → game data + .tres; derived sprites; chiptune stems; first combat party of 4 + pets
- [x] F3 GIRT + CascadeHub + callouts (accepted 2026-11-05): policy BC, callout cache, persona LM stand-in, BT party AI, time-freeze swap, intents, dialogue
- [x] F4 Substrate (accepted 2026-11-12): bwrap/process sandbox, live channel (2PC + probe + rollback), snapshots + WAL, parallel statecharts, guardian
- [x] F5 Balance (accepted 2026-11-12): Monte Carlo runner (G-BAL-01 pass), Optuna TPE tuning, soft-lock detection, save v3 + migrations; first tier-3 boss
- [x] F7 Packaging (accepted 2026-11-12): `forge build --target` Linux / Windows / debug APK / Web PWA, PWAPipeline (G-WEB-01), ShuttleLine contract + generic-folder adapter, BoltPack SBOM + license audit; G-SAVE-01 ring, G-NET-01 offline; G-A11Y-01 partial; unsigned
- [x] F6 Vertical slice (accepted 2026-11-12): quest statechart, farming/gather/craft economy, tiered loot, adaptive music, field ⇄ tunnels ⇄ cave ⇄ lair, save v4 + quit/reload parity, QA autopilot, 12-selection matrix; per-pair balance gate
- [x] PocketLoom C1–C6 (accepted 2026-11-12): FabricCore, LocalForge, standalone UI, capture, LoomLink pairing, offload + sync; debug APK; CI `pocketloom` job
- [x] Private repo + proprietary license (D-003, D-004)

## Backlog (later milestones)

- Firecracker / gVisor launchers (need usable KVM + guest image)
- Hot reload of GDScript code, tilemaps, audio; remote (WS/gRPC) live transport for Studio
- Session host migration (failover tier 3); Crash Predictor model
- Studio PySide6 shell; SwatchStudio GUI
- ONNX G1-Sprite Tiny, NCA G1-Tile, diffusion DyeWorks backends

## Companion / cluster (parallel)

- [x] C1–C6 PocketLoom (accepted 2026-11-12) — see docs/acceptance-tests/C1-C6.md
- [x] C7 LoomCluster scheduler + C8 GroundWeave fallback ladder (0.7.2+f7)

## Blockers

| ID | Description | Owner | Status |
|---|---|---|---|
| — | none | — | — |

## Bugs

| ID | Description | Severity | Notes |
|---|---|---|---|
| — | none filed | — | — |

## Decisions needed

| ID | Question | Owner | By |
|---|---|---|---|
| D-001 | Web export single-threaded fallback strategy? (F7 ships threads + COOP/COEP + SW shim; `nothreads` templates fetched, not built — INFERENCE F7-3) | Factory Lead | before public Web hosting |
| D-002 | Confirm Android reference = Redmi Note 12 Pro 5G (F7 APK is arm64-v8a only, untested on hardware) | Producer | before on-device test |
| D-005 | Final names/stats of 4 fighters + 3 starter pets (GAME_SPEC §10); F6 economy/loot/quest content | Game Design | before content lock |

## Infrastructure

- [x] CI on GitHub Actions with Godot 4.3 headless
- [ ] Windows runner (DirectML) — later
- [ ] Model artifact storage backend beyond local `store/`
