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
| PocketLoom ↔ desktop | Studio, files | rogue pairing, ambient authority, replay, LAN sniffing | **built (C5/C6)**: one-time 8-char code (300 s TTL, rotates after use or 5 bad proofs) proven by HMAC-SHA256 both ways (code never sent), per-device key, capabilities = requested ∩ desktop `--allow` (default offload+sync; `drive_studio`/`mirror` never by default), every request signed (±120 s, monotonic ts), QR only pre-fills — user taps Pair; `paired.json` 0600; phone session excluded from backup. **Gaps:** no TLS/PAKE (payloads readable on raw LAN — use Tailscale; hello proof allows offline code guessing within the TTL), desktop `last_ts` not persisted, no Keystore wrapping (INFERENCES C-7, C-13) | C5 |
| MirrorWeave / drive_studio (LoomLink) | screen/camera frames and video, desktop status, phone input/focus, Studio input | unpaired or unsigned client pushing frames or driving the desktop/phone, oversize/replayed frames, forged keyframes, control abuse | **built (C9, 0.7.4)**: `mirror` / `drive_studio` are opt-in capabilities (not in the default grant); HTTP and WebSocket messages are HMAC-signed with strictly increasing timestamps; ≤ 8 MiB frames, keyframe flag checked against the bitstream; Studio input is an allow-list (keys, normalised pointer, bounded scroll); **phone input/focus can only be queued by the local desktop operator** — remote `/mirror/control` requests for them are refused — and each queued event carries its own MAC that the phone verifies before the AccessibilityService acts (the user must enable that service in Android settings). Gaps: no frame encryption (use Tailscale), no per-client rate limit, Android side never run on a device (INFERENCES C-33…C-35, C-54, C-56) | C9 |
| LoomCluster nodes | jobs, generator output, host CPU | rogue peer submitting/stealing jobs, forged results, replay, oversize results, job flooding, op injection | **built (C7; auth + blobs since 0.7.14)**: every node↔node and client↔node request carries `X-Loom-Ts/Nonce/Sig` = HMAC-SHA256(fleet secret, method‖path‖ts‖nonce‖sha256(body)); nodes answer **401** to unsigned, wrongly keyed, tampered, stale (> ±120 s) or replayed (nonce seen) requests and sign every response (`X-Loom-RSig` over nonce‖status‖sha256(body)), which clients verify — a rogue listener's unsigned answer is refused. The fleet secret is `FORGE_CLUSTER_SECRET` or `.fabric/cluster.key` (`forge cluster keygen`, 0600, git-ignored); a node without one refuses to start. Artifacts travel content-addressed: the executor keeps bytes in its blob store and returns `{sha256,size}`; the origin pulls `GET /blob/<sha256>` (signed), verifies the digest and only then accepts the result. Nodes still bind `127.0.0.1` by default; ops stay a closed allow-list (`hashchain`, `gen` on an existing brief id, `flaky`/`bytes` diagnostics). **Gaps:** one shared fleet secret (no per-node keys or revocation), no encryption — payloads are readable on a raw LAN, so pin to Tailscale/WireGuard before binding off loopback; no per-job quotas; a node holding the secret is trusted for its results (INFERENCES C-17, C-95, C-96) | C7 |
| Multiplayer | game state | cheating, NAT relay abuse | host-authoritative validation; self-hosted TURN with credentials | F6/F7 |
| LiveOps config bundles (F9) | balance values, kill switches, device state | forged/tampered bundle, replay or downgrade of an old bundle, bundle smuggling content/code, crash-looping bundle, remote override of player consent, phone-home | **built (F9, ADR-0022)**: RSA-2048 PKCS#1 v1.5/SHA-256 over the exact payload bytes, key pinned in the build (test keys only in debug builds), `key_id` check; strictly increasing serial + promoted-serial check on disk; strict key set (flags + numeric knobs within F4 ranges only; no content, no `sim.*`, no consent flags); tamper → shipped defaults; crash-loop quarantine after 2 crashed boots; local files only — the game has no fetch path (G-NET-01); private keys never in git (`/.fabric/liveops/`, `*.pem`, readiness check) | F9 |
| Supply chain | dependencies, plugins | compromised packages | pinned deps; SBOM + license audit in CI before BoltPack publish; no community mod marketplace in v1 | F7 |

## 6. Privacy & compliance hooks

Hooks are continuous; depth grows with milestones:

- Age gates, AI-content disclosure, moderation hooks (EU AI Act, COPPA awareness).
- Telemetry stays on-device unless the user opts in to export. **F9:** the `diagnostics` consent flag defaults off, is set only by the player (never by a config bundle), writes a local session record without paths/ids, and `forge liveops diag-export --consent` scrubs home paths, user/host names, e-mails, IPs, MACs and long tokens into a schema-validated local file. There is no upload endpoint.
- Voice (Vosk) is processed offline; audio is not persisted by default.

## 7. Explicit non-goals (v1)

Modern console NDA CertPacks; community mod marketplace (supply-chain blast radius deferred with the feature); dedicated servers.

## 8. Current state (F9, 0.9.0+f9)

All spec milestones F0–F9 + C1–C12 are built. Network surfaces exist only in dev tooling (LoomLink, MirrorWeave, LoomCluster — HMAC-signed, not encrypted, loopback/LAN only); the shipped game has none (G-NET-01, F7/F9 gates). LiveOps is readiness only: no production signing key is pinned yet (release builds ignore every bundle) and no service exists. Unsigned/debug builds only (no Authenticode / Android release key yet).

## 8a. Original F0 state (historical)

Only the store, telemetry and CLI surfaces exist. No network listeners, no sandbox, no models. The F0 surface is low-risk; the table above is the contract for later milestones.
