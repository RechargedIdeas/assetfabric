"""`python -m assetfabric_studio [--state-dir DIR]` — opens the Studio window (needs the `studio` extra: PySide6)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="assetfabric-studio")
    ap.add_argument("--state-dir", type=Path, default=None, help="LoomLink state dir (mirror frames + Studio input spool)")
    a = ap.parse_args(argv)
    try:
        from assetfabric_studio.app import run
    except ImportError as e:   # PySide6 missing: say so instead of pretending
        from forge.i18n import t
        print(t("studio.missing_pyside", err=str(e)), file=sys.stderr)
        return 2
    return run(a.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
