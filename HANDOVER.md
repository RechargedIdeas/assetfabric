# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-12 America/New_York
**Repository:** https://github.com/RechargedIdeas/assetfabric (**private**, branch `main`)
**License:** proprietary, All Rights Reserved (ADR-0001)
**Current Fabric milestone:** **F4 — Substrate: sandbox, hot reload, snapshots, statecharts, guardian** (accepted)
**Current game increment:** `live-tune`
**Next:** F5 — Monte Carlo balance, soft-lock detection, save migration, first boss
**Producer direction (2026-11-05):** build the complete project milestone-by-milestone, push `main` after each milestone, no public releases.

Milestone dashboard: [STATUS.md](STATUS.md).

---

## What exists (honest)

| Piece | State |
|---|---|
| `forge` CLI | status, doctor, validate, job, store, build (`--sandbox`), gen, palette, accept, report, **sandbox, live (set/sprite/push/watch/serve/status)** |
| Asset store + orchestrator | real (SQLite, sha256, provenance); in-order worker; no GC / remote workers |
| Generators | **procedural CPU backends**: G1-Sprite (humanoid/beast/pet), G1-Tile (CA caves), DyeWorks (albedo + normal), **Codegen** (roster → game_data.json + ability .tres), **G1-Audio** (chiptune stems + SFX), **policy** (NumPy BC → JSON MLP), **callouts**, **persona_lm** (bigram stand-in). ONNX/NCA/diffusion/real-LM backends not built |
| Gates | palette, dims, seamless, solvability, floor ratio, BudgetGate (time + bytes) |
| PatternVault | 5 palettes + deuteranopia/protanopia variants |
| SwatchStudio | CLI only (`forge palette`, `forge gen --seed`) |
| Godot binding | `fabric_assets.json` registry + `Fabric` autoload (runtime load, no editor import) |
| Game Zero | sandbox (F1), first combat (F2), **party AI (F3)**: compiled BTs + GIRT policy targeting, time-freeze swap with threaded forward-sim ranking, typed intents via CascadeHub, callouts, post-combat dialogue; keyboard play + headless autoplay + demo mode; deterministic sim; **live tune (F4)**: `--scene=live`, live channel, snapshots/WAL replay, statecharts, guardian-supervised `--serve` |
| Acceptance | `forge accept F0..F4` recorded in `docs/acceptance-tests/results/` (F3/F4 add `perf` blocks) |
| CI | GitHub Actions: pytest + determinism gate + Godot 4.3 headless increments |
| GIRT / CascadeHub | real, CPU/GDScript backends (`autoload/girt.gd`, `autoload/cascade_hub.gd`); ONNX Runtime GDExtension not built |
| Substrate (F4) | **real**: sandbox tiers bwrap + process (Firecracker/gVisor detected, no launcher — `/dev/kvm` not accessible), live channel (atomic hot reload, 2PC, probe, rollback), Tier-2 snapshots + WAL, parallel statecharts + soft-lock analysis, Guardian (crash/hang restart + resume + quarantine). See `docs/SUBSTRATE.md` |
| Studio GUI, PocketLoom, LoomCluster | not started (placeholders) |

## Verify

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git && cd assetfabric
./scripts/bootstrap.sh && source .venv/bin/activate
forge status && pytest -q
forge build && git diff --exit-code games/game-zero/assets/generated
forge accept F4           # needs Godot 4.3 (GODOT_BIN / PATH / godot-bin/)
godot --path games/game-zero
```

## Known issues / limits

- Generated art is placeholder-grade procedural pixel art (by design for F1; quality bar rises with ONNX backends).
- `godot-bin/` (Godot 4.3 Linux) is gitignored; CI downloads it. See `docs/setup/README.md`.
- Godot editor import is bypassed (`.gdignore` on `assets/generated/`); export packaging must include those files as non-resources (F7 task).
- **Sandbox**: no micro-VM/gVisor launcher (no usable KVM); `process` tier is best-effort (audit hook does not stop native code). Hot reload covers numeric data, `sim.*` params and sprites — not code, tilemaps or audio.
- **Swap advisor misses the < 50 ms target**: ≈ 50–100 ms on the 8-vCPU reference box (threaded); serial ≈ 80 ms. GDScript worker threads scale poorly (shared-Variant refcount contention). Hard ceiling 150 ms is gated; `results/F3.json` → `perf.swap_target_met`. Fix path: native sim core (GDExtension) or a C#/Rust step function — see TODO.
- "Micro-LM" is a bigram stand-in (deterministic, safety-gated), not a neural LM; GIRT has no ONNX backend yet.
- Voice (Vosk) intents not wired; typed commands use the same closed grammar.
- Roster names/numbers are placeholders (D-005).

## Next steps (ordered)

1. F5 Fabric: Monte Carlo balance runner (G-BAL-01: 1k encounters, win-rate deviation < 5 %), Bayesian tuning (Optuna, CPU), soft-lock detection (statechart analysis + sim stall detector), versioned save migration.
2. F5 Game: first tier-3 boss cleared, proven by the balance runner.
3. Companion track: PocketLoom FabricCore (Kotlin) + LoomCluster/GroundWeave CPU scheduler.
4. Perf debt: swap advisor < 50 ms (native step function).

## Recent decisions

ADR-0001 license (proprietary) · ADR-0002 Godot 4 Compatibility · ADR-0011 no LLM in tick · ADR-0012 content-addressed store · ADR-0016 one-milestone offset. ADR-0004 GIRT (CPU/GDScript backend for F3). Inferences: `docs/INFERENCES.md` §F1–§F4.

## For the next agent

Read `AGENTS.md` → this file → `TODO.md` → `STATUS.md`. Do not start F(n+1) before `forge accept F(n)` passes.
