"""Schema + manifest validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge.manifest import load_manifest, validate_manifest_file
from forge.paths import find_repo_root


@pytest.fixture
def root() -> Path:
    return find_repo_root(Path(__file__))


def test_repo_forge_yaml_validates(root: Path) -> None:
    errors = validate_manifest_file(root / "forge.yaml", root)
    assert errors == []


def test_load_manifest_milestone_f0(root: Path) -> None:
    m = load_manifest(root / "forge.yaml", root)
    assert m.fabric.milestone == "F0"
    assert m.game.id == "game-zero"
    assert m.game.increment == "env-boots"
    assert any(t.renderer == "compatibility" for t in m.targets)


def test_invalid_manifest_rejected(root: Path, tmp_path: Path) -> None:
    bad = tmp_path / "forge.yaml"
    bad.write_text(yaml.dump({"schema_version": "1.0", "name": "x"}), encoding="utf-8")
    errors = validate_manifest_file(bad, root)
    assert errors, "expected validation failure for incomplete manifest"
