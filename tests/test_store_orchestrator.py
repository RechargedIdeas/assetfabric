"""Asset store + orchestrator stubs."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.orchestrator import JobOrchestrator, JobState
from forge.paths import find_repo_root
from forge.store import AssetStore


@pytest.fixture
def root() -> Path:
    return find_repo_root(Path(__file__))


def test_store_put_get(root: Path) -> None:
    store = AssetStore(root)
    bundle = store.put(b"assetfabric-f0-fixture", media_type="text/plain", provenance={"test": True})
    got = store.get(bundle.digest)
    assert got is not None
    assert got.digest == bundle.digest
    assert got.path.read_bytes() == b"assetfabric-f0-fixture"


def test_orchestrator_enqueue(root: Path) -> None:
    orch = JobOrchestrator(root)
    job = orch.enqueue("noop", {"fixture": True})
    assert job.state == JobState.QUEUED
    ids = {j.id for j in orch.list_jobs()}
    assert job.id in ids
