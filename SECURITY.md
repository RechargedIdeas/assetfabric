# SECURITY.md — Threat model (F0 sketch)

## Principles (from SPEC)

- Untrusted generation / emulator code runs in **sandbox** (gVisor / Firecracker) — Substrate F4.  
- No ambient PocketLoom authority over desktop without **pairing consent**.  
- Multiplayer: **server/host-authoritative** validation; never trust client HP/inventory.  
- SBOM + license audit in CI before BoltPack publish (F7).  
- Content safety gateway for LM outputs (F3+).  
- Compliance awareness: age gates / disclosure / moderation hooks (EU AI Act, COPPA) — hooks continuous, not F0 depth.

## F0 surface

| Asset | Risk | Mitigation now |
|---|---|---|
| Local `store/` blobs | integrity | SHA-256 content addressing |
| Telemetry JSONL | privacy | local-only; no network ship in F0 |
| CLI | low | no remote bind by default |
| Godot project | low | empty; no untrusted addons |

## Explicit non-goals (v1)

Modern console NDA CertPacks; community mod marketplace (supply-chain blast radius deferred with the feature).
