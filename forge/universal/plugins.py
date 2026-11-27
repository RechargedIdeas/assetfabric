# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Plugins + gap detection: how the universal engine grows new capabilities safely.

Lifecycle (CLI: `forge universal gaps | plugin-scaffold | plugin-verify | plugin-register | plugin-rollback | plugins`):

  gaps()      diff content/universal/capabilities.yaml (+ catalog/GroundWeave state) against what built-ins and registered
              plugins actually advertise → ranked list of missing capabilities with a suggested next step.
  scaffold()  write a plugin skeleton (plugin.yaml + adapter.py) for a missing format. The skeleton's export raises
              NotImplementedError, so it FAILS the contract until someone implements it — no placeholder passes.
  verify()    1. manifest schema (id slug, semver, api major, tier/dims/direction/kind, permissions)
              2. static security policy over every .py file (AST): import allow-list, banned builtins, no dunder
                 attribute access, no direct filesystem writes (all writes go through Pack.add), no binary code
              3. contract suite run inside forge.sandbox (bwrap: no network, read-only root): class matches manifest,
                 every declared dimension exports the reference scene twice byte-identically, verify() passes,
                 manifest is honest (adapter id/tier/source digest); import adapters must yield valid, deterministic IR
  register()  re-verifies (never trusts a cached result), refuses built-in ids and non-increasing versions, copies
              the plugin into the local state dir with a tree hash; previous versions are kept for rollback.
  load_active() hot-loads active plugins into the adapter REGISTRY as sandboxed proxies after re-checking the tree
              hash (tamper ⇒ refused). Plugin code only ever runs inside the sandbox.

Plugin tiers are limited to interchange_pack / descriptor_only in U1: plugins may not spawn processes, so they cannot
honestly claim native_verified or cli_bridge."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import yaml

from forge.paths import find_repo_root
from forge.universal import ADAPTER_API_VERSION

STATE_REL = Path(".fabric/universal/plugins")
CAPABILITIES = Path("content/universal/capabilities.yaml")
PLUGIN_TIERS = ("interchange_pack", "descriptor_only")
KINDS = ("adapter",)
DIMS = ("2d", "2.5d", "3d")
DIRECTIONS = ("export", "import", "both")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
MAX_FILES, MAX_BYTES = 50, 512 * 1024
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".png"}

ALLOWED_IMPORTS = {"numpy", "json", "math", "struct", "zlib", "hashlib", "re", "typing", "dataclasses", "io", "base64",
                   "itertools", "collections", "functools", "enum", "string", "textwrap", "fractions", "decimal",
                   "xml.etree.ElementTree", "__future__", "pathlib"}
ALLOWED_FORGE = "forge.universal"
DENIED_FORGE = {"forge.universal.plugins", "forge.universal.plugin_worker", "forge.universal.native",
                "forge.universal.evolution", "forge.universal.catalog_build"}
BANNED_NAMES = {"eval", "exec", "compile", "__import__", "open", "input", "breakpoint", "globals", "locals", "vars",
                "getattr", "setattr", "delattr", "memoryview", "__builtins__"}
ALLOWED_DUNDERS = {"__init__", "__name__", "__future__"}
BANNED_ATTRS = {"write_text", "write_bytes", "unlink", "rmdir", "rename", "chmod", "symlink_to", "hardlink_to", "touch",
                "open", "tofile", "savez", "savetxt", "fromfile", "system", "popen", "rmtree", "ctypeslib", "ctypes",
                "f_globals", "gi_frame", "tb_frame", "f_back"}


def _root(root: Path | None) -> Path:
    return Path(root) if root else find_repo_root()


def state_dir(root: Path | None = None, sd: Path | None = None) -> Path:
    return Path(sd) if sd else _root(root) / STATE_REL


def _semver(v: str) -> tuple[int, int, int]:
    m = SEMVER.match(str(v))
    if not m:
        raise ValueError(f"not semver: {v!r}")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def tree_digest(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(d).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(d)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


# ----------------------------------------------------------------------------- manifest + static policy

def read_manifest(plugin: Path) -> dict[str, Any]:
    return yaml.safe_load((Path(plugin) / "plugin.yaml").read_text(encoding="utf-8")) or {}


def check_manifest(m: dict[str, Any], builtin_ids: set[str] | None = None) -> list[str]:
    errs = []
    for k in ("id", "name", "version", "api_version", "kind", "entrypoint", "tier", "dims"):
        if k not in m:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if not SLUG.match(str(m["id"])):
        errs.append(f"id {m['id']!r} is not a slug")
    if builtin_ids and m["id"] in builtin_ids:
        errs.append(f"id {m['id']!r} collides with a built-in adapter")
    if not SEMVER.match(str(m["version"])):
        errs.append(f"version {m['version']!r} is not semver")
    if str(m["api_version"]).split(".")[0] != ADAPTER_API_VERSION.split(".")[0]:
        errs.append(f"api_version {m['api_version']} incompatible with {ADAPTER_API_VERSION}")
    if m["kind"] not in KINDS:
        errs.append(f"kind {m['kind']!r} not supported (U1: {KINDS})")
    if m["tier"] not in PLUGIN_TIERS:
        errs.append(f"tier {m['tier']!r} not allowed for plugins (allowed {PLUGIN_TIERS}: plugins cannot run native tools)")
    if not m["dims"] or any(d not in DIMS for d in m["dims"]):
        errs.append(f"dims {m['dims']} invalid")
    if m.get("direction", "export") not in DIRECTIONS:
        errs.append(f"direction {m.get('direction')!r} invalid")
    if not re.match(r"^[A-Za-z0-9_/]+\.py:[A-Za-z_][A-Za-z0-9_]*$", str(m["entrypoint"])) or ".." in str(m["entrypoint"]):
        errs.append(f"entrypoint {m['entrypoint']!r} must be 'file.py:Class' inside the plugin")
    perms = m.get("permissions", {}) or {}
    if perms.get("network") or perms.get("subprocess"):
        errs.append("permissions network/subprocess are not grantable to plugins")
    if perms.get("filesystem", "pack") != "pack":
        errs.append("filesystem permission must be 'pack' (writes only through Pack.add)")
    return errs


def _module_ok(name: str) -> bool:
    if name in ALLOWED_IMPORTS or name == "numpy.linalg":
        return True
    if name == ALLOWED_FORGE or name.startswith(ALLOWED_FORGE + "."):
        return not any(name == d or name.startswith(d + ".") for d in DENIED_FORGE)
    return False


def security_scan(plugin: Path) -> dict[str, Any]:
    """Static policy. Returns {"ok", "violations": [...], "files", "bytes"}."""
    plugin = Path(plugin)
    v: list[str] = []
    files = [p for p in sorted(plugin.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    total = sum(p.stat().st_size for p in files)
    if len(files) > MAX_FILES or total > MAX_BYTES:
        v.append(f"too large ({len(files)} files, {total} bytes; limits {MAX_FILES}/{MAX_BYTES})")
    for p in files:
        rel = str(p.relative_to(plugin))
        if p.is_symlink():
            v.append(f"{rel}: symlinks not allowed")
        if p.suffix not in TEXT_SUFFIXES:
            v.append(f"{rel}: file type {p.suffix or '(none)'} not allowed (no binary code)")
        if p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as e:
            v.append(f"{rel}: syntax error {e}")
            continue
        for node in ast.walk(tree):
            ln = getattr(node, "lineno", 0)
            if isinstance(node, ast.Import):
                for a in node.names:
                    if not _module_ok(a.name):
                        v.append(f"{rel}:{ln}: import {a.name} not allowed")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    mod = node.module or ""
                    if not _module_ok(mod):
                        v.append(f"{rel}:{ln}: from {mod} import not allowed")
                    else:
                        for a in node.names:
                            if f"{mod}.{a.name}" in DENIED_FORGE:
                                v.append(f"{rel}:{ln}: from {mod} import {a.name} not allowed")
            elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
                v.append(f"{rel}:{ln}: use of {node.id} not allowed")
            elif isinstance(node, ast.Attribute):
                if node.attr.startswith("__") and node.attr.endswith("__") and node.attr not in ALLOWED_DUNDERS:
                    v.append(f"{rel}:{ln}: dunder attribute {node.attr} not allowed")
                elif node.attr in BANNED_ATTRS:
                    v.append(f"{rel}:{ln}: .{node.attr} not allowed (write files only through Pack.add)")
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                v.append(f"{rel}:{ln}: global/nonlocal state not allowed")
    return {"ok": not v, "violations": v, "files": len(files), "bytes": total}


# ----------------------------------------------------------------------------- sandboxed contract suite

def _sandbox_call(plugin: Path, request: dict[str, Any], root: Path, profile: str = "gen", tier: str = "auto",
                  collect: str | None = None, dest: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    import sys

    from forge.sandbox import Sandbox
    with Sandbox(tier=tier, profile=profile, root=root) as sb:
        shutil.copytree(plugin, sb.scratch / "plugin", ignore=shutil.ignore_patterns("__pycache__"))
        res = sb.run([sys.executable, "-s", "-m", "forge.universal.plugin_worker"], json.dumps({**request, "plugin": "plugin"}))
        meta = {"sandbox_tier": sb.tier, "wall_ms": res.wall_ms, "cpu_s": res.cpu_s, "killed": res.killed, "rc": res.returncode}
        try:
            out = json.loads(res.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            out = {"ok": False, "errors": [f"worker produced no result (rc={res.returncode}, killed={res.killed}): "
                                           f"{res.stderr[-800:]}"], "checks": {"ran": False}}
        if collect and dest is not None and (sb.scratch / collect).exists():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(sb.scratch / collect, dest)
    return out, meta


def verify(plugin: Path, root: Path | None = None, tier: str = "auto") -> dict[str, Any]:
    from forge.universal.exporters import BUILTINS
    root = _root(root)
    plugin = Path(plugin).resolve()
    rep: dict[str, Any] = {"plugin": str(plugin), "checks": {}, "errors": []}
    try:
        m = read_manifest(plugin)
    except (OSError, yaml.YAMLError) as e:
        rep.update(ok=False, errors=[f"plugin.yaml unreadable: {e}"], checks={"manifest": False})
        return rep
    rep["id"], rep["version"] = m.get("id"), m.get("version")
    merrs = check_manifest(m, {a.id for a in BUILTINS})
    rep["checks"]["manifest"] = not merrs
    rep["errors"] += merrs
    scan = security_scan(plugin)
    rep["checks"]["security_policy"] = scan["ok"]
    rep["errors"] += scan["violations"]
    rep["security"] = {k: scan[k] for k in ("files", "bytes")}
    if merrs or not scan["ok"]:
        rep["checks"]["contract"] = False
        rep["errors"].append("contract suite not run: manifest/security checks failed")
        rep["ok"] = False
        return rep
    res, meta = _sandbox_call(plugin, {"op": "contract", "manifest": m}, root, tier=tier)
    rep["sandbox"] = meta
    rep["contract"] = {k: res.get(k) for k in ("checks", "detail")}
    rep["checks"]["contract"] = bool(res.get("ok"))
    rep["errors"] += list(res.get("errors", []))
    rep["tree_sha256"] = tree_digest(plugin)
    rep["ok"] = all(rep["checks"].values()) and not rep["errors"]
    return rep


# ----------------------------------------------------------------------------- registration + hot-load

def _state_file(sd: Path) -> Path:
    return sd / "plugins.json"


def load_state(root: Path | None = None, sd: Path | None = None) -> dict[str, Any]:
    p = _state_file(state_dir(root, sd))
    return json.loads(p.read_text()) if p.exists() else {"schema_version": "1.0", "plugins": {}}


def _save_state(st: dict[str, Any], sd: Path) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    tmp = _state_file(sd).with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n")
    tmp.replace(_state_file(sd))


def register(plugin: Path, root: Path | None = None, sd: Path | None = None, tier: str = "auto") -> dict[str, Any]:
    root = _root(root)
    sd = state_dir(root, sd)
    rep = verify(plugin, root, tier)
    if not rep["ok"]:
        return {"ok": False, "registered": False, "reason": "verification failed", "verify": rep}
    st = load_state(root, sd)
    pid, ver = rep["id"], rep["version"]
    cur = st["plugins"].get(pid)
    if cur and cur.get("active") and _semver(ver) <= _semver(cur["active"]):
        return {"ok": False, "registered": False, "verify": rep,
                "reason": f"version {ver} is not newer than active {cur['active']} (use plugin-rollback to go back)"}
    dest = sd / pid / ver
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(Path(plugin), dest, ignore=shutil.ignore_patterns("__pycache__"))
    entry = st["plugins"].setdefault(pid, {"versions": {}, "active": None, "history": []})
    m = read_manifest(dest)
    entry["versions"][ver] = {"path": str(dest.relative_to(sd)), "tree_sha256": tree_digest(dest),
                              "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "formats": list(m.get("formats", [])), "dims": list(m["dims"]), "tier": m["tier"],
                              "direction": m.get("direction", "export"), "name": m["name"],
                              "contract": rep.get("contract"), "sandbox_tier": rep.get("sandbox", {}).get("sandbox_tier")}
    if entry["active"]:
        entry["history"].append(entry["active"])
    entry["active"] = ver
    _save_state(st, sd)
    return {"ok": True, "registered": True, "id": pid, "version": ver, "previous": entry["history"][-1] if entry["history"] else None,
            "verify": rep}


def rollback(pid: str, root: Path | None = None, sd: Path | None = None) -> dict[str, Any]:
    sd = state_dir(root, sd)
    st = load_state(root, sd)
    e = st["plugins"].get(pid)
    if not e or not e.get("active"):
        return {"ok": False, "reason": f"plugin {pid!r} is not active"}
    frm = e["active"]
    e["active"] = e["history"].pop() if e["history"] else None
    _save_state(st, sd)
    return {"ok": True, "id": pid, "from": frm, "to": e["active"]}


def active(root: Path | None = None, sd: Path | None = None) -> dict[str, dict[str, Any]]:
    st = load_state(root, sd)
    return {pid: {"version": e["active"], **e["versions"][e["active"]]} for pid, e in sorted(st["plugins"].items()) if e.get("active")}


class SandboxedPluginAdapter:
    """Registry proxy for a registered plugin: export/verify run the plugin inside the sandbox; the host copies the
    pack out and re-checks the manifest hashes itself."""

    def __init__(self, plugin_dir: Path, manifest: dict[str, Any], root: Path) -> None:
        self.plugin_dir, self.manifest, self.root = plugin_dir, manifest, root
        self.id, self.name, self.tier = manifest["id"], manifest["name"], manifest["tier"]
        self.direction = manifest.get("direction", "export")
        self.dims, self.formats = tuple(manifest["dims"]), tuple(manifest.get("formats", ()))
        self.convention, self.version = manifest.get("convention", "gltf"), manifest["version"]
        self.api_version, self.plugin = str(manifest["api_version"]), True
        self._last: dict[str, Any] = {}

    def export(self, scene, out: Path) -> dict[str, Any]:
        res, meta = _sandbox_call(self.plugin_dir, {"op": "export", "manifest": self.manifest, "scene_json": scene.to_json(),
                                                    "out": "out"}, self.root, collect="out", dest=Path(out))
        if not res.get("ok"):
            raise RuntimeError(f"plugin {self.id} export failed in sandbox: {res.get('errors') or res.get('verify')}")
        self._last = {"sandbox": meta, "verify": res.get("verify")}
        return res["manifest"]

    def verify(self, out: Path) -> dict[str, Any]:
        from forge.universal.exporters.base import verify_manifest
        errs = verify_manifest(Path(out))
        inner = self._last.get("verify") or {}
        checks = {"manifest": not errs, "plugin_verify_in_sandbox": bool(inner.get("ok"))}
        return {"ok": all(checks.values()), "checks": checks, "errors": errs + list(inner.get("errors", []))}

    def native_check(self, out: Path) -> dict[str, Any]:
        return {"ran": False, "reason": "plugins cannot run native tools"}

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "tier": self.tier, "direction": self.direction, "dims": list(self.dims),
                "convention": self.convention, "formats": list(self.formats), "api_version": self.api_version,
                "version": self.version, "plugin": True}


def load_active(registry: dict[str, Any] | None = None, root: Path | None = None, sd: Path | None = None) -> dict[str, Any]:
    from forge.universal.exporters import REGISTRY
    registry = REGISTRY if registry is None else registry
    root = _root(root)
    sd = state_dir(root, sd)
    loaded, refused = [], {}
    for pid, info in active(root, sd).items():
        d = sd / info["path"]
        if not d.exists() or tree_digest(d) != info["tree_sha256"]:
            refused[pid] = "tree hash mismatch (plugin files changed after registration)"
            continue
        scan = security_scan(d)
        if not scan["ok"]:
            refused[pid] = f"security policy: {scan['violations'][:3]}"
            continue
        if pid in registry and not getattr(registry[pid], "plugin", False):
            refused[pid] = "collides with a built-in adapter"
            continue
        registry[pid] = SandboxedPluginAdapter(d, read_manifest(d), root)
        loaded.append(f"{pid}@{info['version']}")
    return {"loaded": loaded, "refused": refused}


# ----------------------------------------------------------------------------- scaffold

SCAFFOLD_PY = '''# Plugin skeleton generated by `forge universal plugin-scaffold`. It FAILS the contract suite until implemented.
"""{name}: AssetFabric adapter plugin for {formats}."""

import json

from forge.universal.exporters.base import Adapter, Pack, finish_verify


class {cls}(Adapter):
    id = "{id}"
    name = "{name}"
    tier = "interchange_pack"
    direction = "export"
    dims = {dims!r}
    convention = "gltf"
    formats = {fmts!r}
    version = "0.1.0"

    def export(self, scene, out):
        pack = Pack(out)
        # Write files ONLY through pack.add(relative_path, bytes_or_str); keep output deterministic (sorted keys,
        # no timestamps, no randomness). See content/universal/plugins/x3d-export for a complete example.
        raise NotImplementedError("{id}: export not implemented yet")

    def verify(self, out):
        # Re-read what export() wrote with an independent parser and compare against the IR / manifest.
        return finish_verify({{"implemented": False}}, ["verify not implemented"], out)
'''


def scaffold(pid: str, out: Path, formats: list[str], dims: list[str], name: str | None = None) -> dict[str, Any]:
    if not SLUG.match(pid):
        raise ValueError(f"id {pid!r} is not a slug")
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    name = name or f"{pid} adapter"
    cls = "".join(w.capitalize() for w in re.split(r"[-_]", pid)) + "Adapter"
    man = {"id": pid, "name": name, "version": "0.1.0", "api_version": ADAPTER_API_VERSION, "kind": "adapter",
           "entrypoint": f"adapter.py:{cls}", "tier": "interchange_pack", "direction": "export", "dims": list(dims),
           "formats": list(formats), "convention": "gltf",
           "permissions": {"network": False, "subprocess": False, "filesystem": "pack"},
           "description": f"Scaffold for {', '.join(formats)}; implement export()/verify() then run plugin-verify."}
    (out / "plugin.yaml").write_text(yaml.safe_dump(man, sort_keys=False), encoding="utf-8")
    (out / "adapter.py").write_text(SCAFFOLD_PY.format(name=name, formats=", ".join(formats), cls=cls, id=pid,
                                                       dims=tuple(dims), fmts=tuple(formats)), encoding="utf-8")
    return {"ok": True, "path": str(out), "files": ["plugin.yaml", "adapter.py"], "manifest": man}


# ----------------------------------------------------------------------------- gap detection

def gaps(root: Path | None = None, sd: Path | None = None) -> dict[str, Any]:
    """Everything the engine is expected to do but cannot yet, from live state (never a hand-maintained list)."""
    from forge.universal import registry as R
    from forge.universal.exporters import BUILTINS
    root = _root(root)
    caps = yaml.safe_load((root / CAPABILITIES).read_text(encoding="utf-8"))
    have: dict[str, list[str]] = {}
    for a in BUILTINS:
        for f in a.formats:
            have.setdefault(f, []).append(a.id)
    plugs = active(root, sd)
    for pid, info in plugs.items():
        for f in info.get("formats", []):
            have.setdefault(f, []).append(f"plugin:{pid}")
    alias = {"png-normal": "png-normal", "3dgs-ply": "3dgs-ply"}
    items: list[dict[str, Any]] = []
    covered = {}
    for f, spec in caps.get("formats", {}).items():
        who = have.get(alias.get(f, f), [])
        covered[f] = who
        if not who:
            items.append({"kind": "format", "id": f, "severity": "high" if f in ("fbx", "usd") else "medium",
                          "detail": spec.get("why", ""),
                          "next": f"forge universal plugin-scaffold {f}-export --format {f} --dims {','.join(spec.get('dims', ['3d']))}"})
    for feat, spec in caps.get("features", {}).items():
        items.append({"kind": "feature", "id": feat, "severity": "medium", "detail": spec.get("why", ""),
                      "next": "needs a 'processor' plugin kind (not in U1: plugins are adapters only)"})
    es = R.entries(root)
    desc = [e["id"] for e in es if e["tier"] == "descriptor_only"]
    if desc:
        items.append({"kind": "catalog", "id": "descriptor_only", "severity": "low", "count": len(desc), "sample": desc[:12],
                      "detail": "catalog engines whose import formats are unconfirmed (generic glTF/OBJ/atlas pack only)",
                      "next": "confirm the engine's documented import formats, then add a curated convention/pack in registry.py"})
    inf = [e["id"] for e in es if e.get("inference")]
    if inf:
        items.append({"kind": "catalog", "id": "inference_flagged", "severity": "low", "count": len(inf), "sample": inf,
                      "detail": "named tools whose formats are extrapolated ([INFERENCE] U1-*)",
                      "next": "verify against the tool's own documentation or a sample project"})
    no_native = sorted(a.id for a in BUILTINS if a.tier != "native_verified")
    items.append({"kind": "verification", "id": "no_native_check", "severity": "low", "count": len(no_native),
                  "sample": no_native, "detail": "adapters validated by AssetFabric's own readers only (the tool is not run)",
                  "next": "add a headless native check where the tool has a Linux CLI"})
    lad = yaml.safe_load((root / "content/groundweave/ladder.yaml").read_text(encoding="utf-8"))
    planned = sorted({f"{op}:{r['id']}@{r['device']}" for op, spec in lad["ops"].items() for r in spec["ladder"]
                      if r.get("impl") == "planned"})
    if planned:
        items.append({"kind": "acceleration", "id": "planned_gpu_rungs", "severity": "low", "count": len(planned),
                      "sample": planned[:12], "detail": "GroundWeave rungs not implemented (CPU rung serves these ops)",
                      "next": "implement + benchmark the rung; GroundWeave verify enforces byte-identical output"})
    rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda g: (rank[g["severity"]], g["kind"], g["id"]))
    fmt_total = len(caps.get("formats", {}))
    return {"gaps": items, "formats_covered": sum(1 for v in covered.values() if v), "formats_total": fmt_total,
            "coverage": covered, "plugins_active": sorted(plugs)}
