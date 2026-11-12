# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-12 America/New_York
**Repository:** https://github.com/RechargedIdeas/assetfabric (**private**, branch `main`)
**License:** proprietary, All Rights Reserved (ADR-0001)
**Current Fabric milestone:** **F7 — Packaging: Desktop / Android / Web PWA launch candidates, ShuttleLine multi, BoltPack** (accepted, `0.7.0+f7`)
**Current game increment:** `launch-candidates`
**Next:** the **companion track** — verify + land `wip/f5-companions` (PocketLoom FabricCore Kotlin → C1–C6 standalone offline debug APK, LoomCluster C7, GroundWeave C8 CPU fallbacks; C9–C12 interfaces + labelled stubs) on its own branch; F8 (retro/console-style) is optional — confirm scope with the Producer before building
**Producer direction (2026-11-05):** build the complete project milestone-by-milestone, push `main` after each milestone, no public releases.

Milestone dashboard: [STATUS.md](STATUS.md).

---

## What exists (honest)

| Piece | State |
|---|---|
| `forge` CLI | status, doctor, validate, job, store, build (`--sandbox`, `--target` platform builds), gen, palette, accept, report, sandbox, live (set/sprite/push/watch/serve/status), balance (run/tune), softlock, save (inspect/migrate), templates (status/fetch), shuttle (contract/export) |
| Asset store + orchestrator | real (SQLite, sha256, provenance); in-order worker; no GC / remote workers |
| Generators | **procedural CPU backends**: G1-Sprite (humanoid/beast/pet), G1-Tile (CA caves), DyeWorks (albedo + normal), **Codegen** (roster → game_data.json + ability .tres), **G1-Audio** (chiptune stems + SFX), **policy** (NumPy BC → JSON MLP), **callouts**, **persona_lm** (bigram stand-in), **world** (Codegen-World: economy/loot/quests/music/areas → `data/generated/world.json`). ONNX/NCA/diffusion/real-LM backends not built |
| Gates | palette, dims, seamless, solvability, floor ratio, BudgetGate (time + bytes); world: schema, cross-refs, quest-chart soft-lock, economy solvability, loot tables, music rules |
| PatternVault | 5 palettes + deuteranopia/protanopia variants |
| SwatchStudio | CLI only (`forge palette`, `forge gen --seed`) |
| Godot binding | `fabric_assets.json` registry + `Fabric` autoload (runtime load, no editor import) |
| Game Zero | sandbox (F1), first combat (F2), **party AI (F3)**: compiled BTs + GIRT policy targeting, time-freeze swap with threaded forward-sim ranking, typed intents via CascadeHub, callouts, post-combat dialogue; keyboard play + headless autoplay + demo mode; deterministic sim; **live tune (F4)**: `--scene=live`, live channel, snapshots/WAL replay, statecharts, guardian-supervised `--serve`; **first boss (F5)**: `--scene=boss`, tier-3 Cave Warden (3 HP phases, 2 summoned emberlings, enrage) in a carved G1-Tile boss arena, autoplay rally, save on victory; **vertical slice (F6)**: `--scene=slice` — character + pet select, farm plots (plant/grow/harvest), gather nodes, workbench crafting (salve, tonic, gear), tiered loot, quest log (main + side quest), field ⇄ tunnels ⇄ deep cave → Warden's lair → open-world exit, adaptive music (biome × state stems), checkpoints + save/quit/resume, XP/levels, boss unlock; headless QA autopilot (`--autoplay`) |
| Acceptance | `forge accept F0..F7` recorded in `docs/acceptance-tests/results/` (F3–F6 add `perf` blocks); `FORGE_ACCEPT_FAST=1` runs the 2-selection F6 subset (pytest/CI) |
| CI | GitHub Actions: pytest + determinism gate + Godot 4.3 headless increments |
| GIRT / CascadeHub | real, CPU/GDScript backends (`autoload/girt.gd`, `autoload/cascade_hub.gd`); ONNX Runtime GDExtension not built |
| Substrate (F4) | **real**: sandbox tiers bwrap + process (Firecracker/gVisor detected, no launcher — `/dev/kvm` not accessible), live channel (atomic hot reload, 2PC, probe, rollback), Tier-2 snapshots + WAL, parallel statecharts + soft-lock analysis, Guardian (crash/hang restart + resume + quarantine). See `docs/SUBSTRATE.md` |
| Balance (F5) | **real**: `forge balance run` (12 character-select matchups × 200 seeds = 2400 headless boss fights, sharded over CPU cores, CRN, Wilson CIs) — G-BAL-01 pass, gated per choice **and per leader × pet cell** since F6 (pet↔character affinity, INFERENCE F6-1/F6-2); `forge balance tune` (Optuna TPE, CPU, optional extra `tune`) |
| Soft-lock (F5) | **real**: static (statecharts + encounter reachability incl. boss room) + runtime stall/timeout detector; mis-tuned probe proves it fires |
| Save (F5/F6) | **real**: Player State v4 (profile / roster / world incl. farm, checkpoint, quest counters, buffs, gear), migrations v1→v2→v3→v4, canonical JSON + sha256, atomic write + `.bak` recovery; GDScript ↔ Python parity. Cross-device round-trip **G-SAVE-01 proven at F7** (desktop → Android content → Web/IndexedDB → desktop, checksum identical every hop); transfer is manual (`--import-b64`), no cloud sync |
| Packaging (F7) | **real, unsigned/debug**: `forge build --target desktop-linux|desktop-windows|android|web|all` → `dist/` (gitignored). Hermetic Godot home + sha256-pinned 4.3 templates; staged keep-import ships Fabric output byte-for-byte; per-target verify; PWAPipeline (G-WEB-01 9.3 MB gzip / 45 MB, offline SW, COOP/COEP); ShuttleLine contract checked against every PCK/APK; BoltPack SBOM + license audit + `.fabricbolt`. Sizes + SHA-256: docs/acceptance-tests/F7.md. Local-only (CI runs the static F7 subset). See docs/packaging.md |
| Studio GUI, PocketLoom, LoomCluster | not started on `main` (placeholders). Unverified PocketLoom FabricCore / LoomCluster / GroundWeave drafts live on branch `wip/f5-companions` |

## Verify

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git && cd assetfabric
./scripts/bootstrap.sh && source .venv/bin/activate
forge status && pytest -q
forge build && git diff --exit-code games/game-zero/assets/generated
forge accept F6           # needs Godot 4.3 (GODOT_BIN / PATH / godot-bin/); ≈ 30 s on 8 vCPU (12-selection matrix)
forge accept F5           # ≈ 2 min on 8 vCPU (2400-fight balance matrix)
forge templates fetch && forge accept F7   # platform builds + G-WEB-01/G-SAVE-01/G-NET-01 (≈ 1.7–2.5 min; JDK 17, Android SDK, Chrome)
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

## Next steps (ordered)

1. **Companion track** (next run): branch from `main`, review + verify `wip/f5-companions` (PocketLoom FabricCore Kotlin, LoomCluster C7, GroundWeave C8), finish PocketLoom C1–C6 as a standalone offline debug APK, C9–C12 interfaces + clearly labelled stubs; land separately with its own acceptance.
2. Human GUI playtest of the vertical slice (length vs 15–20 min, HUD/quest readability, controls, music mix) — checklist in docs/acceptance-tests/F6.md; play the F7 builds on real Windows, the Redmi Note 12 Pro 5G (D-002) and a public HTTPS host.
3. Signing + store listings (docs/packaging.md §Signing & stores) — needs Producer keys/certs.
4. F8 retro/console-style is optional per SPEC §13 — confirm scope before building; F9 LiveOps is readiness-only.
5. Perf debt: swap advisor < 50 ms (native step function).

## Recent decisions

ADR-0001 license (proprietary) · ADR-0002 Godot 4 Compatibility · ADR-0011 no LLM in tick · ADR-0012 content-addressed store · ADR-0016 one-milestone offset. ADR-0004 GIRT (CPU/GDScript backend for F3). Inferences: `docs/INFERENCES.md` §F1–§F7.

## For the next agent

Read `AGENTS.md` → this file → `TODO.md` → `STATUS.md`. Do not start F(n+1) before `forge accept F(n)` passes.
