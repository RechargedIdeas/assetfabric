# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-05 ~21:10 America/New_York
**Repository:** https://github.com/RechargedIdeas/assetfabric (**private**, branch `main`)
**License:** proprietary, All Rights Reserved (ADR-0001)
**Current Fabric milestone:** **F1 — Content Pipeline** (accepted)
**Current game increment:** `sandbox-encounter`
**Next:** F2 — Codegen (characters / abilities / stats) + G1-Audio → first full combat (party of 4 + pets + enemies)
**Producer direction (2026-11-05):** build the complete project milestone-by-milestone, push `main` after each milestone, no public releases.

Milestone dashboard: [STATUS.md](STATUS.md).

---

## What exists (honest)

| Piece | State |
|---|---|
| `forge` CLI | status, doctor, validate, job, store, **build, gen, palette, accept, report** |
| Asset store + orchestrator | real (SQLite, sha256, provenance); in-order worker; no GC / remote workers |
| Generators | **procedural CPU backends**: G1-Sprite (humanoid/beast 6-frame sheets), G1-Tile (CA caves), DyeWorks (seamless albedo + normal). ONNX/NCA/diffusion backends not built |
| Gates | palette, dims, seamless, solvability, floor ratio, BudgetGate (time + bytes) |
| PatternVault | 5 palettes + deuteranopia/protanopia variants |
| SwatchStudio | CLI only (`forge palette`, `forge gen --seed`) |
| Godot binding | `fabric_assets.json` registry + `Fabric` autoload (runtime load, no editor import) |
| Game Zero | sandbox: hero vs. Emberling in a generated cave; keyboard play + headless autoplay; deterministic sim |
| Acceptance | `forge accept F0`, `forge accept F1` recorded in `docs/acceptance-tests/results/` |
| CI | GitHub Actions: pytest + determinism gate + Godot 4.3 headless increments |
| Studio GUI, PocketLoom, LoomCluster, GIRT, Substrate | not started (placeholders) |

## Verify

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git && cd assetfabric
./scripts/bootstrap.sh && source .venv/bin/activate
forge status && pytest -q
forge build && git diff --exit-code games/game-zero/assets/generated
forge accept F1           # needs Godot 4.3 (GODOT_BIN / PATH / godot-bin/)
godot --path games/game-zero
```

## Known issues / limits

- Generated art is placeholder-grade procedural pixel art (by design for F1; quality bar rises with ONNX backends).
- `godot-bin/` (Godot 4.3 Linux) is gitignored; CI downloads it. See `docs/setup/README.md`.
- Godot editor import is bypassed (`.gdignore` on `assets/generated/`); export packaging must include those files as non-resources (F7 task).
- Enemy AI is rule-based chase/attack; BT + ONNX policies arrive with F3.

## Next steps (ordered)

1. F2: codegen — character/ability/stat YAML → GDScript-consumable `.json`/`.tres`; 4 base fighters + 3 starter pets + enemy tiers; G1-Audio chiptune stems (WAV, CPU synth).
2. Game F2 increment: party of 4 + pets vs. enemy group, followers act, headless victory.
3. Companion track in parallel: PocketLoom FabricCore (Kotlin) + LoomCluster/GroundWeave CPU scheduler.

## Recent decisions

ADR-0001 license (proprietary) · ADR-0002 Godot 4 Compatibility · ADR-0011 no LLM in tick · ADR-0012 content-addressed store · ADR-0016 one-milestone offset. F1 inferences: `docs/INFERENCES.md` §F1.

## For the next agent

Read `AGENTS.md` → this file → `TODO.md` → `STATUS.md`. Do not start F(n+1) before `forge accept F(n)` passes.
