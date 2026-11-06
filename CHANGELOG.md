# CHANGELOG.md

All notable changes to AssetFabric. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are PEP 440 with the Fabric milestone as local label (`0.0.0+f0.0`). AssetFabric is proprietary — versions are internal milestones, not public releases.

## [Unreleased]

### Added
- Private GitHub repository `RechargedIdeas/assetfabric` and first push of `main`.
- Root `LICENSE` (proprietary, All Rights Reserved) and `THIRD_PARTY_NOTICES.md`.
- `docs/design/`: imported authoritative specs (ASSETFABRIC_SPEC, GAME_SPEC, ASSETFABRIC_ML_AI_FEATURES, CHAT_SUMMARY_ASSETFABRIC) with index.
- ADRs 0004–0010 and 0012 written out (previously index-only); all ADRs expanded to full Context/Decision/Consequences/Alternatives prose.
- GitHub hygiene: `CODEOWNERS`, issue templates (bug, task, scope change), PR template.

### Changed
- ADR-0001 License: **proposed → accepted** (proprietary).
- `pyproject.toml` license `LicenseRef-TBD` → `LicenseRef-Proprietary`; `Private :: Do Not Upload` classifier.
- README, SECURITY, CONTRIBUTING, TESTING, HANDOVER, TODO, GLOSSARY, setup and acceptance docs rewritten for a cloned private repo (no box-only paths).

## [0.0.0+f0.0] — 2026-11-05 — F0 Foundation

### Added
- Repository scaffold and documentation suite (SPEC §11).
- Content Forge: `forge` CLI (`status`, `doctor`, `validate`, `job`, `store`).
- `forge.yaml` + JSON Schemas (project manifest, telemetry events).
- Content-addressed asset store + SQLite job orchestrator stubs.
- Telemetry JSONL emitter.
- Empty Godot 4 Game Zero project (Compatibility renderer); headless boot verified with Godot 4.3.
- Studio / PocketLoom / LoomCluster placeholders.
- Pytest suite (12 tests) for schemas, status, store, orchestrator, Godot structure.
- Minimal GitHub Actions CI.
