# ADR-0006 — Speech-to-text: Vosk primary, whisper.cpp optional

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-05 |
| Deciders | Design chat / Recharged Ideas |

## Context

Voice commands must work offline on mid-range Android within a shared CPU budget.

## Decision

**Vosk** with grammar-constrained intents is the primary STT (VoiceBridge). whisper.cpp is an optional high-accuracy fallback, not run concurrently with full TTS without a budget.

## Consequences

- One shared Vosk instance; intents are a constrained grammar.
- Implemented 0.7.8 (`forge/voice.py`): vosk-model-small-en-us-0.15 (Apache-2.0), grammar = the closed intent phrase set, word-confidence gate. Synthetic-speech finding: "hold" ↔ "go" confusion (INFERENCES C-79) — a voice-grammar decision is pending.

## Alternatives considered

- **whisper.cpp primary:** rejected (CPU cost on mobile).

## References

docs/design/ASSETFABRIC_SPEC.md; docs/design/GAME_SPEC.md; source chat https://chat.deepseek.com/share/g90tn4mss3265u0xm3
