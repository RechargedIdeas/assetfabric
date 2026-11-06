# ADR-0011 — No LLM in the combat tick loop

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

LLM latency and nondeterminism would break frame budgets, determinism for RL/balance, and multiplayer authority.

## Decision

The combat tick uses only Behavior Trees, ONNX policies and deterministic rules. LMs produce dialogue/callouts asynchronously via CascadeHub semantic intents; their output never gates a tick.

## Consequences

- HeadlessSim stays deterministic and replayable.
- Telemetry `action_source` distinguishes BT / policy / LLM / player.

## Alternatives considered

- **LLM-driven tactics per tick:** rejected.

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
