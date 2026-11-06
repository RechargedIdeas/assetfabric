# SECURITY.md — Security, privacy & compliance

AssetFabric is a **private, proprietary** repository (see `LICENSE`, ADR-0001). This document is the threat model and security policy, grounded in `docs/design/ASSETFABRIC_SPEC.md` (§2 hard constraints, §6 Substrate, §8 PocketLoom, §12 gap-fill).

## 1. Reporting a vulnerability

- **Do not** open a GitHub issue for security problems, and do not discuss them in PR descriptions.
- Report privately to the repository owner (**@RechargedIdeas**) via GitHub's *Security → Report a vulnerability* (private advisory) on this repo, or directly to the owner.
- Include: affected component/path, reproduction steps, impact, and any proposed fix.
- Target response: acknowledgement within **2 business days**, triage within **5** `[INFERENCE]`.

## 2. Confidentiality of the repository

- All contents are confidential. Do not copy code, specs, or generated assets to public repos, gists, pastebins, or public AI chat shares.
- No public releases, packages, or container images. `pyproject.toml` carries `Private :: Do Not Upload` to block accidental PyPI upload.
- Collaborators are added by the owner only; prefer least privilege (read/triage) for reviewers.

## 3. Secrets

- **Never commit secrets** (API keys, Tailscale auth keys, signing keys, TURN credentials, keystores).
- Use environment variables or GitHub Actions encrypted secrets. `.env*` files are gitignored.
- Signing material for BoltPack (F7) and Android keystores lives outside the repo.
- If a secret is committed: rotate it first, then purge history — rotation is the fix, purge is hygiene.

## 4. Hard runtime constraints with security impact

| # | Constraint | Why |
|---|---|---|
| 2 | No untrusted code without sandbox during authoring | Generators, emulators, user scripts, model-produced code are untrusted |
| 3 | No client-authoritative multiplayer state | Anti-cheat; host/server validates movement, HP, inventory |
| 11 (ADR-0011) | No LLM in combat tick | Prevents prompt-injection-driven gameplay state |

## 5. Threat model by subsystem

| Subsystem | Assets | Threats | Mitigations | Milestone |
|---|---|---|---|---|
| Asset store (`store/`) | generated blobs, manifests | tampering, poisoned assets | SHA-256 content addressing; provenance manifests; gates before promotion (BudgetGate) | F0 (hashing) / F1 (gates) |
| Telemetry (`.fabric/telemetry/`) | play/agent events | privacy leak | local-only JSONL in F0; no network export; PII-free schema | F0 |
| `forge` CLI | local machine | command injection | no remote bind; no shell interpolation of manifest values | F0 |
| REST / MCP / ACP surfaces | Studio + Forge | remote abuse, agent overreach | localhost bind by default; capability tokens; BudgetGate permission engine | F1+ |
| Substrate sandbox | host | escape from untrusted code | Firecracker (untrusted), gVisor (short trusted), Microsandbox; quotas, timeouts, audit (ADR-0007) | F4 |
| ML models | weights, outputs | malicious weights, unsafe LM text | registry with lineage; ONNX only (no pickle loading of untrusted weights) `[INFERENCE]`; content-safety gateway for LM output | F3 |
| PocketLoom ↔ desktop | Studio, files | rogue pairing, ambient authority | pairing handshake (QR/code/Tailscale), capability model, explicit consent, no ambient authority | C5 |
| Multiplayer | game state | cheating, NAT relay abuse | host-authoritative validation; self-hosted TURN with credentials | F6/F7 |
| Supply chain | dependencies, plugins | compromised packages | pinned deps; SBOM + license audit in CI before BoltPack publish; no community mod marketplace in v1 | F7 |

## 6. Privacy & compliance hooks

Hooks are continuous; depth grows with milestones:

- Age gates, AI-content disclosure, moderation hooks (EU AI Act, COPPA awareness).
- Telemetry stays on-device unless the user opts in to export.
- Voice (Vosk) is processed offline; audio is not persisted by default.

## 7. Explicit non-goals (v1)

Modern console NDA CertPacks; community mod marketplace (supply-chain blast radius deferred with the feature); dedicated servers.

## 8. Current state (F0)

Only the store, telemetry and CLI surfaces exist. No network listeners, no sandbox, no models. The F0 surface is low-risk; the table above is the contract for later milestones.
