# LoomCluster (companion track C7) + GroundWeave (C8)

Implemented in `forge/loomcluster.py` (scheduler / node / fleet harness / LoomLink bridge) and `forge/groundweave.py`
(+ `content/groundweave/ladder.yaml`). This directory only documents it.

```bash
forge cluster demo                                # 3 local processes (1/2/4 slots); stealing + SIGKILL failover; digests verified
forge cluster node --id lemur --state-dir /tmp/l --pin 2 --devices cpu           # one node, pinned to 2 cores, GPU hidden
forge cluster node --id main --state-dir /tmp/m --peer http://127.0.0.1:PORT     # join a mesh from any one seed
forge cluster gen --to http://127.0.0.1:PORT --out /tmp/out                      # distribute briefs; bytes land in /tmp/out
forge link serve --cluster http://127.0.0.1:PORT                                 # phone offloads run on the fleet
forge groundweave show | check | verify
forge accept C7-C8                                # recorded in docs/acceptance-tests/results/C7.json, C8.json
```

Design, semantics and limits: [ARCHITECTURE.md](../../ARCHITECTURE.md#loomcluster--groundweave-c7--c8),
[docs/acceptance-tests/C7-C8.md](../../docs/acceptance-tests/C7-C8.md), [docs/INFERENCES.md](../../docs/INFERENCES.md) C-16…C-31.
Fleet inventory: [docs/hardware-fleet.md](../../docs/hardware-fleet.md) (mirrored in `forge.yaml` `cluster.nodes`).

**Not yet:** a multi-machine run, node↔node authentication, a Kotlin cluster peer, real GPU backends.
