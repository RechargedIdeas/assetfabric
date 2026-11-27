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


# ---------------------------------------------------------------- CI sharding (0.7.9, quality gap "CI time")
# `pytest --ci-group=<name>` keeps only that group's tests; the groups partition the whole suite (every test is in exactly
# one group: anything not listed below is `core`), so running all groups == running plain `pytest`. CI runs the groups as
# parallel jobs (.github/workflows/ci.yml); locally plain `pytest -q` still runs everything.
CI_GROUPS: dict[str, tuple[str, ...]] = {
    # headless Godot game increments: F5 = full 2400-fight G-BAL-01 matrix, F6/F4 world + substrate
    "game": ("tests/test_game_increments.py::test_increment_acceptance[F5]",
             "tests/test_game_increments.py::test_increment_acceptance[F6]",
             "tests/test_game_increments.py::test_increment_acceptance[F4]",
             "tests/test_game_increments.py::test_increment_acceptance[F7]",
             "tests/test_f6_world.py", "tests/test_f5_balance_save.py", "tests/test_worldfights.py"),
    # C9–C12 real CPU paths (ffmpeg / Xvfb / OpenCV / ONNX)
    "recon": ("tests/test_game_increments.py::test_increment_acceptance[C12]",
              "tests/test_game_increments.py::test_increment_acceptance[C11]",
              "tests/test_game_increments.py::test_increment_acceptance[C10]",
              "tests/test_game_increments.py::test_increment_acceptance[C9]",
              "tests/test_c12_real.py", "tests/test_c11_dense.py", "tests/test_c9_real.py", "tests/test_c9_c12.py",
              "tests/test_girt_onnx.py",
              # F8 retro (Xvfb captures + emulator, ~40 s) balances the shards
              "tests/test_game_increments.py::test_increment_acceptance[F8]"),
}
CI_GROUP_NAMES = (*CI_GROUPS, "core")


def ci_group_of(nodeid: str) -> str:
    for g, prefixes in CI_GROUPS.items():
        if any(nodeid == p or nodeid.startswith(p + "::") for p in prefixes):
            return g
    return "core"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--ci-group", default="", choices=("", *CI_GROUP_NAMES),
                     help="run one CI shard (game | recon | core); the shards partition the suite")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    group = config.getoption("--ci-group")
    if not group:
        return
    keep, drop = [], []
    for it in items:
        (keep if ci_group_of(it.nodeid) == group else drop).append(it)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep
