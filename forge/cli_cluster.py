"""`forge groundweave …` (C8) and `forge cluster …` (C7) command groups."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click


@click.group("groundweave")
def groundweave_grp() -> None:
    """GPU→CPU fallback ladder (content/groundweave/ladder.yaml)."""


@groundweave_grp.command("check")
def gw_check() -> None:
    """Static rules: every op has a real CPU rung (or gpu_required+route), every generator is declared."""
    from forge import groundweave

    r = groundweave.check()
    click.echo(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)


@groundweave_grp.command("show")
def gw_show() -> None:
    """Detected devices and the backend each op would use here."""
    from forge import groundweave

    click.echo(json.dumps(groundweave.describe(), indent=2))


@groundweave_grp.command("onnx-ep")
@click.option("--selftest", is_flag=True, help="Also run the selection/fallback/demotion contract against a fake onnxruntime.")
def gw_onnx_ep(selftest: bool) -> None:
    """Which onnxruntime execution provider this host would use (AMD-first, CPU fallback). ROCm: rocm_ready_unverified."""
    from forge import onnx_ep
    out = onnx_ep.selftest() if selftest else onnx_ep.report()
    click.echo(json.dumps(out, indent=2))
    if selftest and not out["ok"]:
        raise SystemExit(1)


@groundweave_grp.command("verify")
@click.option("--cores", type=int, default=None, help="Pin to N cores (default: acceptance_node.cores = 2).")
@click.option("--op", "ops", multiple=True, help="Limit to these op ids.")
@click.option("--no-compare", is_flag=True, help="Skip the unpinned byte-identity comparison.")
def gw_verify(cores: int | None, ops: tuple[str, ...], no_compare: bool) -> None:
    """Run every op's CPU backend pinned to the weakest node (2 cores, GPUs hidden) against its budget."""
    from forge import groundweave

    r = groundweave.verify(cores=cores, ops=list(ops) or None, compare=not no_compare)
    click.echo(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)


class _ClusterGroup(click.Group):
    """Turn transport/auth failures of client commands into one clear message instead of a traceback."""

    def invoke(self, ctx: click.Context):  # noqa: ANN201
        from forge import cluster_tls
        from forge import loomcluster as lc

        try:
            return super().invoke(ctx)
        except (lc.ClusterAuthError, cluster_tls.ClusterTLSError) as e:
            hint = ("" if "TLS" not in str(e) and "https" not in str(e)
                    else " (TLS fleet: pass `forge cluster --tls-dir <dir> …` or set FORGE_CLUSTER_TLS_DIR)")
            raise click.ClickException(f"{e}{hint}") from e
        except OSError as e:          # URLError, refused, TLS handshake failures
            raise click.ClickException(f"cluster node unreachable or refused the connection: {e}") from e


@click.group("cluster", cls=_ClusterGroup)
@click.option("--tls-dir", type=click.Path(path_type=Path), default=None,
              help="Talk to a TLS/mTLS fleet with this client's certs (`operator` unless FORGE_CLUSTER_TLS_NAME); "
                   "same as FORGE_CLUSTER_TLS_DIR.")
def cluster_grp(tls_dir: Path | None) -> None:
    """LoomCluster equal nodes (advertise / negotiate / queue / steal / retry)."""
    import os

    from forge import cluster_tls

    if tls_dir:
        os.environ[cluster_tls.DIR_ENV] = str(tls_dir.resolve())


@cluster_grp.command("node")
@click.option("--id", "node_id", required=True)
@click.option("--cores", type=int, default=None)
@click.option("--devices", default=None, help="Comma list; default = GroundWeave detection.")
@click.option("--cap", type=int, default=100, help="Allocation cap (%% of cores) the user grants this node.")
@click.option("--state-dir", type=click.Path(path_type=Path), required=True)
@click.option("--port", type=int, default=0)
@click.option("--pin", type=int, default=0, help="Pin the node and its job children to N CPUs.")
@click.option("--peer", "peers", multiple=True, help="Seed peer URL (gossip discovers the rest).")
@click.option("--bind", default=None, help="Listen address (default cluster.protocol.bind = 127.0.0.1). "
              "Off loopback use the LAN / Tailscale IP, and TLS (docs/cluster-lan-runbook.md).")
@click.option("--advertise", default=None, help="Host name/IP peers use to reach this node (must be in its TLS cert SANs).")
@click.option("--tls-dir", type=click.Path(path_type=Path), default=None,
              help="Enable TLS/mTLS with certs from `forge cluster tls-keygen` (same as FORGE_CLUSTER_TLS_DIR).")
def cluster_node(node_id: str, cores: int | None, devices: str | None, cap: int, state_dir: Path,
                 port: int, pin: int, peers: tuple[str, ...], bind: str | None, advertise: str | None,
                 tls_dir: Path | None) -> None:
    """Run one node in the foreground (prints LOOM_READY <url>). Needs the fleet secret (`forge cluster keygen`)."""
    import os

    from forge import cluster_tls
    from forge import loomcluster as lc

    if tls_dir:
        os.environ[cluster_tls.DIR_ENV] = str(tls_dir.resolve())
    try:
        lc.cluster_key()
        if cluster_tls.enabled():
            cluster_tls.server_context(os.environ.get(cluster_tls.NAME_ENV) or node_id)
    except (lc.ClusterAuthError, cluster_tls.ClusterTLSError, OSError) as e:
        raise click.ClickException(str(e)) from e
    if pin:
        lc.pin_cpus(pin)
    caps = lc.local_caps(node_id, cores, devices.split(",") if devices else None, cap)
    cfg = lc.protocol_config()
    if bind:
        cfg["bind"] = bind
    if advertise:
        cfg["advertise"] = advertise
    node = lc.Node(caps, state_dir, list(peers), cfg, port)
    node.serve(ready=lambda nd: click.echo(f"LOOM_READY {nd.url}"))


@cluster_grp.command("keygen")
def cluster_keygen() -> None:
    """Create the fleet secret `.fabric/cluster.key` (0600) if missing. Copy it to every node (or export
    FORGE_CLUSTER_SECRET); nodes refuse requests not signed with it."""
    from forge import loomcluster as lc

    click.echo(str(lc.keygen()))


@cluster_grp.command("tls-keygen")
@click.option("--name", "names", multiple=True, required=True,
              help="Node id (or `operator` for CLI clients) to issue a certificate for; repeatable.")
@click.option("--host", "hosts", multiple=True,
              help="Extra SAN: LAN IP, Tailscale IP (100.x) or MagicDNS name; localhost/127.0.0.1/::1 always included.")
@click.option("--this-host", is_flag=True, help="Also add this machine's hostname/FQDN as SANs.")
@click.option("--dir", "tls_dir", type=click.Path(path_type=Path), default=None,
              help="Default .fabric/cluster-tls/ (gitignored). The CA key never leaves this machine.")
def cluster_tls_keygen(names: tuple[str, ...], hosts: tuple[str, ...], this_host: bool, tls_dir: Path | None) -> None:
    """Create the private fleet CA (once) and issue mTLS certificates (ECDSA P-256, TLS 1.3) for nodes / operators."""
    from forge import cluster_tls

    d = tls_dir or cluster_tls.default_dir()
    hs = list(hosts) + (cluster_tls.local_hosts() if this_host else [])
    try:
        click.echo(json.dumps(cluster_tls.keygen(d, list(names), hs), indent=2))
    except cluster_tls.ClusterTLSError as e:
        raise click.ClickException(str(e)) from e


@cluster_grp.command("tls-show")
@click.option("--dir", "tls_dir", type=click.Path(path_type=Path), default=None)
def cluster_tls_show(tls_dir: Path | None) -> None:
    """List the fleet CA and issued certificates (subjects, SANs, expiry — never key material)."""
    from forge import cluster_tls

    click.echo(json.dumps(cluster_tls.describe(tls_dir or cluster_tls.default_dir()), indent=2))


@cluster_grp.command("submit")
@click.option("--to", "url", required=True)
@click.option("--op", default="hashchain", type=click.Choice(["hashchain", "gen"]))
@click.option("--brief", "brief_id", default=None, help="Brief id for --op gen.")
@click.option("--count", type=int, default=1)
@click.option("--rounds", type=int, default=100000)
def cluster_submit(url: str, op: str, brief_id: str | None, count: int, rounds: int) -> None:
    """Queue jobs on one node (it is the origin; any node may steal them)."""
    from forge import loomcluster as lc

    out = []
    for i in range(count):
        payload = {"brief_id": brief_id} if op == "gen" else {"seed": i, "rounds": rounds}
        out.append(lc._http(url.rstrip("/") + "/submit", {"op": op, "payload": payload}))
    click.echo(json.dumps(out, indent=2))


@cluster_grp.command("status")
@click.option("--to", "url", required=True)
@click.option("--results", is_flag=True)
def cluster_status(url: str, results: bool) -> None:
    from forge import loomcluster as lc

    click.echo(json.dumps(lc._http(url.rstrip("/") + ("/results" if results else "/status")), indent=2))


@cluster_grp.command("gen")
@click.option("--to", "url", required=True, help="Any node of the fleet; it becomes the origin of the batch.")
@click.option("--brief", "brief_ids", multiple=True, help="Brief ids (default: every brief).")
@click.option("--out", type=click.Path(path_type=Path), default=None,
              help="Write the returned artifact bytes under <out>/<brief>/<name>.")
@click.option("--timeout", type=float, default=600.0)
def cluster_gen(url: str, brief_ids: tuple[str, ...], out: Path | None, timeout: float) -> None:
    """Distribute Content Forge briefs over the fleet; prints per-node counts and the batch digest."""
    from forge import loomcluster as lc
    from forge.paths import find_repo_root
    from forge.pipeline import load_briefs

    ids = list(brief_ids) or [b["id"] for b in load_briefs(find_repo_root())]
    url = url.rstrip("/")
    jobs = [{"id": f"gen:{i}", "op": "gen", "payload": {"brief_id": i, "return_data": bool(out)}} for i in ids]
    res = lc.run_batch(url, jobs, timeout)
    bad = {j: r.get("error") for j, r in res.items() if not r.get("ok")}
    missing = [j["id"] for j in jobs if j["id"] not in res]
    by_node: dict[str, int] = {}
    for r in res.values():
        by_node[r["node"]] = by_node.get(r["node"], 0) + 1
    if out:     # artifact bytes come over signed /blob/<sha256> from the origin (it verified them on accept)
        for jid, r in res.items():
            for name, b in ((r.get("value") or {}).get("blobs") or {}).items():
                dest = out / jid.split(":", 1)[1] / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(lc.fetch_blob(url, b["sha256"]))
    slim = {j: {**r, "value": {k: v for k, v in (r.get("value") or {}).items() if k not in ("data_b64", "blobs")}}
            for j, r in res.items()}
    ok = not bad and not missing
    click.echo(json.dumps({"ok": ok, "jobs": len(jobs), "executed_by_node": dict(sorted(by_node.items())),
                           "batch_digest": lc.batch_digest(slim), "failed": bad, "missing": missing}, indent=2))
    sys.exit(0 if ok else 1)


@cluster_grp.command("demo")
@click.option("--jobs", type=int, default=48)
@click.option("--rounds", type=int, default=150000)
@click.option("--no-kill", is_flag=True, help="Do not SIGKILL a node mid-run.")
@click.option("--state-dir", type=click.Path(path_type=Path), default=None)
def cluster_demo(jobs: int, rounds: int, no_kill: bool, state_dir: Path | None) -> None:
    """3 local processes (1/2/4 slots); jobs submitted to the smallest; steal + failover verified."""
    import tempfile

    from forge import loomcluster as lc

    sd = state_dir or Path(tempfile.mkdtemp(prefix="loomcluster-"))
    r = lc.demo(sd, jobs=jobs, rounds=rounds, kill=not no_kill)
    r["state_dir"] = str(sd)
    click.echo(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)
