# HANDOVER.md — Current State Snapshot

**Last updated:** 2026-11-05 ~20:45 America/New_York  
**Current milestone:** F0 — Foundation (**implementation complete; awaiting Producer acceptance**)  
**Current game increment:** `env-boots` (empty Godot)  
**Next gate:** Sign off F0 → then F1 Content Pipeline (sandbox encounter)  
**Repo path:** `/workspace/assetfabric`  
**Remote:** none (local `git` only — see README §Publish)

---

## What was just completed (F0 implementation session)

- Full documentation suite from `ASSETFABRIC_SPEC` §11.
- Content Forge core skeleton in Python (`forge/`):
  - `forge.yaml` + JSON Schema validation
  - CLI: `status`, `doctor`, `validate`, `job`, `store`
  - Content-addressed asset store scaffolding
  - SQLite job orchestrator stub
  - Telemetry event schema + JSONL emitter
- Empty **Godot 4.3** project at `games/game-zero/` with **Compatibility** (`gl_compatibility`) renderer.
- **Godot headless smoke RAN successfully** on this box (`godot-bin/godot`, gitignored): printed `Game Zero F0 boot OK — AssetFabric env gate`.
- Studio / PocketLoom / LoomCluster **placeholders only**.
- `pytest`: **12 passed**.
- One-milestone offset + **F1 blocked** language in `AGENTS.md` / `BUILD_ORDER.md`.

### Stub vs real (honest)

| Piece | Real | Stub |
|---|---|---|
| Manifest schema + validation | yes | — |
| `forge status` / `doctor` | yes | — |
| Telemetry schema + JSONL append | yes | SQLite/DuckDB dashboards later |
| Asset store put/get + SQLite index | yes | no GC / replication |
| Job orchestrator enqueue/list | yes | no workers / generators |
| Godot project + headless boot | yes | no gameplay |
| Studio GUI | — | package stub only |
| PocketLoom / LoomCluster | — | README placeholders |
| MCP/ACP/REST | — | not started |
| Generators (G1-*) | — | **F1 — blocked** |

---

## What is in progress

- **F0 acceptance** — stop here for review. **Do not start F1.**

---

## Known issues

- `godot-bin/` is gitignored (~107 MB official 4.3 linux binary). Re-fetch with curl to GitHub releases if missing; `scripts/smoke_godot.sh` falls back to structure-only when absent.
- License TBD (ADR-0001 proposed) — blocks public release.
- No git remote configured.
- Package version is PEP 440 `0.0.0+f0.0` (chat’s `0.F0.x` label kept as milestone string, not pip version).

---

## Next steps (ordered)

1. Producer accepts F0 using commands below.  
2. Only then open F1: G1-Sprite/Tile, DyeWorks procedural, PatternVault, SwatchStudio, sandbox encounter.  
3. Do **not** deeply implement C\* in the next Fabric session unless companion track is explicitly scheduled.

---

## Verify commands

```bash
cd /workspace/assetfabric
source .venv/bin/activate
forge doctor && forge status
pytest -q
./scripts/smoke_godot.sh
```

---

## Recent decisions

- Engine: Godot 4 Compatibility — ADR-0002  
- Languages / Studio — ADR-0003, ADR-0015  
- Name AssetFabric — ADR-0013  
- AMD-first — ADR-0014  
- One-milestone offset — ADR-0016  

---

## For the next agent

Read `AGENTS.md` → this file → `TODO.md`. **F1 backlog is blocked.** Suggested start:

```bash
cd /workspace/assetfabric && source .venv/bin/activate && forge status && pytest -q
```
