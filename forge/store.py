"""Content-addressed asset store scaffolding (F0)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge.paths import find_repo_root


@dataclass(frozen=True)
class StoredBundle:
    digest: str
    media_type: str
    size: int
    path: Path
    manifest_path: Path


class AssetStore:
    """SHA-256 addressed blobs + SQLite catalog. Provenance manifests beside blobs."""

    def __init__(self, root: Path | None = None, store_root: Path | None = None) -> None:
        self.root = root or find_repo_root()
        self.store_root = store_root or (self.root / "store")
        self.objects = self.store_root / "objects"
        self.manifests = self.store_root / "manifests"
        self.index_path = self.store_root / "index.sqlite"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    def _ensure_db(self) -> None:
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bundles (
                  digest TEXT PRIMARY KEY,
                  media_type TEXT NOT NULL,
                  size INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  provenance_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def digest_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _object_path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest

    def put(
        self,
        data: bytes,
        *,
        media_type: str = "application/octet-stream",
        provenance: dict[str, Any] | None = None,
    ) -> StoredBundle:
        digest = self.digest_bytes(data)
        obj = self._object_path(digest)
        obj.parent.mkdir(parents=True, exist_ok=True)
        if not obj.exists():
            obj.write_bytes(data)
        prov = provenance or {}
        prov.setdefault("digest", digest)
        prov.setdefault("media_type", media_type)
        prov.setdefault("size", len(data))
        prov.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        man = self.manifests / f"{digest}.json"
        man.write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO bundles(digest, media_type, size, created_at, provenance_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (digest, media_type, len(data), prov["created_at"], json.dumps(prov)),
            )
            conn.commit()
        return StoredBundle(digest, media_type, len(data), obj, man)

    def get(self, digest: str) -> StoredBundle | None:
        obj = self._object_path(digest)
        if not obj.exists():
            return None
        man = self.manifests / f"{digest}.json"
        with sqlite3.connect(self.index_path) as conn:
            row = conn.execute(
                "SELECT media_type, size FROM bundles WHERE digest = ?", (digest,)
            ).fetchone()
        if not row:
            return None
        return StoredBundle(digest, row[0], row[1], obj, man)

    def count(self) -> int:
        with sqlite3.connect(self.index_path) as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM bundles").fetchone()
        return int(n)

    def health(self) -> dict[str, Any]:
        return {
            "root": str(self.store_root.relative_to(self.root)),
            "objects_dir": self.objects.is_dir(),
            "manifests_dir": self.manifests.is_dir(),
            "index_ok": self.index_path.is_file(),
            "bundle_count": self.count(),
        }
