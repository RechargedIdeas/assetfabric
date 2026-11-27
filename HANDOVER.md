# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-27 America/New_York
**Repository:** https://github.com/RechargedIdeas/assetfabric (**private**, branch `main`)
**License:** proprietary, All Rights Reserved (ADR-0001)
**Current Fabric milestone:** **U1 — universal 2D/2.5D/3D engine** (accepted `0.10.0+u1`, 2026-11-27). **All spec milestones are complete: F0–F9 + C1–C12.** F9 LiveOps accepted `0.9.0+f9`; post-F9 ops `0.9.1+f9` + `0.9.2+f9`; F8 retro accepted `0.8.0+f8`; F7 packaging accepted `0.7.0+f7`
**Current game increment:** `liveops-readiness`
**Post-F9 operations (Producer t64u, 2026-11-27):** batch 1 `0.9.1+f9` — in-game diagnostics consent toggle + privacy-notice placeholder (F9-12), LoomCluster TLS 1.3 + mTLS (C-99, docs/cluster-lan-runbook.md), hardware verification kit (`scripts/verify-hardware/`, docs/hardware-verification.md, C-100). Batch 2 `0.9.2+f9` — **AMD-first ONNX EP selection** (`forge/onnx_ep.py`: MIGraphX/ROCm → DirectML → CPU, automatic CPU fallback at session creation and demotion on a failing GPU run, `forge groundweave onnx-ep [--selftest]`, C-101) for every ONNX rung (DepthAnything, GIRT parity, micro-LM) — `rocm_ready_unverified`; **full-scale SplatForge runner** (`forge/splatforge_gpu.py`: bundle → CPU SfM → nerfstudio project → deterministic config → external OpenSplat-class trainer → `check_splat_ply` + scene-bounds check, `forge recon train --stage splat`, C-102) and its **LoomCluster job** (op `recon.splat`, `requires: rocm`, hash-verified bundle in / blobs out, node-local trainer only; `forge recon submit --bundle`, C-103) — both `real_unverified_on_gpu`, contract proven on CPU with a contract-probe trainer and a simulated-rocm loopback node; **Q3 native step: investigated, not built** (C-104, docs/perf/gdscript-thread-scaling/ §0.9.2).
**Companion track:** **PocketLoom C1–C6 accepted** (`forge accept C1-C6`, debug APK `0.1.0-c6`, package `0.7.1+f7`) — standalone offline Android companion + LoomLink pairing/offload/sync; not yet run on a device
**Stub replacement sprint (2026-11-20):** batch 1 landed in `0.7.4+f7` — **C9 MirrorWeave has no stubs**: desktop video (CPU VP8/VP9 via system ffmpeg), X11 capture, signed WebSocket transport and Studio input are `real`; Android MediaProjection/H.264, AccessibilityService input and Camera2 focus are compiled into the APK as **`real_unverified_on_device`** (never run on a phone). Batch 2 landed in `0.7.5+f7` — **C10 video capture** (desktop ffmpeg keyframe ingest real; phone Camera2+MediaRecorder recorder `real_unverified_on_device`), **C11 dense depth** real (DepthAnything V2 Small, Apache-2.0, onnxruntime CPU; weights via `forge models fetch` with SHA-256, never committed), **GIRT ONNX** desktop export + parity tooling (`forge girt`), model licence gate `forge models audit`. Batch 2b landed in `0.7.6+f7` — **ARCore** session + depth: desktop pose coverage and DEPTH16 ingest (+ DepthAnything aligned to ARCore anchors) are real; the ARCore SDK capture (`ArCoreCapture`) is compiled into the APK as `real_unverified_on_device` (ARCore is under Google's terms, not OSS — INFERENCES C-68, confirm before release). Batch 3 landed in `0.7.7+f7` — **C12**: CPU photogrammetry (OpenCV SIFT SfM, sparse, no BA — C-73/C-74; `forge recon photogrammetry`), MeshWeaver (splat density → surface nets → OBJ) and GDGS Godot import (MultiMesh billboards, verified in Godot under Xvfb) are `real`, plus a bounded tiny-scene **CPU SplatForge trainer** (own NumPy isotropic 3DGS, `forge recon train --stage splat-cpu` — C-77); **full-scale SplatForge training stays the only stub** (needs a GPU — C-75). Register: 25 real · 8 real_unverified_on_device · 1 stub · 3 deferred. Batch 4 landed in `0.7.8+f7` — **VoiceBridge** (Vosk small en-us, Apache-2.0, grammar-constrained + confidence gate; synthetic speech 0.90 accuracy / 0.05 wrong-action, the residue is a hold↔go confusion — C-79), **persona micro-LM** on the spec's Qwen2.5-0.5B backbone (int8 ONNX, CPU, review-gated drafting; LoRA planned; the game keeps cache + bigram — C-80), **Studio** Swatches/Voice/Persona tabs + read-only slash commands. PocketLoom ONNX rung stays a stub (C-82). **Quality-gap phase (TODO.md §Current sprint, P1–P10):** Q1 landed in `0.7.9+f7` — CI pytest split into 3 parallel shards that partition the suite (`--ci-group`), apt/uv caches, stale C10–C12 descriptions fixed. Q2 landed in `0.7.10+f7` — **G-A11Y-01 full**: in-game Settings screen (Escape / F10 / pad Start) rebinds every action on keyboard and gamepad, live colour-blind palette remap generated from PatternVault with a ΔE gate, settings persisted in the save profile. Q3 landed in `0.7.11+f7` — **swap advisor < 50 ms on the reference box** (p95 37.8–39.4 ms pinned to 2 physical cores, gated in `forge accept F3`; GitHub runners ≈ 63–66 ms, so partial), pure GDScript data-layout work, outcomes/balance unchanged. Q4 landed in `0.7.12+f7` (slice length), Q5 in `0.7.13+f7` (economy model + per-pair balance). Q6 landed in `0.7.14+f7` — **LoomCluster HMAC node auth + content-addressed blob transfer** (C-95, C-96), **`web-nothreads` single-thread Web fallback** (ADR-0019, D-001 closed, C-97), doc nits.

**Companion interfaces (C9–C12):** accepted (`forge accept C9-C12`); since 0.9.2 the register is 25 real · 8 `real_unverified_on_device` · 2 `real_unverified_on_gpu` (full-scale SplatForge runner + its LoomCluster job) · 1 stub (phone-initiated splat submit, `recon.splat_submit`) · 3 deferred (`content/companions/c9_c12.yaml`). Nothing ran on a phone or a GPU.
**Fleet track:** **LoomCluster C7 + GroundWeave C8 accepted** (`forge accept C7-C8`, package `0.7.2+f7`) — equal-node scheduler proven on **loopback processes** (not a LAN), GPU→CPU ladder with the CPU path proven on 2 pinned cores; no real GPU backend exists yet
**F8 (0.8.0+f8):** Settings → Display style (off / gz-native / nes-style / gb-style + scanlines) as one R1 LUT pass between world and HUD, Q1 integer camera/sprite policy, a11y remap kept, sim byte-identical; NES field-demo ROM built from Fabric content and driven in cynes — docs/acceptance-tests/F8.md, ADR-0021, INFERENCES §F8.
**F9 (0.9.0+f9):** LiveOps readiness only — flag manifest with safe offline defaults (`content/liveops/flags.yaml` → generator `liveops`), RSA-signed **local** config bundles (kill switches + balance knobs = F4 tune limits; anti-replay serial; no content, no consent flags), game `LiveOps` autoload (inbox → verify → promote/reject, crash-loop quarantine, tamper/downgrade → shipped defaults), newer saves read-only, opt-in scrubbed local diagnostics, `forge liveops …`, runbook `docs/liveops-runbook.md`, ADR-0022, INFERENCES §F9. The game never fetches anything (G-NET-01 strict). **No live service, no delivery endpoint, no launch.**
**U1 universal engine (user request t65u; landed `0.10.0+u1`):** `forge/universal/` delivers:
* one scene IR for 2D, 2.5D and 3D, plus 10 coordinate conventions;
* parametric templates through the **real OpenSCAD CLI** and an own NumPy CSG/SDF fallback;
* 23 tiered adapters. **native_verified:** Godot, Blender. **cli_bridge:** OpenSCAD. **interchange_pack:** Unreal, Unity,
  RPG Maker, Sprite Lamp/Pro, Construct, Clickteam, AppGameKit, GameGuru, CopperCube, Esenthel, AGFPRO, RaySupreme,
  COLMAP, 3DGS, Fuse, ePic. Interchange-pack tools are not run;
* the Wikipedia engines catalog (178 rows, rev 1388112807) plus 28 curated tools = 199 entries;
* benchmark-gated self-improvement with rollback;
* sandboxed plugins plus a live gap report.

`forge accept U1` is green. Design: ADR-0023…0026 and `docs/architecture/universal-engine.md`. Inferences: INFERENCES §U1. Package version `0.10.0+u1`; Game Zero stays `0.9.1+f9`.
**Next:** nothing spec-required is left — every remaining item is hardware- or Producer-gated (§Next steps). Quality gaps (a)–(f), (c′) all landed in `0.7.12`–`0.7.15`.
**Producer direction (2026-11-05):** build the complete project milestone-by-milestone, push `main` after each milestone, no public releases.

Milestone dashboard: [STATUS.md](STATUS.md).

---

## What exists (honest)

| Piece | State |
|---|---|
| `forge` CLI | status, doctor, validate, job, store, build (`--sandbox`, `--target` platform builds), gen, palette, accept, report, sandbox, live (set/sprite/push/watch/serve/status), balance (run/tune/tune-affinity/holdout), softlock, save (inspect/migrate), templates (status/fetch), shuttle (contract/export), link (serve — PocketLoom pairing), cluster, groundweave, mirror, lens, depth, recon (C9–C12; stubs exit 3 with a `[STUB …]` label) |
| Asset store + orchestrator | real (SQLite, sha256, provenance); in-order worker; no GC / remote workers |
| Generators | **procedural CPU backends**: G1-Sprite (humanoid/beast/pet), G1-Tile (CA caves), DyeWorks (albedo + normal), **Codegen** (roster → game_data.json + ability .tres), **G1-Audio** (chiptune stems + SFX), **policy** (NumPy BC → JSON MLP), **callouts**, **persona_lm** (bigram stand-in), **world** (Codegen-World: economy/loot/quests/music/areas → `data/generated/world.json`). ONNX/NCA/diffusion/real-LM backends not built |
| Gates | palette, dims, seamless, solvability, floor ratio, BudgetGate (time + bytes); world: schema, cross-refs, quest-chart soft-lock, economy solvability, loot tables, music rules |
| PatternVault | 5 palettes + deuteranopia/protanopia variants |
| SwatchStudio | CLI only (`forge palette`, `forge gen --seed`) |
| Godot binding | `fabric_assets.json` registry + `Fabric` autoload (runtime load, no editor import) |
| Game Zero | sandbox (F1), first combat (F2), **party AI (F3)**: compiled BTs + GIRT policy targeting, time-freeze swap with threaded forward-sim ranking, typed intents via CascadeHub, callouts, post-combat dialogue; keyboard play + headless autoplay + demo mode; deterministic sim; **live tune (F4)**: `--scene=live`, live channel, snapshots/WAL replay, statecharts, guardian-supervised `--serve`; **first boss (F5)**: `--scene=boss`, tier-3 Cave Warden (3 HP phases, 2 summoned emberlings, enrage) in a carved G1-Tile boss arena, autoplay rally, save on victory; **vertical slice (F6)**: `--scene=slice` — character + pet select, farm plots (plant/grow/harvest), gather nodes, workbench crafting (salve, tonic, gear), tiered loot, quest log (main + side quest), field ⇄ tunnels ⇄ deep cave → Warden's lair → open-world exit, adaptive music (biome × state stems), checkpoints + save/quit/resume, XP/levels, boss unlock; headless QA autopilot (`--autoplay`) |
| Universal engine (U1) | **real**: `forge universal …` / `forge parametric …`. **native_verified:** Godot 4.3 GLTFDocument, Blender 4.3 bridge. **cli_bridge:** OpenSCAD 2021.01. Every other named engine/tool is an `interchange_pack` (documented import formats, validated by our own readers; tool not run). There is no FBX/USD writer (gaps). Plugins run only inside forge.sandbox. `forge accept U1` + `tests/test_universal_engine.py` |
| Acceptance | `forge accept C1-C6` (PocketLoom) `forge accept C7-C8` and `forge accept C9-C12` (recorded `results/C*.json`); `forge accept F0..F9` recorded in `docs/acceptance-tests/results/` (F3–F6 add `perf` blocks); `FORGE_ACCEPT_FAST=1` runs the 2-selection F6 subset (pytest/CI) |
| CI | GitHub Actions (push to `main` / `feat/**`, PRs): job `test` = pytest + determinism gate + Godot 4.3 headless increments; job `pocketloom` (parallel) = `forge accept C1-C6` full (JDK 17 + Gradle cache + runner Android SDK) then `forge accept C7-C8` (Godot cached), then `forge accept C9-C12` |
| GIRT / CascadeHub | real, CPU/GDScript backends (`autoload/girt.gd`, `autoload/cascade_hub.gd`); desktop ONNX export/parity opens sessions through `forge.onnx_ep` (AMD-first, CPU fallback, 0.9.2); ONNX Runtime GDExtension in the game not built |
| Substrate (F4) | **real**: sandbox tiers bwrap + process (Firecracker/gVisor detected, no launcher — `/dev/kvm` not accessible), live channel (atomic hot reload, 2PC, probe, rollback), Tier-2 snapshots + WAL, parallel statecharts + soft-lock analysis, Guardian (crash/hang restart + resume + quarantine). See `docs/SUBSTRATE.md` |
| Balance (F5) | **real**: `forge balance run` (12 character-select matchups × 200 seeds = 2400 headless boss fights, sharded over CPU cores, CRN, Wilson CIs) — G-BAL-01 pass, gated per choice **and per leader × pet cell** since F6 (pet↔character affinity, INFERENCE F6-1/F6-2; noise-aware CI check since 0.7.13); **hold-out** `forge balance holdout` (1000 unseen seeds/cell, seed_base 20 000, ≤ 3.5 pp — 2.71 pp in 0.7.13, full `forge accept F5`, C-94); `forge balance tune` / `tune-affinity` (Optuna TPE, CPU, optional extra `tune`) |
| Soft-lock (F5) | **real**: static (statecharts + encounter reachability incl. boss room) + runtime stall/timeout detector; mis-tuned probe proves it fires |
| Save (F5/F6) | **real**: Player State v4 (profile / roster / world incl. farm, checkpoint, quest counters, buffs, gear), migrations v1→v2→v3→v4, canonical JSON + sha256, atomic write + `.bak` recovery; GDScript ↔ Python parity. Cross-device round-trip **G-SAVE-01 proven at F7** (desktop → Android content → Web/IndexedDB → desktop, checksum identical every hop); transfer is manual (`--import-b64`), no cloud sync |
| Retro (F8) | **real**: Console Profile Registry (`content/retro/profiles.yaml`), generator kind `retro` (C1 LUTs + a11y signal solver + Q1 table), Godot `Retro` autoload + `retro_post.gdshader` (CanvasLayer 1; HUD on 2), Settings → Display style / Scanlines saved in the profile; ConsoleReadiness; ForgeConsole ROM path (own 6502 assembler + cycle predictor, iNES NROM-256 field demo, cynes EmulatorHarness); V1 + R2 gates. CertPack + fantasy consoles deferred. `forge retro …`, `forge accept F8` (≈ 40 s) |
| LiveOps (F9) | **real, readiness only**: `content/liveops/flags.yaml` → generator `liveops`; `forge/liveops.py` + `forge liveops manifest|keygen|bundle|verify|install|rollback|status|diag-export|readiness`; game `autoload/liveops.gd` (local inbox/active/previous/rejected/quarantine state machine, RSA verify via Godot `Crypto`, kill switches in Retro + MusicDirector, balance overlay via LiveChannel); newer saves read-only; diagnostics opt-in + scrubbed, never uploaded. No service, no endpoint, no production key yet |
| Packaging (F7) | **real, unsigned/debug**: `forge build --target desktop-linux|desktop-windows|android|web|all` → `dist/` (gitignored). Hermetic Godot home + sha256-pinned 4.3 templates; staged keep-import ships Fabric output byte-for-byte; per-target verify; PWAPipeline (G-WEB-01 9.3 MB gzip / 45 MB, offline SW, COOP/COEP); ShuttleLine contract checked against every PCK/APK; BoltPack SBOM + license audit + `.fabricbolt`. Sizes + SHA-256: docs/acceptance-tests/F7.md. Local-only (CI runs the static F7 subset). See docs/packaging.md |
| PocketLoom (C1–C6) | **real, debug APK** (`companions/pocketloom/`, ≈ 0.89 MB): FabricCore (pure Kotlin/JVM: JobExecutor + Dispatcher, content-addressed AssetStore with version vectors, durable OffloadQueue, Telemetry, ModelCache LRU, LocalForge CPU caves/sprites with gates + retry — ONNX rung is a labelled stub), Android UI (Generate · Library · Capture · Link · Telemetry; string resources only; lint 0 errors), capture via camera intent / import → queued `recon.capture`, LoomLink pairing (one-time code, `loomlink://` QR URI, Tailscale address; HMAC proofs, caps ∩, signed requests, 300 s code TTL) with `forge link serve` on the desktop, offload drain + version-vector sync (conflicts keep both). Proven by JUnit + aapt/apksigner/lint + the same FabricCore code (jar) against the Python server. **Never run on a phone** (no device / KVM). See docs/acceptance-tests/C1-C6.md |
| LoomCluster (C7) | **real, loopback-proven** (`forge/loomcluster.py`, `forge cluster node|submit|status|gen|demo`): equal nodes, adverts + gossip, allocation-capped slots, work stealing, origin leases (owner moves with a steal), retry (3), journal recovery + result redelivery, device placement, `forge link serve --cluster` bridge for PocketLoom offloads. **Unauthenticated HTTP on loopback; never run across machines** |
| GroundWeave (C8) | **real ladder, CPU paths only** (`content/groundweave/ladder.yaml`, `forge/groundweave.py`, `forge groundweave check|show|verify`): every generator kind declared and enforced by `run_brief`; CPU rungs proven on 2 pinned cores, GPU hidden, byte-identical to unpinned / simulated-GPU runs; GPU rungs are `planned` except the ONNX rungs (`depth.estimate` ROCm/DirectML via `forge.onnx_ep`) and `recon.splat` → `opensplat-rocm` (external trainer), which are real code with `verified: false` (0.9.2 rule: a real non-CPU rung must declare `verified`, `true` needs an evidence path); `recon.splat` is `gpu_required` + routed via LoomCluster op `recon.splat` |
| Studio GUI | **real, minimal** (`studio/assetfabric_studio`, PySide6, offscreen-tested): Status, Mirror (phone frames), Console (remote phone input + read-only `/` commands), Swatches (PatternVault), Voice (VoiceBridge), Persona (micro-LM drafts). No character creator, MCP/ACP host |

## Verify

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git && cd assetfabric
./scripts/bootstrap.sh && source .venv/bin/activate
forge status && pytest -q
forge build && git diff --exit-code games/game-zero/assets/generated
forge accept F6           # needs Godot 4.3 (GODOT_BIN / PATH / godot-bin/); ≈ 30 s on 8 vCPU (12-selection matrix)
forge accept F5           # ≈ 2 min on 8 vCPU (2400-fight balance matrix)
forge accept F9           # LiveOps readiness: signed bundles, device state machine, rollback/quarantine, saves, privacy (≈ 11 s; Godot)
forge liveops readiness   # LiveOps checklist (user-gated: production key, live service)
forge accept F8           # retro: profiles, NES ROM + cynes, gamepad settings flow, Xvfb V1/R2 (≈ 40 s; Godot + Xvfb + cynes)
forge templates fetch && forge accept F7   # platform builds + G-WEB-01/G-SAVE-01/G-NET-01 (≈ 1.7–2.5 min; JDK 17, Android SDK, Chrome)
forge accept C1-C6        # PocketLoom: gradle tests + debug APK + lint + Kotlin↔Python LoomLink interop (JDK 17 + Android SDK; ≈ 75 s warm)
forge accept C9-C12       # C9–C12 contracts + stub labelling + real CPU paths (JDK 17 + Android SDK; ≈ 1 min warm)
forge accept C7-C8        # LoomCluster loopback fleet + GroundWeave 2-core/no-GPU proofs (≈ 80 s; Godot + optional JDK/SDK for the Kotlin hop)
forge cluster demo        # 3 local nodes: stealing + SIGKILL failover
forge link serve --bind <LAN/Tailscale IP> [--cluster <node URL>]   # pair a phone running PocketLoom
forge balance run         # G-BAL-01 matrix only
godot --path games/game-zero -- --scene=slice     # the vertical slice (windowed)
```

## Known issues / limits

- Generated art is placeholder-grade procedural pixel art (by design for F1; quality bar rises with ONNX backends).
- `godot-bin/` (Godot 4.3 Linux) is gitignored; CI downloads it. See `docs/setup/README.md`.
- Godot editor import is bypassed (`.gdignore` on `assets/generated/`); packaging stages the project and ships them with `importer="keep"` (INFERENCE F7-2).
- **Packaging (F7)**: unsigned/debug only — no Authenticode, Android release key, AAB, BoltPack signature or store listings. **Windows build never executed** (no Windows host / wine; static PE + PCK checks only). **Android never ran on a device** (no KVM for an emulator; APK content ran on the desktop runtime). Web tested in headless Chrome on localhost only. Exports are not byte-reproducible (GDScript re-tokenised per export). Web ships the threads build plus, since 0.7.14, a single-thread `web-nothreads` fallback for hosts that cannot send COOP/COEP (ADR-0019). G-A11Y-01 is full since 0.7.10 (Settings screen + live palette), proven with injected keyboard/gamepad events and an Xvfb/llvmpipe render — no real gamepad or phone used.
- **LiveOps (F9)**: readiness only — no production key pinned (release builds ignore all bundles), no delivery service, no in-game consent toggle; bundles never touch content or saves by design. Bundle path not exercised on real Windows/Android/Web hosts.
- **Retro (F8)**: the NES ROM is a field demo (party + pet walk the field; no combat/menus/audio); no GB or other-family ROM; HUD stays above the pass (not pixel-quantised, F8-10); gb-style shows "crop growing vs ready" in one shade (ready frame cue carries it, F8-5); R2 control margin thin (modern frame 0.4836 vs 0.5 threshold, not gated); cynes only — no real hardware, flash cart or CRT; fantasy consoles + CertPack deferred.
- **Sandbox**: no micro-VM/gVisor launcher (no usable KVM); `process` tier is best-effort (audit hook does not stop native code). Hot reload covers numeric data, `sim.*` params and sprites — not code, tilemaps or audio.
- **Swap advisor** meets < 50 ms on the reference box since 0.7.11 (this recording: p95 41.72 ms / max 46.29 ms on 2 pinned physical cores; hard gate in `forge accept F3`). **Not met on slower CPUs**: GitHub 2-core runners p95 ≈ 63–66 ms, so pytest/CI only gate the 150 ms ceiling + parity + fidelity. GDScript worker threads scale ≈ 1.3× (engine-level, `docs/perf/gdscript-thread-scaling/`); next step is a native step function (GDExtension) with the GDScript path as CPU fallback.
- In-engine "micro-LM" is still the bigram (deterministic, safety-gated); the real Qwen2.5-0.5B micro-LM (0.7.8) is desktop/build-time drafting with human review, no per-character LoRA. GIRT ONNX is desktop export/parity only (C-63).
- Voice: VoiceBridge (Vosk) is real on the desktop/Studio/CLI (synthetic speech only); the running game has no microphone/Vosk binding yet; "hold" is misheard as "go" on synthetic voices (C-79, needs a grammar decision).
- Roster names/numbers are placeholders (D-005).
- **Balance**: per-pair (leader × pet) spread is gated since F6: 3.21 pp on the acceptance seeds (partly in-sample) and 5.25 pp on unseen seeds ≈ the 200-seed noise floor [INFERENCE F6-2]. An out-of-sample per-cell gate needs ~800 seeds/cell.
- **Slice length** (since 0.7.12): gated on a human-pace *estimate* of 17.15–18.76 min across all 12 selections (ADR-0017, INFERENCE C-92; this recording); the QA autopilot itself finishes in 7.11–8.05 game-minutes. Real human length, readability of the HUD/quest text, controls feel, music mix and art legibility need a **GUI playtest** (see F6.md).
- Economy / loot / quest / music numbers and names are placeholders (D-005, INFERENCE F6-3).
- Optuna log in `results/F5-tune.json` is a short study (12 × 24 seeds) — noise-dominated; shipped values verified at 200 seeds [INFERENCE F5-12].
- F5 acceptance runs 2400 fights; on a 2-core node expect ≈ 7–9 min.
- **PocketLoom**: debug-signed only; never installed on a phone (camera/picker intents, QR → intent hand-off, on-device timings unverified). ONNX rung is a stub (no runtime bundled). LoomLink has no TLS/PAKE: HMAC gives integrity + replay protection, not confidentiality (use Tailscale); the hello proof allows offline guessing of the 8-char code within its 300 s TTL; desktop `last_ts` not persisted across restarts; deletions not synced (no tombstones); session key not Keystore-wrapped. INFERENCES C-1…C-15.

- **C9–C12**: see `docs/acceptance-tests/C9-C12.md` §Not proven — every Android half (MediaProjection, input, Camera2 focus/video, ARCore capture) never ran on a phone (`real_unverified_on_device`), X11-only capture, no WebRTC, no desktop HW H.264; dense depth is CPU-only (DepthAnything V2 Small); reconstruction is CPU photogrammetry + a tiny-scene CPU splat trainer; full-scale splat training is an external-trainer runner + LoomCluster job that never ran on a GPU (`real_unverified_on_gpu`, OpenSplat not bundled, GPU output not bit-reproducible); capture thresholds unvalidated (C-38), overlap unmeasured, ETAs unmeasured, DepthAnything/ARCore licences unverified (C-42); Kotlin classes JVM-tested only, never on a phone.
- **LoomCluster / GroundWeave (C7/C8)**: proven on loopback processes only. Node↔node HTTP is HMAC-authenticated with one shared fleet secret since 0.7.14 (401 on unsigned/stale/replayed); **optional TLS 1.3 + mTLS since 0.9.1** (private fleet CA, C-99) proven on loopback only — plain-HTTP mode is still unencrypted, keep it on loopback; off loopback use TLS + Tailscale/WireGuard (docs/cluster-lan-runbook.md); PocketLoom is a LoomLink client, not a cluster peer; no GPU rung has run on a GPU (ROCm ONNX / OpenSplat rungs are real code, `verified: false`), runtime demotion proven on a synthetic ladder and on a fake onnxruntime; reduced balance matrix (not the full 2400 fights) is what was re-timed on 2 cores; origin loss without restart loses results; artifacts move as signed content-addressed blobs since 0.7.14 (INFERENCES C-16…C-31, C-95, C-96).

## Resume point (paused 2026-11-20)

State at the pause: `main` = `0.7.11+f7` (Q3 landed as **partial**). Resumed 2026-11-26: `0.7.12+f7` = (a); `0.7.13+f7` = (b) + (c) (2026-11-27); `0.7.14+f7` = (d) + (e) + (f) (2026-11-27); `0.7.15+f7` = (c′) P7 world-fight bands (2026-11-27). All work is pushed; nothing local-only.

**Open branches on origin:**

| Branch | Head | Holds | State |
|---|---|---|---|
| `main` | `0.10.0+u1` | everything accepted through F9 (all spec milestones) + post-F9 batches 1–2 + U1 universal engine | CI green |
| `feat/universal-engine-u1` | — | U1 universal 2D/2.5D/3D engine (IR, OpenSCAD/CSG, 23 adapters, catalog, evolution, plugins) | **merged into `main` as `0.10.0+u1`** |
| `feat/post-f9-gpu-perf` | — | post-F9 batch 2 (ONNX EP selection, SplatForge runner + cluster job, Q3 native feasibility) | **fast-forwarded into `main` as `0.9.2+f9`**; safe to delete |
| `feat/post-f9-ops` | — | post-F9 batch 1 (consent toggle, cluster TLS, hardware kit) | **fast-forwarded into `main` as `0.9.1+f9`**; safe to delete |
| `feat/f9-liveops` | — | F9 LiveOps readiness | **fast-forwarded into `main` as `0.9.0+f9`** (2026-11-27); safe to delete |
| `feat/f8-retro` | — | F8 retro / console-style | **fast-forwarded into `main` as `0.8.0+f8`** (2026-11-27); safe to delete |
| `feat/q4-slice` | — | Q4 slice length | **merged into `main` as `0.7.12+f7`** (2026-11-26); safe to delete |
| `feat/q5-economy` | — | Q5 economy model + per-pair hold-out | **merged into `main` as `0.7.13+f7`** (2026-11-27); safe to delete |
| `feat/q6-cluster-web` | — | Q6 cluster auth + blobs, web-nothreads, doc nits | **merged into `main` as `0.7.14+f7`** (2026-11-27); safe to delete |
| `feat/quality-p7` | — | P7 world-fight wipe-rate / clear-time bands | **fast-forwarded into `main` as `0.7.15+f7`** (2026-11-27); safe to delete |
| `feat/quality-q1`…`q3`, `feat/stubs-real-b1`…`b4` (incl. `b2b`), `feat/companions-pocketloom`, `feat/companions-c7-c8`, `feat/companions-c9-c12`, `feat/f5-balance`, `feat/f6-slice`, `feat/f7-packaging` | — | fully merged into `main` (ancestors of `main`) | safe to delete on origin when the Producer agrees |
| `wip/f5-companions` | `73e01e1` | early companion WIP (PocketLoom, LoomCluster, GroundWeave drafts) | **not an ancestor of `main` but superseded** — its content was rebuilt, verified and merged via `feat/companions-pocketloom` and `feat/companions-c7-c8`; keep for history or delete |

**Resume order** (one small patch release each, landed on `main` when green — rules in TODO.md §Current sprint):

1. ✅ **(a) Slice length** (P5) — landed `0.7.12+f7`: Ore Hollow, patrol beat, q_smith, Windward Ridge (C-91); `forge accept F6` gates the human-pace estimate (C-92, ADR-0017): 17.03–18.51 min on all 12 selections; bot 7.10–7.35 game-min. A human GUI playtest stays the real proof.
2. ✅ **(b) D-005 economy / loot / quest tables** (P4) — landed `0.7.13+f7`: economy design model (ADR-0018, C-93), `economy_design` gate in Codegen-World, loot MC + XP pacing in `forge accept F6` on all 12 selections. Names/numbers stay Game-Design sign-off.
3. ✅ **(c) Per-pair balance ≤ 3.5 pp on unseen seeds** (P6) — landed `0.7.13+f7`: **2.71 pp** on 1000 fresh seeds/cell (seed_base 20 000, full `forge accept F5`); bounded Optuna study recorded but not applied (noise), 3 affinities recalibrated by paired CRN probe (C-94). P7 world fights landed in `0.7.15+f7` (item 7).
4. ✅ **(d) LoomCluster node auth + content-addressed blob transfer** (P8) — landed `0.7.14+f7`: HMAC-SHA256 signed requests and responses (fleet secret, ±120 s window, nonce replay guard → 401), `{sha256,size}` results + signed `/blob/<sha256>` pull verified by the origin; C7 `auth_blobs` check (C-95, C-96). Still no encryption.
5. ✅ **(e) Web single-thread fallback** (D-001, P9) — landed `0.7.14+f7`: `web-nothreads` target, ADR-0019, C-97; `patch_sw` fix for Godot 4.3's stale `index.worker.js` SW entry.
6. ✅ **(f) Doc nits** (P10) — landed `0.7.14+f7`; STATUS regenerated.
7. ✅ **(c′) World-fight wipe-rate / clear-time bands** (P7) — landed `0.7.15+f7`: `forge/worldfights.py` replays every recorded slice fight from its start state over fixed seeds; bands in `content/tune/worldfights.yaml` (ADR-0020, C-98) gated per selection × fight in `forge accept F6` — full 8 040 fights, 0 wipes, trash 1.13–4.02 s / elite 2.62–5.00 s / Warden 8.48–9.82 s median clear, all in band; field + ridge first packs +1 cave mite (field was < 1 s). F5 outcomes byte-identical.
8. ✅ **F8** retro/console-style — landed `0.8.0+f8` (2026-11-27): `forge accept F8` green, docs/acceptance-tests/F8.md.
9. ✅ **F9** LiveOps readiness only — landed `0.9.0+f9` (2026-11-27): `forge accept F9` green, docs/acceptance-tests/F9.md. **Project spec-complete (F0–F9 + C1–C12).**
10. ✅ **U1** universal 2D/2.5D/3D engine — landed `0.10.0+u1` (2026-11-27): `forge accept U1` green, docs/acceptance-tests/U1.md. Merged on top of `0.9.2+f9`.

Q3 follow-up (not scheduled): native forward-sim step (GDExtension, ADR-0003) to meet < 50 ms on slow 2-core runners. **0.9.2 investigation (C-104):** the box now has g++ 14.2 + SCons and godot-cpp 4.3 builds cleanly (1 min 41 s on 8 vCPU), but a removed-`move()` probe shows movement is only ≈ 5–15 % of a forward sim, so a cleanly scoped native kernel cannot reach the ≈ 25 % cut needed; the fix is a full native forward sim (combat sim + entities + grid + BT interpreter + GIRT policy, ≈ 1.5 k GDScript lines) with a bit-parity gate and per-platform builds (Linux, Windows, Android arm64, Web dlink) — a milestone of its own; see `docs/perf/gdscript-thread-scaling/`.

## Next steps (ordered)

Every spec milestone (F0–F9, C1–C12) is accepted. U1 (universal engine, t65u) landed `0.10.0+u1`. Its
follow-ups are in TODO.md §U1: native checks for Unity/Unreal, FBX/USD writers, processor plugins, and a GPU
`gen.parametric` rung. What is left needs hardware, people or a Producer decision:

1. **Producer key ceremony for LiveOps** (docs/liveops-runbook.md §Key ceremony): generate the production RSA key
   offline, pin `games/game-zero/data/liveops/pubkey.pem`, add `data/liveops/*` to the export include filters. Until
   then release builds ignore every bundle (`forge liveops readiness` → `production_public_key: user_gated`).
2. **LiveOps service / delivery** — out of F9 scope (readiness only); any fetch from the game needs a Producer decision
   and a network-policy ADR (G-NET-01). ✅ In-game diagnostics consent toggle landed `0.9.1+f9` (F9-12); the privacy
   notice is a marked placeholder → **legal review** (user-gated).
3. **Signing + store listings** (docs/packaging.md §Signing & stores) — Producer keys/certs (Authenticode, Android
   release key/AAB, BoltPack signature).
4. **Real hardware runs**: Windows build never executed (no Windows host); debug APK + PocketLoom on the Redmi Note 12
   Pro 5G (D-002: install, generate, capture, QR pairing, drain + sync, timings; all `real_unverified_on_device`
   Android paths); Web build on a public HTTPS host. **Kit ready (0.9.1):** `scripts/verify-hardware/`
   (`verify-windows.ps1 [-Playtest]`, `verify_android.py`, `verify_web.py`, `hwreport.py`) — docs/hardware-verification.md.
5. **GPU** (Shivati, RX 7900 24 GB): install `onnxruntime-rocm` (or `-migraphx`) and check `forge groundweave onnx-ep`
   picks ROCm/MIGraphX, then run `forge accept C11` there; build OpenSplat (HIP) and run `forge recon train BUNDLE --stage
   splat` and `forge recon submit --bundle BUNDLE --cluster URL` against a node started with `--devices cpu,rocm`. Only
   then may `content/groundweave/ladder.yaml` rungs flip to `verified: true` (with an `evidence:` hw-report path) and
   the register entries leave `real_unverified_on_gpu` (code ready since 0.9.2, C-101…C-103). Also:
   two-machine LoomCluster run on a real LAN/Tailscale (✅ TLS 1.3 + mTLS ready since 0.9.1 — follow
   docs/cluster-lan-runbook.md); Kotlin cluster peer.
6. **Human GUI playtest** of the vertical slice (checklist docs/acceptance-tests/F6.md) — length vs 15–20 min is a
   human-pace estimate today; Game-Design sign-off on names/numbers (D-005).
7. Q3 follow-up (optional): full native forward sim (GDExtension) for < 50 ms swap advisor on slow 2-core runners —
   toolchain feasible since 0.9.2, a partial kernel is not enough (C-104); plan it as its own milestone.

## Recent decisions

ADR-0001 license (proprietary) · ADR-0002 Godot 4 Compatibility · ADR-0011 no LLM in tick · ADR-0012 content-addressed store · ADR-0016 one-milestone offset · ADR-0017 slice human-pace gate · ADR-0018 economy design model · ADR-0019 Web single-thread fallback (D-001 closed) · ADR-0020 world-fight bands · ADR-0021 retro presentation profiles + ROM path (F8) · ADR-0022 LiveOps signed local config bundles (F9). ADR-0004 GIRT (CPU/GDScript backend for F3). Inferences: `docs/INFERENCES.md` §F1–§F9 (F8-1…F8-15, F9-1…F9-11), §C1–C6, §C7/C8 (C-17…C-31), §C9–C12 (C-32…C-50), stub-replacement batch 1 (C-51…C-59). C9–C12: 25 real · 8 real_unverified_on_device · 1 stub after the stub-replacement sprint (C-51…C-82); quality-gap phase C-83…C-97 (Q6: C-95 cluster auth, C-96 blobs, C-97 web-nothreads).

## For the next agent

Read `AGENTS.md` → this file → `TODO.md` → `STATUS.md`. Do not start F(n+1) before `forge accept F(n)` passes.

**Worktrees:** the shared `.venv` has `forge` installed editable from `/workspace/assetfabric`; in a `git worktree` run
`export PYTHONPATH=$PWD` (or `python -m forge …`) so `forge accept` uses the worktree's code — otherwise the console
script silently runs `main`'s code (seen during Q6: a mixed run failed C7 on the missing fleet secret).
