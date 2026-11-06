"""Environment checks for `forge doctor`."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from forge.paths import find_repo_root
from forge.status import collect_status


def run_doctor(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("python>=3.11", sys.version_info >= (3, 11), f"{sys.version.split()[0]}")
    add("platform", True, f"{platform.system()} {platform.machine()}")

    for mod in ("yaml", "pydantic", "jsonschema", "click", "rich"):
        try:
            __import__(mod if mod != "yaml" else "yaml")
            add(f"dep:{mod}", True, "importable")
        except ImportError:
            add(f"dep:{mod}", False, "missing — pip/uv install project deps")

    add("forge.yaml", (root / "forge.yaml").is_file(), "present" if (root / "forge.yaml").is_file() else "missing")
    add(
        "docs/schemas",
        (root / "docs" / "schemas" / "forge.project.schema.json").is_file(),
        "project + telemetry schemas",
    )
    godot_bin = shutil.which("godot") or shutil.which("godot4") or shutil.which("Godot")
    add(
        "godot_binary",
        bool(godot_bin),
        godot_bin or "not on PATH — structure smoke still valid; see scripts/smoke_godot.sh",
    )
    # Weakest-node awareness (informational)
    try:
        import os

        cores = os.cpu_count() or 1
        add("cpu_cores", cores >= 2, f"{cores} (acceptance floor: 2)")
    except Exception:  # noqa: BLE001
        add("cpu_cores", False, "unknown")

    status = collect_status(root)
    add("forge_status", status["healthy"], "healthy" if status["healthy"] else "unhealthy — run forge status")

    return {
        "ok": all(c["ok"] for c in checks if c["name"] != "godot_binary"),
        "checks": checks,
        "note": "godot_binary is advisory for unit tests; `forge accept <F>` needs it.",
    }
