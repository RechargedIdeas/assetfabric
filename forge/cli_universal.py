# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""`forge universal …` and `forge parametric …` command groups (Milestone U1: universal 2D/2.5D/3D engine)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from forge.cli_recon import _emit, _guard


def _strip(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _strip(v) for k, v in d.items() if not str(k).startswith("_")}
    if isinstance(d, list):
        return [_strip(v) for v in d]
    return d


def _with_plugins() -> dict[str, Any]:
    from forge.universal import plugins
    from forge.universal.exporters import REGISTRY
    reg = dict(REGISTRY)
    plugins.load_active(reg)
    return reg


# --------------------------------------------------------------------------------------------------- universal

@click.group("universal")
def universal_grp() -> None:
    """Universal engine (U1): one IR for 2D/2.5D/3D, tiered adapters for engines & tools, the Wikipedia-derived engines
    catalog, benchmark-gated self-improvement, sandboxed plugins and a live gap report."""


@universal_grp.command("catalog")
@click.option("--tier", default=None, help="native_verified | cli_bridge | interchange_pack | descriptor_only")
@click.option("--dims", default=None, help="2d | 2.5d | 3d")
@click.option("--summary", is_flag=True, help="Counts + integrity only.")
def u_catalog(tier: str | None, dims: str | None, summary: bool) -> None:
    """Engines catalog (Wikipedia 'List of game engines' + curated named tools)."""
    from forge.universal import registry as R

    def body() -> Any:
        if summary:
            return R.integrity()
        return R.search("", dims=dims, tier=tier)
    _guard(body)


@universal_grp.command("search")
@click.argument("query")
@click.option("--dims", default=None)
@click.option("--tier", default=None)
def u_search(query: str, dims: str | None, tier: str | None) -> None:
    """Search engines/tools by name, alias or id."""
    from forge.universal import registry as R
    _guard(lambda: R.search(query, dims=dims, tier=tier))


@universal_grp.command("adapters")
def u_adapters() -> None:
    """Built-in adapters + active plugins, with tier, direction, dims and formats."""
    _guard(lambda: [a.describe() for _, a in sorted(_with_plugins().items())])


@universal_grp.command("export")
@click.argument("target")
@click.option("--scene", "scene_spec", default="ref:3d", show_default=True,
              help="ref:3d|ref:2d|ref:2.5d, parametric:<template>[?k=v&...], or an IR JSON path")
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--native", is_flag=True, help="Also run the tool's own binary headlessly when the adapter has a native check.")
def u_export(target: str, scene_spec: str, out: Path, native: bool) -> None:
    """Export a scene for TARGET (adapter id, catalog engine id or named tool) and verify the pack."""
    from forge.universal import engine

    def body() -> Any:
        r = engine.export(target, engine.load_scene(scene_spec), out, native=native, registry=_with_plugins())
        if not r["ok"]:
            _emit(r)
            sys.exit(1)
        return r
    _guard(body)


@universal_grp.command("verify")
@click.argument("target")
@click.argument("pack", type=click.Path(exists=True, file_okay=False, path_type=Path))
def u_verify(target: str, pack: Path) -> None:
    """Re-verify an exported PACK with TARGET's reader (manifest hashes + format checks)."""
    from forge.universal import engine

    def body() -> Any:
        a, _ = engine.adapter_for(target, registry=_with_plugins())
        r = a.verify(pack)
        if not r["ok"]:
            _emit(r)
            sys.exit(1)
        return r
    _guard(body)


@universal_grp.command("demo")
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--native", is_flag=True, help="Run Godot/Blender/OpenSCAD checks where installed.")
@click.option("--adapter", "adapters", multiple=True)
def u_demo(out: Path, native: bool, adapters: tuple[str, ...]) -> None:
    """Every adapter × every reference scene (2D, 2.5D, 3D) + importer round-trips."""
    from forge.universal import engine

    def body() -> Any:
        r = engine.demo(out, native=native, adapters=list(adapters) or None, registry=_with_plugins())
        if not r["ok"]:
            _emit(r)
            sys.exit(1)
        return r
    _guard(body)


@universal_grp.command("native")
def u_native() -> None:
    """Which native tools (Godot, Blender, OpenSCAD) are installed on this machine."""
    from forge.universal import native, openscad

    def body() -> Any:
        a = native.availability()
        a["openscad_version"] = openscad.openscad_version()
        return a
    _guard(body)


@universal_grp.command("gaps")
def u_gaps() -> None:
    """What the engine cannot do yet (formats, features, unconfirmed catalog entries, planned GPU rungs) + next step."""
    from forge.universal import plugins
    _guard(plugins.gaps)


@universal_grp.command("evolve")
@click.argument("family", type=click.Choice(["parametric.csg", "maps2d.normal"]))
@click.option("--rounds", default=1, show_default=True)
@click.option("--state-dir", type=click.Path(path_type=Path), default=None)
def u_evolve(family: str, rounds: int, state_dir: Path | None) -> None:
    """Propose → benchmark → gate → promote (strict improvement + every gate) for a recipe FAMILY."""
    from forge.universal import evolution as E
    _guard(lambda: E.evolve(family, rounds=rounds, state_dir=state_dir))


@universal_grp.command("evolve-history")
@click.argument("family", type=click.Choice(["parametric.csg", "maps2d.normal"]))
@click.option("--state-dir", type=click.Path(path_type=Path), default=None)
def u_evolve_history(family: str, state_dir: Path | None) -> None:
    """Versions, rejections and rollbacks for a recipe FAMILY."""
    from forge.universal import evolution as E
    _guard(lambda: E.history(family, state_dir=state_dir))


@universal_grp.command("evolve-rollback")
@click.argument("family", type=click.Choice(["parametric.csg", "maps2d.normal"]))
@click.argument("version", type=int)
@click.option("--state-dir", type=click.Path(path_type=Path), default=None)
def u_evolve_rollback(family: str, version: int, state_dir: Path | None) -> None:
    """Make VERSION the active recipe again."""
    from forge.universal import evolution as E
    _guard(lambda: E.rollback(family, version, state_dir=state_dir))


@universal_grp.command("plugin-scaffold")
@click.argument("plugin_id")
@click.option("--format", "formats", multiple=True, required=True)
@click.option("--dims", default="3d", show_default=True, help="comma-separated")
@click.option("--out", type=click.Path(path_type=Path), default=None)
def u_scaffold(plugin_id: str, formats: tuple[str, ...], dims: str, out: Path | None) -> None:
    """Write a plugin skeleton (fails the contract until export/verify are implemented)."""
    from forge.universal import plugins
    _guard(lambda: plugins.scaffold(plugin_id, out or Path("plugins") / plugin_id, list(formats), dims.split(",")))


@universal_grp.command("plugin-verify")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
def u_pverify(path: Path) -> None:
    """Manifest + static security policy + sandboxed contract suite."""
    from forge.universal import plugins

    def body() -> Any:
        r = plugins.verify(path)
        if not r["ok"]:
            _emit(r)
            sys.exit(1)
        return r
    _guard(body)


@universal_grp.command("plugin-register")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
def u_pregister(path: Path) -> None:
    """Re-verify and activate a plugin version (refuses non-increasing versions; previous kept for rollback)."""
    from forge.universal import plugins

    def body() -> Any:
        r = plugins.register(path)
        if not r["ok"]:
            _emit(r)
            sys.exit(1)
        return r
    _guard(body)


@universal_grp.command("plugin-rollback")
@click.argument("plugin_id")
def u_prollback(plugin_id: str) -> None:
    """Re-activate the previously active version of PLUGIN_ID (or deactivate it if there is none)."""
    from forge.universal import plugins
    _guard(lambda: plugins.rollback(plugin_id))


@universal_grp.command("plugins")
def u_plugins() -> None:
    """Active plugins + load check (tree hash, security policy)."""
    from forge.universal import plugins
    from forge.universal.exporters import REGISTRY
    _guard(lambda: {"active": plugins.active(), "load": plugins.load_active(dict(REGISTRY))})


@universal_grp.command("catalog-build")
@click.argument("wikitext", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def u_catalog_build(wikitext: Path) -> None:
    """Regenerate content/universal/engines_catalog.yaml from a fetched wikitext snapshot (see catalog_build fetch)."""
    from forge.universal import registry as R
    _guard(lambda: {k: v for k, v in R.build_catalog(wikitext).items() if k != "entries"})


# --------------------------------------------------------------------------------------------------- parametric

@click.group("parametric")
def parametric_grp() -> None:
    """Parametric generation: YAML templates → OpenSCAD (real CLI when installed) or the NumPy CSG fallback."""


@parametric_grp.command("list")
def p_list() -> None:
    """Templates with their parameters, ranges and triangle budgets."""
    from forge.universal import openscad
    _guard(lambda: {tid: {"version": t["version"], "unit_m": t["unit_m"], "tri_budget": t["tri_budget"], "params": t["params"]}
                    for tid, t in sorted(openscad.load_templates().items())})


def _kv(pairs: tuple[str, ...]) -> dict[str, float]:
    out = {}
    for p in pairs:
        k, sep, v = p.partition("=")
        if not sep:
            raise click.BadParameter(f"expected key=value, got {p!r}")
        out[k] = float(v)
    return out


@parametric_grp.command("build")
@click.argument("template")
@click.option("--set", "sets", multiple=True, help="key=value parameter override (repeatable)")
@click.option("--backend", type=click.Choice(["auto", "openscad-cli", "csg-sdf-cpu"]), default="auto", show_default=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--no-cross-check", is_flag=True)
def p_build(template: str, sets: tuple[str, ...], backend: str, out: Path, no_cross_check: bool) -> None:
    """Build TEMPLATE → model.scad/.stl/.obj/.off/.glb + report.json."""
    from forge.universal import openscad

    def body() -> Any:
        r = _strip(openscad.build(template, _kv(sets), out, backend=backend, cross_check=not no_cross_check))
        if not r["ok"]:
            _emit(r)
            sys.exit(1)
        return r
    _guard(body)


@parametric_grp.command("scad")
@click.argument("template")
@click.option("--set", "sets", multiple=True)
def p_scad(template: str, sets: tuple[str, ...]) -> None:
    """Print the OpenSCAD source for TEMPLATE with bound parameters."""
    from forge.universal import openscad
    try:
        t = openscad.load_templates()[template]
        click.echo(openscad.emit_scad(t, openscad.bind(t, _kv(sets))), nl=False)
    except (KeyError, ValueError) as e:
        click.echo(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        sys.exit(1)
