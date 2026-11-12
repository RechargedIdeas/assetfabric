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


@groundweave_grp.command("verify")
@click.option("--cores", type=int, default=None, help="Pin to N cores (default: acceptance_node.cores = 2).")
@click.option("--op", "ops", multiple=True, help="Limit to these op ids.")
def gw_verify(cores: int | None, ops: tuple[str, ...]) -> None:
    """Run every op's CPU backend pinned to the weakest node (2 cores, GPUs hidden) against its budget."""
    from forge import groundweave

    r = groundweave.verify(cores=cores, ops=list(ops) or None)
    click.echo(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)


@click.group("cluster")
def cluster_grp() -> None:
    """LoomCluster equal nodes (advertise / negotiate / queue / steal)."""


@cluster_grp.command("node")
@click.option("--id", "node_id", required=True)
@click.option("--cores", type=int, default=None)
@click.option("--devices", default=None, help="Comma list; default = GroundWeave detection.")
@click.option("--cap", type=int, default=100, help="Allocation cap (%% of cores) the user grants this node.")
@click.option("--state-dir", type=click.Path(path_type=Path), required=True)
@click.option("--port", type=int, default=0)
@click.option("--peer", "peers", multiple=True, help="Seed peer URL (gossip discovers the rest).")
def cluster_node(node_id: str, cores: int | None, devices: str | None, cap: int, state_dir: Path,
                 port: int, peers: tuple[str, ...]) -> None:
    """Run one node in the foreground (prints LOOM_READY <url>)."""
    from forge import loomcluster as lc

    caps = lc.local_caps(node_id, cores, devices.split(",") if devices else None, cap)
    node = lc.Node(caps, state_dir, list(peers), lc.protocol_config(), port)
    node.serve(ready=lambda nd: click.echo(f"LOOM_READY {nd.url}"))


@cluster_grp.command("submit")
@click.option("--to", "url", required=True)
@click.option("--op", default="hashchain", type=click.Choice(["hashchain", "gen"]))
@click.option("--brief", "brief_id", default=None, help="Brief id for --op gen.")
@click.option("--count", type=int, default=1)
@click.option("--rounds", type=int, default=100000)
def cluster_submit(url: str, op: str, brief_id: str | None, count: int, rounds: int) -> None:
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
