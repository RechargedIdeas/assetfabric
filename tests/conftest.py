from __future__ import annotations

from pathlib import Path

import pytest

from forge.milestones import godot_binary
from forge.paths import find_repo_root

ROOT = find_repo_root(Path(__file__))


@pytest.fixture
def root() -> Path:
    return ROOT


requires_godot = pytest.mark.skipif(godot_binary(ROOT) is None, reason="Godot binary not available")
