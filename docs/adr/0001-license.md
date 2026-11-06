# ADR-0001 — License: proprietary, All Rights Reserved

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Producer (Recharged Ideas) |

## Context

F0 was built local-only with `LicenseRef-TBD`, and public publication was blocked on this ADR. The Producer then requested a properly set-up **private** GitHub repository. The design chat never chose a license; AssetFabric is intended as an internal production fabric whose first product (Game Zero) is a commercial game.

## Decision

AssetFabric is **proprietary — Copyright © 2026 Recharged Ideas, All Rights Reserved.** The root `LICENSE` states this; `pyproject.toml` declares `LicenseRef-Proprietary` and the `Private :: Do Not Upload` classifier. The repository is hosted privately at `github.com/RechargedIdeas/assetfabric`.

## Consequences

- No public releases, no open-source publication, no PyPI upload.
- Third-party dependencies keep their own licenses (`THIRD_PARTY_NOTICES.md`); copyleft components (e.g. PySide6/LGPL) must be dynamically linked and reviewed before any distribution.
- Any future open-sourcing of a sub-component (e.g. a Godot plugin) requires a new ADR superseding this one for that component.
- Shipping builds (F7 BoltPack) still require SBOM + license audit.

## Alternatives considered

- **MIT / Apache-2.0:** rejected — would permit redistribution of a private product fabric.
- **Dual license (as Sophonts):** rejected — no community/OSS goal for this product.
- **Leave TBD:** rejected — blocks repo hygiene and contributor clarity.

## Notes

`[INFERENCE]` the choice itself was made by the Producer at repo-creation time, not in the design chat.

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
