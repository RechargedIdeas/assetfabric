# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Adapter SDK: the contract every engine/tool adapter (built-in or plugin) implements.

    class MyAdapter(Adapter):
        id = "my-tool"; name = "My Tool"; tier = "interchange_pack"; direction = "export"
        dims = ("3d",); convention = "gltf"
        def export(self, scene, out) -> dict: ...      # write files through Pack; return pack.finish(...)
        def verify(self, out) -> dict: ...             # re-read what was written; {"ok", "checks"}
        def import_(self, path) -> ir.Scene: ...       # import-direction adapters
        def native_check(self, out) -> dict: ...       # native_verified adapters: run the real tool headless

Packs are deterministic: files are written from bytes only (no timestamps), and `assetfabric_manifest.json` lists every
file with its SHA-256, the adapter id/tier/api version, the target convention and the source IR digest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from forge import __version__
from forge.universal import ADAPTER_API_VERSION, TIERS, ir

MANIFEST = "assetfabric_manifest.json"


class AdapterError(ValueError):
    pass


class Pack:
    def __init__(self, out: Path) -> None:
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, dict[str, Any]] = {}

    def add(self, rel: str, data: bytes | str) -> Path:
        if isinstance(data, str):
            data = data.encode("utf-8")
        if rel.startswith("/") or ".." in Path(rel).parts:
            raise AdapterError(f"unsafe pack path {rel!r}")
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.files[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        return p

    def finish(self, adapter: "Adapter", scene: ir.Scene | None, **extra: Any) -> dict[str, Any]:
        man = {"adapter": adapter.id, "adapter_name": adapter.name, "tier": adapter.tier, "api_version": ADAPTER_API_VERSION,
               "generator": f"AssetFabric forge {__version__}", "convention": adapter.convention,
               "source_digest": scene.digest() if scene is not None else None,
               "source_dimension": scene.dimension if scene is not None else None,
               "files": dict(sorted(self.files.items())), **extra}
        (self.out / MANIFEST).write_text(json.dumps(man, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return man


def read_manifest(out: Path) -> dict[str, Any]:
    return json.loads((Path(out) / MANIFEST).read_text(encoding="utf-8"))


def verify_manifest(out: Path) -> list[str]:
    """Every listed file exists with the recorded hash; no stray files."""
    errs = []
    man = read_manifest(out)
    for rel, meta in man["files"].items():
        p = Path(out) / rel
        if not p.exists():
            errs.append(f"missing {rel}")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != meta["sha256"]:
            errs.append(f"hash mismatch {rel}")
    listed = set(man["files"]) | {MANIFEST}
    stray = sorted(str(p.relative_to(out)) for p in Path(out).rglob("*") if p.is_file() and str(p.relative_to(out)) not in listed)
    if stray:
        errs.append(f"unlisted files: {stray[:5]}")
    if man.get("tier") not in TIERS:
        errs.append(f"bad tier {man.get('tier')!r}")
    return errs


class Adapter:
    id: str = ""
    name: str = ""
    tier: str = "interchange_pack"
    direction: str = "export"            # export | import | both
    dims: tuple[str, ...] = ("3d",)
    convention: str = "gltf"
    formats: tuple[str, ...] = ()
    api_version: str = ADAPTER_API_VERSION
    version: str = "1.0.0"

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        raise AdapterError(f"{self.id}: export not supported")

    def verify(self, out: Path) -> dict[str, Any]:
        errs = verify_manifest(out)
        return {"ok": not errs, "checks": {"manifest": not errs}, "errors": errs}

    def import_(self, path: Path) -> ir.Scene:
        raise AdapterError(f"{self.id}: import not supported")

    def sample_input(self, out: Path) -> Path:
        """Import adapters: write a representative tool-output file (from our own deterministic writers) for the
        contract suite. Never claims to be real output from the third-party tool."""
        raise AdapterError(f"{self.id}: no sample input")

    def native_check(self, out: Path) -> dict[str, Any]:
        return {"ran": False, "reason": "no native tool for this adapter"}

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "tier": self.tier, "direction": self.direction, "dims": list(self.dims),
                "convention": self.convention, "formats": list(self.formats), "api_version": self.api_version,
                "version": self.version}


def finish_verify(checks: dict[str, bool], errs: list[str], out: Path, **extra: Any) -> dict[str, Any]:
    m = verify_manifest(out)
    errs = list(errs) + m
    checks = {"manifest": not m, **checks}
    return {"ok": all(checks.values()) and not errs, "checks": checks, "errors": errs, **extra}
