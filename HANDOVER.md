# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-27 America/New_York
**Repository:** https://github.com/RechargedIdeas/assetfabric (**private**, branch `main`)
**License:** proprietary, All Rights Reserved (ADR-0001)
**Current Fabric milestone:** **F7 — Packaging: Desktop / Android / Web PWA launch candidates, ShuttleLine multi, BoltPack** (accepted, `0.7.0+f7`)
**Current game increment:** `launch-candidates`
**Companion track:** **PocketLoom C1–C6 accepted** (`forge accept C1-C6`, debug APK `0.1.0-c6`, package `0.7.1+f7`) — standalone offline Android companion + LoomLink pairing/offload/sync; not yet run on a device
**Stub replacement sprint (2026-11-20):** batch 1 landed in `0.7.4+f7` — **C9 MirrorWeave has no stubs**: desktop video (CPU VP8/VP9 via system ffmpeg), X11 capture, signed WebSocket transport and Studio input are `real`; Android MediaProjection/H.264, AccessibilityService input and Camera2 focus are compiled into the APK as **`real_unverified_on_device`** (never run on a phone). Batch 2 landed in `0.7.5+f7` — **C10 video capture** (desktop ffmpeg keyframe ingest real; phone Camera2+MediaRecorder recorder `real_unverified_on_device`), **C11 dense depth** real (DepthAnything V2 Small, Apache-2.0, onnxruntime CPU; weights via `forge models fetch` with SHA-256, never committed), **GIRT ONNX** desktop export + parity tooling (`forge girt`), model licence gate `forge models audit`. Batch 2b landed in `0.7.6+f7` — **ARCore** session + depth: desktop pose coverage and DEPTH16 ingest (+ DepthAnything aligned to ARCore anchors) are real; the ARCore SDK capture (`ArCoreCapture`) is compiled into the APK as `real_unverified_on_device` (ARCore is under Google's terms, not OSS — INFERENCES C-68, confirm before release). Batch 3 landed in `0.7.7+f7` — **C12**: CPU photogrammetry (OpenCV SIFT SfM, sparse, no BA — C-73/C-74; `forge recon photogrammetry`), MeshWeaver (splat density → surface nets → OBJ) and GDGS Godot import (MultiMesh billboards, verified in Godot under Xvfb) are `real`, plus a bounded tiny-scene **CPU SplatForge trainer** (own NumPy isotropic 3DGS, `forge recon train --stage splat-cpu` — C-77); **full-scale SplatForge training stays the only stub** (needs a GPU — C-75). Register: 25 real · 8 real_unverified_on_device · 1 stub · 3 deferred. Batch 4 landed in `0.7.8+f7` — **VoiceBridge** (Vosk small en-us, Apache-2.0, grammar-constrained + confidence gate; synthetic speech 0.90 accuracy / 0.05 wrong-action, the residue is a hold↔go confusion — C-79), **persona micro-LM** on the spec's Qwen2.5-0.5B backbone (int8 ONNX, CPU, review-gated drafting; LoRA planned; the game keeps cache + bigram — C-80), **Studio** Swatches/Voice/Persona tabs + read-only slash commands. PocketLoom ONNX rung stays a stub (C-82). **Quality-gap phase (TODO.md §Current sprint, P1–P10):** Q1 landed in `0.7.9+f7` — CI pytest split into 3 parallel shards that partition the suite (`--ci-group`), apt/uv caches, stale C10–C12 descriptions fixed. Q2 landed in `0.7.10+f7` — **G-A11Y-01 full**: in-game Settings screen (Escape / F10 / pad Start) rebinds every action on keyboard and gamepad, live colour-blind palette remap generated from PatternVault with a ΔE gate, settings persisted in the save profile. Q3 landed in `0.7.11+f7` — **swap advisor < 50 ms on the reference box** (p95 37.8–39.4 ms pinned to 2 physical cores, gated in `forge accept F3`; GitHub runners ≈ 63–66 ms, so partial), pure GDScript data-layout work, outcomes/balance unchanged.

**Companion interfaces (C9–C12):** accepted (`forge accept C9-C12`); after the stub-replacement sprint the register is 25 real · 8 `real_unverified_on_device` · 1 stub (full-scale SplatForge GPU training) · 3 deferred (`content/companions/c9_c12.yaml`). Nothing ran on a phone or a GPU.
**Fleet track:** **LoomCluster C7 + GroundWeave C8 accepted** (`forge accept C7-C8`, package `0.7.2+f7`) — equal-node scheduler proven on **loopback processes** (not a LAN), GPU→CPU ladder with the CPU path proven on 2 pinned cores; no real GPU backend exists yet
**Next:** **resumed 2026-11-26** (Producer t61u "Properly proceed with all"). Quality gap (a) slice length landed in `0.7.12+f7`; (b) economy tables + (c) per-pair balance landed in `0.7.13+f7` (Q5); continue at [§Resume point](#resume-point-paused-2026-11-20) with (d)–(f) (Q6 WIP on `feat/q6-cluster-web`) and P7 world fights, then F8 (confirmed by the Producer, t59u) and F9 (LiveOps readiness only).
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
| Acceptance | `forge accept C1-C6` (PocketLoom) `forge accept C7-C8` and `forge accept C9-C12` (recorded `results/C*.json`); `forge accept F0..F7` recorded in `docs/acceptance-tests/results/` (F3–F6 add `perf` blocks); `FORGE_ACCEPT_FAST=1` runs the 2-selection F6 subset (pytest/CI) |
| CI | GitHub Actions (push to `main` / `feat/**`, PRs): job `test` = pytest + determinism gate + Godot 4.3 headless increments; job `pocketloom` (parallel) = `forge accept C1-C6` full (JDK 17 + Gradle cache + runner Android SDK) then `forge accept C7-C8` (Godot cached), then `forge accept C9-C12` |
| GIRT / CascadeHub | real, CPU/GDScript backends (`autoload/girt.gd`, `autoload/cascade_hub.gd`); ONNX Runtime GDExtension not built |
| Substrate (F4) | **real**: sandbox tiers bwrap + process (Firecracker/gVisor detected, no launcher — `/dev/kvm` not accessible), live channel (atomic hot reload, 2PC, probe, rollback), Tier-2 snapshots + WAL, parallel statecharts + soft-lock analysis, Guardian (crash/hang restart + resume + quarantine). See `docs/SUBSTRATE.md` |
| Balance (F5) | **real**: `forge balance run` (12 character-select matchups × 200 seeds = 2400 headless boss fights, sharded over CPU cores, CRN, Wilson CIs) — G-BAL-01 pass, gated per choice **and per leader × pet cell** since F6 (pet↔character affinity, INFERENCE F6-1/F6-2; noise-aware CI check since 0.7.13); **hold-out** `forge balance holdout` (1000 unseen seeds/cell, seed_base 20 000, ≤ 3.5 pp — 2.71 pp in 0.7.13, full `forge accept F5`, C-94); `forge balance tune` / `tune-affinity` (Optuna TPE, CPU, optional extra `tune`) |
| Soft-lock (F5) | **real**: static (statecharts + encounter reachability incl. boss room) + runtime stall/timeout detector; mis-tuned probe proves it fires |
| Save (F5/F6) | **real**: Player State v4 (profile / roster / world incl. farm, checkpoint, quest counters, buffs, gear), migrations v1→v2→v3→v4, canonical JSON + sha256, atomic write + `.bak` recovery; GDScript ↔ Python parity. Cross-device round-trip **G-SAVE-01 proven at F7** (desktop → Android content → Web/IndexedDB → desktop, checksum identical every hop); transfer is manual (`--import-b64`), no cloud sync |
| Packaging (F7) | **real, unsigned/debug**: `forge build --target desktop-linux|desktop-windows|android|web|all` → `dist/` (gitignored). Hermetic Godot home + sha256-pinned 4.3 templates; staged keep-import ships Fabric output byte-for-byte; per-target verify; PWAPipeline (G-WEB-01 9.3 MB gzip / 45 MB, offline SW, COOP/COEP); ShuttleLine contract checked against every PCK/APK; BoltPack SBOM + license audit + `.fabricbolt`. Sizes + SHA-256: docs/acceptance-tests/F7.md. Local-only (CI runs the static F7 subset). See docs/packaging.md |
| PocketLoom (C1–C6) | **real, debug APK** (`companions/pocketloom/`, ≈ 0.89 MB): FabricCore (pure Kotlin/JVM: JobExecutor + Dispatcher, content-addressed AssetStore with version vectors, durable OffloadQueue, Telemetry, ModelCache LRU, LocalForge CPU caves/sprites with gates + retry — ONNX rung is a labelled stub), Android UI (Generate · Library · Capture · Link · Telemetry; string resources only; lint 0 errors), capture via camera intent / import → queued `recon.capture`, LoomLink pairing (one-time code, `loomlink://` QR URI, Tailscale address; HMAC proofs, caps ∩, signed requests, 300 s code TTL) with `forge link serve` on the desktop, offload drain + version-vector sync (conflicts keep both). Proven by JUnit + aapt/apksigner/lint + the same FabricCore code (jar) against the Python server. **Never run on a phone** (no device / KVM). See docs/acceptance-tests/C1-C6.md |
| LoomCluster (C7) | **real, loopback-proven** (`forge/loomcluster.py`, `forge cluster node|submit|status|gen|demo`): equal nodes, adverts + gossip, allocation-capped slots, work stealing, origin leases (owner moves with a steal), retry (3), journal recovery + result redelivery, device placement, `forge link serve --cluster` bridge for PocketLoom offloads. **Unauthenticated HTTP on loopback; never run across machines** |
| GroundWeave (C8) | **real ladder, CPU paths only** (`content/groundweave/ladder.yaml`, `forge/groundweave.py`, `forge groundweave check|show|verify`): every generator kind declared and enforced by `run_brief`; CPU rungs proven on 2 pinned cores, GPU hidden, byte-identical to unpinned / simulated-GPU runs; every GPU rung is `planned` (no ONNX/ROCm/DirectML/Vulkan backend built); `recon.splat` is `gpu_required` + routed |
| Studio GUI | **real, minimal** (`studio/assetfabric_studio`, PySide6, offscreen-tested): Status, Mirror (phone frames), Console (remote phone input + read-only `/` commands), Swatches (PatternVault), Voice (VoiceBridge), Persona (micro-LM drafts). No character creator, MCP/ACP host |

## Verify

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git && cd assetfabric
./scripts/bootstrap.sh && source .venv/bin/activate
forge status && pytest -q
forge build && git diff --exit-code games/game-zero/assets/generated
forge accept F6           # needs Godot 4.3 (GODOT_BIN / PATH / godot-bin/); ≈ 30 s on 8 vCPU (12-selection matrix)
forge accept F5           # ≈ 2 min on 8 vCPU (2400-fight balance matrix)
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
- **Packaging (F7)**: unsigned/debug only — no Authenticode, Android release key, AAB, BoltPack signature or store listings. **Windows build never executed** (no Windows host / wine; static PE + PCK checks only). **Android never ran on a device** (no KVM for an emulator; APK content ran on the desktop runtime). Web tested in headless Chrome on localhost only. Exports are not byte-reproducible (GDScript re-tokenised per export). Web ships the threads build only (D-001). G-A11Y-01 is full since 0.7.10 (Settings screen + live palette), proven with injected keyboard/gamepad events and an Xvfb/llvmpipe render — no real gamepad or phone used.
- **Sandbox**: no micro-VM/gVisor launcher (no usable KVM); `process` tier is best-effort (audit hook does not stop native code). Hot reload covers numeric data, `sim.*` params and sprites — not code, tilemaps or audio.
- **Swap advisor** meets < 50 ms on the reference box since 0.7.11 (p95 37.8–39.4 ms on 2 pinned physical cores; hard gate in `forge accept F3`). **Not met on slower CPUs**: GitHub 2-core runners p95 ≈ 63–66 ms, so pytest/CI only gate the 150 ms ceiling + parity + fidelity. GDScript worker threads scale ≈ 1.3× (engine-level, `docs/perf/gdscript-thread-scaling/`); next step is a native step function (GDExtension) with the GDScript path as CPU fallback.
- In-engine "micro-LM" is still the bigram (deterministic, safety-gated); the real Qwen2.5-0.5B micro-LM (0.7.8) is desktop/build-time drafting with human review, no per-character LoRA. GIRT ONNX is desktop export/parity only (C-63).
- Voice: VoiceBridge (Vosk) is real on the desktop/Studio/CLI (synthetic speech only); the running game has no microphone/Vosk binding yet; "hold" is misheard as "go" on synthetic voices (C-79, needs a grammar decision).
- Roster names/numbers are placeholders (D-005).
- **Balance**: per-pair (leader × pet) spread is gated since F6: 3.21 pp on the acceptance seeds (partly in-sample) and 5.25 pp on unseen seeds ≈ the 200-seed noise floor [INFERENCE F6-2]. An out-of-sample per-cell gate needs ~800 seeds/cell.
- **Slice length** (since 0.7.12): gated on a human-pace *estimate* of 17.0–18.5 min across all 12 selections (ADR-0017, INFERENCE C-92); the QA autopilot itself finishes in 7.1–7.35 game-minutes. Real human length, readability of the HUD/quest text, controls feel, music mix and art legibility need a **GUI playtest** (see F6.md).
- Economy / loot / quest / music numbers and names are placeholders (D-005, INFERENCE F6-3).
- Optuna log in `results/F5-tune.json` is a short study (12 × 24 seeds) — noise-dominated; shipped values verified at 200 seeds [INFERENCE F5-12].
- F5 acceptance runs 2400 fights; on a 2-core node expect ≈ 7–9 min.
- **PocketLoom**: debug-signed only; never installed on a phone (camera/picker intents, QR → intent hand-off, on-device timings unverified). ONNX rung is a stub (no runtime bundled). LoomLink has no TLS/PAKE: HMAC gives integrity + replay protection, not confidentiality (use Tailscale); the hello proof allows offline guessing of the 8-char code within its 300 s TTL; desktop `last_ts` not persisted across restarts; deletions not synced (no tombstones); session key not Keystore-wrapped. INFERENCES C-1…C-15.

- **C9–C12**: see `docs/acceptance-tests/C9-C12.md` §Not proven — every Android half (MediaProjection, input, Camera2 focus/video, ARCore capture) never ran on a phone (`real_unverified_on_device`), X11-only capture, no WebRTC, no desktop HW H.264; dense depth is CPU-only (DepthAnything V2 Small); reconstruction is CPU photogrammetry + a tiny-scene CPU splat trainer, full-scale splat training needs a GPU (stub); capture thresholds unvalidated (C-38), overlap unmeasured, ETAs unmeasured, DepthAnything/ARCore licences unverified (C-42); Kotlin classes JVM-tested only, never on a phone.
- **LoomCluster / GroundWeave (C7/C8)**: proven on loopback processes only. Node↔node HTTP has no auth/encryption (don't bind off loopback); PocketLoom is a LoomLink client, not a cluster peer; no real GPU rung exists (all `planned`), runtime demotion proven on a synthetic ladder; reduced balance matrix (not the full 2400 fights) is what was re-timed on 2 cores; origin loss without restart loses results; large artifacts ride in result JSON (INFERENCES C-16…C-31).

## Resume point (paused 2026-11-20)

State at the pause: `main` = `0.7.11+f7` (Q3 landed as **partial**). Resumed 2026-11-26: `0.7.12+f7` = (a); `0.7.13+f7` = (b) + (c) (2026-11-27). All work is pushed; nothing local-only.

**Open branches on origin:**

| Branch | Head | Holds | State |
|---|---|---|---|
| `main` | Q3 + this docs pass | everything accepted through Q3 | CI green |
| `feat/q4-slice` | — | Q4 slice length | **merged into `main` as `0.7.12+f7`** (2026-11-26); safe to delete |
| `feat/q5-economy` | — | Q5 economy model + per-pair hold-out | **merged into `main` as `0.7.13+f7`** (2026-11-27); safe to delete |
| `feat/quality-q1`…`q3`, `feat/stubs-real-b1`…`b4` (incl. `b2b`), `feat/companions-pocketloom`, `feat/companions-c7-c8`, `feat/companions-c9-c12`, `feat/f5-balance`, `feat/f6-slice`, `feat/f7-packaging` | — | fully merged into `main` (ancestors of `main`) | safe to delete on origin when the Producer agrees |
| `wip/f5-companions` | `73e01e1` | early companion WIP (PocketLoom, LoomCluster, GroundWeave drafts) | **not an ancestor of `main` but superseded** — its content was rebuilt, verified and merged via `feat/companions-pocketloom` and `feat/companions-c7-c8`; keep for history or delete |

**Resume order** (one small patch release each, landed on `main` when green — rules in TODO.md §Current sprint):

1. ✅ **(a) Slice length** (P5) — landed `0.7.12+f7`: Ore Hollow, patrol beat, q_smith, Windward Ridge (C-91); `forge accept F6` gates the human-pace estimate (C-92, ADR-0017): 17.03–18.51 min on all 12 selections; bot 7.10–7.35 game-min. A human GUI playtest stays the real proof.
2. ✅ **(b) D-005 economy / loot / quest tables** (P4) — landed `0.7.13+f7`: economy design model (ADR-0018, C-93), `economy_design` gate in Codegen-World, loot MC + XP pacing in `forge accept F6` on all 12 selections. Names/numbers stay Game-Design sign-off.
3. ✅ **(c) Per-pair balance ≤ 3.5 pp on unseen seeds** (P6) — landed `0.7.13+f7`: **2.71 pp** on 1000 fresh seeds/cell (seed_base 20 000, full `forge accept F5`); bounded Optuna study recorded but not applied (noise), 3 affinities recalibrated by paired CRN probe (C-94). **P7 world fights** (wipe-rate / clear-time bands) still open.
4. **(d) LoomCluster node auth** (HMAC + pairing secret like LoomLink, replay refusal) **+ content-addressed blob transfer** (P8).
5. **(e) Web single-thread fallback** (D-001, P9).
6. **(f) Doc nits** (P10) — then regenerate STATUS (`forge report`).
7. **F8** retro/console-style (confirmed by the Producer, t59u), then **F9** LiveOps readiness only.

Q3 follow-up (not scheduled): native forward-sim step (GDExtension, ADR-0003) to meet < 50 ms on slow 2-core runners — needs a C++ toolchain, per-platform builds (Linux, Windows, Android arm64, Web dlink) and a bit-parity gate; see `docs/perf/gdscript-thread-scaling/`.

## Next steps (ordered)

1. **Resume point above** — quality gaps (a)–(f), then F8 + F9 (both confirmed by the Producer, t59u, C-85; F9 is LiveOps *readiness only*).
2. **Remaining hardware-gated items**: first real GPU rung (ROCm ONNX) + full-scale SplatForge on a `rocm` LoomCluster node (the only C9–C12 stub left); two-machine LoomCluster run; Kotlin cluster peer.
3. **PocketLoom on hardware**: `adb install` the debug APK on the Redmi Note 12 Pro 5G (D-002); generate, capture (camera + import), pair via QR with `forge link serve`, drain + sync; record timings.
4. Human GUI playtest of the vertical slice (length vs 15–20 min, HUD/quest readability, controls, music mix) — checklist in docs/acceptance-tests/F6.md; play the F7 builds on real Windows, the Redmi Note 12 Pro 5G (D-002) and a public HTTPS host.
5. Signing + store listings (docs/packaging.md §Signing & stores) — needs Producer keys/certs.
6. F8 retro/console-style is optional per SPEC §13 — confirm scope before building; F9 LiveOps is readiness-only.

## Recent decisions

ADR-0001 license (proprietary) · ADR-0002 Godot 4 Compatibility · ADR-0011 no LLM in tick · ADR-0012 content-addressed store · ADR-0016 one-milestone offset. ADR-0004 GIRT (CPU/GDScript backend for F3). Inferences: `docs/INFERENCES.md` §F1–§F7, §C1–C6, §C7/C8 (C-17…C-31), §C9–C12 (C-32…C-50), stub-replacement batch 1 (C-51…C-59). C9–C12: 25 real · 8 real_unverified_on_device · 1 stub after the stub-replacement sprint (C-51…C-82); quality-gap phase C-83…C-90.

## For the next agent

Read `AGENTS.md` → this file → `TODO.md` → `STATUS.md`. Do not start F(n+1) before `forge accept F(n)` passes.
