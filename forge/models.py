"""Model weights registry + checksum-verified fetch (`content/models/models.yaml`).

Weights live in `store/models/<id>/` (gitignored). A file is only used when its SHA-256 matches the registry; `fetch`
downloads to a temporary name, verifies, then renames, so a partial or tampered download is never picked up.
Override the directory with `FORGE_MODELS_DIR` (e.g. a shared cache on a LoomCluster node)."""
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from forge.paths import find_repo_root


def registry(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    return yaml.safe_load((root / "content" / "models" / "models.yaml").read_text())["models"]


def models_dir(root: Path | None = None) -> Path:
    env = os.environ.get("FORGE_MODELS_DIR")
    return Path(env) if env else (root or find_repo_root()) / "store" / "models"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def path_for(model_id: str, file: str | None = None, root: Path | None = None) -> Path:
    spec = registry(root)[model_id]
    name = file or spec["files"][0]["path"]
    return models_dir(root) / model_id / name


def status(model_id: str, root: Path | None = None, verify: bool = True) -> dict[str, Any]:
    spec = registry(root)[model_id]
    files = []
    for f in spec["files"]:
        p = models_dir(root) / model_id / f["path"]
        ok = p.exists() and p.stat().st_size == f["bytes"] and (not verify or sha256_file(p) == f["sha256"])
        files.append({"path": str(p), "present": p.exists(), "verified": ok})
    return {"id": model_id, "licence": spec["licence"], "ready": all(f["verified"] for f in files), "files": files}


def require(model_id: str, root: Path | None = None) -> Path:
    """Path of the model's first file, verified; raises FileNotFoundError naming the fetch command otherwise."""
    st = status(model_id, root)
    if not st["ready"]:
        raise FileNotFoundError(f"model {model_id!r} not fetched or checksum mismatch — run `forge models fetch {model_id}`")
    return Path(st["files"][0]["path"])


def fetch(model_id: str, root: Path | None = None, timeout: float = 600.0) -> dict[str, Any]:
    spec = registry(root)[model_id]
    out = models_dir(root) / model_id
    out.mkdir(parents=True, exist_ok=True)
    for f in spec["files"]:
        dst = out / f["path"]
        if dst.exists() and sha256_file(dst) == f["sha256"]:
            continue
        tmp = dst.with_suffix(dst.suffix + ".part")
        h = hashlib.sha256()
        with urllib.request.urlopen(f["url"], timeout=timeout) as r, tmp.open("wb") as w:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
                w.write(chunk)
        if h.hexdigest() != f["sha256"]:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"{model_id}/{f['path']}: SHA-256 mismatch (got {h.hexdigest()}, want {f['sha256']})")
        tmp.replace(dst)
    return status(model_id, root, verify=False)
