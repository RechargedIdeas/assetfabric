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
