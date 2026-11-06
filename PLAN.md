# PLAN.md — Project Plan

## Vision

**AssetFabric** is a universal content-generation and execution platform. **Game Zero** is its first shippable product and the proof that AssetFabric is sufficient to build a production game end-to-end.

## Design pillars

### Fabric

1. Offline-first tooling and runtimes.
2. Protocol surfaces are first-class (GUI/CLI/REST/MCP/ACP).
3. BudgetGate + validators before promotion.
4. GroundWeave: every GPU path has CPU fallback; weakest node 2 cores / no GPU.
5. One-milestone offset vs Game Zero.

### Game Zero (from GAME_SPEC)

1. Offline-first gameplay.
2. AI-native but fallback-safe — **no LLM on combat tick**.
3. Party as system (followers, pets, tactics, synergies).
4. Tactical clarity (time-freeze swap).
5. Fabric-proven content.
6. Equal balance intent (Monte Carlo / Bayesian).
7. Cross-input + a11y.

## Definition of Done — AssetFabric v1 (summary)

Full acceptance-tested list lives under `docs/acceptance-tests/` as it grows. Headline (SPEC §14):

- Content gen + validation + Godot bridge  
- AI runtime (GIRT / CascadeHub / policies / micro LM off tick)  
- Substrate (sandbox / hot reload / snapshots)  
- Balance/QA + player state + l10n/a11y  
- Platform targets + observability  
- PocketLoom C1–C6 minimum for “two editions”  
- LoomCluster / GroundWeave for fleet  

Each with **executable acceptance tests**. Not on the DoD list ⇒ out of scope without a formal trade.

## Milestones

See `BUILD_ORDER.md`. F0 = foundation (this plan’s starting gate).

## Parallel contract

- Fabric may be **at most one milestone ahead** of the Game.  
- F(n) incomplete until its Game increment ships + passes acceptance.  
- Every Fabric feature validated by a Game acceptance test.

## Timeline (indicative, 12–15 people)

| Quarter | Fabric | Game |
|---|---|---|
| Q1 | F0 + F1 | Sandbox encounter playable |
| Q2 | F2 + F3 | Full combat + party AI |
| Q3 | F4 + F5 | Vertical slice + boss |
| Q4 | F6 + F7 | Tier 1 + Tier 2 launches |

Smaller teams → proportionally longer. **If vertical slice slips, cut DoD scope — do not endlessly extend Fabric.**

## Fleet

See `docs/hardware-fleet.md`. AMD-first: DirectML / ROCm / Vulkan — not CUDA-first.

## Out-of-Scope for v1 (hard contract)

- Quantum **hardware** backend (simulation OK)
- Fantasy consoles (PICO-8, TIC-80)
- Modern console CertPacks
- Mod / community marketplace
- P2P mesh beyond 2 players
- Dedicated servers
- Live seasonal content (remote config readiness OK later)
- M1-Architect discovery as a ship gate
- Cross-platform cloud saves
- Full Studio “beauty” polish (functional required)

## Failure modes and guardrails

| Failure mode | Guardrail |
|---|---|
| Fabric paralysis | One-milestone offset |
| Scope creep | Out-of-Scope hard contract |
| Perfectionism | Acceptance by test |
| Game blocked by Fabric | Blocker escalation (`AGENTS.md`) |

## Open design decisions (Game)

Document in DECISIONS before locking content (`GAME_SPEC` §10):

- Exact names/stats of 4 base fighters  
- Exact 3 starter pets  
- Farming economy numbers `[INFERENCE: crops/economy unspecified]`  
- Whether F8 retro ROM authenticity is in v1  
- Max pets / synergy coefficients  
