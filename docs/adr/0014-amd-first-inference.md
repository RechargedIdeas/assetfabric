# 0014 — AMD-first inference

- **Status:** accepted
- **Date:** 2026-11-05
- **Deciders:** design chat / Recharged Ideas (recorded in F0)
- **Context:** Locked in AssetFabric / Game Zero design chat and ASSETFABRIC_SPEC.
- **Decision:** Fleet has no NVIDIA; prefer DirectML (Windows), ROCm 6.x (Linux 7900), Vulkan universal; Vega = DirectML/Vulkan only.
- **Consequences:** Binding for v1 unless superseded by a later ADR + scope change.
- **Alternatives considered:** See chatgrab transcript; rejected alternatives documented there.
- **References:** ASSETFABRIC_SPEC.md; GAME_SPEC.md; chat share g90tn4mss3265u0xm3
