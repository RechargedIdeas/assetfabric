# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Native-tool verification: load AssetFabric output in the real tool, headless, and report what it saw.

* Godot 4 (`GLTFDocument` at runtime, temp project, Compatibility renderer) — available in CI.
* Blender (`blender --background --factory-startup`, bundled glTF importer) — when installed (box: apt `blender`).
* OpenSCAD — see `forge.universal.openscad` (real CLI compile).

Every function returns {"ran": False, "reason": ...} when the binary is absent — never a fake pass."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def godot_binary() -> str | None:
    from forge.milestones import godot_binary as gb
    from forge.paths import find_repo_root
    try:
        return gb(find_repo_root())
    except FileNotFoundError:
        return os.environ.get("GODOT_BIN") or shutil.which("godot")


def blender_binary() -> str | None:
    env = os.environ.get("FORGE_BLENDER")
    if env and Path(env).exists():
        return env
    return shutil.which("blender")


def _last_json(prefix: str, text: str) -> dict[str, Any] | None:
    for ln in reversed(text.splitlines()):
        if ln.startswith(prefix):
            return json.loads(ln[len(prefix):])
    return None


def godot_load_glb(path: Path, timeout: float = 180.0) -> dict[str, Any]:
    gb = godot_binary()
    if not gb:
        return {"ran": False, "reason": "godot_not_installed"}
    with tempfile.TemporaryDirectory(prefix="af-godot-gltf-") as d:
        proj = Path(d)
        (proj / "project.godot").write_text('config_version=5\n[application]\nconfig/name="af-gltf-check"\n'
                                            '[rendering]\nrenderer/rendering_method="gl_compatibility"\n', encoding="utf-8")
        p = subprocess.run([gb, "--headless", "--path", str(proj), "--script", str(HERE / "godot_gltf_check.gd"), "--",
                            str(Path(path).resolve())], capture_output=True, text=True, timeout=timeout)
    rep = _last_json("AF_GODOT ", p.stdout + p.stderr)
    if rep is None:
        return {"ran": True, "ok": False, "reason": "no report", "tail": (p.stdout + p.stderr)[-800:]}
    v = _version(gb, ["--version"])
    return {"ran": True, "ok": rep.get("err") == 0, "tool": "godot", "version": v, **rep}


def blender_import(path: Path, timeout: float = 300.0) -> dict[str, Any]:
    """Import a .glb / .obj / .stl in Blender and report objects, vertex/face counts, materials, armatures.
    For a Blender bridge pack pass the pack's `import_assetfabric.py` via `blender_run_bridge` instead."""
    bb = blender_binary()
    if not bb:
        return {"ran": False, "reason": "blender_not_installed"}
    with tempfile.TemporaryDirectory(prefix="af-blender-") as d:
        out = Path(d) / "report.json"
        p = subprocess.run([bb, "--background", "--factory-startup", "--python-exit-code", "3",
                            "--python", str(HERE / "blender_check.py"), "--", str(Path(path).resolve()), str(out)],
                           capture_output=True, text=True, timeout=timeout)
        if not out.exists():
            return {"ran": True, "ok": False, "reason": f"exit {p.returncode}", "tail": (p.stdout + p.stderr)[-1200:]}
        rep = json.loads(out.read_text())
    return {"ran": True, "ok": p.returncode == 0 and rep.get("ok", False), "tool": "blender",
            "version": _version(bb, ["--version"]), **rep}


def blender_run_bridge(script: Path, report: Path, timeout: float = 300.0) -> dict[str, Any]:
    """Run a generated Blender bridge script exactly as a user would (`blender -b -P import_assetfabric.py`)."""
    bb = blender_binary()
    if not bb:
        return {"ran": False, "reason": "blender_not_installed"}
    p = subprocess.run([bb, "--background", "--factory-startup", "--python-exit-code", "3", "--python", str(script),
                        "--", "--report", str(report)], capture_output=True, text=True, timeout=timeout,
                       cwd=str(Path(script).parent))
    if not Path(report).exists():
        return {"ran": True, "ok": False, "reason": f"exit {p.returncode}", "tail": (p.stdout + p.stderr)[-1200:]}
    rep = json.loads(Path(report).read_text())
    return {"ran": True, "ok": p.returncode == 0 and rep.get("ok", False), "tool": "blender",
            "version": _version(bb, ["--version"]), **rep}


def _version(binary: str, args: list[str]) -> str | None:
    try:
        p = subprocess.run([binary, *args], capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def availability() -> dict[str, Any]:
    from forge.universal import openscad
    return {"godot": godot_binary() is not None, "blender": blender_binary() is not None,
            "openscad": openscad.openscad_binary() is not None}
