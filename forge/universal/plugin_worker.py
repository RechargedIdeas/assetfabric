# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Plugin worker: `python -m forge.universal.plugin_worker` reads one JSON request on stdin, prints one JSON line.

Always runs *inside* a forge Sandbox (bwrap: no network, read-only root, only the scratch dir writable; process tier:
PEP 578 audit hook refusing sockets and writes outside scratch). Plugin code is never imported in the host process.

Requests (paths are relative to the sandbox scratch dir, where the host copied the plugin):
  {"op": "contract", "plugin": "plugin", "manifest": {...}}         → runs the contract suite
  {"op": "export", "plugin": "plugin", "manifest": {...}, "scene_json": "...", "out": "out"}  → one export + verify
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def load_adapter(plugin_dir: Path, manifest: dict[str, Any]):
    from forge.universal.exporters.base import Adapter
    rel, _, cls_name = manifest["entrypoint"].partition(":")
    path = (plugin_dir / rel).resolve()
    if plugin_dir.resolve() not in path.parents:
        raise ValueError("entrypoint escapes the plugin directory")
    mod_name = "afplugin_" + manifest["id"].replace("-", "_")
    spec = importlib.util.spec_from_file_location(mod_name, path, submodule_search_locations=[str(plugin_dir)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    cls = getattr(mod, cls_name)
    if not (isinstance(cls, type) and issubclass(cls, Adapter)):
        raise TypeError(f"{cls_name} is not an Adapter subclass")
    return cls()


def _tree_hashes(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


def contract(req: dict[str, Any]) -> dict[str, Any]:
    from forge.universal import ir, reference
    man = req["manifest"]
    checks: dict[str, bool] = {}
    errs: list[str] = []
    detail: dict[str, Any] = {}
    a = load_adapter(Path(req["plugin"]), man)
    want = {"id": man["id"], "tier": man["tier"], "direction": man.get("direction", "export"),
            "dims": tuple(man["dims"]), "formats": tuple(man.get("formats", ())), "version": man["version"]}
    got = {"id": a.id, "tier": a.tier, "direction": a.direction, "dims": tuple(a.dims), "formats": tuple(a.formats),
           "version": a.version}
    checks["class_matches_manifest"] = got == want
    if got != want:
        errs.append(f"adapter attributes {got} differ from manifest {want}")
    scenes = reference.all_scenes()
    if a.direction in ("export", "both"):
        for dim in a.dims:
            sc = scenes[dim]
            runs = []
            for k in ("a", "b"):          # same instance twice: hidden mutable state shows up as a diff
                out = Path(f"out_{k}") / dim.replace(".", "_")
                t0 = time.perf_counter()
                man_out = a.export(sc, out)
                runs.append((out, man_out, round(time.perf_counter() - t0, 4)))
            (oa, ma, ta), (ob, mb, _) = runs
            ha, hb = _tree_hashes(oa), _tree_hashes(ob)
            v = a.verify(oa)
            checks[f"export_{dim}_deterministic"] = ha == hb
            checks[f"export_{dim}_verify"] = bool(v.get("ok"))
            checks[f"export_{dim}_manifest"] = (ma.get("adapter") == a.id and ma.get("tier") == a.tier
                                                and ma.get("source_digest") == sc.digest())
            if ha != hb:
                errs.append(f"{dim}: export is not deterministic ({sorted(k for k in set(ha) | set(hb) if ha.get(k) != hb.get(k))[:5]})")
            if not v.get("ok"):
                errs.append(f"{dim}: verify failed {v.get('errors')}")
            detail[dim] = {"files": len(ha), "bytes": sum((oa / k).stat().st_size for k in ha), "export_s": ta}
    if a.direction in ("import", "both"):
        Path("sample").mkdir(exist_ok=True)
        sample = a.sample_input(Path("sample"))
        s1, s2 = a.import_(sample), a.import_(sample)
        val = ir.validate(s1)
        checks["import_valid_ir"] = bool(val.get("ok"))
        checks["import_deterministic"] = s1.digest() == s2.digest()
        if not val.get("ok"):
            errs.append(f"import: invalid IR {val.get('errors')}")
    return {"ok_protocol": True, "ok": all(checks.values()) and not errs, "checks": checks, "errors": errs, "detail": detail}


def export(req: dict[str, Any]) -> dict[str, Any]:
    from forge.universal import ir
    a = load_adapter(Path(req["plugin"]), req["manifest"])
    sc = ir.Scene.from_json(req["scene_json"])
    out = Path(req["out"])
    man = a.export(sc, out)
    v = a.verify(out)
    return {"ok_protocol": True, "ok": bool(v.get("ok")), "manifest": man, "verify": v}


def main() -> int:
    from forge.sandbox_worker import _install_guards
    _install_guards()
    req = json.loads(sys.stdin.read() or "{}")
    try:
        if req.get("op") == "contract":
            res = contract(req)
        elif req.get("op") == "export":
            res = export(req)
        else:
            res = {"ok_protocol": False, "error": f"unknown op {req.get('op')!r}"}
    except Exception as e:  # noqa: BLE001 — every plugin failure is reported, never raised into the host
        res = {"ok_protocol": True, "ok": False, "checks": {"ran": False}, "errors": [f"{type(e).__name__}: {e}"],
               "trace": traceback.format_exc()[-1500:]}
    sys.stdout.write(json.dumps(res, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
