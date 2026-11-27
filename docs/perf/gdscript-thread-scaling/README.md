# GDScript worker-thread scaling (Godot 4.3) — why the swap advisor stops at ~1.3× on 2 cores

Standalone microbenchmark behind INFERENCE C-88 / quality gap P3. Four equal tasks, run serially and as one
`WorkerThreadPool` group task; each task touches only **its own** objects/containers.

```bash
taskset -c 0,1 godot --headless --path docs/perf/gdscript-thread-scaling -s bench.gd
```

Measured 2026-11-20 on the 8-vCPU reference box (Intel Xeon, no SMT), pinned to 2 cores (speed-up = serial / threaded;
2.0 would be perfect):

| Workload | Editor binary | `linux_release` template |
|---|---|---|
| iterate private `RefCounted` objects, typed loop var | 0.76× | 1.08× |
| same, untyped | 0.79× | 0.86× |
| method calls on private objects | 0.65× | 0.89× |
| allocate small Dictionary + Array | 0.34× | 0.62× |
| (control) private Dictionary reads with literal keys | 1.98× | — |
| (control) private PackedFloat64Array reads | 1.97× | — |

Object-Variant traffic and allocation serialise across threads even with nothing shared at the script level, so a forward
sim built from `SimEntity` objects cannot scale on 2 cores in GDScript. The remaining fix path is a native step function
(GDExtension) or a full struct-of-arrays rewrite of `CombatSim`; neither is done (TODO P3 follow-up).

## Last attempt before landing Q3 (2026-11-20)

Worst freeze state (party_ai tick 300, 15 entities, 4 candidates), **serial** `rank()` on one pinned core, best of 5:

| Variant | ms |
|---|---|
| shipped (BT + GIRT policy, LOD 4) | 54.8–57.8 |
| brains never think (movement, casts, cooldowns only) | 22.8–24.0 |
| rule brain instead of BT | 31.6–32.5 |
| GIRT policy disabled | 48.6–50.7 |
| cooldown decrement loop removed | no change |

Thread pool sized to the affinity mask (`/proc/self/status` `Cpus_allowed_list`, so 2 tasks instead of 4 on a 2-core
pin): p95 36.9–41.8 ms over 6 runs vs 38.0–40.8 ms before — within noise, **not shipped**. One task (serial) on the same
pin: p95 ≈ 56 ms. The cost is spread across interpreted movement, BT and policy code, not one hot spot, so no
remaining GDScript-level change gets the ≈ 25 % needed on GitHub's slower 2-core runners. The native step (GDExtension)
stays the follow-up; it was not attempted because the box has no C++ toolchain and a native sim needs per-platform
builds (Linux, Windows, Android arm64, Web with dlink templates) plus a bit-parity gate against the GDScript sim.

## 0.9.2 — native step feasibility (2026-11-27, INFERENCE C-104)

Toolchain: g++ 14.2.0 (Debian) + SCons are now on the build box. `godot-cpp` tag `godot-4.3-stable` (`fbbf9ec`) builds
cleanly: `scons platform=linux target=template_release -j8` → `libgodot-cpp.linux.template_release.x86_64.a` (75 MB) in
1 min 41 s wall on 8 vCPU (≈ 5–7 min expected on a 2-core runner without cache). So building an extension is feasible.

What a native piece would buy — swapbench pinned to 2 cores (`taskset -c 0,1`, `--reps=5`), same box, 2 runs each:

| Variant | p50 ms | p95 ms |
|---|---|---|
| shipped (GDScript) | 21.59 / 22.04 | 38.21 / 35.97 |
| `move()` short-circuited in forward clones (upper bound of a native movement kernel) | 19.39 / 20.49 | 31.96 / 36.55 |

Even a free movement step saves ≈ 5–15 %; GitHub's 2-core runners need ≈ 25 % (63–66 → < 50 ms). The rest of the cost is
brains (BT interpreter + GIRT policy ≈ 55 % per the table above), casts and cooldowns — all reading `SimEntity` objects. So
the only native change that closes the gap is the **whole forward sim** in C++ (combat sim, entities, grid flow fields,
BT interpreter, GIRT policy), fed from the struct-of-arrays mirror and gated by a bit-parity check against the GDScript
sim (Godot's `Vector2` is float32 while GDScript `float` is double — every conversion point must be replicated), plus
Linux/Windows/Android-arm64/Web(dlink) binaries and a cached CI build. That is scoped as its own milestone; nothing native
was added in 0.9.2 and the GDScript path remains the only implementation.

Reproduce the probe: copy `games/game-zero` to a scratch dir, insert at the top of `CombatSim.move()`
`if forward: e.moving = dir.length_squared() > 0.0001; return`, then run
`taskset -c 0,1 godot --headless --path <scratch> -- --scene=swapbench --reps=5`.

