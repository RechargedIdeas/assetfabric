# AssetFabric

> **Private & proprietary** — © 2026 Recharged Ideas. All Rights Reserved. See [LICENSE](LICENSE).

**AssetFabric** is a universal content fabric and execution substrate for producing games and assets end-to-end: generation, validation, packaging, AI runtime, sandboxed execution, reconstruction, clustering, and companion tooling.

**Game Zero** — an offline-first 8-bit fighter/farming hybrid on Godot 4 — is its **first product and MVP test**. Every Fabric milestone is proven by a playable Game Zero increment.

**Not this product:** [Future Beasts](https://github.com/RechargedIdeas/future-beasts) is a separate browser game with its own HMAP engine. It does not import this studio. Game Zero is not Future Beasts.

**Architecture in one line:** Python/PySide6 **Studio** → **Content Forge** (generators · validators · orchestrator · BudgetGate) → **Substrate** (sandbox · hot reload · snapshots) → **Godot 4 Compatibility runtime** (GIRT · CascadeHub) — spread over equal **LoomCluster** nodes with **GroundWeave** CPU fallbacks, and a standalone Android companion, **PocketLoom**.

## Status

| | |
|---|---|
| Fabric milestone | **F9 — LiveOps foundation (readiness only)** ✅ accepted (`forge accept F9`, `0.9.0+f9`) — **all spec milestones F0–F9 + C1–C12 complete**; F8 retro ✅, F7 packaging ✅ |
| Game increment | `launch-candidates` — unsigned Linux + Windows builds, debug Android APK, Web PWA (9.3 MB gzip, offline) + single-thread Web fallback (`web-nothreads`, 9.37 MB, since 0.7.14) of the vertical slice; saves round-trip desktop → Android → Web → desktop |
| Companion track | **PocketLoom C1–C6** ✅ accepted (`forge accept C1-C6`) — standalone offline Android companion, debug APK ≈ 0.89 MB: on-device generation, library, capture, LoomLink pairing (code / QR URI / Tailscale), offload + sync. Not yet run on a phone (no device/KVM) |
| Fleet track | **LoomCluster C7 + GroundWeave C8** ✅ accepted (`forge accept C7-C8`) — equal nodes that advertise/negotiate, steal work, retry and recover from crashes (proven on **loopback processes**, not a LAN; HMAC-authenticated since 0.7.14, not encrypted); results are byte-identical on 1, 2 or 3 nodes; every generator has a declared GPU→CPU ladder, and its CPU path is proven on 2 pinned cores with GPUs hidden. PocketLoom offloads run on the fleet via LoomLink. No real GPU backend exists yet — every GPU rung is a labelled `planned` stub |
| Companion interfaces | **C9 MirrorWeave · C10 LensForge · C11 depth · C12 SplatForge path** ✅ accepted (`forge accept C9-C12`). After the stub-replacement sprint (0.7.4–0.7.8) the register (`content/companions/c9_c12.yaml`) is **25 real CPU paths · 8 `real_unverified_on_device` (Kotlin compiled into the APK, never run on a phone) · 1 stub (full-scale SplatForge GPU training — no GPU here) · 3 deferred**. Nothing has run on a phone or a GPU |
| Version | `0.8.0+f8` (PocketLoom `0.1.0-c6`) |
| Quality-gap phase | Q1 CI shards (`0.7.9`) ✅ · Q2 G-A11Y-01 full (`0.7.10`) ✅ · Q3 swap advisor (`0.7.11`) ◐ **partial** — p95 37.8–39.4 ms on 2 pinned cores of the reference box (gated), ≈ 63–66 ms on GitHub's 2-core runners (reported only). Q4 slice length (`0.7.12`) ✅ — human-pace estimate 17.0–18.5 min on all 12 selections, gated in `forge accept F6` (a model until a human playtest, ADR-0017). Q5 economy design model + per-pair balance (`0.7.13`) ✅ — economy/loot/XP targets gated in Codegen-World and `forge accept F6` (ADR-0018); per-pair spread 2.71 pp on 1000 unseen seeds/cell (≤ 3.5 pp, full `forge accept F5`). Q6 cluster auth + blobs, Web single-thread fallback, doc nits (`0.7.14`) ✅ — HMAC-signed LoomCluster requests/responses (401 on unsigned/stale/replayed) + content-addressed `/blob/<sha256>` transfer; `web-nothreads` build (9.37 MB gzip, no COOP/COEP needed, D-001 closed, ADR-0019). P7 world-fight bands (`0.7.15`) ✅ — every slice fight replayed from its recorded start state (8 040 fights), wipe-rate / clear-time bands gated per selection × fight in `forge accept F6` (ADR-0020). All software quality gaps closed except the hardware-gated Q3 native step. See [TODO.md](TODO.md) |
| Retro (F8) | **F8 — retro/console-style** ✅ accepted (`forge accept F8`, `0.8.0+f8`): Settings → Display style switches Game Zero live between modern, `gz-native` (320×180 ×4), `nes-style` (256×144 ×5, computed 2C02 NTSC palette) and `gb-style` (160×90 ×8, DMG 4-shade) + scanlines — one R1 LUT post-process, Q1 integer camera/sprite policy, V1 frame gates, R2 discriminator; colour-blind palettes kept; sim byte-identical in every profile. ForgeConsole real-ROM path: iNES NROM field demo (party + pet) built from Fabric content with an own 6502 assembler + cycle predictor, booted and driven in the cynes emulator. ADR-0021, INFERENCES §F8 — [docs/acceptance-tests/F8.md](docs/acceptance-tests/F8.md) |
| LiveOps (F9) | **readiness only** ✅: flag manifest with safe offline defaults (`content/liveops/flags.yaml`: kill switches `retro_styles`, `adaptive_music`, `remote_balance`; consent `diagnostics` off), RSA-signed **local** config bundles for balance knobs (= F4 tune limits), anti-replay serials, roll-forward rollback, crash-loop quarantine, tamper → shipped defaults, newer saves read-only, opt-in scrubbed local diagnostics, `forge liveops …`, [runbook](docs/liveops-runbook.md). The game never fetches anything (G-NET-01). No live service, no launch. ADR-0022 — [docs/acceptance-tests/F9.md](docs/acceptance-tests/F9.md) |
| Next | Nothing spec-required is left. Remaining items are hardware- or Producer-gated: [HANDOVER.md §Next steps](HANDOVER.md#next-steps-ordered) |

Live dashboard: [STATUS.md](STATUS.md) · details: [HANDOVER.md](HANDOVER.md).

![F3 time-freeze swap](docs/media/f3-time-freeze.png)

## Quick start

Requires Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/). Godot 4.3+ is optional (needed for the full headless boot).

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git
cd assetfabric
./scripts/bootstrap.sh
source .venv/bin/activate
forge doctor          # environment checks
forge status          # exit 0 == healthy
pytest -q
./scripts/smoke_godot.sh
forge build           # regenerate content from content/briefs/ (deterministic)
forge accept F6       # headless Godot acceptance (needs Godot 4.3); FORGE_ACCEPT_FAST=1 for the CI subset
forge build --target all   # F7 platform builds → dist/ (needs `forge templates fetch`, JDK 17, Android SDK; see docs/packaging.md)
forge accept C1-C6    # PocketLoom: Gradle build + debug APK verify + Kotlin↔Python LoomLink interop (JDK 17, Android SDK)
forge accept C7-C8    # LoomCluster loopback fleet + GroundWeave 2-core/no-GPU proofs (≈ 80 s; Godot for the runtime probes)
forge accept C9-C12   # MirrorWeave / LensForge / depth / SplatForge-path: real CPU paths + the one remaining labelled stub (JDK 17, Android SDK; ≈ 1 min warm)
forge mirror|lens|depth|recon --help   # C9–C12 tools; the remaining stub (full-scale splat training) exits 3 with a [STUB …] label
forge cluster demo    # 3 local nodes, work stealing + SIGKILL failover   ·   forge groundweave show|check|verify
forge link serve --bind <LAN/Tailscale IP> [--cluster <node URL>]   # pair a PocketLoom phone (code + loomlink:// QR); offloads run on the fleet
forge balance run     # Monte Carlo G-BAL-01 matrix (12 matchups × 200 seeds)
forge live serve --headless &   # Game Zero under the guardian; then: forge live set sim.leash=72
```

Play Game Zero: `godot --path games/game-zero -- --scene=slice` (the vertical slice), or open `games/game-zero/` in the Godot editor. More: [docs/setup/README.md](docs/setup/README.md).

## Repository layout

| Path | Contents |
|---|---|
| `forge/` | Content Forge Python package and `forge` CLI |
| `forge.yaml` | Project manifest (milestone, targets, profiles, fleet) |
| `content/` | Content briefs, roster, world (economy/loot/quests/music/areas) + PatternVault palettes (inputs to `forge build`) |
| `docs/design/` | **Authoritative design specs** imported from the design chat |
| `docs/adr/` | Architecture Decision Records |
| `docs/schemas/` | JSON Schemas (manifest, telemetry) |
| `docs/acceptance-tests/` | Milestone acceptance checklists |
| `games/game-zero/` | Game Zero Godot 4 project ([README](games/game-zero/README.md)) |
| `studio/` | Desktop Studio (PySide6) — minimal real tabs: Status, Mirror, Console (read-only `/` commands), Swatches, Voice, Persona |
| `companions/pocketloom/` | PocketLoom Android companion + FabricCore (Kotlin) — C1–C6 ([README](companions/pocketloom/README.md)) |
| `forge/loomcluster.py`, `forge/groundweave.py`, `content/groundweave/ladder.yaml` | LoomCluster (C7) equal-node scheduler + GroundWeave (C8) fallback ladder; `cluster/loomcluster/` holds its README |
| `forge/mirrorweave.py`, `lensforge.py`, `depth.py`, `realityloom.py`, `stubs.py`, `registry.py`, `content/companions/c9_c12.yaml` | C9–C12 interfaces, real CPU paths and the real/stub/deferred register (`companions/pocketloom/fabriccore` has the Kotlin side) |
| `store/` | Content-addressed asset store (blobs gitignored) |
| `locales/` | Locale string tables (no hard-coded strings) |
| `content/tune/` | Live-tune limits (F4); also bound balance/tuning knobs (F5) |
| `scripts/` | bootstrap and smoke scripts |
| `tests/` | pytest suite |

## Documentation map

| Doc | Role |
|---|---|
| [AGENTS.md](AGENTS.md) | Rules of engagement for agents and humans — **read first** |
| [HANDOVER.md](HANDOVER.md) | Current state snapshot |
| [TODO.md](TODO.md) | Sprint tasks, backlog, blockers, decisions needed |
| [PLAN.md](PLAN.md) | Vision, pillars, Definition of Done, out-of-scope |
| [BUILD_ORDER.md](BUILD_ORDER.md) | F0–F9 + C1–C12 sequence |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Systems map and code map |
| [DECISIONS.md](DECISIONS.md) | ADR index |
| [TESTING.md](TESTING.md) | QA pyramid, acceptance, CI gates |
| [SECURITY.md](SECURITY.md) | Threat model, vulnerability reporting, confidentiality |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, workflow, PR checklist |
| [GLOSSARY.md](GLOSSARY.md) | Terms |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [STATUS.md](STATUS.md) | Generated milestone dashboard |
| [docs/design/](docs/design/README.md) | ASSETFABRIC_SPEC, GAME_SPEC, ML/AI features, chat summary |
| [docs/tool-catalog.md](docs/tool-catalog.md) | Fabric tools and their milestones |
| [docs/SUBSTRATE.md](docs/SUBSTRATE.md) | Sandbox tiers, live channel, snapshots, statecharts, guardian (F4) |
| [docs/acceptance-tests/F5.md](docs/acceptance-tests/F5.md) | Balance runner, Optuna tuning, soft-lock detection, save migration, first boss (F5) |
| [docs/acceptance-tests/F6.md](docs/acceptance-tests/F6.md) | Vertical slice: quests, farming/craft, loot, adaptive music, cave ↔ open world, save/quit/reload (F6) |
| [docs/acceptance-tests/F7.md](docs/acceptance-tests/F7.md) | Launch candidates: Linux/Windows/Android/Web builds, G-WEB-01, G-SAVE-01, G-NET-01, sizes + SHA-256 (F7) |
| [docs/acceptance-tests/F8.md](docs/acceptance-tests/F8.md) | Retro / console-style: profiles, R1/Q1/V1/R2 gates, NES ROM + emulator, known gaps (F8) |
| [docs/acceptance-tests/F9.md](docs/acceptance-tests/F9.md) | LiveOps readiness: flags, signed bundles, device state machine, rollback/quarantine, saves, privacy, G-NET-01 (F9) |
| [docs/liveops-runbook.md](docs/liveops-runbook.md) | LiveOps runbook: key ceremony, issue/verify/deliver, rollback, quarantine, kill switches, diagnostics |
| [docs/packaging.md](docs/packaging.md) | How to build, verify and host every platform build; signing/store TODO (F7) |
| [docs/hardware-fleet.md](docs/hardware-fleet.md) | AMD-first node inventory |
| [docs/INFERENCES.md](docs/INFERENCES.md) | Register of `[INFERENCE]` decisions |

Design source: https://chat.deepseek.com/share/g90tn4mss3265u0xm3 — prefer the specs over invention; extrapolations are marked **`[INFERENCE]`**.

## Governing principle

> A Fabric milestone is **not complete** until a **game increment that depends on it ships, is playable, and passes its acceptance test.** (ADR-0016)

## Hard constraints

No LLM in the combat tick · no unsandboxed untrusted code · no client-authoritative multiplayer · no hard-coded strings/paths · every GPU path has a CPU fallback · weakest acceptance node is 2 cores, no GPU · AMD-first (DirectML/ROCm/Vulkan), never CUDA-required.

## v1 non-goals

Quantum hardware backends (simulation OK), fantasy consoles (PICO-8/TIC-80), modern console CertPacks, mod marketplace, P2P beyond 2 players, dedicated servers, M1-Architect as a ship gate.

## License & distribution

Proprietary — **All Rights Reserved** (ADR-0001). This repository is private; there are no public releases, packages, or open-source distributions. Third-party components keep their own licenses ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). Report security issues privately per [SECURITY.md](SECURITY.md).
