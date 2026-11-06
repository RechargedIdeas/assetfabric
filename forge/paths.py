"""Resolve project-relative paths from manifests — never hard-code absolute host paths."""

from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward looking for forge.yaml or pyproject.toml named assetfabric-forge."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        manifest = candidate / "forge.yaml"
        if manifest.is_file():
            return candidate
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            text = pyproject.read_text(encoding="utf-8")
            if "name = \"assetfabric-forge\"" in text or "name = 'assetfabric-forge'" in text:
                return candidate
    raise FileNotFoundError(
        "Could not locate AssetFabric repo root (forge.yaml / assetfabric-forge pyproject)."
    )


def schema_dir(root: Path | None = None) -> Path:
    root = root or find_repo_root()
    return root / "docs" / "schemas"
