"""forge CLI — human + agent scripting surface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from forge import __milestone__, __version__
from forge.doctor import run_doctor
from forge.manifest import validate_manifest_file
from forge.orchestrator import JobOrchestrator
from forge.paths import find_repo_root
from forge.status import collect_status
from forge.store import AssetStore
from forge.telemetry import TelemetryStore, make_system_event, validate_event

console = Console(stderr=False)


@click.group()
@click.version_option(__version__, prog_name="forge")
def main() -> None:
    """AssetFabric Content Forge CLI."""


@main.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def status_cmd(as_json: bool, root: Path | None) -> None:
    """Report Fabric + Game Zero environment health."""
    try:
        root = root or find_repo_root()
    except FileNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        sys.exit(2)
    report = collect_status(root)
    # Emit a status telemetry heartbeat (best-effort)
    try:
        TelemetryStore(root).emit(
            make_system_event(
                "forge.status",
                action_taken={"healthy": report["healthy"]},
                action_source="system",
            )
        )
    except Exception:  # noqa: BLE001 — status must still print
        pass
    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        healthy = report["healthy"]
        color = "green" if healthy else "red"
        console.print(
            f"[bold {color}]forge status[/bold {color}]  "
            f"v{report['version']}  milestone={report['milestone']}  "
            f"{'HEALTHY' if healthy else 'UNHEALTHY'}"
        )
        table = Table(title="Components")
        table.add_column("Component")
        table.add_column("OK")
        table.add_column("Detail")
        comps = report["components"]
        table.add_row("manifest", str(comps["manifest"]["ok"]), str(comps["manifest"]["errors"] or "ok"))
        table.add_row("schemas", str(comps["schemas"]["ok"]), "ok" if comps["schemas"]["ok"] else str(comps["schemas"].get("error")))
        table.add_row("asset_store", str(comps["asset_store"]["ok"]), f"bundles={comps['asset_store']['bundle_count']}")
        table.add_row("orchestrator", str(comps["orchestrator"]["ok"]), f"jobs={comps['orchestrator']['job_count']}")
        g = comps["godot"]
        table.add_row(
            "godot",
            str(g["healthy"]),
            f"renderer={g.get('renderer')} path={g.get('path')}" + (f" err={g['errors']}" if g["errors"] else ""),
        )
        console.print(table)
        console.print("[dim]One-milestone offset:[/dim]", report["one_milestone_offset"]["rule"])
        off = report["one_milestone_offset"]
        console.print(f"[dim]Offset guard:[/dim] {'ok' if off['ok'] else 'UNPROVEN ' + str(off['unproven_prior_milestones'])}")
    sys.exit(0 if report["healthy"] else 1)


@main.command("doctor")
@click.option("--json", "as_json", is_flag=True)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def doctor_cmd(as_json: bool, root: Path | None) -> None:
    """Environment and dependency checks."""
    root = root or find_repo_root()
    report = run_doctor(root)
    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        for c in report["checks"]:
            mark = "[green]OK[/green]" if c["ok"] else "[yellow]WARN[/yellow]" if c["name"] == "godot_binary" and not c["ok"] else "[red]FAIL[/red]"
            console.print(f"{mark}  {c['name']}: {c['detail']}")
        console.print(report["note"])
    # doctor ok ignores advisory godot_binary
    sys.exit(0 if report["ok"] else 1)


@main.command("validate")
@click.argument("what", type=click.Choice(["manifest", "telemetry-event"]), default="manifest")
@click.option("--file", "file_path", type=click.Path(path_type=Path), default=None)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def validate_cmd(what: str, file_path: Path | None, root: Path | None) -> None:
    """Validate schemas (manifest or a telemetry event JSON file)."""
    root = root or find_repo_root()
    if what == "manifest":
        path = file_path or (root / "forge.yaml")
        errors = validate_manifest_file(path, root)
        if errors:
            for e in errors:
                console.print(f"[red]{e}[/red]")
            sys.exit(1)
        console.print("[green]manifest OK[/green]")
        return
    if not file_path:
        console.print("[red]--file required for telemetry-event[/red]")
        sys.exit(2)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    errors = validate_event(payload, root)
    if errors:
        for e in errors:
            console.print(f"[red]{e}[/red]")
        sys.exit(1)
    console.print("[green]telemetry event OK[/green]")


@main.command("job")
@click.argument("action", type=click.Choice(["enqueue", "list"]))
@click.option("--kind", default="noop")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def job_cmd(action: str, kind: str, root: Path | None) -> None:
    """Job orchestrator stub controls."""
    root = root or find_repo_root()
    orch = JobOrchestrator(root)
    if action == "enqueue":
        job = orch.enqueue(kind, {"source": "cli"})
        click.echo(json.dumps({"id": job.id, "kind": job.kind, "state": job.state.value}))
    else:
        jobs = orch.list_jobs()
        click.echo(json.dumps([{"id": j.id, "kind": j.kind, "state": j.state.value} for j in jobs], indent=2))


@main.command("store")
@click.argument("action", type=click.Choice(["put", "stats"]))
@click.option("--file", "file_path", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def store_cmd(action: str, file_path: Path | None, root: Path | None) -> None:
    """Asset store scaffolding commands."""
    root = root or find_repo_root()
    store = AssetStore(root)
    if action == "stats":
        click.echo(json.dumps(store.health(), indent=2))
        return
    if not file_path:
        console.print("[red]--file required for put[/red]")
        sys.exit(2)
    data = file_path.read_bytes()
    bundle = store.put(data, media_type="application/octet-stream", provenance={"source_path_key": "cli.put"})
    click.echo(json.dumps({"digest": bundle.digest, "size": bundle.size}))


@main.command("build")
@click.option("--brief", "pattern", default="**/*.yaml", help="Glob under content/briefs/.")
@click.option("--no-export", is_flag=True, help="Generate + gate + store only; do not write into the game.")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def build_cmd(pattern: str, no_export: bool, root: Path | None) -> None:
    """Run content briefs through generators → gates → store → Godot export."""
    from forge.pipeline import build_all

    report = build_all(root or find_repo_root(), pattern, export=not no_export)
    click.echo(json.dumps(report, indent=2))
    sys.exit(0 if report["ok"] else 1)


@main.command("gen")
@click.argument("brief_id")
@click.option("--seed", type=int, default=None, help="Override the brief seed (exploration).")
@click.option("--no-export", is_flag=True)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def gen_cmd(brief_id: str, seed: int | None, no_export: bool, root: Path | None) -> None:
    """Generate a single brief by id."""
    from forge.pipeline import Context, load_briefs, run_brief

    ctx = Context.create(root)
    briefs = {b["id"]: b for b in load_briefs(ctx.root)}
    if brief_id not in briefs:
        console.print(f"[red]unknown brief {brief_id!r}[/red]; known: {sorted(briefs)}")
        sys.exit(2)
    b = dict(briefs[brief_id])
    if seed is not None:
        b["seed"] = seed
    out = run_brief(b, ctx, export=not no_export)
    click.echo(json.dumps({"ok": out.ok, "gates": [g.__dict__ for g in out.gates], "files": out.meta.get("files")}, indent=2, default=str))
    sys.exit(0 if out.ok else 1)


@main.command("palette")
@click.argument("name", required=False)
@click.option("--variant", default=None, help="Colour-blind variant (deuteranopia, protanopia).")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def palette_cmd(name: str | None, variant: str | None, root: Path | None) -> None:
    """PatternVault: list palettes or show one as swatches (SwatchStudio CLI echo)."""
    from forge.imaging import rgba_to_hex
    from forge.patternvault import PatternVault

    vault = PatternVault(root or find_repo_root())
    if not name:
        for n in vault.names():
            p = vault.get(n)
            console.print(f"{p.ref:20s} " + " ".join(f"[on {rgba_to_hex(c)}]  [/]" for c in p.colours) + f"  {p.description}")
        console.print(f"[dim]variants: {', '.join(vault.variants())}[/dim]")
        return
    p = vault.get(name, variant)
    for i, c in enumerate(p.colours):
        console.print(f"[on {rgba_to_hex(c)}]      [/] {i}: {rgba_to_hex(c)}")


@main.command("accept")
@click.argument("milestone")
@click.option("--no-write", is_flag=True, help="Do not record docs/acceptance-tests/results/<F>.json.")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def accept_cmd(milestone: str, no_write: bool, root: Path | None) -> None:
    """Run the Game Zero headless acceptance for a Fabric milestone (needs Godot)."""
    from forge.milestones import INCREMENTS, accept

    if milestone not in INCREMENTS:
        console.print(f"[red]unknown milestone {milestone}; known {sorted(INCREMENTS)}[/red]")
        sys.exit(2)
    report = accept(milestone, root or find_repo_root(), write=not no_write)
    click.echo(json.dumps(report, indent=2))
    sys.exit(0 if report["passed"] else 1)


@main.command("report")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def report_cmd(root: Path | None) -> None:
    """Regenerate STATUS.md (milestone dashboard) from recorded acceptance results."""
    from forge.report import write

    click.echo(str(write(root or find_repo_root())))


if __name__ == "__main__":
    main()
