# CONTRIBUTING.md

AssetFabric is a **private, proprietary** repository owned by Recharged Ideas (see `LICENSE`). Contributions are by invitation only. Humans and AI agents follow the same rules — read [`AGENTS.md`](AGENTS.md) first.

## 1. Setup

Prerequisites: Python ≥ 3.11, [`uv`](https://docs.astral.sh/uv/), git. Optional: Godot 4.3+ (headless smoke / editor).

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git
cd assetfabric
./scripts/bootstrap.sh          # creates .venv and installs forge in editable mode
source .venv/bin/activate
forge doctor && forge status
pytest -q
./scripts/smoke_godot.sh        # structure smoke; full headless boot if Godot is found
```

Full environment notes: [`docs/setup/README.md`](docs/setup/README.md).

## 2. Workflow

1. Pick a task from [`TODO.md`](TODO.md) in the **current milestone** (see `forge.yaml` → `fabric.milestone`).
2. Branch from `main`: `<type>/<scope>-<short-desc>` (e.g. `feat/forge-palette-gate`).
3. Write the failing acceptance/unit test first, then the change.
4. Update docs in the **same commit** (HANDOVER/TODO when state changes; schemas in `docs/schemas/` and `forge/schemas/` together).
5. Open a PR using the template; CI must be green.
6. `main` is protected by convention: merge via PR, no force-push to `main`.

## 3. Commit messages

```
<type>(<scope>): <short summary>

<what and why>

Acceptance: <test that proves it>
Refs: <ADR-NNNN, milestone>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`.
Scopes: `fabric`, `forge`, `game`, `studio`, `substrate`, `docs`, `cluster`, `pocketloom`.

## 4. PR checklist

- [ ] Task belongs to the current milestone (one-milestone offset, ADR-0016)
- [ ] Acceptance test added/updated; fails before, passes after
- [ ] `pytest` green and `forge status` healthy locally
- [ ] Docs / HANDOVER / TODO / CHANGELOG updated if state changed
- [ ] No hard-coded user strings (use `locales/`) or absolute host paths
- [ ] No Out-of-Scope features (`PLAN.md`)
- [ ] GPU work has a CPU path (GroundWeave) or is declared GPU-required
- [ ] New inferences marked `[INFERENCE]` and registered
- [ ] No secrets, no large binaries (Godot binaries, model weights, store blobs stay out of git)

## 5. Code style

- Python: type hints, `from __future__ import annotations`, small pure functions, `pathlib`; tests in `tests/` with pytest.
- GDScript: Godot 4 style guide (snake_case, typed vars where practical), no gameplay strings in code — use locale keys.
- JSON Schemas: draft 2020-12, versioned `$id`.

## 6. Scope changes and decisions

- Scope changes: `docs/scope-changes/YYYY-MM-DD-<title>.md` + Producer/Factory Lead approval (`AGENTS.md` §3.3).
- Architectural decisions: new ADR in `docs/adr/` + index row in `DECISIONS.md`.

## 7. Roles

| Role | Responsibility | Holder |
|---|---|---|
| Producer | scope, milestone acceptance | Recharged Ideas |
| Factory Lead | architecture, ADR approval | Recharged Ideas `[INFERENCE: until staffed]` |
| Game Design / Eng / ML / QA / TA | per chat staffing plan | TBD |

Code owners: [`.github/CODEOWNERS`](.github/CODEOWNERS).
