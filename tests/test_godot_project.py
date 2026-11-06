"""Lightweight Godot project.godot structure / Compatibility renderer check."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from forge.paths import find_repo_root


@pytest.fixture
def project_godot() -> Path:
    root = find_repo_root(Path(__file__))
    path = root / "games" / "game-zero" / "project.godot"
    assert path.is_file()
    return path


def test_project_godot_well_formed(project_godot: Path) -> None:
    text = project_godot.read_text(encoding="utf-8")
    assert "config_version=5" in text
    assert "[application]" in text
    assert re.search(r'config/name\s*=\s*"Game Zero"', text)
    assert 'renderer/rendering_method="gl_compatibility"' in text
    assert "GL Compatibility" in text or "gl_compatibility" in text
    assert 'run/main_scene="res://scenes/boot.tscn"' in text


def test_boot_scene_exists() -> None:
    root = find_repo_root(Path(__file__))
    assert (root / "games" / "game-zero" / "scenes" / "boot.tscn").is_file()
    assert (root / "games" / "game-zero" / "scenes" / "boot.gd").is_file()
