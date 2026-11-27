# TODO.md — Actionable Tasks

Last updated: 2026-11-27 America/New_York

## Current sprint — quality gaps (Producer t59u, 2026-11-20; phase 2 of "replace stubs, fix quality gaps, then F8 and F9")

> Paused 2026-11-20, resumed 2026-11-26 (Producer t61u). Q1–Q2 done, Q3 partial, ✅ (a) row 5 slice length (0.7.12) → ✅ (b) row 4
> D-005 tables + ✅ (c) row 6 balance (0.7.13, Q5) → ✅ (d) row 8 cluster auth/blobs + ✅ (e) row 9 D-001 + ✅ (f) row 10 doc nits
> (0.7.14, Q6) → ✅ (c′) row 7 world fights (0.7.15, P7). **Every software quality-gap row is closed** except the
> hardware-gated row 3 follow-up (native step). **F8 landed in `0.8.0+f8`** (docs/acceptance-tests/F8.md). **Next: F9 LiveOps readiness only** (HANDOVER.md §Next steps).

## F8 follow-ups (not scheduled; see docs/acceptance-tests/F8.md §Not proven)

- [ ] NES ROM beyond the field demo (combat, menus, chip audio) — only if the Producer wants a ROM product.
- [ ] GB ROM / other families (Genesis, GBA, PS1) — registry entry + ROMBuilder per family.
- [ ] Fantasy consoles (PICO-8/TIC-80) and CertPack — SPEC §1 hard deferrals.
- [ ] Real hardware / flash cart / CRT check; human eye test of the profiles.
- [ ] Stronger R2 control margin (modern frame scores 0.49 vs the 0.5 capture threshold; not gated).
- [ ] Optional pixel-quantised HUD mode (HUD is above the pass for readability, INFERENCE F8-10).

Inventory 2026-11-20 from TODO / HANDOVER / STATUS / docs/INFERENCES.md / acceptance docs / DECISIONS (D-001, D-005).
Rule: each row lands as its own patch release on `main` (tests + `forge accept` gate + docs) or is marked blocked with the
reason. Hardware / Producer-gated rows are listed at the end and are **not** worked here.

| P | Gap | Source | Fix plan | Gate | Batch / state |
|---|---|---|---|---|---|
| 1 | CI wall ≈ 14.5 min (pytest 13 min single job; some runs 30 min with queueing) | F7-16, CI runs | pytest split into 3 parallel shards that partition the suite (`--ci-group`), uv + apt caches, superseded runs cancelled on feature branches | `tests/test_ci_groups.py` (partition + no stale shard refs) | Q1 `0.7.9+f7` |
| 2 | **G-A11Y-01 partial**: no in-game rebinding screen, no runtime colour-blind palette switch, H / `/` / 1–4 hard-coded keys, no gamepad map | F7-11, F7.md | every game key becomes an InputMap action (keyboard + gamepad defaults); in-game Settings screen (locale keys, keyboard/gamepad navigable) to rebind any action and pick palette off/deuteranopia/protanopia; both persisted in the save (`profile.settings`) | F7 G-A11Y-01 → full pass (rebind + palette round-trip on desktop / Android content / Web) | ✅ Q2 `0.7.10+f7` — G-A11Y-01 passes (Settings screen, keyboard+gamepad rebinding, live palette remap, ΔE gate, render check) |
| 3 | Swap advisor 50–100 ms vs < 50 ms (GAME_SPEC §4.1) in the party scene | F3.md, HANDOVER perf debt | profile → algorithmic + data-layout hot-path work in the forward sim (no behaviour change outside forward clones), measure on 2 pinned cores; GDExtension only if that is not enough | F3 `swap_target_met` becomes a hard check on the 8-vCPU box **and** a 2-core pinned measurement | ◐ Q3 `0.7.11+f7` — reference box: p95 37.8–39.4 ms on 2 pinned physical cores, hard-gated in `forge accept F3`; LOD fidelity 17/17; outcomes unchanged. **Partial**: GitHub 2-core runners p95 ≈ 63–66 ms (CI reports, gates ceiling only). Follow-up: native step (GDExtension) or SoA CombatSim — GDScript threads scale ≈ 1.3× (`docs/perf/gdscript-thread-scaling/`; final attempt before landing: cost spread over movement/BT/policy, affinity-sized pool no gain, no C++ toolchain here) |
| 4 | **D-005 / F6-3** economy, loot and quest content are placeholders | F6-3, D-005 | data-driven tables (crops, recipes, shop, loot, quest chain, XP) per GAME_SPEC §4.4/§5 shapes, generated + gated by Codegen-World, balanced with the existing sims; names/numbers stay Game-Design-owned (D-005 remains open for *sign-off*) | world gates + economy solvability + quest soft-lock | ✅ Q5 `0.7.13+f7` — economy design model `content/world/economy_design.yaml` + `forge/economy.py` (ADR-0018, C-93): derived item values, Codegen-World `economy_design` gate (ROI 1.33/1.50, loot/kill 2.04/8.33/64.14), F6 loot MC (2000 seeds: P(flint edge) 1.000, P(warden charm) 0.9995, coin p50 131) + XP pacing 3/4/4/5 on all 13 runs; D-005 open for sign-off only |
| 5 | Vertical slice: bot 2.9 game-min vs 15–20 min | F6-12 | real content and pacing (second crop cycle, longer crop timers, quest chain steps, travel, boss gating) — not a slower bot; add a human-pace estimate model (reading, navigation, menu time) and gate it | F6 `length` hard check on the estimate (bot time reported as-is) | ✅ Q4 `0.7.12+f7` — human-pace estimate 17.03–18.51 min on all 12 selections (gated, ADR-0017, C-92); bot 7.10–7.35 game-min (was 2.9) from new content: Ore Hollow, patrol beat in the 2nd crop cycle, q_smith side quest, Windward Ridge open world (C-91); 0 wipes, 0 soft-locks. Human playtest still pending |
| 6 | Per-pair balance spread on unseen seeds 5.25 pp (noise floor at 200 seeds/cell); thin Optuna evidence | F6-2, F6-14, F5-12 | faster balance worker (from Q3), more seeds per cell out-of-sample, longer Optuna study recorded | per-cell spread ≤ 3.5 pp on unseen seeds | ✅ Q5 `0.7.13+f7` — hold-out 1000 seeds/cell on fresh seed_base 20 000: **2.71 pp** (gated in full `forge accept F5`); first hold-out (9000) 5.41 pp → 3 affinities recalibrated by paired CRN probe; bounded Optuna study (6 × 100, 140 s) recorded, too noisy to apply; 200-seed check noise-aware (C-94) |
| 7 | World fights tuned by hand | TODO Balance | Monte Carlo over the slice's area packs | wipe-rate / clear-time bands | ✅ P7 `0.7.15+f7` — `forge/worldfights.py` replays every recorded slice fight from its start state (levels, gear/buffs, carried HP, pulled packs) over fixed seeds; bands `content/tune/worldfights.yaml` (ADR-0020, C-98) gated per selection × fight in `forge accept F6`. Full: 8 040 fights, 0 wipes; trash median clear 1.13–4.02 s (band 1–6), elite 2.62–5.00 s (2–9), Warden 8.48–9.82 s (8–30), wipe ≤ 2 / 6 / 10 % all met. Tuned: field pack + ridge first pack +1 cave mite (field was 0.63–0.93 s for 5 selections) |
| 8 | LoomCluster node↔node HTTP unauthenticated (C-17); large blobs inside result JSON (C-28) | C-17, C-28 | HMAC-signed node requests with a pairing secret (LoomLink scheme), refuse unsigned/replayed; content-addressed blob transfer (`/blob/<sha256>`) for large artifacts | C7 auth + blob checks | ✅ Q6 `0.7.14+f7` — HMAC-SHA256 signed requests + responses with a fleet secret (`FORGE_CLUSTER_SECRET` / `forge cluster keygen`), 401 on unsigned/wrong-key/tampered/stale/replayed; `{sha256,size}` results + signed `/blob/<sha256>` pull verified by the origin; C7 `auth_blobs` check (C-95, C-96). No encryption — Tailscale before leaving loopback |
| 9 | **D-001** Web single-thread fallback | F7-3, D-001 | decide + implement if feasible (`nothreads` export variant, advisor serial path) | F7 web checks on both variants | ✅ Q6 `0.7.14+f7` — `web-nothreads` target (ADR-0019, C-97): 9.37 MB gzip, header-less host, SW + offline boot, IndexedDB save round-trip, advisor serial path; `patch_sw` fixes Godot 4.3's stale `index.worker.js` SW entry. D-001 closed |
| 10 | Doc nits / stale claims | STATUS, milestones.py C10–C12 text, HANDOVER | regenerate STATUS (`forge report`), fix stale "labelled stubs" descriptions | review | ✅ Q1 + pause docs pass + Q6 `0.7.14+f7` — C7 description, C9–C12 register counts, stale auth / threads-only claims, `.fabric/godot-home` symlink ignore; STATUS regenerated |

**Not worked here (hardware / Producer / Game-Design gated):** Windows runtime run; Android on a device (D-002); GPU rungs;
signing + store listings (keys); human GUI playtest; final roster names/stats sign-off (D-005 owner); "hold"↔"go" voice
grammar decision (C-79). F8 scope was confirmed by the Producer (t59u, C-85).

## Previous sprint — stub replacement (Producer t59u, 2026-11-20: "replace stubs with real code, fix quality gaps, then F8 and F9")

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

## Earlier sprint — companion track (historical: C9–C12 first landed as interfaces + stubs in 0.7.3; superseded by the stub-replacement sprint above)

- [x] PocketLoom C1–C6: standalone offline debug APK (FabricCore JobExecutor + local store, on-device generation, UI, capture, pairing, offload/sync) — accepted 2026-11-12 (`forge accept C1-C6`)
- [x] LoomCluster C7 + GroundWeave C8 (drafts from `wip/f5-companions` reviewed, hardened, verified) — accepted 2026-11-19 (`forge accept C7-C8`, 0.7.2+f7)
- [ ] C7 follow-ups: LAN/Tailscale run across two real machines; cluster auth (reuse LoomLink HMAC) before binding off loopback; PocketLoom (Kotlin) as a cluster *peer* node; blob transfer for large artifacts; origin election/hand-off when the origin never returns
- [ ] C8 follow-ups: first real GPU rung (ROCm/DirectML/Vulkan ONNX for G1-Sprite/Tile) wired through `groundweave.execute`; re-time the full 2400-fight balance on a 2-core node
- [x] C9–C12 (MirrorWeave, LensForge, depth, SplatForge): interfaces + clearly labelled stubs — accepted 2026-11-19 (`forge accept C9-C12`, 0.7.3+f7)
- [ ] C9–C12 follow-ups (each replaces a labelled stub; see `content/companions/c9_c12.yaml`): MediaProjection screen capture + H.264/WebRTC (C9); overlap/parallax measurement and validating the capture thresholds against a real reconstruction (C10, C-38/C-40); DepthAnything V2 CPU/ROCm estimator — verify its licence first, ARCore depth (C11, C-42); SplatForge/OpenSplat on a ROCm LoomCluster node, CPU photogrammetry (COLMAP), MeshWeaver, GDGS Godot import, `.splat` validation (C12)
- [ ] **F8 (retro/console-style) is optional — confirm scope with the Producer before starting.** F9 is post / LiveOps readiness only
- [ ] **Human GUI playtest of the vertical slice** (F6 carry-over): measure real length vs 15–20 min; HUD/quest/overlay readability; controls (E interact, H salve, Tab freeze, `/` command); music mix and fades; art legibility of plots/bench/nodes. Checklist: docs/acceptance-tests/F6.md §Human playtest
- [ ] Slice length: the 15–20 min gate is a model (ADR-0017); if humans finish well under 15 min, add content rather than slowing the bot or retuning `content/tune/pace.yaml`

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
- [ ] Real-browser Web test on a public HTTPS host (Chrome, Firefox, Safari) with COOP/COEP, plus the `web-nothreads` fallback on a host without COOP/COEP (D-001 closed in 0.7.14, ADR-0019)
- [ ] **Signing**: Windows Authenticode (+ rcedit icon/version), Linux AppImage/Flatpak signature, Android release keystore (env only, never committed) + AAB, BoltPack detached signature over `bolt.json`
- [ ] **Store listings** (Producer): itch.io / own web host, Google Play (copy, screenshots, content rating, privacy), Steam later
- [x] G-A11Y-01 full: in-game input rebinding UI + runtime colour-blind palette toggle (0.7.10)
- [ ] Cached CI `package` job (templates + SDK cache) running `forge accept F7` full on `main` (INFERENCE F7-16)
- [ ] Reproducible exports (pin GDScript tokenisation / compare by content) if byte-identical rebuilds are required

## Balance (F6)

- [x] Per-pair (leader × pet) spread < 5 pp: pet↔character affinity → 3.21 pp on the gate seeds, now gated (INFERENCE F6-1/F6-2)
- [ ] Per-pair spread on *unseen* seeds is 5.25 pp ≈ noise floor at 200 seeds/cell; an out-of-sample per-cell gate needs ~800 seeds/cell (faster worker first)
- [ ] Longer Optuna study (≥ 100 seeds/matchup per trial) once the runner is faster; consider Ax/surrogate
- [ ] Faster balance worker (native step function would also fix swap advisor)
- [x] Balance the slice's world fights with the Monte Carlo runner — P7 `0.7.15`: wipe-rate / clear-time bands gated in `forge accept F6` (ADR-0020, C-98)
- [ ] World fights are forgiving for the bot (0 wipes in 8 040 replays; ≥ 1 fighter downed in 98 % of Warden fights): confirm with a human playtest whether trash needs more threat (Game Design)

## Perf debt

- [~] Swap advisor < 50 ms — met on the reference node since 0.7.11 (p95 37.8–39.4 ms, 2 pinned cores, gated in `forge accept F3`); **not met on GitHub 2-core runners** (p95 ≈ 63–66 ms). Remaining fix: native step (GDExtension, ADR-0003) with a bit-parity gate — see `docs/perf/gdscript-thread-scaling/`
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
- [x] Stub replacement sprint 0.7.4–0.7.8 (C9–C12: 25 real · 8 real_unverified_on_device · 1 stub · 3 deferred)
- [x] Quality gaps Q1 CI shards (0.7.9), Q2 G-A11Y-01 full (0.7.10); Q3 swap advisor partial (0.7.11)

## Backlog (later milestones)

- Firecracker / gVisor launchers (need usable KVM + guest image)
- Hot reload of GDScript code, tilemaps, audio; remote (WS/gRPC) live transport for Studio
- Session host migration (failover tier 3); Crash Predictor model
- Studio PySide6 shell; SwatchStudio GUI
- ONNX G1-Sprite Tiny, NCA G1-Tile, diffusion DyeWorks backends

## Companion / cluster (parallel)

- [x] C1–C6 PocketLoom (accepted 2026-11-12) — see docs/acceptance-tests/C1-C6.md
- [x] C7 LoomCluster scheduler + C8 GroundWeave fallback ladder (0.7.2+f7)
- [x] C9–C12 accepted (0.7.3+f7); stubs replaced 0.7.4–0.7.8

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
| D-002 | Confirm Android reference = Redmi Note 12 Pro 5G (F7 APK is arm64-v8a only, untested on hardware) | Producer | before on-device test |
| D-005 | Sign-off of final names/stats of 4 fighters + 3 starter pets (GAME_SPEC §10) and of the economy design numbers (content tables + gates landed in 0.7.13, ADR-0018) | Game Design | before content lock |

## Infrastructure

- [x] CI on GitHub Actions with Godot 4.3 headless
- [ ] Windows runner (DirectML) — later
- [ ] Model artifact storage backend beyond local `store/`
