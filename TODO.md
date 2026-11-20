# TODO.md — Actionable Tasks

Last updated: 2026-11-20 America/New_York

## Current sprint — stub replacement (Producer t59u, 2026-11-20: "replace stubs with real code, fix quality gaps, then F8 and F9")

Rule for this sprint: a stub becomes `real` only when a CPU code path runs **here** (8 vCPU, no GPU/KVM/phone/Windows) on real
data with tests and `forge accept`. Android-only APIs get a real Kotlin implementation compiled into the APK (+ JVM unit tests of
the platform-free half) and the new honest register state **`real_unverified_on_device`** — never "device-proven". GPU-only rungs
stay `planned` with the reason written down. Every new dependency/model is licence-checked for proprietary commercial use and
recorded in BoltPack (`THIRD_PARTY_NOTICES.md`). Model weights are never committed (fetched with SHA-256 into `store/models/`).

### Inventory (2026-11-20, from `content/companions/c9_c12.yaml`, `content/groundweave/ladder.yaml`, HANDOVER, INFERENCES)

| # | Stub / planned item | Where | Plan | Batch |
|---|---|---|---|---|
| 1 ✅ 0.7.4 | `mirror.screen_capture` (Android MediaProjection) | C9 register, `ScreenCaptureSource` | desktop X11 capture via system ffmpeg `x11grab` (real, Xvfb-tested) + Kotlin MediaProjection service in the APK (`real_unverified_on_device`) | B1 |
| 2 ✅ 0.7.4 | `mirror.video_stream` (H.264/WebRTC) | C9 | CPU encode via **system** ffmpeg (VP8/VP9 libvpx BSD; H.264 only if the host's ffmpeg has it — never bundled), chunked + signed over a LoomLink-authenticated WebSocket; decode-back PSNR test | B1 |
| 3 ✅ 0.7.4 | `mirror.android_input` | C9 | signed desktop→phone input queue (tap/swipe/key/text, normalised coords) + Kotlin AccessibilityService `dispatchGesture` (`real_unverified_on_device`) | B1 |
| 4 ✅ 0.7.4 | `mirror.studio_input` | C9 | phone→desktop input events validated + delivered to a Studio input bus; Studio (PySide6) maps them to Qt events, offscreen-tested | B1 |
| 5 ✅ 0.7.4 | `mirror.camera_focus` / `lens.focus_control` | C9/C10 | focus request contract + desktop→phone queue; Kotlin Camera2 AF/manual focus (platform API, no CameraX dep) (`real_unverified_on_device`) | B1/B2 |
| 6 ✅ 0.7.5 | `lens.video_capture` | C10 | Kotlin Camera2 + MediaRecorder (H.264 hardware encoder on the phone) (`real_unverified_on_device`); desktop side ingests the clip, extracts frames with ffmpeg, runs `assess_set` | B2 |
| 7 ✅ 0.7.6 (`real_unverified_on_device`; ARCore terms C-68) | `lens.arcore_session`, `depth.arcore` | C10/C11 | Kotlin ARCore session + depth image wrapper if the ARCore AAR licence allows and it builds; else stays stub with reason | B2 |
| 8 ✅ 0.7.5 | `depth.dense_estimate` + ladder `depthanything-v2-onnx@cpu` | C11 | DepthAnything V2 **Small** (Apache-2.0; Base/Large are CC-BY-NC — forbidden) ONNX on onnxruntime CPU EP, then the existing metric alignment; `@rocm` rung code via ORT providers stays `planned` (no GPU here) | B2 |
| 9 ◐ 0.7.5 (desktop export + parity real; in-engine rung planned, C-63) | GIRT ONNX backend (`runtime.girt` `onnxruntime-gdextension@vulkan`) | F3 / C8 | export the BC MLP to ONNX, run via onnxruntime CPU EP with parity to NumPy/GDScript (desktop tooling); in-engine GDExtension + Vulkan stays `planned` | B2 |
| 10 ✗ stays stub (C-64, reaffirmed C-82 in 0.7.8) | PocketLoom ONNX rung (C-4) | C1–C6 | no small generative sprite/cave model exists to run — bundling onnxruntime-android with nothing to run would be a fake rung; revisit when `g1-sprite-onnx-tiny` is trained | — |
| 11 ✅ 0.7.7 (OpenCV, not COLMAP — C-73/C-74) | `recon.photogrammetry` + ladder `colmap-cpu-photogrammetry@cpu` | C12 | pycolmap (BSD-3) CPU SfM on a rendered tiny scene with known poses; pose error vs ground truth | B3 |
| 12 ◐ 0.7.7: tiny-scene CPU trainer real (own NumPy, no PyTorch — C-77); full-scale stays stub (`gpu_required`, C-75) | `recon.splatforge` | C12 | small CPU 3DGS trainer (PyTorch CPU, BSD) on a tiny scene, PSNR must rise, INRIA .ply passes `check_splat_ply`; OpenSplat@rocm stays `planned` | B3 |
| 13 ✅ 0.7.7 (surface nets, own NumPy — C-72) | `recon.meshweaver` | C12 | splat/point density → marching cubes (scikit-image BSD) → OBJ/glTF mesh; SuGaR@rocm stays `planned` | B3 |
| 14 ✅ 0.7.7 (billboard approximation — C-71) | `recon.gdgs_import` | C12 | ShuttleLine imports INRIA .ply into a Godot scene (MultiMesh billboard splats, Compatibility renderer), headless-verified | B3 |
| 15 ✅ 0.7.8 (desktop/Studio/CLI; in-game mic capture planned — C-78/C-79) | Voice (Vosk) not wired | F3 / HANDOVER | vosk (Apache-2.0) + small en model (Apache-2.0) → the existing closed intent grammar; test on synthesized speech | B4 |
| 16 ✅ 0.7.8 (Qwen2.5-0.5B int8 ONNX CPU, review-gated drafting; LoRA planned; in-engine stays bigram — C-80) | Persona "micro-LM" = bigram stand-in | F3 / INFERENCE 39 | tiny neural LM (CPU, NumPy-trained, JSON weights) if it can keep the Python↔GDScript parity gate; else keep bigram and say why | B4 |
| 17 ◐ 0.7.8 (Status/Mirror/Console + Swatches/Voice/Persona, read-only slash commands; character creator + MCP/ACP host not built — C-81) | Studio GUI placeholder | HANDOVER | minimal PySide6 Studio window (status, mirror viewer, input sink) — offscreen-tested | B1/B4 |
| 18 | GPU rungs: `g1-sprite-onnx-tiny@rocm/vulkan`, `g1-tile-nca@rocm`, `dyeworks-sdxl@rocm`, `dyeworks-sd15@directml`, `mlp-train-rocm`, `opensplat-rocm`, `mirror-h264-hw@vulkan`, `meshweaver-sugar@rocm`, `gdgs-raster-import@vulkan` | ladder | **stay `planned`** — no GPU, no ROCm/DirectML/Vulkan device on the build box; cannot be executed or verified here | — |
| 19 | Deferred `recon.nerf_neural_sdf`, `recon.large_scene_lod`, `recon.rc_models` | C12 register | **stay deferred** — spec marks them research/future; `rc_models` needs real capture runs to train on | — |

## Previous sprint — companion track (C9–C12 landed as interfaces + stubs; next needs Producer input)

- [x] PocketLoom C1–C6: standalone offline debug APK (FabricCore JobExecutor + local store, on-device generation, UI, capture, pairing, offload/sync) — accepted 2026-11-12 (`forge accept C1-C6`)
- [x] LoomCluster C7 + GroundWeave C8 (drafts from `wip/f5-companions` reviewed, hardened, verified) — accepted 2026-11-19 (`forge accept C7-C8`, 0.7.2+f7)
- [ ] C7 follow-ups: LAN/Tailscale run across two real machines; cluster auth (reuse LoomLink HMAC) before binding off loopback; PocketLoom (Kotlin) as a cluster *peer* node; blob transfer for large artifacts; origin election/hand-off when the origin never returns
- [ ] C8 follow-ups: first real GPU rung (ROCm/DirectML/Vulkan ONNX for G1-Sprite/Tile) wired through `groundweave.execute`; re-time the full 2400-fight balance on a 2-core node
- [x] C9–C12 (MirrorWeave, LensForge, depth, SplatForge): interfaces + clearly labelled stubs — accepted 2026-11-19 (`forge accept C9-C12`, 0.7.3+f7)
- [ ] C9–C12 follow-ups (each replaces a labelled stub; see `content/companions/c9_c12.yaml`): MediaProjection screen capture + H.264/WebRTC (C9); overlap/parallax measurement and validating the capture thresholds against a real reconstruction (C10, C-38/C-40); DepthAnything V2 CPU/ROCm estimator — verify its licence first, ARCore depth (C11, C-42); SplatForge/OpenSplat on a ROCm LoomCluster node, CPU photogrammetry (COLMAP), MeshWeaver, GDGS Godot import, `.splat` validation (C12)
- [ ] **F8 (retro/console-style) is optional — confirm scope with the Producer before starting.** F9 is post / LiveOps readiness only
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
