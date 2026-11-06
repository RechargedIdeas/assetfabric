# ADR-0005 — Micro LM: shared small backbone + per-character LoRA

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Characters need dialogue and callouts with distinct personalities, offline, within mobile memory.

## Decision

One shared backbone (**Qwen2.5-0.5B** or TinyLlama class, INT4) with **per-character LoRA** adapters managed by LoRAManager (residency + callout pre-generation cache). LMs run **outside** the combat tick (ADR-0011).

## Consequences

- Callouts are pre-generated / cached; dialogue may stream.
- Content-safety gate applies to LM output (SECURITY.md).

## Alternatives considered

- **One model per character:** rejected (memory).
- **Cloud LLM:** rejected (offline-first).

## Notes

`[INFERENCE]` exact backbone (Qwen vs TinyLlama) left open in chat; Qwen2.5-0.5B listed first.

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
