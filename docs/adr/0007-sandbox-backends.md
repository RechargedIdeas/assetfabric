# ADR-0007 — Sandbox backends: gVisor (short trusted) + Firecracker (untrusted/long)

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Generators, emulators and user scripts run during authoring; untrusted code must never run unsandboxed (hard constraint #2).

## Decision

Sandbox Orchestrator selects **gVisor** for short trusted jobs, **Firecracker** for long-running/untrusted/stateful sessions, **Microsandbox** for interactive Studio sandboxes. Lifecycle `CREATED → PROVISIONING → RUNNING → SNAPSHOTTING → RESTORING → TERMINATED`.

## Consequences

- Requires KVM for Firecracker; hosts without it must fall back to a documented, weaker **process sandbox** and label it as such `[INFERENCE]`.
- F4 deliverable.

## Implementation note (F4, 2026-11-12)

The reference box has `/dev/kvm` without access and no `runsc`. F4 ships the ladder firecracker → gvisor → **bwrap** (namespaces) → **process** (rlimits + audit hook); the first two are detected and report why they are unavailable. See `docs/SUBSTRATE.md`.

## Alternatives considered

- **Containers only:** rejected for untrusted code.

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
