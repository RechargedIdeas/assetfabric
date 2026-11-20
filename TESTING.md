# TESTING.md — QA strategy, acceptance & CI gates

Every Fabric milestone is proven by an **executable acceptance test** and a playable Game Zero increment (ADR-0016). Source: `docs/design/ASSETFABRIC_SPEC.md` §12–14 and `docs/design/GAME_SPEC.md` §6.

## 1. Test pyramid

| Layer | Scope | Location | Status |
|---|---|---|---|
| Unit | schemas, pure functions | `tests/` | F0 ✅ |
| Component | store, orchestrator, CLI | `tests/` | F0 ✅ |
| Integration | generators → gates → store → registry; determinism; codegen; audio; AI models; sandbox tiers, live channel, statecharts, guardian | `tests/test_f1_pipeline.py`, `tests/test_f2_codegen_audio.py`, `tests/test_f3_ai.py`, `tests/test_f4_substrate.py`, `tests/test_f5_balance_save.py`, `tests/test_f6_world.py` | F1–F6 ✅ |
| Headless game | Godot `--headless` autoplay per increment (incl. GDScript↔Python model parity); F4 also drives a live process under the guardian; F5 runs the 2400-fight Monte Carlo matrix + save round-trip; F6 plays the whole vertical slice with the QA autopilot, quits + resumes in a new process, and runs the selection matrix (2 in pytest/CI via `FORGE_ACCEPT_FAST=1`, 12 in `forge accept F6`) | `tests/test_game_increments.py`, `forge accept` | F0–F6 ✅ |
| Acceptance | milestone gates | `docs/acceptance-tests/F*.md`, `forge accept F0..F6` | F0–F6 ✅ |
| Fleet / fallback | LoomCluster (loopback processes: determinism over 1/2/3 nodes, stealing, SIGKILL failover, retry, origin restart, device placement, LoomLink bridge) and GroundWeave (ladder rules, runtime demotion, pipeline enforcement, 2-core GPU-hidden byte-identical verify) | `tests/test_c7_c8.py` (fast, ≈ 7 s), `forge accept C7-C8` (full, ≈ 80 s) | C7/C8 ✅ |
| Perf / fidelity | Retro authenticity (V1); GroundWeave 2-core budgets are now gated by `forge groundweave verify` | later | F1+ |
| Balance / soft-lock | Monte Carlo G-BAL-01 (sharded headless workers), soft-lock static + runtime detector | `forge balance run`, `forge softlock`, `forge accept F5` | F5 ✅ |
| Hybrid QA | Scripted QA autopilot plays the slice headless (F6 ✅); human GUI playtest checklist in F6.md (pending) | `world/autopilot.gd`, `docs/acceptance-tests/F6.md` | F6 ◐ |

## 2. Running tests

```bash
source .venv/bin/activate
pytest -q                         # unit + component (≈ 14 min with Godot)
forge accept F7                   # F7 full: exports + platform proofs (local; see docs/packaging.md)
forge accept C7-C8                # LoomCluster loopback fleet + GroundWeave 2-core/no-GPU proofs (Godot for the GIRT/balance probes; JDK+SDK adds the Kotlin LoomLink hop)
forge groundweave verify          # every op's CPU path: 2 cores pinned, GPUs hidden, budget + byte-identity vs unpinned / simulated-GPU runs
forge cluster demo                # 3 local nodes, work stealing + SIGKILL failover
forge accept C1-C6                # PocketLoom: gradle tests + debug APK + lint + Kotlin↔Python LoomLink interop (JDK 17 + Android SDK)
(cd companions/pocketloom && ./gradlew :fabriccore:test)   # FabricCore JVM unit tests only
forge validate manifest           # forge.yaml against schema
forge status                      # exit 0 == healthy
forge doctor                      # env checks (godot binary advisory)
./scripts/smoke_godot.sh          # structure check + headless boot if Godot present
REQUIRE_GODOT=1 ./scripts/smoke_godot.sh   # fail if Godot is missing
```

## 3. F0 acceptance matrix

| ID | Criterion | Proof |
|---|---|---|
| F0-DOC | Doc suite (SPEC §11) present | files exist (`tests/test_status.py`) |
| F0-MAN | `forge.yaml` validates | `forge validate manifest`, `tests/test_manifest.py` |
| F0-TEL | Telemetry schema validates events | `tests/test_telemetry.py` |
| F0-CLI | `forge status` healthy | CLI exit 0 |
| F0-STO | Asset store put/get round-trip | `tests/test_store_orchestrator.py` |
| F0-ORC | Orchestrator enqueue/list | `tests/test_store_orchestrator.py` |
| F0-GOD | Godot project well-formed, Compatibility renderer, boots headless | `tests/test_godot_project.py` + smoke |
| F0-OFF | One-milestone offset documented; F1 blocked | AGENTS.md / BUILD_ORDER.md |

Checklist form: [`docs/acceptance-tests/F0.md`](docs/acceptance-tests/F0.md).

## 3b. Milestone acceptance

Each milestone has a checklist in `docs/acceptance-tests/F<n>.md` and an executable increment in `forge/milestones.py`. `forge accept F<n>` runs Godot headless with the increment's args, parses the `FABRIC_RESULT` JSON line, checks criteria, and records `docs/acceptance-tests/results/F<n>.json`. `forge status` fails if a prior milestone lacks a passing record (offset guard).

| Milestone | Checklist | Increment |
|---|---|---|
| F0 | [F0.md](docs/acceptance-tests/F0.md) | env-boots |
| F1 | [F1.md](docs/acceptance-tests/F1.md) | sandbox-encounter |
| F2 | [F2.md](docs/acceptance-tests/F2.md) | first-combat |
| F3 | [F3.md](docs/acceptance-tests/F3.md) | party-ai |
| F4 | [F4.md](docs/acceptance-tests/F4.md) | live-tune (custom runner: backlog run + guardian-supervised serve run) |
| F5 | [F5.md](docs/acceptance-tests/F5.md) | first-boss (custom runner: boss clear ×2 + save round-trip + 2400-fight balance matrix + soft-lock probe; ≈ 2 min on 8 vCPU, ≈ 7–9 min on 2 cores) |
| F6 | [F6.md](docs/acceptance-tests/F6.md) | vertical-slice (custom runner: slice playthrough + quit/resume parity + selection matrix + parity + world gates; ≈ 30 s on 8 vCPU full, ≈ 15 s fast) |
| C7–C8 | [C7-C8.md](docs/acceptance-tests/C7-C8.md) | loomcluster / groundweave (companion track: loopback fleet of OS processes + CPU-fallback proofs; ≈ 50 s + ≈ 25 s; fast mode = smaller batches, no Kotlin hop) |
| C1–C6 | [C1-C6.md](docs/acceptance-tests/C1-C6.md) | pocketloom (companion track, not an F-gate: Gradle build once → JUnit + aapt/apksigner/lint + `fabriccore-all.jar` driven against the Python LoomLink server; ≈ 75 s with warm Gradle caches; fast mode = Python half + static scans) |
| F7 | [F7.md](docs/acceptance-tests/F7.md) | launch-candidates (custom runner: `forge build --target all` + desktop slice in a network-less namespace + Android content slice + G-SAVE-01 ring desktop → Android → Web → desktop + PWA smoke + remap; ≈ 2.5 min full, ≈ 3 s fast) |

## 4. CI gates

Workflow: `.github/workflows/ci.yml` (Ubuntu, `uv`, cached Godot 4.3 download). On every push to `main` / `feat/**` and every PR:

1. Install `.[dev]` into a venv.
2. `forge status` (must exit 0 — includes the offset guard).
3. `pytest -q` — unit, pipeline, **determinism gate** (regenerated assets == committed), and **headless Godot increments** for every registered milestone.
4. `REQUIRE_GODOT=1 scripts/smoke_godot.sh`.

PocketLoom: job **`pocketloom`** (setup-java 17, Gradle cache via `gradle/actions/setup-gradle`, runner Android SDK) runs `forge accept C1-C6 --no-write` in full mode; `tests/test_companions.py` (Python half, shared vectors, fast-mode accepts) runs in the main job. Pushes to `feat/**` branches also run CI.

F7: the F7 **fast** subset runs inside pytest (presets, manifest targets, ShuttleLine vs sources, BoltPack SBOM + license audit for every target, network-API scan, editor save/remap round-trip). Platform exports + `forge accept F7` (full) are **local-only** (≈1 GB templates, JDK + Android SDK, headless Chrome; ≈ 2.5 min) — see [docs/packaging.md §CI](docs/packaging.md#ci). Planned: cached `package` job, Windows runner for DirectML. `[INFERENCE: workflow shape]`

## 5. Performance & fidelity contracts

- **Weakest acceptance node:** 2 CPU cores, no GPU. Every acceptance test must pass there.
- Generator runtime budgets (SPEC §5.1): authoring 50–500 ms; runtime <100 ms where claimed.
- Optimal swap forward-sim <50 ms; mobile upscale <5 ms (target).
- Web PWA <45 MB compressed (G-WEB-01, gated by PWAPipeline at F7: sum of gzip-9 sizes).

## 6. Game acceptance (later milestones)

See `docs/design/GAME_SPEC.md` §6: vertical slice (F6), system acceptance (G-AI, G-NET, G-BAL…), and the milestone ↔ game increment table.

## 7. Rules

- A test must fail before and pass after the change it proves.
- No milestone is accepted on "passes on one machine".
- Flaky tests are bugs: file in `TODO.md` §Bugs; do not mark xfail silently.
