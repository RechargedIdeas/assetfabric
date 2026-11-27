# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Engine & Tool Adapter Catalog (`content/universal/engines_catalog.yaml`).

Two sources, merged deterministically by `build_catalog`:

1. Every row of Wikipedia's "List of game engines" (revision pinned in the YAML) → an engine entry with factual
   fields + an **interchange profile**: dimensions, packs (glTF/OBJ for 3D, PNG atlas + TexturePacker-style JSON for
   2D, both + layer manifest for 2.5D), coordinate convention (curated where known, else glTF and the engine's own
   importer converts — [INFERENCE U1-1]), adapter and tier.
2. `content/universal/named_tools.yaml` — the tools named in the user's request plus photogrammetry and 3DGS software,
   each bound to a concrete adapter in `forge.universal.exporters`.

Tier rule for Wikipedia rows (honest by construction): `interchange_pack` only when the engine has a public toolchain
(open-source/freeware licence or a curated publicly sold editor) AND a modern import path (release ≥ 2000 or curated);
in-house engines (Frostbite, Decima, RAGE, …) and legacy DOS-era engines are `descriptor_only` with the reason recorded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from forge.paths import find_repo_root
from forge.universal import TIERS, catalog_build as cb

CATALOG_PATH = Path("content/universal/engines_catalog.yaml")
NAMED_PATH = Path("content/universal/named_tools.yaml")

# Coordinate conventions for engines where the convention is well documented (others: glTF + engine importer).
CURATED_CONVENTION = {
    "unity": "unity", "unreal-engine": "unreal", "godot": "godot", "blender-game-engine": "blender",
    "cryengine": "zup-rh-yfwd", "amazon-lumberyard": "zup-rh-yfwd", "o3de": "zup-rh-yfwd", "panda3d": "zup-rh-yfwd",
    "torque3d": "zup-rh-yfwd", "source": "source", "source-2": "source", "goldsrc": "source", "quake-engine": "source",
    "id-tech-2": "source", "id-tech-3": "source", "id-tech-4": "source", "ioquake3": "source", "qfusion": "source",
    "babylon-js": "directx-yup", "irrlicht": "directx-yup", "three-js": "opengl-yup", "playcanvas": "opengl-yup",
    "a-frame": "opengl-yup", "ogre": "opengl-yup", "jmonkeyengine": "opengl-yup", "libgdx": "opengl-yup",
    "monogame-xna": "opengl-yup", "stride": "opengl-yup", "defold": "opengl-yup", "s-box": "source",
}
# Publicly obtainable proprietary editors/SDKs (a user can install them and import files).
PUBLIC_PROPRIETARY = {
    "unity", "unreal-engine", "appgamekit", "buildbox", "c4-engine", "clickteam-fusion", "construct", "cryengine",
    "amazon-lumberyard", "dx-studio", "flare3d", "gamemaker", "gamesalad", "gamestudio", "leadwerks", "marmalade",
    "pico-8", "pixel-game-maker-mv", "phyreengine", "roblox", "rpg-maker", "source", "source-2", "stencyl", "unigine",
    "v-play-game-engine", "visual3d-game-engine", "zillions-of-games", "defold", "heroengine", "craftstudio",
    "m-u-g-e-n", "future-pinball", "blend4web", "layaair", "nscripter", "virtools", "autodesk-stingray-bitsquid",
}
# Pre-2000 engines that still import PNG / OBJ / glTF today (maintained toolchains).
MODERN_IMPORT_OK = {"adventure-game-studio", "crystal-space", "stratagus", "java-3d", "rpg-maker", "clickteam-fusion",
                    "gamemaker", "aleph-one", "clanlib", "unreal-engine", "worldforge", "nscripter", "virtools"}
NAMED_ALIASES = {"unreal-engine": "unreal-engine", "unity": "unity", "godot": "godot", "rpg-maker": "rpg-maker",
                 "clickteam-fusion": "clickteam-fusion", "construct": "construct-2", "appgamekit": "appgamekit",
                 "blender-game-engine": "blender"}
PACKS = {"2d": ["png-atlas", "texturepacker-json", "png-frames"], "2.5d": ["png-atlas", "texturepacker-json", "layer-manifest", "glb-cards"],
         "3d": ["glb", "obj-mtl"]}


def _year(s: str) -> int | None:
    import re
    m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", s or "")
    return int(m.group(1)) if m else None


def profile_for(row: dict[str, Any]) -> dict[str, Any]:
    sid = cb.slug(row["name"])
    dims = cb.dims_of(row.get("orientation", ""))
    lic = cb.license_class(row.get("license", ""))
    year = _year(row.get("release_year", ""))
    public = lic in ("open_source", "freeware", "mixed") or sid in PUBLIC_PROPRIETARY
    modern = (year is None or year >= 2000) or sid in MODERN_IMPORT_OK
    packs: list[str] = []
    for d in dims:
        for p in PACKS.get(d, []):
            if p not in packs:
                packs.append(p)
    if dims == ["unknown"]:
        packs = []
    named = NAMED_ALIASES.get(sid)
    if named:
        tier, adapter, reason = None, None, "named tool — see named_tools"
    elif not packs:
        tier, adapter, reason = "descriptor_only", None, "no 2D/3D orientation listed"
    elif not public:
        tier, adapter, reason = "descriptor_only", "catalog-generic", "in-house / non-public engine: no public import pipeline"
    elif not modern:
        tier, adapter, reason = "descriptor_only", "catalog-generic", "legacy engine: native formats predate PNG/OBJ/glTF import"
    else:
        tier, adapter, reason = "interchange_pack", "catalog-generic", "public toolchain + modern import formats"
    conv = CURATED_CONVENTION.get(sid)
    return {"dims": dims, "license_class": lic, "public_toolchain": public, "packs": packs,
            "convention": conv or "gltf", "convention_source": "curated" if conv else "inference:U1-1 (glTF; engine importer converts)",
            "named_tool": named, "adapter": adapter, "tier": tier, "tier_reason": reason}


def build_catalog(src: Path, root: Path | None = None, write: bool = True) -> dict[str, Any]:
    root = root or find_repo_root()
    meta_path = src.with_suffix(".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    rows = cb.parse(src.read_text(encoding="utf-8"))
    engines: dict[str, dict[str, Any]] = {}
    dup = 0
    for r in rows:
        sid = cb.slug(r["name"])
        if sid in engines:
            dup += 1
            continue
        engines[sid] = {"id": sid, "name": r["name"], "alternate_names": r["alternate_names"],
                        "language": r["language"], "release_year": r["release_year"], "scripting": r["scripting"],
                        "cross_platform": r["cross_platform"], "orientation": r["orientation"],
                        "platforms": r["platforms"], "license": r["license"], "source": "wikipedia",
                        "profile": profile_for(r)}
    named = yaml.safe_load((root / NAMED_PATH).read_text(encoding="utf-8"))["tools"]
    doc = {
        "schema_version": "1.0",
        "generated_by": "python -m forge.universal.catalog_build build",
        "attribution": "Engine rows derived from Wikipedia, 'List of game engines' (CC BY-SA 4.0, Wikipedia contributors); "
                       "factual fields only, prose columns dropped.",
        "source": {"wikipedia": {k: meta.get(k) for k in ("title", "revid", "timestamp", "url")},
                   "named_tools": str(NAMED_PATH)},
        "counts": {"wikipedia_rows": len(rows), "wikipedia_unique": len(engines), "wikipedia_duplicates": dup,
                   "named_tools": len(named)},
        "engines": [engines[k] for k in sorted(engines)],
        "named_tools": named,
    }
    tiers: dict[str, int] = {}
    for e in doc["engines"]:
        t = e["profile"]["tier"] or "named"
        tiers[t] = tiers.get(t, 0) + 1
    doc["counts"]["wikipedia_by_tier"] = dict(sorted(tiers.items()))
    doc["counts"]["named_by_tier"] = {t: sum(1 for n in named if n["tier"] == t) for t in TIERS}
    if write:
        hdr = ("# GENERATED — do not edit by hand. Rebuild: python -m forge.universal.catalog_build fetch && "
               "python -m forge.universal.catalog_build build\n# Copyright © 2026 Recharged Ideas (catalog structure); "
               "engine facts from Wikipedia (CC BY-SA 4.0).\n")
        (root / CATALOG_PATH).write_text(hdr + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=140),
                                         encoding="utf-8")
    return doc["counts"]


_CACHE: dict[str, Any] = {}


def load(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    key = str(root)
    if key not in _CACHE:
        _CACHE[key] = yaml.safe_load((root / CATALOG_PATH).read_text(encoding="utf-8"))
    return _CACHE[key]


def entries(root: Path | None = None) -> list[dict[str, Any]]:
    """Flattened view: every Wikipedia engine + every named tool as {id, name, kind, dims, adapter, tier, ...}."""
    cat = load(root)
    out = []
    named = {n["id"]: n for n in cat["named_tools"]}
    for e in cat["engines"]:
        p = e["profile"]
        if p["named_tool"]:
            n = named[p["named_tool"]]
            out.append({"id": e["id"], "name": e["name"], "kind": "engine", "source": "wikipedia+named",
                        "dims": p["dims"], "adapter": n["adapter"], "tier": n["tier"], "convention": n["convention"],
                        "named_tool": n["id"]})
        else:
            out.append({"id": e["id"], "name": e["name"], "kind": "engine", "source": "wikipedia", "dims": p["dims"],
                        "adapter": p["adapter"], "tier": p["tier"], "convention": p["convention"], "packs": p["packs"],
                        "tier_reason": p["tier_reason"]})
    wiki_ids = {e["id"] for e in cat["engines"]}
    for n in cat["named_tools"]:
        if n["id"] in wiki_ids:
            continue
        out.append({"id": n["id"], "name": n["name"], "kind": n["kind"], "source": "named", "dims": n["dims"],
                    "adapter": n["adapter"], "tier": n["tier"], "convention": n["convention"],
                    "direction": n.get("direction"), "inference": bool(n.get("inference"))})
    return out


def search(query: str = "", dims: str | None = None, tier: str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    q = query.lower().strip()
    res = []
    for e in entries(root):
        if q and q not in e["name"].lower() and q not in e["id"]:
            continue
        if dims and dims not in e["dims"]:
            continue
        if tier and e["tier"] != tier:
            continue
        res.append(e)
    return res


def resolve(entry_id: str, root: Path | None = None) -> dict[str, Any]:
    for e in entries(root):
        if e["id"] == entry_id or e.get("named_tool") == entry_id:
            return e
    raise KeyError(f"no catalog entry {entry_id!r}")


def integrity(root: Path | None = None) -> dict[str, Any]:
    """Catalog invariants: unique ids, valid tiers/conventions, every adapter registered, counts consistent,
    every named tool from the user's request present, Wikipedia revision pinned."""
    from forge.universal import coords
    from forge.universal.exporters import REGISTRY
    cat = load(root)
    errs: list[str] = []
    ids = [e["id"] for e in cat["engines"]]
    if len(ids) != len(set(ids)):
        errs.append("duplicate engine ids")
    nids = [n["id"] for n in cat["named_tools"]]
    if len(nids) != len(set(nids)):
        errs.append("duplicate named-tool ids")
    if cat["counts"]["wikipedia_unique"] != len(ids) or cat["counts"]["named_tools"] != len(nids):
        errs.append("counts do not match entries")
    if not (cat["source"]["wikipedia"] or {}).get("revid"):
        errs.append("Wikipedia revision not pinned")
    for e in entries(root):
        if e["tier"] not in TIERS:
            errs.append(f"{e['id']}: tier {e['tier']!r}")
        if e["convention"] not in coords.CONVENTIONS:
            errs.append(f"{e['id']}: convention {e['convention']!r}")
        if e["adapter"] and e["adapter"] not in REGISTRY:
            errs.append(f"{e['id']}: adapter {e['adapter']!r} not registered")
        if e["tier"] != "descriptor_only" and not e["adapter"]:
            errs.append(f"{e['id']}: tier {e['tier']} without adapter")
    required = {"unreal-engine", "creative-engine", "rpg-maker", "sprite-lamp", "sprite-pro", "gameguru", "clickteam-fusion",
                "construct-2", "coppercube-6", "esenthel", "epic-character-generator", "agfpro-3", "appgamekit",
                "raysupreme-3d", "fuse", "flipside-studio", "blender", "unity", "godot", "openscad", "colmap", "meshroom",
                "realitycapture", "openmvs", "opensplat", "nerfstudio", "postshot", "supersplat"}
    missing = sorted(required - set(nids))
    if missing:
        errs.append(f"named tools missing: {missing}")
    return {"ok": not errs, "errors": errs, "wikipedia_unique": len(ids), "named_tools": len(nids),
            "entries_total": len(entries(root)), "by_tier": _by_tier(entries(root))}


def _by_tier(es: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {t: 0 for t in TIERS}
    for e in es:
        out[e["tier"]] = out.get(e["tier"], 0) + 1
    return out
