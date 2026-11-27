# GLOSSARY.md

| Term | Meaning |
|---|---|
| **AssetFabric** | Universal content fabric + execution substrate (renamed from Asset Factory). |
| **Game Zero** | First MVP product — 8-bit fighter/farming hybrid. |
| **Content Forge** | Generation / validation / orchestration core (`forge` CLI). |
| **Fabric milestone (F0…)** | Platform increment; incomplete until linked game increment ships. |
| **One-milestone offset** | Fabric ≤ one milestone ahead of Game. |
| **GroundWeave** | GPU→CPU software fallback ladder; 2-core/no-GPU acceptance. |
| **LoomCluster** | Equal-node compute clustering. |
| **PocketLoom** | Android Kotlin companion (standalone + optional pair). |
| **LoomLink** | Pairing (QR / codes / Tailscale). |
| **GIRT** | Godot Inference Runtime. |
| **CascadeHub** | Multi-agent typed message bus. |
| **DyeWorks** | PBR / material generation tool. |
| **ShuttleLine** | Multi-engine export (Godot first). |
| **BoltPack** | Signed SBOM-audited `.fabricbolt` packages. |
| **PatternVault** | Versioned palettes/patterns/capture profiles. |
| **Substrate / UEF** | Sandbox, micro-VMs, hot reload, snapshots, emulator harness. |
| **BudgetGate** | Resource/permission gate before asset promotion. |
| **Compatibility renderer** | Godot `gl_compatibility` — project target for 2D/mobile/Web. |
| **`[INFERENCE]`** | Extrapolation not stated verbatim in source chat. |
| **ADR** | Architecture Decision Record (`docs/adr/`). |
| **Producer** | Owner of scope and milestone acceptance (Recharged Ideas). |
| **Factory Lead** | Architecture owner; approves ADRs/scope changes. |
| **Game increment** | Playable Game Zero step that proves a Fabric milestone (`forge.yaml` `game.increment`). |
| **HeadlessSim** | Deterministic simulation harness for RL/balance. |
| **GodotIPC / PWAPipeline** | Android data-plane bridge / Web export orchestrator. |
| **FabricCore** | Shared Kotlin module for PocketLoom (JVM-only today; KMP targets later — INFERENCE C-1); also runs as a desktop CLI jar. |
| **LocalForge** | PocketLoom on-device generation (CPU procedural caves/sprites; ONNX rung later). |
| **OffloadQueue** | PocketLoom durable queue of jobs waiting for a paired desktop. |
| **RC family** | Reality-capture models (chat "R1"), renamed to avoid the Retro R1 clash. |
| **SwatchStudio** | Live material tuning UI with CLI echo. |
| **Config bundle (LiveOps)** | F9 signed local file: kill-switch flags + balance-knob patches, strictly increasing serial; never content, never consent (ADR-0022). |
| **Kill switch** | F9 flag (default on) a config bundle may turn off without a rebuild (`retro_styles`, `adaptive_music`, `remote_balance`). |
| **Roll-forward rollback** | F9: re-issue an earlier bundle's content (or defaults) under a new serial — devices never accept an older serial. |
| **Crash-loop quarantine** | F9: a bundle whose boots die `max_boot_fails` (2) times is moved to `quarantine/` and the previous bundle restored. |
| **docs/design/** | Frozen imports of the authoritative design specs. |
