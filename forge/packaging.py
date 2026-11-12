"""F7 packaging — Godot 4.3 exports for desktop-linux / desktop-windows / android / web (SPEC §3 Layer A, §13 F7).

``forge build --target <t>`` drives the checked-in presets (``games/game-zero/export_presets.cfg``)
through a hermetic Godot home:

* **Toolchain** — Godot 4.3-stable (``godot-bin/``), matching export templates (fetched + sha256-pinned
  into ``.fabric/godot-home``), JDK 17 + Android SDK for the APK (``JAVA_HOME`` / ``ANDROID_HOME`` /
  ``.fabric/jdk`` / ``/workspace/{jdk,android-sdk}``), a generated **debug** keystore. Nothing here is
  committed (``.fabric/godot-home``, ``dist/``, ``*.keystore`` are gitignored).
* **Stage** — the game is copied to ``dist/.stage/game-zero``; there the ``.gdignore`` that bypasses the
  editor import on ``assets/generated`` is removed and every PNG/WAV gets a ``importer="keep"`` stub, so
  Fabric output ships byte-for-byte as plain files (the runtime loads them itself — F1 design). The repo
  copy is never touched (determinism gate stays meaningful) [INFERENCE F7-2].
* **Export** — ``godot --headless --export-{release,debug} <preset>``; artifacts land in ``dist/<target>/``
  with ``BUILD.json`` (commands, sizes, SHA-256, toolchain, smoke results).
* **Post-steps** — per target smoke (exported Linux binary boots; PE header for Windows; aapt/apksigner
  for the APK; PWAPipeline for Web), ShuttleLine import contract and BoltPack (SBOM + license manifest).

Unsigned / debug builds only; code-signing, store signing and listings are TODO (docs/packaging.md).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GODOT_VERSION = "4.3"
TEMPLATE_VERSION = "4.3.stable"
TPZ_NAME = "Godot_v4.3-stable_export_templates.tpz"
TPZ_URL = f"https://github.com/godotengine/godot/releases/download/4.3-stable/{TPZ_NAME}"
TPZ_SHA256 = "f5f10dbaf56a7908349e64b94ea8c2c93c2cc11fb1014c9565b68a2bb437b922"
DEBUG_KEY_ALIAS = "androiddebugkey"
DEBUG_KEY_PASS = "android"          # the well-known Android *debug* keystore password — not a secret


@dataclass(frozen=True)
class Target:
    id: str
    preset: str
    kind: str                       # forge.yaml target kind
    mode: str                       # release | debug
    artifact: str                   # primary artifact, relative to dist/<id>/
    templates: tuple[str, ...]      # template files needed
    needs_android: bool = False
    notes: str = ""


TARGETS: dict[str, Target] = {
    "desktop-linux": Target("desktop-linux", "desktop-linux", "godot-desktop", "release", "GameZero.x86_64",
                            ("linux_release.x86_64", "linux_debug.x86_64")),
    "desktop-windows": Target("desktop-windows", "desktop-windows", "godot-desktop", "release", "GameZero.exe",
                              ("windows_release_x86_64.exe", "windows_release_x86_64_console.exe",
                               "windows_debug_x86_64.exe", "windows_debug_x86_64_console.exe"),
                              notes="cross-exported from Linux; unsigned (rcedit/codesign off)"),
    "android": Target("android", "android", "godot-android", "debug", "GameZero-debug.apk",
                      ("android_debug.apk", "android_release.apk"), needs_android=True,
                      notes="debug keystore, arm64-v8a, Compatibility renderer, no INTERNET permission"),
    "web": Target("web", "web", "godot-web", "release", "index.html",
                  ("web_release.zip", "web_debug.zip", "web_nothreads_release.zip", "web_nothreads_debug.zip"),
                  notes="threads build + PWA (offline SW, COOP/COEP)"),
}
ORDER = list(TARGETS)


# --------------------------------------------------------------------------- helpers

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def project_dir(root: Path) -> Path:
    from forge.manifest import load_manifest

    return root / load_manifest(None, root).game.project_path


def dist_dir(root: Path) -> Path:
    return root / "dist"


def godot_home(root: Path) -> Path:
    return root / ".fabric" / "godot-home"


def templates_dir(root: Path) -> Path:
    return godot_home(root) / "data" / "godot" / "export_templates" / TEMPLATE_VERSION


def game_version(root: Path) -> str:
    text = (project_dir(root) / "project.godot").read_text(encoding="utf-8")
    m = re.search(r'config/version="([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def _cands(*xs: Any) -> list[Path]:
    return [Path(x) for x in xs if x]


def find_jdk(root: Path) -> Path | None:
    """JDK 17+ home (Godot 4.3 Android export runs apksigner/keytool with it)."""
    globs = []
    for base in (root / ".fabric" / "jdk", Path("/workspace/jdk")):
        if base.is_dir():
            globs += sorted(base.glob("jdk-17*")) + sorted(base.glob("jdk-2*"))
    which = shutil.which("java")
    for c in _cands(os.environ.get("JAVA_HOME"), *globs, Path(which).resolve().parent.parent if which else None):
        if (c / "bin" / "java").exists() and (c / "bin" / "keytool").exists():
            return c
    return None


def find_android_sdk(root: Path) -> Path | None:
    lp = project_dir(root).parent.parent / "companions" / "pocketloom" / "local.properties"
    from_props = None
    if lp.exists():
        m = re.search(r"^sdk\.dir=(.+)$", lp.read_text(encoding="utf-8"), re.M)
        from_props = m.group(1).strip() if m else None
    for c in _cands(os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), from_props, "/workspace/android-sdk"):
        if (c / "build-tools").is_dir() and (c / "platform-tools").is_dir():
            return c
    return None


def build_tool(sdk: Path, name: str) -> Path | None:
    for d in sorted((sdk / "build-tools").iterdir(), reverse=True):
        if (d / name).exists():
            return d / name
    return None


def godot_bin(root: Path) -> str:
    from forge.milestones import godot_binary

    gb = godot_binary(root)
    if not gb:
        raise FileNotFoundError("Godot 4.3 binary not found (GODOT_BIN, PATH, or godot-bin/godot)")
    return gb


def godot_version(gb: str) -> str:
    try:
        return subprocess.run([gb, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def tool_env(root: Path) -> dict[str, str]:
    """Hermetic Godot home (templates + editor settings) + JDK on PATH (apksigner needs `java`)."""
    h = godot_home(root)
    env = dict(os.environ)
    env.update({"XDG_CONFIG_HOME": str(h / "config"), "XDG_DATA_HOME": str(h / "data"), "XDG_CACHE_HOME": str(h / "cache")})
    jdk = find_jdk(root)
    if jdk:
        env["JAVA_HOME"] = str(jdk)
        env["PATH"] = f"{jdk / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


# --------------------------------------------------------------------------- toolchain

def templates_status(root: Path) -> dict[str, Any]:
    d = templates_dir(root)
    need = sorted({t for tg in TARGETS.values() for t in tg.templates})
    have = [t for t in need if (d / t).exists()]
    ver = (d / "version.txt").read_text(encoding="utf-8").strip() if (d / "version.txt").exists() else None
    return {"dir": str(d), "version": ver, "ok": ver == TEMPLATE_VERSION and len(have) == len(need),
            "missing": [t for t in need if t not in have]}


def fetch_templates(root: Path, tpz: Path | None = None, log=print) -> dict[str, Any]:
    """Install the 4.3-stable templates we need into the hermetic home (download once, sha256-pinned)."""
    st = templates_status(root)
    if st["ok"]:
        return st | {"fetched": False}
    cache = root / ".fabric" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    cands = _cands(tpz, os.environ.get("FORGE_TEMPLATES_TPZ"), cache / TPZ_NAME, Path("/workspace/godot-templates/templates.tpz"))
    src = next((c for c in cands if c.exists()), None)
    if src is None:
        src = cache / TPZ_NAME
        log(f"downloading {TPZ_URL} (~1 GB) …")
        tmp = src.with_suffix(".part")
        with urllib.request.urlopen(TPZ_URL, timeout=600) as r, tmp.open("wb") as f:     # noqa: S310 (pinned https URL)
            shutil.copyfileobj(r, f, 1 << 20)
        tmp.rename(src)
    digest = sha256_file(src)
    if digest != TPZ_SHA256:
        raise RuntimeError(f"export templates sha256 mismatch: {digest} != {TPZ_SHA256} ({src})")
    d = templates_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    wanted = {f"templates/{t}" for tg in TARGETS.values() for t in tg.templates} | {"templates/version.txt"}
    with zipfile.ZipFile(src) as z:
        for name in wanted:
            with z.open(name) as i, (d / Path(name).name).open("wb") as o:
                shutil.copyfileobj(i, o, 1 << 20)
    return templates_status(root) | {"fetched": True, "tpz": str(src), "tpz_sha256": digest}


def ensure_android(root: Path) -> dict[str, Any]:
    """Debug keystore + editor settings (SDK / JDK / keystore) for the Android preset."""
    jdk, sdk = find_jdk(root), find_android_sdk(root)
    rep: dict[str, Any] = {"jdk": str(jdk) if jdk else None, "sdk": str(sdk) if sdk else None}
    if not jdk or not sdk:
        rep["ok"] = False
        rep["reason"] = "JDK 17 and Android SDK (build-tools, platform-tools) required"
        return rep
    h = godot_home(root)
    ks = h / "debug.keystore"
    if not ks.exists():
        h.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(jdk / "bin" / "keytool"), "-genkeypair", "-keystore", str(ks), "-storepass", DEBUG_KEY_PASS,
                        "-keypass", DEBUG_KEY_PASS, "-alias", DEBUG_KEY_ALIAS, "-dname", "CN=Android Debug,O=Android,C=US",
                        "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000"], check=True, capture_output=True)
    settings = ('[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
                f'export/android/android_sdk_path = "{sdk}"\nexport/android/java_sdk_path = "{jdk}"\n'
                f'export/android/debug_keystore = "{ks}"\nexport/android/debug_keystore_user = "{DEBUG_KEY_ALIAS}"\n'
                f'export/android/debug_keystore_pass = "{DEBUG_KEY_PASS}"\n')
    cfg = h / "config" / "godot"
    cfg.mkdir(parents=True, exist_ok=True)
    for n in ("editor_settings-4.3.tres", "editor_settings-4.tres"):
        (cfg / n).write_text(settings, encoding="utf-8")
    return rep | {"ok": True, "keystore": str(ks)}


def toolchain(root: Path) -> dict[str, Any]:
    gb = None
    try:
        gb = godot_bin(root)
    except FileNotFoundError:
        pass
    sdk = find_android_sdk(root)
    return {"godot": gb, "godot_version": godot_version(gb) if gb else None, "templates": templates_status(root),
            "jdk": str(find_jdk(root) or "") or None, "android_sdk": str(sdk) if sdk else None,
            "aapt": str(build_tool(sdk, "aapt") or "") if sdk else None,
            "wine": shutil.which("wine") or shutil.which("wine64"), "bwrap": shutil.which("bwrap"),
            "chrome": chrome_path()}


def chrome_path() -> str | None:
    for c in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(c)
        if p:
            return p
    return None


# --------------------------------------------------------------------------- stage + export

KEEP_IMPORT = '[remap]\n\nimporter="keep"\n'


def stage(root: Path, log=print) -> Path:
    """Copy the game to dist/.stage and turn the import-bypassed Fabric output into keep-as-is files."""
    src = project_dir(root)
    dst = dist_dir(root) / ".stage" / src.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".godot", "*.import"))
    gen = dst / "assets" / "generated"
    (gen / ".gdignore").unlink(missing_ok=True)
    for f in gen.rglob("*"):
        if f.suffix.lower() in (".png", ".wav", ".ogg", ".svg", ".jpg", ".webp"):
            Path(str(f) + ".import").write_text(KEEP_IMPORT, encoding="utf-8")
    proc = subprocess.run([godot_bin(root), "--headless", "--path", str(dst), "--import"], env=tool_env(root),
                          capture_output=True, text=True, timeout=600)
    if not (dst / ".godot").is_dir():
        raise RuntimeError("Godot import of the stage failed:\n" + proc.stdout[-2000:] + proc.stderr[-2000:])
    log(f"staged {src} → {dst}")
    return dst


def source_digest(root: Path) -> str:
    """Digest of the game sources that go into an export (for BUILD.json provenance)."""
    h = hashlib.sha256()
    base = project_dir(root)
    for p in sorted(base.rglob("*")):
        if p.is_file() and ".godot" not in p.parts and not p.name.endswith(".import"):
            h.update(str(p.relative_to(base)).encode())
            h.update(sha256_file(p).encode())
    return h.hexdigest()


def file_table(d: Path) -> list[dict[str, Any]]:
    return [{"path": str(p.relative_to(d)), "size": p.stat().st_size, "sha256": sha256_file(p)}
            for p in sorted(d.rglob("*")) if p.is_file() and p.name not in ("BUILD.json",)]


def export(root: Path, target: str, stage_dir: Path, log=print) -> dict[str, Any]:
    t = TARGETS[target]
    out_dir = dist_dir(root) / target
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    out = out_dir / t.artifact
    if t.needs_android:
        a = ensure_android(root)
        if not a["ok"]:
            return {"target": target, "ok": False, "error": a["reason"]}
    cmd = [godot_bin(root), "--headless", "--path", str(stage_dir), f"--export-{t.mode}", t.preset, str(out)]
    t0 = time.time()
    proc = subprocess.run(cmd, env=tool_env(root), capture_output=True, text=True, timeout=900)
    wall = round(time.time() - t0, 1)
    log_text = proc.stdout + proc.stderr
    (dist_dir(root) / ".logs").mkdir(parents=True, exist_ok=True)
    (dist_dir(root) / ".logs" / f"{target}.log").write_text(log_text, encoding="utf-8")
    ok = out.exists() and out.stat().st_size > 0 and "ERROR: Project export" not in log_text
    rel_cmd = ["godot", "--headless", "--path", "dist/.stage/game-zero", f"--export-{t.mode}", t.preset, f"dist/{target}/{t.artifact}"]
    rep = {"target": target, "ok": ok, "preset": t.preset, "mode": t.mode, "kind": t.kind, "notes": t.notes,
           "command": " ".join(rel_cmd), "export_wall_s": wall, "exit_code": proc.returncode,
           "errors": [ln for ln in log_text.splitlines() if ln.startswith("ERROR")][:10]}
    if ok:
        rep["artifact"] = {"path": f"dist/{target}/{t.artifact}", "size": out.stat().st_size, "sha256": sha256_file(out)}
    log(f"export {target}: {'ok' if ok else 'FAILED'} in {wall}s")
    return rep


# --------------------------------------------------------------------------- PCK / APK readers (ShuttleLine)

def read_pck(path: Path) -> dict[str, bytes]:
    """Godot 4 PCK (format v2) → {res path: bytes}. Plain, unencrypted packs only."""
    data = path.read_bytes()
    if data[:4] != b"GDPC":
        raise ValueError(f"{path} is not a Godot PCK")
    fmt, _maj, _min, _pat, flags, file_base = struct.unpack_from("<IIIIIQ", data, 4)
    if fmt != 2:
        raise ValueError(f"unsupported PCK format {fmt}")
    if flags & 1:
        raise ValueError("encrypted PCK directory")
    off = 4 + 4 * 5 + 8 + 16 * 4
    (count,) = struct.unpack_from("<I", data, off)
    off += 4
    out: dict[str, bytes] = {}
    for _ in range(count):
        (ln,) = struct.unpack_from("<I", data, off)
        off += 4
        name = data[off:off + ln].rstrip(b"\0").decode()
        off += ln
        foff, size = struct.unpack_from("<QQ", data, off)
        off += 16 + 16 + 4                                   # offset, size, md5, flags
        if not name.startswith("res://"):
            name = "res://" + name
        out[name] = data[file_base + foff:file_base + foff + size]
    return out


def read_apk_assets(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {"res://" + n[len("assets/"):]: z.read(n) for n in z.namelist() if n.startswith("assets/") and not n.endswith("/")}


def shipped_files(root: Path, target: str) -> dict[str, bytes]:
    d = dist_dir(root) / target
    if target == "android":
        return read_apk_assets(d / TARGETS[target].artifact)
    if target == "web":
        return read_pck(d / "index.pck")
    return read_pck(d / "GameZero.pck")


def unpack_android_content(root: Path, dest: Path) -> Path:
    """Extract the APK's packed project (assets/) so the exact Android content can be exercised by the desktop
    runtime when no device/emulator is available (labelled as such in reports)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for res, blob in shipped_files(root, "android").items():
        p = dest / res[len("res://"):]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    return dest


# --------------------------------------------------------------------------- per-target verification

def pe_info(p: Path) -> dict[str, Any]:
    b = p.read_bytes()[:4096]
    if b[:2] != b"MZ":
        return {"pe": False}
    (pe_off,) = struct.unpack_from("<I", b, 0x3C)
    sig = b[pe_off:pe_off + 4]
    machine, nsec = struct.unpack_from("<HH", b, pe_off + 4)
    opt = pe_off + 24
    (magic,) = struct.unpack_from("<H", b, opt)
    (subsystem,) = struct.unpack_from("<H", b, opt + 68)
    return {"pe": sig == b"PE\0\0", "machine": hex(machine), "x86_64": machine == 0x8664, "pe32_plus": magic == 0x20B,
            "subsystem": {2: "windows_gui", 3: "windows_cui"}.get(subsystem, subsystem), "sections": nsec}


def run_exported(binary: Path, *args: str, timeout: int = 300, sandbox_net: bool = False, extra: list[str] | None = None,
                 cwd: Path | None = None) -> tuple[int, str]:
    cmd = [str(binary), "--headless", *(extra or []), "--", *args]
    if sandbox_net and shutil.which("bwrap"):
        cmd = ["bwrap", "--dev-bind", "/", "/", "--unshare-net", "--die-with-parent", *cmd]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    return proc.returncode, proc.stdout + proc.stderr


def verify_desktop_linux(root: Path) -> dict[str, Any]:
    from forge.milestones import parse_output

    b = dist_dir(root) / "desktop-linux" / TARGETS["desktop-linux"].artifact
    code, out = run_exported(b, "--net-report", timeout=60)
    r = parse_output(out)
    boots = r.get("_boot_ok", False) and code == 0
    return {"ok": boots and bool((r.get("net") or {}).get("offline_peer")), "boots": boots, "net": r.get("net"),
            "version": r.get("version"), "how": "exported binary run headless (--net-report)"}


def verify_desktop_windows(root: Path) -> dict[str, Any]:
    d = dist_dir(root) / "desktop-windows"
    rep: dict[str, Any] = {"exe": pe_info(d / "GameZero.exe"), "console_wrapper": pe_info(d / "GameZero.console.exe")
                           if (d / "GameZero.console.exe").exists() else None,
                           "pck_present": (d / "GameZero.pck").exists()}
    try:
        lin, win = shipped_files(root, "desktop-linux"), shipped_files(root, "desktop-windows")
        # Same file set; every data file byte-identical. Compiled GDScript (.gdc binary tokens) is re-tokenised
        # per export and not byte-stable across exports, so scripts are compared by presence only [INFERENCE F7-7].
        rep["pck_fileset_equal_linux"] = set(lin) == set(win)
        rep["pck_data_equal_linux"] = all(lin[k] == win.get(k) for k in lin if not k.endswith(".gdc"))
        rep["pck_content_equal_linux"] = rep["pck_fileset_equal_linux"] and rep["pck_data_equal_linux"]
    except (OSError, ValueError) as exc:
        rep["pck_content_equal_linux"] = False
        rep["pck_error"] = str(exc)
    wine = shutil.which("wine") or shutil.which("wine64")
    if wine:
        try:
            p = subprocess.run([wine, str(d / "GameZero.console.exe"), "--headless", "--", "--net-report"],
                               capture_output=True, text=True, timeout=180)
            rep["wine_smoke"] = {"ran": True, "boot_ok": "Game Zero F0 boot OK" in p.stdout + p.stderr}
        except (OSError, subprocess.SubprocessError) as exc:
            rep["wine_smoke"] = {"ran": False, "reason": str(exc)}
    else:
        rep["wine_smoke"] = {"ran": False, "reason": "wine not installed on the build host (documented; run on Windows)"}
    rep["ok"] = bool(rep["exe"].get("pe") and rep["exe"].get("x86_64") and rep["pck_present"] and rep["pck_content_equal_linux"])
    return rep


def verify_android(root: Path) -> dict[str, Any]:
    sdk = find_android_sdk(root)
    apk = dist_dir(root) / "android" / TARGETS["android"].artifact
    rep: dict[str, Any] = {"apk_size": apk.stat().st_size}
    env = tool_env(root)
    aapt = build_tool(sdk, "aapt") if sdk else None
    if aapt:
        badging = subprocess.run([str(aapt), "dump", "badging", str(apk)], capture_output=True, text=True, env=env).stdout
        perms = subprocess.run([str(aapt), "dump", "permissions", str(apk)], capture_output=True, text=True, env=env).stdout
        m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
        rep["package"] = {"name": m.group(1), "version_code": int(m.group(2)), "version_name": m.group(3)} if m else None
        rep["min_sdk"] = int(re.search(r"sdkVersion:'(\d+)'", badging).group(1)) if "sdkVersion:'" in badging else None
        rep["target_sdk"] = int(re.search(r"targetSdkVersion:'(\d+)'", badging).group(1)) if "targetSdkVersion" in badging else None
        rep["native_code"] = re.findall(r"native-code: (.+)", badging)[0].replace("'", "").split() if "native-code" in badging else []
        rep["launchable"] = "launchable-activity" in badging
        rep["permissions"] = re.findall(r"uses-permission: name='([^']+)'", perms)
        rep["internet_permission"] = "android.permission.INTERNET" in rep["permissions"]
    apksigner = build_tool(sdk, "apksigner") if sdk else None
    if apksigner:
        v = subprocess.run([str(apksigner), "verify", "--verbose", str(apk)], capture_output=True, text=True, env=env)
        rep["signature"] = {"verifies": v.returncode == 0 and v.stdout.startswith("Verifies"),
                            "schemes": re.findall(r"Verified using (v[\d.]+) scheme[^:]*: true", v.stdout), "key": "debug keystore"}
    analyzer = (sdk / "cmdline-tools" / "latest" / "bin" / "apkanalyzer") if sdk else None
    if analyzer and analyzer.exists():
        s = subprocess.run([str(analyzer), "apk", "download-size", str(apk)], capture_output=True, text=True, env=env, timeout=120)
        if s.returncode == 0 and s.stdout.strip().isdigit():
            rep["apkanalyzer_download_size"] = int(s.stdout.strip())
    rep["ok"] = bool(rep.get("package") and rep.get("launchable") and (rep.get("signature") or {}).get("verifies")
                     and "arm64-v8a" in rep.get("native_code", []) and not rep.get("internet_permission"))
    return rep


# --------------------------------------------------------------------------- build driver

def build_targets(root: Path, targets: list[str], *, skip_smoke: bool = False, log=print) -> dict[str, Any]:
    from forge.boltpack import bolt_target
    from forge.pwa import pwa_pipeline
    from forge.shuttleline import verify_target

    tc = toolchain(root)
    if not tc["godot"] or GODOT_VERSION not in (tc["godot_version"] or ""):
        return {"ok": False, "error": f"Godot {GODOT_VERSION} required, found {tc['godot_version']!r}", "toolchain": tc}
    if not tc["templates"]["ok"]:
        tc["templates"] = fetch_templates(root, log=log)
    st = stage(root, log=log)
    sdig = source_digest(root)
    version = game_version(root)
    results: dict[str, Any] = {}
    for t in targets:
        rep = export(root, t, st, log=log)
        if rep["ok"]:
            if t == "web":
                rep["pwa"] = pwa_pipeline(root, smoke=not skip_smoke, log=log)
            elif not skip_smoke:
                rep["verify"] = {"desktop-linux": verify_desktop_linux, "desktop-windows": verify_desktop_windows,
                                 "android": verify_android}[t](root)
            rep["shuttle"] = verify_target(root, t)
            rep["files"] = file_table(dist_dir(root) / t)
            rep["total_size"] = sum(f["size"] for f in rep["files"])
            art = dist_dir(root) / t / TARGETS[t].artifact      # post-steps may patch it (PWAPipeline hook)
            rep["artifact"] = {"path": f"dist/{t}/{TARGETS[t].artifact}", "size": art.stat().st_size, "sha256": sha256_file(art)}
            rep["bolt"] = bolt_target(root, t, version)
        rep.update({"version": version, "source_digest": sdig, "godot": tc["godot_version"],
                    "templates": TEMPLATE_VERSION, "templates_tpz_sha256": TPZ_SHA256,
                    "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        if rep["ok"]:
            (dist_dir(root) / t / "BUILD.json").write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        results[t] = rep
    ok = all(r["ok"] and (r.get("verify", {}).get("ok", True) if not skip_smoke else True)
             and (r.get("pwa", {}).get("ok", True)) and r.get("shuttle", {}).get("ok") and r.get("bolt", {}).get("ok")
             for r in results.values())
    return {"ok": ok, "version": version, "targets": results, "toolchain": tc}


def gz_size(p: Path) -> int:
    return len(gzip.compress(p.read_bytes(), compresslevel=9))
