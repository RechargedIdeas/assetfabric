# TESTING.md — QA pyramid & acceptance

## Pyramid (target)

1. **Unit** — schemas, pure functions (`tests/`).  
2. **Component** — store, orchestrator, CLI.  
3. **Integration** — Forge → Godot import (F1+).  
4. **Acceptance** — milestone gates (`docs/acceptance-tests/`).  
5. **Perf / fidelity** — GroundWeave 2-core budgets; retro authenticity (later).

## F0 acceptance (executable)

```bash
source .venv/bin/activate
forge validate manifest
forge status          # exit 0
forge doctor          # exit 0 (godot_binary advisory)
pytest -q
./scripts/smoke_godot.sh
```

| ID | Criterion | Proof |
|---|---|---|
| F0-DOC | Doc suite present | files exist |
| F0-MAN | Manifest validates | `forge validate` |
| F0-TEL | Telemetry schema validates events | unit tests |
| F0-CLI | `forge status` healthy | CLI exit 0 |
| F0-STO | Asset store put/get | unit tests |
| F0-ORC | Orchestrator enqueue | unit tests |
| F0-GOD | Godot project well-formed Compatibility | structure tests + smoke script |
| F0-OFF | One-milestone offset documented; F1 blocked | AGENTS / BUILD_ORDER |

## Game acceptance (later)

See `GAME_SPEC.md` §6 (G-AI-*, G-NET-*, G-BAL-*, vertical slice).

## CI gates `[INFERENCE: workflow shape]`

F0 ships a minimal GitHub Actions workflow that runs `pytest` + structure smoke. Full multi-OS matrix is post-F0.
