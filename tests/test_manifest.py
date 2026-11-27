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


def test_manifest_milestone_matches_package_and_increment(root: Path) -> None:
    import forge
    from forge.milestones import INCREMENTS

    m = load_manifest(root / "forge.yaml", root)
    assert m.fabric.milestone == forge.__milestone__
    assert m.game.id == "game-zero"
    # U-track milestones are Fabric-only; Game Zero stays on the last F increment.
    if m.fabric.milestone.startswith("F"):
        assert m.game.increment == INCREMENTS[m.fabric.milestone].increment
    else:
        assert m.fabric.milestone in INCREMENTS
        assert m.game.increment == INCREMENTS["F9"].increment
    assert any(t.renderer == "compatibility" for t in m.targets)


def test_invalid_manifest_rejected(root: Path, tmp_path: Path) -> None:
    bad = tmp_path / "forge.yaml"
    bad.write_text(yaml.dump({"schema_version": "1.0", "name": "x"}), encoding="utf-8")
    errors = validate_manifest_file(bad, root)
    assert errors, "expected validation failure for incomplete manifest"
