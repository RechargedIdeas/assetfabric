# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-19 America/New_York
**Repository:** https://github.com/RechargedIdeas/assetfabric (**private**, branch `main`)
**License:** proprietary, All Rights Reserved (ADR-0001)
**Current Fabric milestone:** **F7 — Packaging: Desktop / Android / Web PWA launch candidates, ShuttleLine multi, BoltPack** (accepted, `0.7.0+f7`)
**Current game increment:** `launch-candidates`
**Companion track:** **PocketLoom C1–C6 accepted** (`forge accept C1-C6`, debug APK `0.1.0-c6`, package `0.7.1+f7`) — standalone offline Android companion + LoomLink pairing/offload/sync; not yet run on a device
**Companion interfaces (C9–C12):** **accepted as typed interfaces + clearly labelled stubs** (`forge accept C9-C12`, package `0.7.3+f7`) — MirrorWeave, LensForge, metric depth, SplatForge path. 16 capabilities are real CPU paths, 14 are stubs that refuse, 3 deferred (`content/companions/c9_c12.yaml`). No live stream, ARCore, dense depth or reconstruction exists; nothing ran on a phone or a GPU
**Fleet track:** **LoomCluster C7 + GroundWeave C8 accepted** (`forge accept C7-C8`, package `0.7.2+f7`) — equal-node scheduler proven on **loopback processes** (not a LAN), GPU→CPU ladder with the CPU path proven on 2 pinned cores; no real GPU backend exists yet
**Next:** nothing in the spec's companion table remains (it ends at C12). The next spec items are **F8 (retro/console-style, optional — confirm scope with the Producer before building; scope is *not* assumed)** and **F9 (post — LiveOps readiness only)**. Non-spec follow-ups (TODO.md): replace the C9–C12 stubs one by one, first real GPU rung, LAN/Tailscale cluster run + node auth, Kotlin cluster peer, PocketLoom on hardware
**Producer direction (2026-11-05):** build the complete project milestone-by-milestone, push `main` after each milestone, no public releases.

Milestone dashboard: [STATUS.md](STATUS.md).

---

## What exists (honest)

| Piece | State |
|---|---|
| `forge` CLI | status, doctor, validate, job, store, build (`--sandbox`, `--target` platform builds), gen, palette, accept, report, sandbox, live (set/sprite/push/watch/serve/status), balance (run/tune), softlock, save (inspect/migrate), templates (status/fetch), shuttle (contract/export), link (serve — PocketLoom pairing), cluster, groundweave, mirror, lens, depth, recon (C9–C12; stubs exit 3 with a `[STUB …]` label) |
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
| Balance (F5) | **real**: `forge balance run` (12 character-select matchups × 200 seeds = 2400 headless boss fights, sharded over CPU cores, CRN, Wilson CIs) — G-BAL-01 pass, gated per choice **and per leader × pet cell** since F6 (pet↔character affinity, INFERENCE F6-1/F6-2); `forge balance tune` (Optuna TPE, CPU, optional extra `tune`) |
| Soft-lock (F5) | **real**: static (statecharts + encounter reachability incl. boss room) + runtime stall/timeout detector; mis-tuned probe proves it fires |
| Save (F5/F6) | **real**: Player State v4 (profile / roster / world incl. farm, checkpoint, quest counters, buffs, gear), migrations v1→v2→v3→v4, canonical JSON + sha256, atomic write + `.bak` recovery; GDScript ↔ Python parity. Cross-device round-trip **G-SAVE-01 proven at F7** (desktop → Android content → Web/IndexedDB → desktop, checksum identical every hop); transfer is manual (`--import-b64`), no cloud sync |
| Packaging (F7) | **real, unsigned/debug**: `forge build --target desktop-linux|desktop-windows|android|web|all` → `dist/` (gitignored). Hermetic Godot home + sha256-pinned 4.3 templates; staged keep-import ships Fabric output byte-for-byte; per-target verify; PWAPipeline (G-WEB-01 9.3 MB gzip / 45 MB, offline SW, COOP/COEP); ShuttleLine contract checked against every PCK/APK; BoltPack SBOM + license audit + `.fabricbolt`. Sizes + SHA-256: docs/acceptance-tests/F7.md. Local-only (CI runs the static F7 subset). See docs/packaging.md |
| PocketLoom (C1–C6) | **real, debug APK** (`companions/pocketloom/`, ≈ 0.97 MB): FabricCore (pure Kotlin/JVM: JobExecutor + Dispatcher, content-addressed AssetStore with version vectors, durable OffloadQueue, Telemetry, ModelCache LRU, LocalForge CPU caves/sprites with gates + retry — ONNX rung is a labelled stub), Android UI (Generate · Library · Capture · Link · Telemetry; string resources only; lint 0 errors), capture via camera intent / import → queued `recon.capture`, LoomLink pairing (one-time code, `loomlink://` QR URI, Tailscale address; HMAC proofs, caps ∩, signed requests, 300 s code TTL) with `forge link serve` on the desktop, offload drain + version-vector sync (conflicts keep both). Proven by JUnit + aapt/apksigner/lint + the same FabricCore code (jar) against the Python server. **Never run on a phone** (no device / KVM). See docs/acceptance-tests/C1-C6.md |
| LoomCluster (C7) | **real, loopback-proven** (`forge/loomcluster.py`, `forge cluster node|submit|status|gen|demo`): equal nodes, adverts + gossip, allocation-capped slots, work stealing, origin leases (owner moves with a steal), retry (3), journal recovery + result redelivery, device placement, `forge link serve --cluster` bridge for PocketLoom offloads. **Unauthenticated HTTP on loopback; never run across machines** |
| GroundWeave (C8) | **real ladder, CPU paths only** (`content/groundweave/ladder.yaml`, `forge/groundweave.py`, `forge groundweave check|show|verify`): every generator kind declared and enforced by `run_brief`; CPU rungs proven on 2 pinned cores, GPU hidden, byte-identical to unpinned / simulated-GPU runs; every GPU rung is `planned` (no ONNX/ROCm/DirectML/Vulkan backend built); `recon.splat` is `gpu_required` + routed |
| Studio GUI | not started on `main` (placeholder) |

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
- **Packaging (F7)**: unsigned/debug only — no Authenticode, Android release key, AAB, BoltPack signature or store listings. **Windows build never executed** (no Windows host / wine; static PE + PCK checks only). **Android never ran on a device** (no KVM for an emulator; APK content ran on the desktop runtime). Web tested in headless Chrome on localhost only. Exports are not byte-reproducible (GDScript re-tokenised per export). Web ships the threads build only (D-001). G-A11Y-01 partial: no rebinding UI / palette toggle.
- **Sandbox**: no micro-VM/gVisor launcher (no usable KVM); `process` tier is best-effort (audit hook does not stop native code). Hot reload covers numeric data, `sim.*` params and sprites — not code, tilemaps or audio.
- **Swap advisor misses the < 50 ms target**: ≈ 50–100 ms on the 8-vCPU reference box (threaded); serial ≈ 80 ms. GDScript worker threads scale poorly (shared-Variant refcount contention). Hard ceiling 150 ms is gated; `results/F3.json` → `perf.swap_target_met`. (The F6 slice measured 24–46 ms for its two freezes; not re-measured in the party scene, so the target stays open.) Fix path: native sim core (GDExtension) or a C#/Rust step function — see TODO.
- "Micro-LM" is a bigram stand-in (deterministic, safety-gated), not a neural LM; GIRT has no ONNX backend yet.
- Voice (Vosk) intents not wired; typed commands use the same closed grammar.
- Roster names/numbers are placeholders (D-005).
- **Balance**: per-pair (leader × pet) spread is gated since F6: 3.21 pp on the acceptance seeds (partly in-sample) and 5.25 pp on unseen seeds ≈ the 200-seed noise floor [INFERENCE F6-2]. An out-of-sample per-cell gate needs ~800 seeds/cell.
- **Slice length**: the QA autopilot finishes the slice in ≈ 2.8–3.4 game-minutes vs the GAME_SPEC §6.1 15–20 min human target (soft metric, INFERENCE F6-12). Human length, readability of the HUD/quest text, controls feel, music mix and art legibility need a **GUI playtest** (see F6.md).
- Economy / loot / quest / music numbers and names are placeholders (D-005, INFERENCE F6-3).
- Optuna log in `results/F5-tune.json` is a short study (12 × 24 seeds) — noise-dominated; shipped values verified at 200 seeds [INFERENCE F5-12].
- F5 acceptance runs 2400 fights; on a 2-core node expect ≈ 7–9 min.
- **PocketLoom**: debug-signed only; never installed on a phone (camera/picker intents, QR → intent hand-off, on-device timings unverified). ONNX rung is a stub (no runtime bundled). LoomLink has no TLS/PAKE: HMAC gives integrity + replay protection, not confidentiality (use Tailscale); the hello proof allows offline guessing of the 8-char code within its 300 s TTL; desktop `last_ts` not persisted across restarts; deletions not synced (no tombstones); session key not Keystore-wrapped. INFERENCES C-1…C-15.

- **C9–C12 (interfaces + stubs)**: see `docs/acceptance-tests/C9-C12.md` §Not proven — no live stream/video/input injection, no ARCore or dense depth, no reconstruction; capture thresholds unvalidated (C-38), overlap unmeasured, ETAs unmeasured, DepthAnything/ARCore licences unverified (C-42); Kotlin classes JVM-tested only, never on a phone.
- **LoomCluster / GroundWeave (C7/C8)**: proven on loopback processes only. Node↔node HTTP has no auth/encryption (don't bind off loopback); PocketLoom is a LoomLink client, not a cluster peer; no real GPU rung exists (all `planned`), runtime demotion proven on a synthetic ladder; reduced balance matrix (not the full 2400 fights) is what was re-timed on 2 cores; origin loss without restart loses results; large artifacts ride in result JSON (INFERENCES C-16…C-31).

## Next steps (ordered)

1. **Producer decision needed:** is F8 (retro/console-style) wanted? SPEC §13 marks it optional — **confirm scope first**; F9 is LiveOps *readiness only* and comes after. Do not start either unconfirmed.
2. **C9–C12 stubs → real, in value order** (each is a row in `content/companions/c9_c12.yaml`; replace the stub, flip it to `real`, extend the tests, and the registry check enforces the rest): first real GPU rung (ROCm ONNX) + SplatForge/OpenSplat on a `rocm` LoomCluster node; DepthAnything V2 estimator (verify licence, C-42); MediaProjection screen capture; overlap measurement + validating capture thresholds (C-38/C-40). Then the C7/C8 follow-ups in TODO.md (two-machine run + node auth, Kotlin peer).
3. **PocketLoom on hardware**: `adb install` the debug APK on the Redmi Note 12 Pro 5G (D-002); generate, capture (camera + import), pair via QR with `forge link serve`, drain + sync; record timings.
4. Human GUI playtest of the vertical slice (length vs 15–20 min, HUD/quest readability, controls, music mix) — checklist in docs/acceptance-tests/F6.md; play the F7 builds on real Windows, the Redmi Note 12 Pro 5G (D-002) and a public HTTPS host.
5. Signing + store listings (docs/packaging.md §Signing & stores) — needs Producer keys/certs.
6. F8 retro/console-style is optional per SPEC §13 — confirm scope before building; F9 LiveOps is readiness-only.
7. Perf debt: swap advisor < 50 ms (native step function).

## Recent decisions

ADR-0001 license (proprietary) · ADR-0002 Godot 4 Compatibility · ADR-0011 no LLM in tick · ADR-0012 content-addressed store · ADR-0016 one-milestone offset. ADR-0004 GIRT (CPU/GDScript backend for F3). Inferences: `docs/INFERENCES.md` §F1–§F7, §C1–C6, §C7/C8 (C-17…C-31), §C9–C12 (C-32…C-50). C9–C12 are interfaces + labelled stubs, not features (C-32).

## For the next agent

Read `AGENTS.md` → this file → `TODO.md` → `STATUS.md`. Do not start F(n+1) before `forge accept F(n)` passes.
