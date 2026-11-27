# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Universal engine facade: resolve a target (adapter id, catalog engine id, or named tool) to an adapter, load a
scene (reference scene, IR JSON, or parametric template), export + verify (+ native check), and run the full demo
matrix used by `forge universal demo` and `forge accept U1`."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from forge.universal import ir, reference
from forge.universal import registry as R
from forge.universal.exporters import REGISTRY
from forge.universal.exporters.base import Adapter, AdapterError
from forge.universal.exporters.generic import CatalogGenericAdapter


def adapter_for(target: str, root: Path | None = None, registry: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any] | None]:
    """Adapter id → adapter; otherwise a catalog / named-tool id → its adapter (generic pack carries the entry)."""
    reg = REGISTRY if registry is None else registry
    if target in reg:
        return reg[target], None
    try:
        e = R.resolve(target, root)
    except KeyError as exc:
        raise AdapterError(f"unknown adapter or catalog entry {target!r}") from exc
    if e["adapter"] == "catalog-generic":
        return CatalogGenericAdapter(e), e
    return reg[e["adapter"]], e


def load_scene(spec: str, root: Path | None = None) -> ir.Scene:
    """`ref:3d|2d|2.5d`, `parametric:<template>[?k=v&k=v]`, or a path to an IR JSON file."""
    if spec.startswith("ref:"):
        scenes = reference.all_scenes()
        key = spec[4:]
        if key not in scenes:
            raise ValueError(f"reference scene {key!r} unknown; have {sorted(scenes)}")
        return scenes[key]
    if spec.startswith("parametric:"):
        from forge.universal import openscad
        tid, _, q = spec[len("parametric:"):].partition("?")
        overrides = {k: float(v) for k, v in (p.split("=", 1) for p in q.split("&") if p)} if q else None
        return openscad.build(tid, overrides, root=root)["_scene"]
    return ir.Scene.from_json(Path(spec).read_text(encoding="utf-8"))


def export(target: str, scene: ir.Scene, out: Path, native: bool = False, root: Path | None = None,
           registry: dict[str, Any] | None = None) -> dict[str, Any]:
    a, entry = adapter_for(target, root, registry)
    if a.direction == "import":
        raise AdapterError(f"{a.id} is an import adapter")
    if scene.dimension not in a.dims:
        raise AdapterError(f"{a.id} does not take {scene.dimension} scenes (dims {list(a.dims)})")
    t0 = time.perf_counter()
    man = a.export(scene, Path(out))
    t_exp = time.perf_counter() - t0
    v = a.verify(Path(out))
    res = {"target": target, "adapter": a.id, "tier": a.tier, "entry": entry and entry["id"], "dimension": scene.dimension,
           "out": str(out), "files": len(man["files"]), "bytes": sum(f["bytes"] for f in man["files"].values()),
           "export_s": round(t_exp, 4), "verify": {"ok": v["ok"], "checks": v.get("checks", {}), "errors": v.get("errors", [])}}
    if native:
        res["native"] = a.native_check(Path(out))
    res["ok"] = bool(v["ok"]) and (not native or res["native"].get("ok", True) is not False)
    return res


def import_check(a: Adapter, work: Path) -> dict[str, Any]:
    (work / "sample").mkdir(parents=True, exist_ok=True)
    sample = a.sample_input(work / "sample")
    s1 = a.import_(sample)
    s2 = a.import_(sample)
    val = ir.validate(s1)
    return {"adapter": a.id, "tier": a.tier, "ok": bool(val["ok"]) and s1.digest() == s2.digest(),
            "valid_ir": bool(val["ok"]), "deterministic": s1.digest() == s2.digest(), "dimension": s1.dimension,
            "nodes": len(s1.nodes), "errors": val.get("errors", [])}


def demo(out: Path, native: bool = False, adapters: list[str] | None = None, root: Path | None = None,
         registry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every exporter × every reference scene it accepts (+ every importer's sample round-trip)."""
    reg = REGISTRY if registry is None else registry
    scenes = reference.all_scenes()
    rows, imports = [], []
    for aid in sorted(adapters or reg):
        a = reg[aid]
        if a.direction in ("export", "both"):
            for dim, sc in scenes.items():
                if dim in a.dims:
                    try:
                        r = export(aid, sc, Path(out) / aid / dim.replace(".", "_"), native=native and a.tier != "interchange_pack",
                                   root=root, registry=reg)
                    except Exception as e:  # noqa: BLE001 — recorded, never hidden
                        r = {"adapter": aid, "dimension": dim, "ok": False, "error": f"{type(e).__name__}: {e}"}
                    rows.append(r)
        if a.direction in ("import", "both") and not getattr(a, "plugin", False):
            try:
                imports.append(import_check(a, Path(out) / aid / "import"))
            except AdapterError:
                pass
            except Exception as e:  # noqa: BLE001
                imports.append({"adapter": aid, "ok": False, "error": f"{type(e).__name__}: {e}"})
    nat = [r for r in rows if "native" in r]
    return {"ok": all(r["ok"] for r in rows) and all(i["ok"] for i in imports),
            "exports": rows, "imports": imports,
            "counts": {"adapters": len(adapters or reg), "exports": len(rows), "exports_ok": sum(r["ok"] for r in rows),
                       "imports": len(imports), "imports_ok": sum(i["ok"] for i in imports),
                       "native_ran": sum(1 for r in nat if r["native"].get("ran")),
                       "native_ok": sum(1 for r in nat if r["native"].get("ran") and r["native"].get("ok"))}}
