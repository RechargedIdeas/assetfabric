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
    for f in spec["files"]:
        if f.get("unpack"):
            unpacked(model_id, f["path"], root)
    return status(model_id, root, verify=False)


def unpacked(model_id: str, file: str | None = None, root: Path | None = None) -> Path:
    """Directory an `unpack: zip` registry file extracts to (`store/models/<id>/<unpack>/`). The archive is SHA-256-verified
    first; extraction is idempotent (a `.ok` marker carries the archive hash) and refuses absolute or `..` member paths."""
    import shutil
    import zipfile
    spec = registry(root)[model_id]
    f = next(x for x in spec["files"] if (file is None and x.get("unpack")) or x["path"] == file)
    arc = models_dir(root) / model_id / f["path"]
    out = models_dir(root) / model_id / f["unpack"]
    mark = out.with_name(out.name + ".ok")
    if mark.exists() and mark.read_text().strip() == f["sha256"] and out.is_dir():
        return out
    if not arc.exists() or sha256_file(arc) != f["sha256"]:
        raise FileNotFoundError(f"model {model_id!r} not fetched or checksum mismatch — run `forge models fetch {model_id}`")
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(arc) as z:
        for m in z.namelist():
            if m.startswith("/") or ".." in Path(m).parts:
                raise ValueError(f"{model_id}: unsafe archive member {m!r}")
        z.extractall(tmp)
    strip = f.get("strip")                     # top-level folder inside the archive
    src = tmp / strip if strip else tmp
    shutil.rmtree(out, ignore_errors=True)
    src.replace(out)
    shutil.rmtree(tmp, ignore_errors=True)
    mark.write_text(f["sha256"] + "\n")
    return out


NON_COMMERCIAL = ("CC-BY-NC", "NC-", "non-commercial", "research-only", "OpenRAIL")


def audit(root: Path | None = None) -> dict[str, Any]:
    """BoltPack-style licence audit of the model registry: every model licence must be on BoltPack's permissive allow-list
    (proprietary commercial use) and none may be non-commercial; every file must be pinned (revision URL + SHA-256)."""
    from forge.boltpack import ALLOWED

    bad: list[str] = []
    for mid, spec in registry(root).items():
        lic = str(spec.get("licence", ""))
        if lic not in ALLOWED or any(t.lower() in lic.lower() for t in NON_COMMERCIAL):
            bad.append(f"{mid}: licence {lic!r} not allowed for proprietary commercial use")
        for f in spec.get("files", []):
            if len(str(f.get("sha256", ""))) != 64 or "/resolve/main/" in str(f.get("url", "")):
                bad.append(f"{mid}/{f.get('path')}: not pinned (needs a revision URL + SHA-256)")
    return {"ok": not bad, "problems": bad, "models": sorted(registry(root))}
