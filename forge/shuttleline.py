"""ShuttleLine — multi-target import contract (SPEC §3/§4.5: "Multi-engine export (Godot first; Unity/Unreal
adapters) — Godot@F1; multi@F7").

The **contract** (``shuttleline.contract/1``) is the engine-neutral description of everything Fabric hands
to an engine: every registry asset, its kind/tags/generator, every file with its SHA-256 and the import
rule per adapter. F7 makes it *multi-target* and *checked*:

* ``verify_target(root, target)`` opens the shipped artifact of a platform build (PCK for desktop/Web, APK
  ``assets/`` for Android) and proves every contract file arrived — byte-identical for plain files
  (``keep`` import), or as a converted binary resource behind a ``.remap`` for Godot resources (``.tres``).
  Result: ``dist/<target>/shuttle.json``.
* Adapters: ``godot`` (runtime registry, real since F1) and ``generic-folder`` (engine-neutral bundle:
  files by kind + ``shuttle.json``; the hand-off format for other engines, real). ``unity`` / ``unreal``
  are declared *not built* [INFERENCE F7-6].
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "shuttleline.contract/1"
ADAPTERS = {
    "godot": {"status": "real", "since": "F1", "import": "runtime registry (Fabric autoload); plain files shipped as-is"},
    "generic-folder": {"status": "real", "since": "F7", "import": "files grouped by kind + shuttle.json (engine-neutral)"},
    "unity": {"status": "not built", "import": "planned: StreamingAssets + importer script reading shuttle.json"},
    "unreal": {"status": "not built", "import": "planned: Content/Fabric + Python import commandlet reading shuttle.json"},
}
REQUIRED_RUNTIME = ["res://assets/generated/fabric_assets.json", "res://data/generated/game_data.json",
                    "res://data/generated/world.json", "res://locale/en.json"]


def registry(root: Path) -> dict[str, Any]:
    from forge.packaging import project_dir

    return json.loads((project_dir(root) / "assets" / "generated" / "fabric_assets.json").read_text(encoding="utf-8"))


def contract(root: Path) -> dict[str, Any]:
    from forge import __version__

    reg = registry(root)
    assets = {}
    for aid, a in sorted(reg["assets"].items()):
        files = {}
        for name, f in sorted(a["files"].items()):
            files[name] = {"res": f["res"], "sha256": f["sha256"],
                           "godot_import": "resource (converted on export)" if f["res"].endswith((".tres", ".tscn")) else "keep"}
        assets[aid] = {"kind": a["kind"], "tags": a.get("tags", []), "generator": (a.get("meta") or {}).get("model_id"),
                       "files": files}
    return {"schema": SCHEMA, "fabric_version": __version__, "registry_schema": reg.get("schema_version"),
            "adapters": ADAPTERS, "required_runtime": REQUIRED_RUNTIME, "assets": assets,
            "counts": {"assets": len(assets), "files": sum(len(a["files"]) for a in assets.values())}}


def check_sources(root: Path) -> dict[str, Any]:
    """Contract vs the game tree (no export needed — CI fast path)."""
    from forge.packaging import project_dir, sha256_file

    base = project_dir(root)
    c = contract(root)
    bad = []
    for aid, a in c["assets"].items():
        for name, f in a["files"].items():
            p = base / f["res"][len("res://"):]
            if not p.exists() or sha256_file(p) != f["sha256"]:
                bad.append(f"{aid}/{name}")
    missing_rt = [r for r in REQUIRED_RUNTIME if not (base / r[len("res://"):]).exists()]
    return {"ok": not bad and not missing_rt, "mismatched": bad, "missing_runtime": missing_rt, "counts": c["counts"]}


def verify_target(root: Path, target: str) -> dict[str, Any]:
    from forge.packaging import dist_dir, shipped_files

    c = contract(root)
    try:
        shipped = shipped_files(root, target)
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    identical, converted, missing = 0, 0, []
    for aid, a in c["assets"].items():
        for name, f in a["files"].items():
            blob = shipped.get(f["res"])
            if blob is not None and hashlib.sha256(blob).hexdigest() == f["sha256"]:
                identical += 1
                continue
            remap = shipped.get(f["res"] + ".remap")
            if f["godot_import"] != "keep" and remap is not None:
                m = re.search(rb'path="([^"]+)"', remap)
                if m and m.group(1).decode() in shipped:
                    converted += 1
                    continue
            missing.append(f"{aid}/{name}")
    missing_rt = [r for r in REQUIRED_RUNTIME if r not in shipped]
    rep = {"schema": SCHEMA, "target": target, "adapter": "godot", "shipped_files": len(shipped),
           "contract_files": c["counts"]["files"], "identical": identical, "converted_resources": converted,
           "missing": missing, "missing_runtime": missing_rt, "ok": not missing and not missing_rt}
    out = dist_dir(root) / target / "shuttle.json"
    out.write_text(json.dumps(rep | {"contract": c}, indent=2) + "\n", encoding="utf-8")
    return rep


def export_generic(root: Path, out: Path) -> dict[str, Any]:
    """generic-folder adapter: <out>/<kind>/<file> + shuttle.json (paths relative to <out>)."""
    from forge.packaging import project_dir

    c = contract(root)
    if out.exists():
        shutil.rmtree(out)
    base = project_dir(root)
    n = 0
    for aid, a in c["assets"].items():
        for name, f in a["files"].items():
            dst = out / a["kind"] / aid / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base / f["res"][len("res://"):], dst)
            f["path"] = str(dst.relative_to(out))
            n += 1
    (out / "shuttle.json").write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "files": n, "out": str(out)}
