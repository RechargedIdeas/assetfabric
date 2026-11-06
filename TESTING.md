# TESTING.md — QA strategy, acceptance & CI gates

Every Fabric milestone is proven by an **executable acceptance test** and a playable Game Zero increment (ADR-0016). Source: `docs/design/ASSETFABRIC_SPEC.md` §12–14 and `docs/design/GAME_SPEC.md` §6.

## 1. Test pyramid

| Layer | Scope | Location | Status |
|---|---|---|---|
| Unit | schemas, pure functions | `tests/` | F0 ✅ |
| Component | store, orchestrator, CLI | `tests/` | F0 ✅ |
| Integration | Forge → Godot import, generators → store | `tests/integration/` | F1+ |
| Headless game | Godot `--headless` scripted runs | `scripts/smoke_godot.sh`, `games/game-zero/tests/` | F0 boot ✅ |
| Acceptance | milestone gates | `docs/acceptance-tests/F*.md` | F0 ✅ |
| Perf / fidelity | GroundWeave 2-core budgets, retro authenticity (V1) | later | F1+ |
| Hybrid QA | AI agent playtests + human playtesters | later | F5+ |

## 2. Running tests

```bash
source .venv/bin/activate
pytest -q                         # unit + component
forge validate manifest           # forge.yaml against schema
forge status                      # exit 0 == healthy
forge doctor                      # env checks (godot binary advisory)
./scripts/smoke_godot.sh          # structure check + headless boot if Godot present
REQUIRE_GODOT=1 ./scripts/smoke_godot.sh   # fail if Godot is missing
```

## 3. F0 acceptance matrix

| ID | Criterion | Proof |
|---|---|---|
| F0-DOC | Doc suite (SPEC §11) present | files exist (`tests/test_status.py`) |
| F0-MAN | `forge.yaml` validates | `forge validate manifest`, `tests/test_manifest.py` |
| F0-TEL | Telemetry schema validates events | `tests/test_telemetry.py` |
| F0-CLI | `forge status` healthy | CLI exit 0 |
| F0-STO | Asset store put/get round-trip | `tests/test_store_orchestrator.py` |
| F0-ORC | Orchestrator enqueue/list | `tests/test_store_orchestrator.py` |
| F0-GOD | Godot project well-formed, Compatibility renderer, boots headless | `tests/test_godot_project.py` + smoke |
| F0-OFF | One-milestone offset documented; F1 blocked | AGENTS.md / BUILD_ORDER.md |

Checklist form: [`docs/acceptance-tests/F0.md`](docs/acceptance-tests/F0.md).

## 4. CI gates

Workflow: `.github/workflows/f0-ci.yml` (Ubuntu, `uv`). On every push to `main` and every PR:

1. Install `.[dev]` into a venv.
2. `forge status` (must exit 0).
3. `pytest -q`.
4. `scripts/smoke_godot.sh` in structure-only mode (no Godot binary on hosted runners in F0).

Planned (not yet implemented): Godot headless boot in CI, Windows runner for DirectML, scope guard enforcing the one-milestone offset, SBOM/license audit (F7). `[INFERENCE: workflow shape]`

## 5. Performance & fidelity contracts

- **Weakest acceptance node:** 2 CPU cores, no GPU. Every acceptance test must pass there.
- Generator runtime budgets (SPEC §5.1): authoring 50–500 ms; runtime <100 ms where claimed.
- Optimal swap forward-sim <50 ms; mobile upscale <5 ms (target).
- Web PWA <45 MB compressed.

## 6. Game acceptance (later milestones)

See `docs/design/GAME_SPEC.md` §6: vertical slice (F6), system acceptance (G-AI, G-NET, G-BAL…), and the milestone ↔ game increment table.

## 7. Rules

- A test must fail before and pass after the change it proves.
- No milestone is accepted on "passes on one machine".
- Flaky tests are bugs: file in `TODO.md` §Bugs; do not mark xfail silently.
