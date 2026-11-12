"""Companion track C1–C6 (PocketLoom) — Python half: desktop LoomLink, shared vectors, static Android scans.

The Kotlin half (FabricCore JUnit tests, APK build/verify, Kotlin↔Python interop) runs in `forge accept C1…C6`
(full mode, needs JDK 17 + Android SDK) and in CI's `pocketloom` job.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from forge import accept_companions as ac
from forge.loomlink import SyncStore, canonical, op_hashchain, plan_sync, vv_compare
from forge.milestones import C_ORDER, INCREMENTS, accept


def vectors(root: Path) -> dict:
    return json.loads((root / "tests/fixtures/loomlink_vectors.json").read_text(encoding="utf-8"))


def test_sync_plan_fixture_regression(root: Path) -> None:
    rep = ac.sync_fixture_check(root)
    assert rep["ok"] and rep["cases"] >= 5, rep


def test_hashchain_vectors(root: Path) -> None:
    for v in vectors(root)["hashchain"]:
        assert op_hashchain({"seed": v["seed"], "rounds": v["rounds"]})["digest"] == v["digest"]


def test_vv_compare() -> None:
    assert vv_compare({"a": 1}, {"a": 1, "b": 0}) == "equal"
    assert vv_compare({"a": 2}, {"a": 1}) == "a"
    assert vv_compare({}, {"a": 1}) == "b"
    assert vv_compare({"a": 1}, {"b": 1}) == "concurrent"


def test_conflict_keeps_both_and_converges(tmp_path: Path) -> None:
    desk = SyncStore(tmp_path / "d", "desktop")
    phone = SyncStore(tmp_path / "p", "pl-1")
    desk.put("x", "sprite", b"desk")
    phone.put("x", "sprite", b"phone")
    plan = plan_sync(desk.entries, phone.entries, "pl-1")
    assert plan["conflicts"] == [{"id": "x", "resolution": "keep_both", "phone_copy": "x~pl-1"}]
    assert plan["push"] == ["x"] and plan["pull"][0]["sha256"] == desk.entries["x"]["sha256"]


def test_desktop_link_python_client() -> None:
    with tempfile.TemporaryDirectory() as t:
        rep = ac.python_link_checks(Path(t))
    assert rep["ok"], rep


def test_android_strings_and_offline_scan(root: Path) -> None:
    s = ac.strings_report(root)
    assert s["ok"], s
    assert s["defined"] >= 50
    o = ac.offline_scan(root)
    assert o["ok"], o


def test_ui_literal_detector() -> None:
    assert ac.UI_LITERAL.search('label.setText("Hello")')
    assert ac.UI_LITERAL.search('view.text = "Pair now"')
    assert not ac.UI_LITERAL.search("view.setText(R.string.link_pair)")
    assert not ac.UI_LITERAL.search('seed.setText("1")')


def test_png_reader_roundtrip() -> None:
    from forge.imaging import Image

    data = Image(2, 1, [(1, 2, 3, 255), (0, 0, 0, 0)]).to_png()
    w, h, px = ac.png_pixels(data)
    assert (w, h) == (2, 1) and px == [(1, 2, 3, 255), (0, 0, 0, 0)]


def test_registry() -> None:
    assert C_ORDER == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert all(INCREMENTS[m].runner for m in C_ORDER)


@pytest.mark.parametrize("ms", ["C1", "C3", "C5", "C6"])
def test_accept_fast_mode(root: Path, monkeypatch: pytest.MonkeyPatch, ms: str) -> None:
    monkeypatch.setenv("FORGE_ACCEPT_FAST", "1")
    rep = accept(ms, root, write=False)
    assert rep["result"]["mode"] == "fast"
    assert rep["passed"], rep["errors"]


def test_canonical_vector(root: Path) -> None:
    for c in vectors(root)["canonical"]:
        assert canonical(c["value"]) == c["text"]
