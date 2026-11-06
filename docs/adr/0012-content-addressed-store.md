# ADR-0012 — Content-addressed asset store with provenance

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Generated assets need dedup, integrity, reproducibility and lineage back to generator, model and brief.

## Decision

Assets are stored by **SHA-256** under `store/objects/<2>/<hash>` with a JSON manifest per asset (`store/manifests/`) and a SQLite index. Manifests record provenance (generator, model id/version, inputs, gates passed).

## Consequences

- Blobs/index are gitignored; only scaffolding is tracked.
- GC/replication are later work.

## Alternatives considered

- **Path-based asset folders:** rejected (no integrity/lineage).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
