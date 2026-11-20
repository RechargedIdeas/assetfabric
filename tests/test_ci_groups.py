"""CI shards (0.7.9): the `--ci-group` shards must partition the suite and must not reference tests that no longer exist."""

from __future__ import annotations

from pathlib import Path

from forge.milestones import INCREMENTS
from tests.conftest import CI_GROUP_NAMES, CI_GROUPS, ci_group_of


def test_every_shard_prefix_points_at_a_real_test(root: Path) -> None:
    for group, prefixes in CI_GROUPS.items():
        for p in prefixes:
            path, _, rest = p.partition("::")
            assert (root / path).is_file(), (group, p)
            if "[" in rest:
                assert rest.split("[", 1)[1].rstrip("]") in INCREMENTS, (group, p)


def test_groups_partition_every_test_id() -> None:
    ids = ["tests/test_game_increments.py::test_increment_acceptance[%s]" % m for m in sorted(INCREMENTS)]
    ids += ["tests/test_c12_real.py::test_x", "tests/test_status.py::test_y", "tests/test_f6_world.py::test_z[1]"]
    for i in ids:
        assert ci_group_of(i) in CI_GROUP_NAMES
    # C1 must not be captured by the C12 prefix (exact param match)
    assert ci_group_of("tests/test_game_increments.py::test_increment_acceptance[C1]") == "core"
    assert ci_group_of("tests/test_game_increments.py::test_increment_acceptance[C12]") == "recon"
    assert ci_group_of("tests/test_game_increments.py::test_increment_acceptance[F5]") == "game"
