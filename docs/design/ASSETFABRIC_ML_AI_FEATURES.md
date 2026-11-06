# ASSETFABRIC_ML_AI_FEATURES.md — ML/AI Feature Inventory

> **Source:** DeepSeek share https://chat.deepseek.com/share/g90tn4mss3265u0xm3  
> Inventory of **all ML/AI and closely related game-AI features** discussed, for **Luciverse concept reuse**.  
> Labels: **AssetFabric** | **Game** | **Transferable-to-Luciverse**  
> `[INFERENCE]` = not verbatim but strongly implied by architecture.

---

## How to read

- **AssetFabric:** tooling/substrate/models that exist independent of Game Zero.  
- **Game:** features specific to the fighter/farming MVP.  
- **Transferable-to-Luciverse:** reusable concepts/patterns for another universe/product (Luciverse) — usually Fabric substrate + agent patterns + reconstruction/cluster, not Game Zero lore.

---

## A. AssetFabric — Generation & Media Models

| Feature | Description | Labels |
|---|---|---|
| G1-Sprite diffusion / tiny ONNX sprite gens | Palette-constrained 8-bit sprites + anim frames | AssetFabric · Transferable |
| G1-Tile Neural Cellular Automata | Tilemaps/caves with solvability + diversity (CMA-ME) | AssetFabric · Transferable |
| G1-Texture / DyeWorks diffusion | PBR channel synthesis; SD-class on GPU; procedural fallback | AssetFabric · Transferable |
| G1-Audio / chiptune stems | Biome/mood stem layers | AssetFabric · Transferable |
| Procedural pixel pipeline (non-ML) | Deterministic palette/noise grammar — always available | AssetFabric · Transferable |
| 3D asset generation tools | Gap-fill: mesh/3D gens integrated into Forge | AssetFabric · Transferable |
| PBR material generation | DyeWorks multi-backend | AssetFabric · Transferable |
| Rigging/animation assist | Gap-fill for 3D characters | AssetFabric · Transferable · `[INFERENCE: specific model not named]` |
| Post-gen optimization / web-readiness | Compress/pack for tiers | AssetFabric · Transferable |
| Style-conformance gate (perceptual hash) | Reject style drift | AssetFabric · Transferable |
| Dimensional coherence gate | Same aesthetic across 2D/2.5D/3D | AssetFabric · Transferable |
| Retro authenticity models (R2) | Constraint solver, fidelity delta, discriminator | AssetFabric · Transferable |
| Console constraint models (C1) | Palette/cycle/solver for console-style targets | AssetFabric · Transferable |
| Shimmer predictor (Q1) | Pixel stability / camera policy | AssetFabric · Transferable |
| RealityLoom routing | Capture → splat vs photogrammetry decisioning | AssetFabric · Transferable |
| SplatForge (3DGS training) | Images → Gaussian splat assets | AssetFabric · Transferable |
| MeshWeaver (splat→mesh) | SuGaR/GOF-class extraction | AssetFabric · Transferable |
| Photogrammetry backends | COLMAP/Meshroom paths | AssetFabric · Transferable |
| Capture quality / splat param models (RC/R1 family) | Optimize reconstruction | AssetFabric · Transferable |
| DepthAnything V2 (+ ARCore) | Monocular depth / distance for LensForge | AssetFabric · Transferable |
| Voice STT (Vosk; whisper.cpp fallback) | Offline streaming STT shared | AssetFabric · Game · Transferable |
| WhisperWeft intent classifier | Grammar-constrained voice→command | AssetFabric · Transferable |
| Content safety gateway | Filter LM dialogue/callouts | AssetFabric · Game · Transferable |

---

## B. AssetFabric — Data / Scale / Hardware / Meta

| Feature | Description | Labels |
|---|---|---|
| D1-Active learning curator | Selects what to label/train next | AssetFabric · Transferable |
| D1-Synth synthetic data factory | Improves FID without human labels | AssetFabric · Transferable |
| D1-Augment policy learner | Learns augmentation policies | AssetFabric · Transferable |
| S1-Up mobile realtime upscaler | <5 ms mobile target | AssetFabric · Transferable |
| S1-Down learned downscaler | Tier targeting | AssetFabric · Transferable |
| Joint scale-consistency trainer | Up/down cycle consistency | AssetFabric · Transferable |
| H1-NAS hardware-aware search | Device-class architectures | AssetFabric · Transferable |
| H1-Compress | Prune → distill → quantize | AssetFabric · Transferable |
| H1-Registry | Per-device adapter registry | AssetFabric · Transferable |
| M1-Architect | Agentic architecture discovery | AssetFabric · Transferable · **deferred v1 ship** |
| M1-Tuner | Bayesian/NSGA hyperparam & pipeline opt | AssetFabric · Transferable |
| Automated self-training pipeline | Closed-loop train→export→deploy | AssetFabric · Transferable |
| Manual training workspace | Human-in-loop Studio training | AssetFabric · Transferable |
| Continual learning + replay/regularization | On-device or node fine-tune | AssetFabric · Game · Transferable |
| Model registry + MLflow lineage | Reproducible production models | AssetFabric · Transferable |
| Drift detector + retraining gate | Ops monitoring | AssetFabric · Transferable |
| O1 observers / thought-stream schema | Non-LLM + LLM traces | AssetFabric · Transferable |
| Telemetry dashboards | Fleet, flow, heatmap, Pareto, curves, anomalies | AssetFabric · Transferable |
| Interactive model sandbox | Load models, interact, multi-agent sandbox | AssetFabric · Transferable |

---

## C. AssetFabric — Substrate / Execution AI

| Feature | Description | Labels |
|---|---|---|
| Backend Selector model | Choose WASM vs native vs quantum sim backend | AssetFabric · Transferable |
| Snapshot Policy Optimizer | Snapshot interval / WAL policy | AssetFabric · Transferable |
| Crash Predictor | Pre-crash signatures → proactive snapshot/migrate | AssetFabric · Transferable |
| Sandbox Resource Allocator | Quotas under stability constraints | AssetFabric · Transferable |
| Quantum Circuit Optimizer | Rewrite circuits for sim/hardware | AssetFabric · Transferable · sim-only v1 |
| Guardian self-healing | Watchdog + repair actions | AssetFabric · Transferable |
| Atomic hot-reload health probes | Validate before commit | AssetFabric · Transferable |

---

## D. AssetFabric — Cluster / Device / Control Intelligence

| Feature | Description | Labels |
|---|---|---|
| LoomCluster negotiation | Equal nodes advertise/negotiate resources | AssetFabric · Transferable |
| GroundWeave fallback ladder | GPU ops → CPU software paths | AssetFabric · Transferable |
| Work stealing + checkpointing | Distributed jobs | AssetFabric · Transferable |
| OffloadQueue (PocketLoom) | Defer heavy work until paired/cluster available | AssetFabric · Transferable |
| On-device model cache/eviction | Mobile LocalForge | AssetFabric · Transferable |
| MirrorWeave streaming control | Cross-device UI control + screen share | AssetFabric · Transferable |
| LensForge camera intelligence | Enhanced capture telemetry | AssetFabric · Transferable |
| AMD/DirectML/Vulkan/ROCm backend selection | Hardware-aware inference routing | AssetFabric · Transferable |

---

## E. AssetFabric — Agentic Tooling Interfaces

| Feature | Description | Labels |
|---|---|---|
| MCP server (tools as agent skills) | Generation/validate/export as MCP tools | AssetFabric · Transferable |
| ACP agent sessions | Editor↔agent protocol | AssetFabric · Transferable |
| Embedded Godot MCP host / ACP bridge | Runtime agent inside engine | AssetFabric · Transferable |
| Agentic Factory orchestration | Factory directing its own jobs (gap-fill) | AssetFabric · Transferable |
| Runtime LLM safety gate | Governance before LM actions | AssetFabric · Transferable |
| Hybrid QA agents | Automated playtest agents + humans | AssetFabric · Game · Transferable |
| Localization key emitter / a11y palette compiler | Generated, not retrofitted | AssetFabric · Game · Transferable |

---

## F. Game — Combat / Party / World AI

| Feature | Description | Labels |
|---|---|---|
| Per-character BT + ONNX RL policy (PPO) | Strategy BT, tactics neural | Game · Transferable (agent pattern) |
| Per-character micro LM + LoRA | Personality/callouts/commands only | Game · Transferable (LoRA-persona pattern) |
| Shared LM backbone INT4 | One backbone, many adapters | Game · Transferable |
| Pet AI same architecture | Synergy-aware policies | Game · Transferable |
| Enemy tier-scaled policies | Shared/generic adapters | Game · Transferable |
| Boss hierarchical RL | Manager phases + worker execution | Game · Transferable |
| CascadeHub multi-agent bus | Typed intents; LM only for surface text | Game · Transferable |
| Party tactics system | Player-authored coordination | Game |
| Character synergy bonuses | Multiplier graph | Game |
| Time-freeze optimal swap forward-sim | <50 ms decision support | Game · Transferable (UI+sim pattern) |
| Cached combat callouts | Pre-gen library, no LM in tick | Game · Transferable |
| Live dialogue LM | Non-tick, latency-budgeted | Game · Transferable |
| Player↔agent voice/text chat | Shared STT + bus | Game · Transferable |
| Online fine-tuning during play | Small replay buffer | Game · Transferable |
| Character creator → LoRA + policy warm-start | Content→model pipeline | Game · AssetFabric · Transferable |
| Thought streams for all game agents | Debug/Studio visibility | Game · Transferable |
| Automated balance (RuleSmith-like / Optuna) | Multi-agent self-play + Bayesian opt | Game · Transferable |
| Pet stacking diminishing returns model | Balance dimension | Game |
| Soft-lock detection playthroughs | Progression QA | Game · Transferable |
| Adaptive / vertical remix music | Macro state director | Game · Transferable |
| Quest state machine | Progression | Game |
| Farming loop systems | Economy | Game |
| Boss/trash tier schema | Content scaling | Game |
| P2P netcode (rollback fight / interpolate explore) | Networking | Game · Transferable |
| Server-authoritative anti-cheat validators | MP integrity | Game · Transferable |
| Remote config / feature flags | LiveOps readiness | Game · Transferable |

---

## G. Game — Presentation ML-adjacent

| Feature | Description | Labels |
|---|---|---|
| Retro pixelation / quantization post-process | Unifying look | Game · AssetFabric · Transferable |
| Pixel-to-meter / billboard hybrid sprites | HD-2D-like presentation | Game · Transferable |
| Authenticity discriminator (R2) | Console-style feel without ROM | Game · AssetFabric · Transferable |

---

## H. Explicitly deferred / limited (still inventoriable for Luciverse)

| Feature | Note | Labels |
|---|---|---|
| M1-Architect full discovery | Out of Game Zero v1 DoD | AssetFabric · Transferable (later) |
| Quantum hardware execution | Simulators OK; hardware later | AssetFabric · Transferable (later) |
| Quantum circuit game mechanics | Out of Game Zero v1 | Game (later) · Transferable concept |
| Fantasy console targets | Separate product line | AssetFabric (later) |
| CUDA-only 3DGS trainers | Need ROCm/OpenSplat/CPU paths on this fleet | AssetFabric constraint |

---

## I. Luciverse reuse checklist (priority)

Highest transfer value from this chat:

1. **Content Forge protocol surface** (GUI/CLI/API/MCP/ACP + slash terminal)  
2. **Generator + BudgetGate + style/solvability validators**  
3. **GIRT + CascadeHub + “no LLM in tick” rule**  
4. **Shared backbone + LoRA personas**  
5. **Substrate:** sandbox/micro-VM, hot reload, snapshots, Guardian  
6. **LoomCluster + GroundWeave two-core guarantee**  
7. **PocketLoom dual-edition companion + LoomLink**  
8. **RealityLoom / SplatForge / MeshWeaver** reconstruction map  
9. **Telemetry/thought-stream schema + Studio sandbox**  
10. **One-milestone offset + acceptance-tested DoD discipline**  
11. **Hybrid BT+RL+hierarchical bosses** party AI pattern  
12. **Time-freeze forward-sim decision UI** pattern  

Lower transfer (Game Zero-specific): fighter roster fantasy, farming economy numbers, cave-biome narrative, 8-bit fighter IP.

---

## J. Cross-cutting principles (apply everywhere)

1. Deterministic fallbacks if inference fails or exceeds latency.  
2. Offline-first: no remote dependency for core loops.  
3. Structured intents on the bus; natural language is a skin.  
4. Quantize/specialize per device (H1); never assume NVIDIA.  
5. Every model version has lineage; drift is monitored.  
6. Sandbox untrusted generation and emulators.  

---

*End of ASSETFABRIC_ML_AI_FEATURES.md*
