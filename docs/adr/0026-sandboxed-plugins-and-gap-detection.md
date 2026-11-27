# ADR-0026 — Growth via sandboxed, contract-tested plugins and a live gap report

| Field | Value |
|---|---|
| Status | **accepted** (U1) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (user request t65u: universal 2D/2.5D/3D engine); agent implementation |

## Context

t65u asks for an engine that can "expand itself over time to be capable of anything … it lacks as new things emerge".
Running third-party or generated code inside the content pipeline is a security and determinism risk.

## Decision

1. **Gap detection is computed, not hand-maintained.** `forge universal gaps` diffs `capabilities.yaml` against:
   * the formats advertised by built-in adapters and active plugins;
   * descriptor-only and inference-flagged catalog entries;
   * adapters without a native check;
   * planned GroundWeave rungs.

   Each gap carries a concrete next step, e.g. a `plugin-scaffold` command.
2. **Plugins** are directories with `plugin.yaml` (id, semver, API major, kind `adapter`, entrypoint, tier, dims,
   formats, permissions). In U1 the permissions are fixed: no network, no subprocess, filesystem = Pack only.
3. **Verification has three independent layers:**
   * manifest rules (plugin tiers limited to `interchange_pack`/`descriptor_only`);
   * a static AST policy: import allow-list; no `eval/exec/compile/open/getattr/__import__`; no dunder access; no
     direct file writes; no binary files; size limits;
   * a contract suite executed **inside forge.sandbox** (bwrap: no network, read-only root; process tier: audit hooks).
     The class must match the manifest; every declared dimension must export twice byte-identically; `verify()` must
     pass; the manifest must be honest; importers must produce valid, deterministic IR.
4. **Registration** re-verifies, refuses built-in ids and non-increasing versions, stores a tree hash, and keeps
   previous versions for rollback.
5. **Hot-load** installs **sandboxed proxies**, so plugin code never runs in the host process. A changed tree hash
   means the plugin is refused.

## Consequences

* New formats ship without touching core code. The X3D example closes a real gap in U1.
* Hostile code is stopped at more than one layer. The three fixtures (network exfiltration, hidden state, sandbox
  escape) are rejected in tests and acceptance.
* Plugins cannot be `native_verified` (no subprocess). Native tool checks stay in reviewed core code.
* "Processor" plugins (LOD, UV unwrap, retargeting) are a reported gap. They need a second plugin kind in a later
  milestone.
