"""Telemetry event schema tests (SPEC §5.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.paths import find_repo_root
from forge.telemetry import TelemetryStore, make_system_event, validate_event


@pytest.fixture
def root() -> Path:
    return find_repo_root(Path(__file__))


def test_minimal_event_valid(root: Path) -> None:
    event = make_system_event("unit.test").model_dump(mode="json")
    assert validate_event(event, root) == []


def test_missing_required_fails(root: Path) -> None:
    errors = validate_event({"event_type": "x"}, root)
    assert errors


def test_store_emit_roundtrip(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate telemetry file under tmp by pointing store root via monkeypatch of find? Use explicit root copy.
    # Simpler: write into real .fabric but unique event; or construct store with custom path.
    store = TelemetryStore(root)
    before = store.path.read_text(encoding="utf-8") if store.path.exists() else ""
    store.emit(make_system_event("unit.emit", action_source="system"))
    after = store.path.read_text(encoding="utf-8")
    assert len(after) > len(before)
    assert "unit.emit" in after
