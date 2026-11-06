# docs/design — Authoritative design specs

These are the **source-of-truth design documents** for AssetFabric and Game Zero, imported verbatim from the ChatGrabber extract of the DeepSeek design chat:

- **Source chat:** https://chat.deepseek.com/share/g90tn4mss3265u0xm3 (56 messages, high-fidelity grab)
- **Imported:** 2026-11-05 (America/New_York)

| File | What it is |
|---|---|
| [ASSETFABRIC_SPEC.md](ASSETFABRIC_SPEC.md) | Production build spec: architecture, tool catalog, ML mesh, Substrate, PocketLoom, LoomCluster, hardware, doc suite, build order, DoD |
| [GAME_SPEC.md](GAME_SPEC.md) | Game Zero MVP: pitch, pillars, systems, scope, acceptance criteria, milestone ↔ game increments |
| [ASSETFABRIC_ML_AI_FEATURES.md](ASSETFABRIC_ML_AI_FEATURES.md) | ML/AI feature inventory (model families, training, telemetry) |
| [CHAT_SUMMARY_ASSETFABRIC.md](CHAT_SUMMARY_ASSETFABRIC.md) | Narrative arc of the design chat |

## Rules for using these specs

1. **Prefer these specs over invention.** If a spec decides something, follow it.
2. If you must fill a gap, mark the text **`[INFERENCE]`** and register it in [`docs/F0_INFERENCES.md`](../F0_INFERENCES.md) (or the milestone's inference register).
3. These files are **frozen imports** — do not edit them to match the implementation. When the implementation intentionally diverges, record an ADR in [`docs/adr/`](../adr/) and index it in [`DECISIONS.md`](../../DECISIONS.md). ADRs + `ARCHITECTURE.md` supersede the specs where they conflict.
4. Paths in the specs such as `/workspace/chatgrab-output/…` refer to the original grab location on the shared build box; inside this repo the canonical copies are here.
