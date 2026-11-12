"""Headless Godot acceptance for each Game Zero increment (skipped without Godot)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.milestones import INCREMENTS, accept
from tests.conftest import requires_godot


@requires_godot
@pytest.mark.parametrize("milestone", sorted(INCREMENTS))
def test_increment_acceptance(root: Path, milestone: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_ACCEPT_FAST", "1")      # F6: 2-selection matrix (full 12 via `forge accept F6`)
    report = accept(milestone, root, write=False)
    assert report["passed"], (report["errors"], report.get("perf"))


@requires_godot
def test_sandbox_is_deterministic(root: Path) -> None:
    a = accept("F1", root, write=False)["result"]["state_hash"]
    b = accept("F1", root, write=False)["result"]["state_hash"]
    assert a == b
