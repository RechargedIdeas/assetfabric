# Substrate (F4) — sandbox · atomic hot reload · snapshots · statecharts · guardian

Implements ASSETFABRIC_SPEC §6.2–6.3 on hosts **without KVM** (the reference box exposes `/dev/kvm` without access). Everything here is CPU-only and runs on the 2-core acceptance node.

## 1. Sandbox tiers (`forge/sandbox.py`, ADR-0007)

| Tier | Isolation | Status on the reference box |
|---|---|---|
| `firecracker` | micro-VM | **detected only** — no launcher (needs usable `/dev/kvm`, guest kernel + rootfs). Reports `available=false` with the reason |
| `gvisor` | user-space kernel (`runsc`) | **detected only** — `runsc` missing, no launcher |
| `bwrap` | Linux namespaces: user/pid/net/ipc/uts, read-only `/`, private `/tmp`, only the scratch dir writable, no network, rlimits | **real, default** where unprivileged namespaces work |
| `process` | subprocess + rlimits (CPU, AS, FSIZE, NOFILE, no core), scrubbed env, scratch cwd + `TMPDIR`, PEP 578 audit hook refusing sockets and writes outside scratch | **real fallback** (e.g. GitHub runners with AppArmor-restricted userns). Best effort: a hostile *native* extension can bypass the audit hook — this tier is for first-party generators, not hostile code |

`best_tier()` walks the ladder top-down and picks the first tier that is available **and** has a launcher; forcing an unavailable tier raises. Lifecycle `CREATED → PROVISIONING → RUNNING → (SNAPSHOTTING | RESTORING) → TERMINATED`, every transition emitted to telemetry with `sandbox_id` + `profile`. Profiles: `gen` (60 s CPU, 2 GiB), `short`, `train`. Scratch-dir disk snapshots (tar.gz) stand in for Microsandbox disk snapshots.

Worker protocol: `python -m forge.sandbox_worker` reads one JSON request on stdin (`generate` or `exec`) and prints one JSON line. Sandboxed generator output is **byte-identical** to in-process output (tested for every available tier).

```bash
forge sandbox doctor                    # which tiers this host really provides
forge sandbox run spr_rock_brute        # one brief in the best tier, gates + wall/cpu stats
forge build --sandbox auto              # every generator job sandboxed
```

## 2. Live channel — atomic hot reload + live tune (`forge/live.py` ↔ `autoload/live.gd`)

File-based (no sockets), works headless, in CI and on desktop dev builds. Default dir `.fabric/live/game-zero/` (gitignored).

1. **Ticket** — monotonic number under an `flock`; `tickets/<n>.json` then `HEAD` written via temp + `fsync` + `os.replace` (readers see the old or new HEAD, never half).
2. **Stage / validate in isolation** — assets are regenerated inside the sandbox and staged under `stage/<n>/` with sha256; numeric patches are validated against `tune_limits` (from `content/tune/limits.yaml`, exported into `game_data.json` by codegen). Structural changes (new units, ability lists, ids) are refused → `forge build`.
3. **Prepare (game)** — the game re-validates every patch (limits, finite, existing numeric leaf) and every staged file's sha256 (defense in depth: a ticket that bypassed forge validation is **rejected**).
4. **Commit at a tick boundary** — `inflight.json` marks the ticket, then snapshot sim + data overlay, apply patches, re-derive stats through the same builder path as encounter load (`EncounterBuilder.restat`: pet bonuses, tiers, HP ratio kept), swap textures.
5. **Health probe** — forward-simulate a clone 90 ticks; invariant violation (NaN position, HP out of range, unresolvable cast) → **rollback** to the exact pre-commit state hash.
6. **Ack** — `acks/<n>.json` with `committed | rejected | rolled_back | quarantined`, hashes, apply µs.

```bash
forge live serve --allow-fault-injection --headless   # game under the guardian
forge live set enemies.rock_brute.stats.hp=30 sim.leash=72
forge live sprite spr_rock_brute --seed 7              # sandboxed regen + hot swap
forge live watch                                       # edit content/roster/*.yaml → live patches
forge live status
```

## 3. Snapshots + WAL (Tier 2: application/ECS)

`CombatSim.to_snapshot()/restore()` capture the full sim (entities incl. inline ability numbers, cooldowns, casts, brain memory, tunables); `full_hash()` hashes it at full float precision. A session WAL records commands, swaps and committed tickets. **Restore from disk + WAL replay reproduces the final state hash** (F4 acceptance). Serve mode writes an atomic session snapshot (`snapshots/auto.json`) every 300 ticks and after every commit. Tier 1 (micro-VM) and Tier 3 (CRIU) are not implemented.

## 4. Parallel statecharts (`sim/statechart.gd` ↔ `forge/statechart.py`)

SCXML subset: concurrent regions, event fan-out in sorted region order, named guards, final states. Game Zero's `live_session` chart runs **combat / movement / ai / dialogue / reload** concurrently. Python adds static soft-lock analysis (unreachable, dead ends, traps, dangling targets) used as a gate; the F4 acceptance replays the game's event log in Python and requires identical state (parity).

## 5. Guardian (`forge/guardian.py`)

Supervises a child: crash (non-zero / signal) or hang (heartbeat `status.json` older than `hang_s`) → SIGKILL the process group → exponential backoff (`base·factor^k`, capped) → restart with `--live-resume`; > `max_restarts` in `window_s` → `gave_up`. On resume the game restores the session snapshot, **quarantines** the ticket that was in flight when the previous process died (a poison ticket is never re-applied), and re-applies committed tickets after the snapshot. Failover ladder status: in-sandbox rollback ✅ · sandbox/session restore ✅ · session host migration ❌ (LoomCluster, later) · predictive Crash Predictor ❌.

## 6. Not done / honest limits

- No micro-VM or gVisor launcher (no usable KVM here); `process` tier is best-effort.
- Hot reload covers numeric data, `sim.*` params and sprite textures; not GDScript code, tilemaps or audio (→ `forge build` + restart).
- Live channel is local-filesystem only (no remote Studio transport yet).
