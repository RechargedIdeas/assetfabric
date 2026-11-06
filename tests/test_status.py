"""forge status health aggregation."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli import main
from forge.paths import find_repo_root
from forge.status import collect_status


@pytest.fixture
def root() -> Path:
    return find_repo_root(Path(__file__))


def test_collect_status_healthy(root: Path) -> None:
    report = collect_status(root)
    assert report["healthy"] is True
    assert report["milestone"] == "F0"
    assert report["components"]["godot"]["healthy"] is True
    assert report["components"]["godot"]["renderer"] == "gl_compatibility"
    assert "one milestone ahead" in report["one_milestone_offset"]["rule"].lower() or \
        "at most one milestone" in report["one_milestone_offset"]["rule"].lower()


def test_cli_status_exit_zero(root: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["status", "--json", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert '"healthy": true' in result.output.lower() or '"healthy": true' in result.output
