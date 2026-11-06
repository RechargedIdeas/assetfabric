"""Entry point stub — refuses to pretend a GUI exists in F0."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "AssetFabric Studio GUI is not implemented in F0 "
        "(PySide6 shell arrives with F1 SwatchStudio / dashboards).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
