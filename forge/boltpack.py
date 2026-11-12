"""BoltPack — SBOM-audited publish packages (``.fabricbolt``) (SPEC §4.5: "Signed, SBOM-audited publish
packages — F7").

Per platform build:

* ``dist/<target>/sbom.cdx.json`` — CycloneDX 1.5 SBOM of what actually ships: the Godot 4.3-stable runtime
  (template SHA-256 for that platform), every third-party component compiled into the engine as reported
  by the engine itself (``Engine.get_copyright_info()``), platform extras (Android ``libc++_shared``,
  Web Emscripten runtime), and Game Zero content (proprietary; per-asset Fabric provenance).
* ``dist/<target>/LICENSES/`` — license manifest + texts (Godot MIT + engine third-party notices, our
  proprietary LICENSE, THIRD_PARTY_NOTICES.md).
* License audit — every license id must be on the allow-list (permissive + our proprietary ref); any
  copyleft id (GPL/LGPL/AGPL/SSPL/EUPL) fails the bolt.
* ``dist/bolt/GameZero-<version>-<target>.fabricbolt`` — zip of the artifact dir + ``bolt.json`` manifest
  (file SHA-256s, SBOM digest, audit). **Unsigned**: ``bolt.json.signature`` records the TODO (no release
  keys yet, by producer direction no public releases).

Python/forge dependencies are build tools and do not ship inside Game Zero, so they are not in the game SBOM.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

ALLOWED = {"Expat", "MIT", "BSD-2-Clause", "BSD-3-Clause", "BSD-3-clause", "BSD-2-clause", "Zlib", "FTL", "Apache-2.0",
           "Apache-2.0 WITH LLVM-exception", "ISC", "OFL-1.1", "Unicode", "CC0-1.0", "CC0", "public-domain",
           "BSL-1.0", "MPL-2.0", "curl", "Bitstream-Vera", "MIT OR NCSA", "Unlicense", "Zlib or MIT", "Apache-2.0 or MIT",
           "LicenseRef-Proprietary", "Brotli", "Pixar", "Libpng", "IJG", "BSD-1-Clause", "MIT-0", "ICU", "Bitstream",
           "Unicode-DFS-2016", "OpenSSL", "HarfBuzz", "glslang", "CC-BY-4.0", "NCSA", "LLVM-exception"}
WEAK_COPYLEFT = {"MPL-2.0"}        # file-level copyleft: allowed for unmodified engine code, reported
COPYLEFT = ("GPL", "LGPL", "AGPL", "SSPL", "EUPL")
TEMPLATE_FOR = {"desktop-linux": "linux_release.x86_64", "desktop-windows": "windows_release_x86_64.exe",
                "android": "android_debug.apk", "web": "web_release.zip"}

ENGINE_INFO_GD = """extends SceneTree
func _init():
\tvar out := {"copyright": Engine.get_copyright_info(), "licenses": Engine.get_license_info().keys(),
\t\t"license_texts": Engine.get_license_info(), "godot_license": Engine.get_license_text(), "version": Engine.get_version_info()}
\tprint("ENGINE_INFO " + JSON.stringify(out))
\tquit(0)
"""


def engine_info(root: Path) -> dict[str, Any]:
    """Ask the Godot 4.3 binary itself what it bundles (cached under .fabric/cache)."""
    from forge.packaging import godot_bin

    cache = root / ".fabric" / "cache" / "godot-engine-info.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        s = Path(td) / "engine_info.gd"
        s.write_text(ENGINE_INFO_GD, encoding="utf-8")
        (Path(td) / "project.godot").write_text("config_version=5\n", encoding="utf-8")
        p = subprocess.run([godot_bin(root), "--headless", "--path", td, "--script", str(s)], capture_output=True, text=True, timeout=120)
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("ENGINE_INFO ")), None)
    if not line:
        raise RuntimeError("could not read engine copyright info:\n" + p.stdout[-1000:] + p.stderr[-1000:])
    info = json.loads(line[len("ENGINE_INFO "):])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(info), encoding="utf-8")
    return info


def _engine_components(info: dict[str, Any]) -> list[dict[str, Any]]:
    comps = []
    for c in info["copyright"]:
        if c["name"].lower().startswith("godot engine"):
            continue
        lic = sorted({p.get("license", "") for p in c.get("parts", []) if p.get("license")})
        comps.append({"type": "library", "name": c["name"], "scope": "required",
                      "licenses": [{"license": {"name": x}} for x in lic],
                      "copyright": "; ".join(sorted({cr for p in c.get("parts", []) for cr in p.get("copyright", [])}))[:500],
                      "properties": [{"name": "fabric:origin", "value": "compiled into Godot 4.3-stable (Engine.get_copyright_info)"}]})
    return comps


def sbom(root: Path, target: str, version: str) -> dict[str, Any]:
    from forge.packaging import TEMPLATE_VERSION, sha256_file, templates_dir
    from forge.shuttleline import registry

    info = engine_info(root)
    tpl = templates_dir(root) / TEMPLATE_FOR[target]
    gd = {"type": "framework", "name": "godot-engine", "version": "4.3-stable", "scope": "required",
          "purl": "pkg:github/godotengine/godot@4.3-stable", "licenses": [{"license": {"id": "MIT"}}],
          "hashes": [{"alg": "SHA-256", "content": sha256_file(tpl)}] if tpl.exists() else [],
          "properties": [{"name": "fabric:template", "value": f"{TEMPLATE_VERSION}/{TEMPLATE_FOR[target]}"}]}
    comps = [gd, *_engine_components(info)]
    if target == "android":
        comps.append({"type": "library", "name": "libc++_shared (Android NDK)", "scope": "required",
                      "licenses": [{"expression": "Apache-2.0 WITH LLVM-exception"}],
                      "properties": [{"name": "fabric:origin", "value": "bundled in android_debug.apk template (lib/arm64-v8a)"}]})
        comps.append({"type": "library", "name": "godot-android-lib", "version": "4.3-stable", "scope": "required",
                      "licenses": [{"license": {"id": "MIT"}}]})
    if target == "web":
        comps.append({"type": "library", "name": "emscripten-runtime", "scope": "required",
                      "licenses": [{"expression": "MIT OR NCSA"}],
                      "properties": [{"name": "fabric:origin", "value": "generated JS/wasm glue in web_release.zip"}]})
    reg = registry(root)
    gens = sorted({(a.get("meta") or {}).get("model_id", "?") for a in reg["assets"].values()})
    comps.append({"type": "application", "name": "game-zero", "version": version, "scope": "required",
                  "licenses": [{"license": {"id": "LicenseRef-Proprietary"}}],
                  "properties": [{"name": "fabric:assets", "value": str(len(reg["assets"]))},
                                 {"name": "fabric:generators", "value": ", ".join(gens)}]})
    seed = f"{target}:{version}:{gd['hashes'][0]['content'] if gd['hashes'] else ''}"
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "serialNumber": "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "assetfabric/" + seed)),
            "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "tools": [{"vendor": "Recharged Ideas", "name": "forge BoltPack", "version": version}],
                         "component": {"type": "application", "name": f"Game Zero ({target})", "version": version}},
            "components": comps}


def _license_ids(c: dict[str, Any]) -> list[str]:
    out = []
    for lic in c.get("licenses", []):
        if "expression" in lic:
            out.append(lic["expression"])
        else:
            out.append(lic["license"].get("id") or lic["license"].get("name"))
    return out


def audit(bom: dict[str, Any]) -> dict[str, Any]:
    seen: dict[str, list[str]] = {}
    for c in bom["components"]:
        for lid in _license_ids(c):
            seen.setdefault(lid, []).append(c["name"])
    import re as _re

    def atoms(expr: str) -> list[str]:
        return [a.strip("() ") for a in _re.split(r"\s+(?:and|or|AND|OR|WITH)\s+", expr) if a.strip("() ")]

    copyleft = {k: v for k, v in seen.items() if any(x in k.upper() for x in COPYLEFT)}
    unknown = {k: v for k, v in seen.items() if k not in copyleft and not all(a in ALLOWED for a in atoms(k))}
    no_license = [c["name"] for c in bom["components"] if not _license_ids(c)]
    return {"licenses": {k: len(v) for k, v in sorted(seen.items())}, "copyleft": copyleft, "unknown": unknown,
            "unlicensed_components": no_license,
            "weak_copyleft": {k: v for k, v in seen.items() if k in WEAK_COPYLEFT}, "ok": not copyleft and not unknown and not no_license}


def write_licenses(root: Path, d: Path, bom: dict[str, Any], aud: dict[str, Any]) -> None:
    info = engine_info(root)
    lic = d / "LICENSES"
    lic.mkdir(parents=True, exist_ok=True)
    (lic / "GODOT_LICENSE.txt").write_text(info["godot_license"], encoding="utf-8")
    notices = ["Third-party components compiled into Godot Engine 4.3-stable (from Engine.get_copyright_info()).", ""]
    for c in info["copyright"]:
        for p in c.get("parts", []):
            notices.append(f"{c['name']}: {', '.join(p.get('copyright', []))} — {p.get('license', '')}")
    notices += ["", "License texts:", ""]
    for k, v in sorted(info["license_texts"].items()):
        notices += [f"----- {k} -----", v, ""]
    (lic / "GODOT_THIRDPARTY.txt").write_text("\n".join(notices), encoding="utf-8")
    for f in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        if (root / f).exists():
            (lic / f).write_text((root / f).read_text(encoding="utf-8"), encoding="utf-8")
    manifest = {"target": bom["metadata"]["component"]["name"], "audit": aud,
                "components": [{"name": c["name"], "licenses": _license_ids(c)} for c in bom["components"]]}
    (lic / "license-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def bolt_target(root: Path, target: str, version: str) -> dict[str, Any]:
    from forge.packaging import dist_dir, sha256_file

    d = dist_dir(root) / target
    bom = sbom(root, target, version)
    aud = audit(bom)
    (d / "sbom.cdx.json").write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
    write_licenses(root, d, bom, aud)
    files = [{"path": str(p.relative_to(d)), "size": p.stat().st_size, "sha256": sha256_file(p)}
             for p in sorted(d.rglob("*")) if p.is_file() and p.name != "BUILD.json"]
    manifest = {"format": "fabricbolt/1", "name": "game-zero", "version": version, "target": target,
                "files": files, "sbom": {"path": "sbom.cdx.json", "sha256": sha256_file(d / "sbom.cdx.json"),
                                         "components": len(bom["components"])},
                "license_audit": aud, "signature": {"signed": False, "todo": "release signing key + detached signature (docs/packaging.md §Signing)"}}
    out_dir = dist_dir(root) / "bolt"
    out_dir.mkdir(parents=True, exist_ok=True)
    bolt = out_dir / f"GameZero-{version}-{target}.fabricbolt"
    with zipfile.ZipFile(bolt, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("bolt.json", json.dumps(manifest, indent=2) + "\n")
        for f in files:
            z.write(d / f["path"], "payload/" + f["path"])
    return {"ok": aud["ok"], "bolt": str(bolt.relative_to(root)), "bolt_size": bolt.stat().st_size,
            "bolt_sha256": hashlib.sha256(bolt.read_bytes()).hexdigest(), "components": len(bom["components"]),
            "licenses": aud["licenses"], "copyleft": aud["copyleft"], "unknown": aud["unknown"], "signed": False}
