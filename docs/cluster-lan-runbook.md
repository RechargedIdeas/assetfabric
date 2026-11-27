# LoomCluster across real machines — LAN / Tailscale runbook (post-F9, 0.9.1)

LoomCluster (C7) is proven on loopback processes only. This runbook is how to run it across the real fleet
(docs/hardware-fleet.md: `main` = Shivati, RX 7900 XTX; `secondary` = Vega box) with every layer of protection on:

| Layer | What it gives | How |
|---|---|---|
| Network: Tailscale / WireGuard (recommended) or a trusted wired LAN | only your machines can reach the port | Tailscale ACL / host firewall: allow TCP `47801` from fleet IPs only |
| TLS 1.3 + mTLS (0.9.1, INFERENCE C-99) | confidentiality; a node only talks to holders of a fleet-CA certificate, and checks the peer's hostname | `forge cluster tls-keygen` + `--tls-dir` |
| HMAC fleet secret (0.7.14, C-95) | every request/response signed, ±120 s window, replay guard | `forge cluster keygen` → `.fabric/cluster.key` |

Never bind a node off loopback without TLS; never expose the port to the internet. A node holding both the secret and a
certificate is fully trusted (it can submit jobs and return results).

## 1. On the CA host (Shivati) — once

```bash
source .venv/bin/activate                          # forge venv with the dev or liveops extra (cryptography)
forge cluster keygen                               # .fabric/cluster.key (0600) — the shared fleet secret
# one certificate per node, with every name/IP peers will use to reach it (+ localhost/127.0.0.1/::1 automatically)
forge cluster tls-keygen --name main      --host 100.101.102.10 --host shivati.tailnet-xyz.ts.net --this-host
forge cluster tls-keygen --name secondary --host 100.101.102.11 --host vega.tailnet-xyz.ts.net
forge cluster tls-keygen --name operator                         # for `forge cluster submit/status/gen` clients
forge cluster tls-show                                           # subjects, SANs, expiry (no key material)
```

Everything lands in `.fabric/cluster-tls/` (git-ignored): `ca.pem`, `ca.key.pem` (**stays on this machine**),
`nodes/<name>.pem` + `nodes/<name>.key.pem` (0600). Node certificates are valid 397 days, the CA 825 days.

## 2. Copy to each other machine

Copy over a trusted channel (scp over Tailscale, USB stick) — **not** chat or e-mail:

- `.fabric/cluster.key` (same file on every node), or export it as `FORGE_CLUSTER_SECRET`;
- `.fabric/cluster-tls/ca.pem`;
- that machine's own `nodes/<name>.pem` + `nodes/<name>.key.pem` (and `operator.*` where you run the CLI).

```bash
# on secondary, from main:
scp main:assetfabric/.fabric/cluster.key .fabric/
mkdir -p .fabric/cluster-tls/nodes && scp main:assetfabric/.fabric/cluster-tls/ca.pem .fabric/cluster-tls/
scp main:'assetfabric/.fabric/cluster-tls/nodes/secondary.*' .fabric/cluster-tls/nodes/
chmod 600 .fabric/cluster.key .fabric/cluster-tls/nodes/*.key.pem
```

## 3. Start the nodes

```bash
# main (Shivati) — bind the Tailscale IP (or 0.0.0.0 behind a firewall) and advertise a name that is in its cert
forge cluster node --id main --cap 80 --state-dir .fabric/cluster/main \
  --bind 100.101.102.10 --advertise 100.101.102.10 --port 47801 --tls-dir .fabric/cluster-tls
# secondary
forge cluster node --id secondary --cap 70 --state-dir .fabric/cluster/secondary \
  --bind 100.101.102.11 --advertise 100.101.102.11 --port 47801 --tls-dir .fabric/cluster-tls \
  --peer https://100.101.102.10:47801
```

Each prints `LOOM_READY https://…`. The node id selects its certificate (`nodes/<id>.pem`; override with
`FORGE_CLUSTER_TLS_NAME`). With TLS on, `http://` peers are refused (no downgrade) and the node refuses to start if its
certificate or key is missing.

## 4. Use and verify

```bash
forge cluster --tls-dir .fabric/cluster-tls submit --to https://100.101.102.10:47801 --count 24 --rounds 2000000
forge cluster --tls-dir .fabric/cluster-tls status --to https://100.101.102.11:47801   # transport: https+mtls, stolen_in > 0
forge cluster --tls-dir .fabric/cluster-tls gen --to https://100.101.102.10:47801 <brief-id> …
```

What to record for the first real two-machine run (it moves C7 from "loopback only" to proven): both `status` outputs
(`transport`, `peers`, `stats.executed` / `stolen_in` on both nodes), the batch digest from `forge cluster gen` vs a
single-node run (must be identical), a `kill -9` of `secondary` mid-batch (the origin re-queues after `lease_s`), and
`stats.tls_rejected` / `auth_rejected` after an attempt from a machine without a certificate (expected: refused).

Build-box rehearsal (0.9.1): two nodes on `127.0.0.2` / `127.0.0.3` with certificates issued exactly as above
(`--host 127.0.0.2`, `--host 127.0.0.3`) meshed over `https+mtls`, and the second node stole 3 of 6 submitted jobs.
That exercises `--bind/--advertise/--tls-dir`, not a real network.

## Rotation / revocation

There is no CRL. To revoke one node, re-issue everything: move `.fabric/cluster-tls/` aside, rerun step 1 (new CA),
copy step 2 again, restart all nodes; also rotate `.fabric/cluster.key` (delete it, `forge cluster keygen`, copy).
Rotate certificates before `not_after` (`forge cluster tls-show`).

## Troubleshooting

| Symptom | Cause |
|---|---|
| `CERTIFICATE_VERIFY_FAILED … IP address mismatch` | the URL host is not in that node's SANs — re-issue with `--host` |
| `TLSV13_ALERT_CERTIFICATE_REQUIRED` / `UNKNOWN_CA` | client has no / a foreign certificate (missing `--tls-dir`, wrong CA) |
| `plaintext peer refused while cluster TLS is on` | an `http://` seed peer — use `https://` |
| `401` | wrong or missing fleet secret, clock skew > 120 s (enable NTP), or replay |
| node unreachable | firewall / Tailscale ACL / `--bind` on the wrong interface |
