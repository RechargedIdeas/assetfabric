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
@click.option("--sandbox", "sandbox_tier", default=None, type=click.Choice(["auto", "bwrap", "process"]),
              help="Run every generator job inside a Substrate sandbox tier (F4).")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def build_cmd(pattern: str, no_export: bool, sandbox_tier: str | None, root: Path | None) -> None:
    """Run content briefs through generators → gates → store → Godot export."""
    from forge.pipeline import build_all

    report = build_all(root or find_repo_root(), pattern, export=not no_export, sandbox=sandbox_tier)
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


@main.group("sandbox")
def sandbox_grp() -> None:
    """Substrate sandbox tiers (F4): firecracker / gvisor / bwrap / process."""


@sandbox_grp.command("doctor")
def sandbox_doctor() -> None:
    """Probe which isolation tiers this host can actually provide."""
    from forge.sandbox import describe

    click.echo(json.dumps(describe(), indent=2))


@sandbox_grp.command("run")
@click.argument("brief_id")
@click.option("--tier", default="auto", type=click.Choice(["auto", "bwrap", "process"]))
@click.option("--root", type=click.Path(path_type=Path), default=None)
def sandbox_run(brief_id: str, tier: str, root: Path | None) -> None:
    """Generate one brief inside a sandbox (no export) and report gates + sandbox stats."""
    from forge import sandbox
    from forge.pipeline import load_briefs

    root = root or find_repo_root()
    briefs = {b["id"]: b for b in load_briefs(root)}
    if brief_id not in briefs:
        console.print(f"[red]unknown brief {brief_id!r}[/red]")
        sys.exit(2)
    out = sandbox.generate(briefs[brief_id], root, tier=tier)
    click.echo(json.dumps({"ok": out.ok, "sandbox": out.meta["sandbox"], "gates": {g.gate: g.ok for g in out.gates},
                           "artifacts": [a.name for a in out.artifacts]}, indent=2))
    sys.exit(0 if out.ok else 1)


@main.group("live")
def live_grp() -> None:
    """Live channel to a running game (F4): hot reload + live tune, no rebuild."""


def _channel(live_dir: Path | None, root: Path | None):
    from forge.live import LiveChannel

    return LiveChannel(live_dir, root or find_repo_root())


_live_dir_opt = click.option("--live-dir", type=click.Path(path_type=Path), default=None,
                             help="Default: .fabric/live/game-zero (the game's default too).")


def _finish(ch, n: int | None, wait: float) -> None:
    out: dict = {"ticket": n}
    if n and wait > 0:
        out["ack"] = ch.wait_ack(n, wait)
    click.echo(json.dumps(out, indent=2))
    sys.exit(0 if not out.get("ack") or out["ack"]["status"] == "committed" else 1)


@live_grp.command("set")
@click.argument("assignments", nargs=-1, required=True)
@_live_dir_opt
@click.option("--wait", default=5.0, help="Seconds to wait for the game's ack (0 = fire and forget).")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def live_set(assignments: tuple[str, ...], live_dir: Path | None, wait: float, root: Path | None) -> None:
    """Tune values: forge live set enemies.rock_brute.stats.hp=30 sim.leash=64"""
    from forge.live import LiveError

    patches = []
    for a in assignments:
        if "=" not in a:
            console.print(f"[red]expected path=value, got {a!r}[/red]")
            sys.exit(2)
        k, v = a.split("=", 1)
        patches.append({"path": k, "value": float(v) if "." in v or "e" in v.lower() else int(v)})
    ch = _channel(live_dir, root)
    try:
        n = ch.push(patches, source="forge live set")
    except LiveError as exc:
        console.print(f"[red]rejected:[/red] {exc}")
        sys.exit(1)
    _finish(ch, n, wait)


@live_grp.command("sprite")
@click.argument("brief_id")
@click.option("--seed", type=int, default=None)
@click.option("--tier", default="auto", type=click.Choice(["auto", "bwrap", "process"]))
@_live_dir_opt
@click.option("--wait", default=5.0)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def live_sprite(brief_id: str, seed: int | None, tier: str, live_dir: Path | None, wait: float, root: Path | None) -> None:
    """Regenerate a sprite brief in the sandbox and hot-swap it into the running game."""
    ch = _channel(live_dir, root)
    _finish(ch, ch.push_sprite(brief_id, seed, tier), wait)


@live_grp.command("push")
@click.option("--tier", default="auto", type=click.Choice(["auto", "bwrap", "process"]))
@_live_dir_opt
@click.option("--wait", default=5.0)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def live_push(tier: str, live_dir: Path | None, wait: float, root: Path | None) -> None:
    """Re-run codegen on content/roster (sandboxed) and push numeric changes live."""
    from forge.live import LiveError

    ch = _channel(live_dir, root)
    try:
        n, patches = ch.push_roster(tier)
    except LiveError as exc:
        console.print(f"[red]rejected:[/red] {exc}")
        sys.exit(1)
    console.print(f"{len(patches)} patch(es)")
    _finish(ch, n, wait)


@live_grp.command("watch")
@click.option("--interval", default=0.5)
@click.option("--tier", default="auto", type=click.Choice(["auto", "bwrap", "process"]))
@_live_dir_opt
@click.option("--root", type=click.Path(path_type=Path), default=None)
def live_watch(interval: float, tier: str, live_dir: Path | None, root: Path | None) -> None:
    """Watch content/roster/*.yaml; on save, push numeric changes to the running game."""
    import time as _t

    from forge.live import LiveError

    ch = _channel(live_dir, root)
    src = ch.root / "content" / "roster"

    def sig() -> tuple:
        return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in src.glob("*.yaml")))

    last = sig()
    console.print(f"watching {src} → {ch.dir} (Ctrl-C to stop)")
    while True:
        _t.sleep(interval)
        cur = sig()
        if cur == last:
            continue
        last = cur
        try:
            n, patches = ch.push_roster(tier)
            console.print(f"ticket {n}: {len(patches)} patch(es)" if n else "no numeric change")
        except LiveError as exc:
            console.print(f"[yellow]{exc}[/yellow]")


@live_grp.command("serve")
@click.option("--scene", default="live", help="Game Zero scene to serve (default: live).")
@click.option("--encounter", default=None)
@click.option("--headless/--windowed", default=False)
@click.option("--hang-s", default=5.0, help="Heartbeat staleness that counts as a hang.")
@click.option("--allow-fault-injection", is_flag=True, help="Honour fault=probe|crash|hang tickets (testing only).")
@_live_dir_opt
@click.option("--root", type=click.Path(path_type=Path), default=None)
def live_serve(scene: str, encounter: str | None, headless: bool, hang_s: float, allow_fault_injection: bool,
               live_dir: Path | None, root: Path | None) -> None:
    """Run Game Zero under the Guardian (crash/hang → restart with backoff + --live-resume)."""
    from forge.guardian import Guardian, GuardianPolicy
    from forge.manifest import load_manifest
    from forge.milestones import godot_binary

    root = root or find_repo_root()
    ch = _channel(live_dir, root)
    gb = godot_binary(root)
    if not gb:
        console.print("[red]Godot binary not found[/red]")
        sys.exit(2)
    project = root / load_manifest(None, root).game.project_path
    argv = [gb, *(["--headless"] if headless else []), "--path", str(project), "--", f"--scene={scene}",
            "--serve", f"--live-dir={ch.dir}"] + (["--autoplay"] if headless else [])
    if encounter:
        argv.append(f"--encounter={encounter}")
    if allow_fault_injection:
        argv.append("--allow-fault-injection")
    g = Guardian(argv, ch.dir, heartbeat=ch.dir / "status.json", restart_args=["--live-resume"],
                 policy=GuardianPolicy(hang_s=hang_s), log_child=ch.dir / "godot.log", root=root)
    console.print(f"guardian: serving {scene} on {ch.dir} (Ctrl-C to stop)")
    try:
        status = g.run()
    except KeyboardInterrupt:
        g._stop.set()
        g._kill()
        status = "stopped"
    click.echo(json.dumps(g.summary(), indent=2))
    sys.exit(0 if status in ("exited", "stopped") else 1)


@live_grp.command("status")
@_live_dir_opt
@click.option("--root", type=click.Path(path_type=Path), default=None)
def live_status(live_dir: Path | None, root: Path | None) -> None:
    """Show HEAD ticket, the game's last status and recent acks."""
    ch = _channel(live_dir, root)
    acks = sorted((ch.dir / "acks").glob("*.json"), key=lambda p: int(p.stem))[-5:]
    click.echo(json.dumps({"dir": str(ch.dir), "head": ch.head(), "game": ch.status(),
                           "acks": [json.loads(p.read_text()) for p in acks]}, indent=2))


@main.group("balance")
def balance_grp() -> None:
    """Monte Carlo balance runner + Bayesian tuning (F5, G-BAL-01)."""


def _parse_sets(assignments: tuple[str, ...]) -> list[dict]:
    out = []
    for a in assignments:
        k, v = a.split("=", 1)
        out.append({"path": k, "value": float(v) if "." in v or "e" in v.lower() else int(v)})
    return out


@balance_grp.command("run")
@click.option("--encounter", default="boss_warden")
@click.option("--seeds", default=200, help="Seeds per matchup (12 matchups; 200 → 2400 encounters).")
@click.option("--seed-base", default=1000)
@click.option("--variance", default=0.20, help="± damage roll (BalanceConfig default).")
@click.option("--workers", default=0, help="Godot worker processes (0 = CPU count).")
@click.option("--set", "sets", multiple=True, help="Override path=value (live-tune limits apply).")
@click.option("--out", type=click.Path(path_type=Path), default=None)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def balance_run(encounter: str, seeds: int, seed_base: int, variance: float, workers: int, sets: tuple[str, ...],
                out: Path | None, root: Path | None) -> None:
    """Run the matchup matrix and report win rates, CIs, deviation and the G-BAL-01 verdict."""
    from forge.balance import BalanceConfig, run

    agg = run(BalanceConfig(encounter=encounter, seeds=seeds, seed_base=seed_base, variance=variance, workers=workers,
                            overrides=_parse_sets(sets)), root or find_repo_root())
    text = json.dumps(agg, indent=2)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
    click.echo(text)
    sys.exit(0 if agg["verdict"]["G-BAL-01"] else 1)


@balance_grp.command("tune")
@click.option("--trials", default=30)
@click.option("--seeds", default=60)
@click.option("--out", type=click.Path(path_type=Path), default=None)
@click.option("--root", type=click.Path(path_type=Path), default=None)
def balance_tune(trials: int, seeds: int, out: Path | None, root: Path | None) -> None:
    """Optuna TPE search over forge.balance.TUNE_SPACE; prints the best overrides (apply them to content/roster)."""
    from forge.balance import tune

    res = tune(trials=trials, seeds=seeds, root=root or find_repo_root())
    text = json.dumps(res, indent=2)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
    click.echo(text)


@main.command("softlock")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def softlock_cmd(root: Path | None) -> None:
    """Static soft-lock report: statecharts + encounter reachability (runtime layer: forge balance)."""
    from forge.softlock import static_report

    rep = static_report(root or find_repo_root())
    rep.pop("chart_details", None)
    click.echo(json.dumps(rep, indent=2))
    sys.exit(0 if rep["ok"] else 1)


@main.group("save")
def save_grp() -> None:
    """Game Zero saves: inspect, validate, migrate (F5)."""


@save_grp.command("inspect")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def save_inspect(path: Path) -> None:
    """Validate a save (format, version, checksum) and print its layers."""
    from forge.save import validate

    s = json.loads(path.read_text(encoding="utf-8"))
    errs = validate(s)
    click.echo(json.dumps({"errors": errs, "version": s.get("version"), "save": s}, indent=2))
    sys.exit(0 if not errs else 1)


@save_grp.command("migrate")
@click.argument("src", type=click.Path(exists=True, path_type=Path))
@click.argument("dst", type=click.Path(path_type=Path))
def save_migrate(src: Path, dst: Path) -> None:
    """Migrate an older save to the current version (same code path as the game)."""
    from forge.save import migrate

    s, steps = migrate(json.loads(src.read_text(encoding="utf-8")))
    dst.write_text(json.dumps(s, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    click.echo(json.dumps({"migrated_from": steps, "version": s["version"], "checksum": s["checksum"]}))


@main.command("report")
@click.option("--root", type=click.Path(path_type=Path), default=None)
def report_cmd(root: Path | None) -> None:
    """Regenerate STATUS.md (milestone dashboard) from recorded acceptance results."""
    from forge.report import write

    click.echo(str(write(root or find_repo_root())))


if __name__ == "__main__":
    main()
