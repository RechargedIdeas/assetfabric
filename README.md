# AssetFabric

**Universal content fabric and execution substrate** for producing games and assets end-to-end: generation, validation, packaging, AI runtime, sandboxed execution, reconstruction, clustering, and companion tooling.

**First product / MVP test:** [Game Zero](games/game-zero/) — offline-first 8-bit fighter/farming hybrid on **Godot 4 Compatibility**.

> Prefer authoritative specs (chatgrab) over invention. Extrapolations are marked **`[INFERENCE]`**.
> Rename: Asset Factory → **AssetFabric** (fabric metaphor; avoid third-party AssetFactory collision).

Source design chat: https://chat.deepseek.com/share/g90tn4mss3265u0xm3

## Current milestone

**F0 — Foundation** (in progress / acceptance this session)

| Gate | Status |
|---|---|
| Doc suite (§11) | shipped |
| `forge` CLI + `forge status` healthy | shipped |
| Manifest + telemetry schemas | shipped |
| Asset store + orchestrator stubs | shipped |
| Empty Godot project (Compatibility) | shipped |
| F1 blocked until F0 game/env gate | enforced in AGENTS / BUILD_ORDER |

## Quick start

```bash
cd /workspace/assetfabric   # or your clone
./scripts/bootstrap.sh
source .venv/bin/activate
forge doctor
forge status
pytest
./scripts/smoke_godot.sh
```

Optional Godot headless (if binary available):

```bash
godot --path games/game-zero --headless --quit-after 1
```

## What AssetFabric is

- Unified generation toolkit (GUI + CLI + REST + MCP + ACP + in-Studio terminal)
- Godot 4 production toolkit (plugins, bridges, import contracts)
- ML model mesh + metamodels + training/telemetry
- Universal emulation / console-style layer + micro-VM sandbox + hot reload / snapshots
- Android Kotlin companion (**PocketLoom**): standalone offline + optional desktop pairing
- Heterogeneous compute clustering (**LoomCluster**) with CPU software fallbacks (**GroundWeave**)

## What it is not (v1 hard deferrals)

Quantum *hardware* backend (simulation OK), fantasy consoles (PICO-8/TIC-80), modern console CertPacks, community mod marketplace, P2P mesh beyond 2 players, dedicated servers, full M1-Architect as a ship gate.

## Doc map

| Doc | Role |
|---|---|
| [AGENTS.md](AGENTS.md) | Agent rules, one-milestone offset, scope |
| [BUILD_ORDER.md](BUILD_ORDER.md) | F0–F7 + C1–C12 sequence |
| [HANDOVER.md](HANDOVER.md) | Current state for next agent |
| [PLAN.md](PLAN.md) | Vision, DoD, milestones, out-of-scope |
| [TODO.md](TODO.md) | Sprint tasks / blockers |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Systems map |
| [DECISIONS.md](DECISIONS.md) | ADR index |
| [TESTING.md](TESTING.md) | QA / acceptance |
| [SECURITY.md](SECURITY.md) | Threat model sketch |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup / PR checklist |
| [GLOSSARY.md](GLOSSARY.md) | Terms |
| [CHANGELOG.md](CHANGELOG.md) | Versions |
| [docs/tool-catalog.md](docs/tool-catalog.md) | Fabric tools |
| [docs/hardware-fleet.md](docs/hardware-fleet.md) | AMD-first fleet |

Authoritative condensed specs (outside repo, chatgrab): `ASSETFABRIC_SPEC.md`, `GAME_SPEC.md`, `ASSETFABRIC_ML_AI_FEATURES.md`.

## Governing principle

A Fabric milestone is **not complete** until a **game increment that depends on it ships, is playable, and passes its acceptance test.**

## Publish

This repo is local-first (`git init` on the shared box). To publish:

```bash
# after creating an empty GitHub repo you own:
git remote add origin git@github.com:<org>/assetfabric.git
git push -u origin main
```

Do not create public releases until license ADR-0001 is decided.
