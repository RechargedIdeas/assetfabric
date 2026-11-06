"""Load and validate forge.yaml against the project JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import BaseModel, Field

from forge.paths import find_repo_root, schema_dir


class FabricSection(BaseModel):
    milestone: str
    version: str | None = None


class GameSection(BaseModel):
    id: str
    increment: str
    project_path: str = "games/game-zero"


class Target(BaseModel):
    id: str
    kind: str
    renderer: str
    enabled: bool = True


class ProjectManifest(BaseModel):
    schema_version: str
    name: str
    description: str | None = None
    fabric: FabricSection
    game: GameSection
    targets: list[Target]
    profiles: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    briefs: list[dict[str, Any]] = Field(default_factory=list)
    models: dict[str, Any] = Field(default_factory=dict)
    cluster: dict[str, Any] = Field(default_factory=dict)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    store: dict[str, Any] = Field(default_factory=dict)


def load_schema(root: Path | None = None) -> dict[str, Any]:
    path = schema_dir(root) / "forge.project.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest(path: Path | None = None, root: Path | None = None) -> ProjectManifest:
    root = root or find_repo_root()
    path = path or (root / "forge.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"forge.yaml must be a mapping: {path}")
    schema = load_schema(root)
    jsonschema.validate(instance=raw, schema=schema)
    return ProjectManifest.model_validate(raw)


def validate_manifest_file(path: Path, root: Path | None = None) -> list[str]:
    """Return list of validation error strings (empty = ok)."""
    root = root or find_repo_root(path.parent)
    errors: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — surface parse errors to CLI
        return [f"YAML parse error: {exc}"]
    if not isinstance(raw, dict):
        return ["forge.yaml root must be a mapping"]
    try:
        jsonschema.validate(instance=raw, schema=load_schema(root))
    except jsonschema.ValidationError as exc:
        errors.append(exc.message)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    if not errors:
        try:
            ProjectManifest.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"pydantic: {exc}")
    return errors
