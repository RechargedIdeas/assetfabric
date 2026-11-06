# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-05 ~21:20 America/New_York
**Repository:** https://github.com/RechargedIdeas/assetfabric (**private**, branch `main`)
**License:** proprietary, All Rights Reserved (ADR-0001)
**Current Fabric milestone:** **F2 — Codegen + G1-Audio** (accepted)
**Current game increment:** `first-combat`
**Next:** F3 — GIRT, CascadeHub, micro-LM path + callout cache → party AI, time-freeze swap with ranked recommendations, dialogue
**Producer direction (2026-11-05):** build the complete project milestone-by-milestone, push `main` after each milestone, no public releases.

Milestone dashboard: [STATUS.md](STATUS.md).

---

## What exists (honest)

| Piece | State |
|---|---|
| `forge` CLI | status, doctor, validate, job, store, **build, gen, palette, accept, report** |
| Asset store + orchestrator | real (SQLite, sha256, provenance); in-order worker; no GC / remote workers |
| Generators | **procedural CPU backends**: G1-Sprite (humanoid/beast/pet), G1-Tile (CA caves), DyeWorks (albedo + normal), **Codegen** (roster → game_data.json + ability .tres), **G1-Audio** (chiptune stems + SFX). ONNX/NCA/diffusion backends not built |
| Gates | palette, dims, seamless, solvability, floor ratio, BudgetGate (time + bytes) |
| PatternVault | 5 palettes + deuteranopia/protanopia variants |
| SwatchStudio | CLI only (`forge palette`, `forge gen --seed`) |
| Godot binding | `fabric_assets.json` registry + `Fabric` autoload (runtime load, no editor import) |
| Game Zero | sandbox (F1) + first combat (F2): 4 fighters + 3 pets vs. 7 enemies; abilities from codegen `.tres`; music stem; keyboard play + headless autoplay; deterministic sim |
| Acceptance | `forge accept F0..F2` recorded in `docs/acceptance-tests/results/` |
| CI | GitHub Actions: pytest + determinism gate + Godot 4.3 headless increments |
| Studio GUI, PocketLoom, LoomCluster, GIRT, Substrate | not started (placeholders) |

## Verify

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git && cd assetfabric
./scripts/bootstrap.sh && source .venv/bin/activate
forge status && pytest -q
forge build && git diff --exit-code games/game-zero/assets/generated
forge accept F2           # needs Godot 4.3 (GODOT_BIN / PATH / godot-bin/)
godot --path games/game-zero
```

## Known issues / limits

- Generated art is placeholder-grade procedural pixel art (by design for F1; quality bar rises with ONNX backends).
- `godot-bin/` (Godot 4.3 Linux) is gitignored; CI downloads it. See `docs/setup/README.md`.
- Godot editor import is bypassed (`.gdignore` on `assets/generated/`); export packaging must include those files as non-resources (F7 task).
- Party/enemy AI is rule-based (F2); BT + ONNX policies + time-freeze swap arrive with F3.
- Roster names/numbers are placeholders (D-005).

## Next steps (ordered)

1. F3 Fabric: GIRT (inference runtime facade with latency budgets + CPU path), CascadeHub (typed message bus), behaviour trees + small ONNX-compatible policy evaluated in pure GDScript, callout cache pre-generated offline (no LM in tick), dialogue path.
2. F3 Game: party AI via BTs, time-freeze swap overlay with forward-sim ranked recommendations (<50 ms), callouts.
3. Companion track: PocketLoom FabricCore (Kotlin), LoomCluster/GroundWeave CPU scheduler.

## Recent decisions

ADR-0001 license (proprietary) · ADR-0002 Godot 4 Compatibility · ADR-0011 no LLM in tick · ADR-0012 content-addressed store · ADR-0016 one-milestone offset. F1 inferences: `docs/INFERENCES.md` §F1.

## For the next agent

Read `AGENTS.md` → this file → `TODO.md` → `STATUS.md`. Do not start F(n+1) before `forge accept F(n)` passes.
