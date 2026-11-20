"""Aggregate health for `forge status`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge import __milestone__, __version__
from forge.milestones import offset_report
from forge.manifest import load_manifest, validate_manifest_file
from forge.orchestrator import JobOrchestrator
from forge.paths import find_repo_root, schema_dir
from forge.store import AssetStore
from forge.telemetry import load_event_schema


def _groundweave_health(root: Path) -> dict[str, Any]:
    """C8: every generator kind has a declared GPU→CPU ladder (static; `forge groundweave verify` proves budgets)."""
    try:
        from forge import groundweave

        r = groundweave.check(root)
        return {"ok": r["ok"], "ops": r["ops"], "problems": r["problems"], "devices": groundweave.detect_devices()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "problems": [f"{type(exc).__name__}: {exc}"]}


def _godot_project_health(root: Path, project_path: str) -> dict[str, Any]:
    godot_root = root / project_path
    project_file = godot_root / "project.godot"
    ok = project_file.is_file()
    renderer = None
    features = None
    parse_ok = False
    errors: list[str] = []
    if ok:
        text = project_file.read_text(encoding="utf-8")
        parse_ok = "[application]" in text and "config/name" in text
        if not parse_ok:
            errors.append("project.godot missing [application] / config/name")
        for line in text.splitlines():
            if "renderer/rendering_method" in line and "=" in line:
                renderer = line.split("=", 1)[1].strip().strip('"')
            if "config/features" in line and "=" in line:
                features = line.split("=", 1)[1].strip()
        if renderer and renderer != "gl_compatibility":
            errors.append(
                f"expected Compatibility renderer (gl_compatibility), found {renderer!r}"
            )
    else:
        errors.append(f"missing {project_path}/project.godot")
    return {
        "path": project_path,
        "project_godot_exists": ok,
        "parse_ok": parse_ok,
        "renderer": renderer,
        "features": features,
        "errors": errors,
        "healthy": ok and parse_ok and not errors,
    }


def collect_status(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    manifest_path = root / "forge.yaml"
    manifest_errors = validate_manifest_file(manifest_path, root) if manifest_path.exists() else [
        "forge.yaml missing"
    ]
    manifest = None
    if not manifest_errors:
        manifest = load_manifest(manifest_path, root)

    schema_ok = (schema_dir(root) / "forge.project.schema.json").is_file() and (
        schema_dir(root) / "telemetry.event.schema.json"
    ).is_file()
    # Touch telemetry schema load to prove it parses
    try:
        load_event_schema(root)
        telemetry_schema_ok = True
    except Exception as exc:  # noqa: BLE001
        telemetry_schema_ok = False
        schema_ok = False
        telemetry_err = str(exc)
    else:
        telemetry_err = None

    store = AssetStore(root)
    orch = JobOrchestrator(root)
    game_path = manifest.game.project_path if manifest else "games/game-zero"
    godot = _godot_project_health(root, game_path)

    offset_rule = {
        "fabric_milestone": manifest.fabric.milestone if manifest else None,
        "game_increment": manifest.game.increment if manifest else None,
        "rule": (
            "Fabric may be at most one milestone ahead of the Game. "
            "F(n+1) Fabric work is blocked until F(n) game/env gate passes."
        ),
        **offset_report(root, manifest.fabric.milestone if manifest else "F0"),
    }

    components = {
        "manifest": {"ok": not manifest_errors, "errors": manifest_errors},
        "schemas": {"ok": schema_ok, "telemetry_schema_ok": telemetry_schema_ok, "error": telemetry_err},
        "asset_store": {"ok": True, **store.health()},
        "orchestrator": {"ok": True, **orch.health()},
        "godot": godot,
        "groundweave": _groundweave_health(root),
    }
    healthy = all(
        [
            components["manifest"]["ok"],
            components["schemas"]["ok"],
            components["asset_store"]["ok"],
            components["orchestrator"]["ok"],
            components["godot"]["healthy"],
            components["groundweave"]["ok"],
            offset_rule["ok"],
        ]
    )
    return {
        "healthy": healthy,
        "version": __version__,
        "milestone": __milestone__,
        "repo_root": str(root),
        "components": components,
        "one_milestone_offset": offset_rule,
        "weakest_acceptance": {
            "cpu_cores": 2,
            "gpu": False,
            "note": "Every GPU path needs CPU/GroundWeave fallback (ADR GroundWeave).",
        },
    }
