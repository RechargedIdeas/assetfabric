"""Companion track acceptance C1–C6: PocketLoom (Android, Kotlin) + FabricCore.

Full mode (``forge accept C1`` … ``C6``; needs JDK 17 + Android SDK — the same ones F7 uses) runs the Gradle
build once per process (``:fabriccore:test :fabriccore:fatJar :app:assembleDebug``), then checks:

* **C1 PocketLoom / FabricCore** — FabricCore JVM unit tests (JUnit XML) all pass; the fat jar has no third-party
  runtime code (only ``fabric/`` + the Kotlin stdlib); the debug APK verifies with ``apksigner``, ``aapt`` badging
  matches (package, minSdk 26, targetSdk 35, launcher activity) and its dex carries FabricCore.
* **C2 On-device generation** — the *same* FabricCore code, run as ``java -jar`` pinned to 2 cores (weakest
  acceptance node), generates 16 caves + 16 sprites through the backend ladder: every output passes its gates,
  is palette-locked (re-checked independently here by decoding the PNG), is byte-identical across two fresh
  homes, uses the CPU rung, reports the ONNX rung as an honest stub, and stays inside the per-asset budget.
* **C3 Standalone UI** — the APK's manifest has the launcher + ``loomlink://`` pairing intent and a non-exported
  capture provider; every ``R.string`` the app uses exists, no UI text is hard-coded in Kotlin, the app code
  itself opens no sockets (network only via FabricCore's LoomLink, after the user pairs), and the CLI ``status``
  (the telemetry screen's data) reports store/model/queue/backends. **Not exercised on a device/emulator** —
  this box has no KVM; reported, not gated.
* **C4 Local capture** — a real JPEG ingested through FabricCore lands in the store as ``capture`` with telemetry
  (size, dimensions, source), queues a ``recon.capture`` offload job, rejects non-images; the APK declares the
  ``IMAGE_CAPTURE`` query and requests no CAMERA permission.
* **C5 Pairing** — Kotlin client ↔ Python ``forge/loomlink.py`` desktop: wrong code rejected; ``loomlink://`` URI
  pairing grants requested ∩ allowed capabilities; the one-time code rotates; unsigned / replayed / unknown-device
  requests are refused; five bad proofs rotate the code.
* **C6 Offload + sync** — jobs and a capture queued while the desktop is down stay queued; after it is back they
  drain with results equal to the desktop's own computation; the capture blob arrives byte-identical; a library
  sync with a concurrent edit keeps both copies, leaves both indexes identical, and a second sync is a no-op.

Fast mode (``FORGE_ACCEPT_FAST=1`` or no JDK/SDK: pytest / CI without Gradle) runs only the Python + static half
(fixture vectors, desktop LoomLink server with the Python client, manifest/string scans) and says so.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import zipfile
import zlib
from pathlib import Path
from typing import Any

from forge.accept_f6 import fast_mode

PL = Path("companions") / "pocketloom"
APK_REL = PL / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
JAR_REL = PL / "fabriccore" / "build" / "libs" / "fabriccore-all.jar"
VERSION = "0.1.0-c6"
PACKAGE = "com.rechargedideas.pocketloom"
GEN_BUDGET_MS = 250.0          # per asset on 2 cores (CPU rung); measured ~1–20 ms on the T1 box
_BUILD: dict[str, Any] = {}


# ----------------------------------------------------------------------------------- toolchain

def toolchain(root: Path) -> dict[str, Any]:
    from forge.packaging import build_tool, find_android_sdk, find_jdk

    jdk, sdk = find_jdk(root), find_android_sdk(root)
    return {"jdk": str(jdk) if jdk else None, "sdk": str(sdk) if sdk else None,
            "aapt": str(build_tool(sdk, "aapt")) if sdk and build_tool(sdk, "aapt") else None,
            "apksigner": str(build_tool(sdk, "apksigner")) if sdk and build_tool(sdk, "apksigner") else None}


def full_possible(root: Path) -> bool:
    t = toolchain(root)
    return not fast_mode() and bool(t["jdk"] and t["sdk"] and t["aapt"] and t["apksigner"])


def _env(root: Path) -> dict[str, str]:
    t = toolchain(root)
    env = dict(os.environ, JAVA_HOME=t["jdk"], ANDROID_HOME=t["sdk"], ANDROID_SDK_ROOT=t["sdk"])
    env["PATH"] = f"{t['jdk']}/bin:{env.get('PATH', '')}"
    return env


def gradle_build(root: Path) -> dict[str, Any]:
    """One Gradle run per process: unit tests + fat jar + debug APK. Copies the APK to dist/pocketloom/."""
    if _BUILD:
        return _BUILD
    pl = root / PL
    t0 = time.time()
    proc = subprocess.run(["./gradlew", "--no-daemon", "-q", ":fabriccore:test", ":fabriccore:fatJar", ":app:assembleDebug"],
                          cwd=pl, env=_env(root), capture_output=True, text=True, timeout=1800)
    out: dict[str, Any] = {"ok": proc.returncode == 0, "seconds": round(time.time() - t0, 1)}
    if proc.returncode != 0:
        out["log_tail"] = (proc.stdout + proc.stderr)[-3000:]
    out["junit"] = junit(pl / "fabriccore" / "build" / "test-results" / "test")
    apk = root / APK_REL
    if apk.exists():
        dist = root / "dist" / "pocketloom"
        dist.mkdir(parents=True, exist_ok=True)
        dst = dist / f"pocketloom-{VERSION}-debug.apk"
        shutil.copy2(apk, dst)
        data = dst.read_bytes()
        out["apk"] = {"path": str(dst.relative_to(root)), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    _BUILD.update(out)
    return _BUILD


def junit(d: Path) -> dict[str, Any]:
    classes: dict[str, dict[str, int]] = {}
    for f in sorted(d.glob("TEST-*.xml")) if d.is_dir() else []:
        head = f.read_text(encoding="utf-8")[:2000]
        m = re.search(r'<testsuite name="([^"]+)" tests="(\d+)" skipped="(\d+)" failures="(\d+)" errors="(\d+)"', head)
        if m:
            classes[m.group(1).rsplit(".", 1)[-1]] = {"tests": int(m.group(2)), "skipped": int(m.group(3)),
                                                     "failures": int(m.group(4)) + int(m.group(5))}
    total = sum(c["tests"] for c in classes.values())
    failed = sum(c["failures"] for c in classes.values())
    return {"classes": classes, "tests": total, "failures": failed, "ok": total > 0 and failed == 0}


def _suites_ok(b: dict[str, Any], *names: str) -> dict[str, Any]:
    cl = b.get("junit", {}).get("classes", {})
    sel = {n: cl.get(n) for n in names}
    return {"suites": sel, "ok": all(v and v["failures"] == 0 and v["tests"] > 0 for v in sel.values())}


def jar(root: Path, *args: str, home: Path | None = None, cores: str | None = None,
        timeout: int = 120) -> tuple[int, Any]:
    t = toolchain(root)
    argv = [f"{t['jdk']}/bin/java", "-Xshare:auto", "-jar", str(root / JAR_REL), *args]
    if home is not None:
        argv += ["--home", str(home)]
    if cores and shutil.which("taskset"):
        argv = ["taskset", "-c", cores, *argv]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    try:
        return p.returncode, json.loads(p.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return p.returncode, {"stdout": p.stdout[-500:], "stderr": p.stderr[-1500:]}


# ----------------------------------------------------------------------------------- APK readers

def aapt(root: Path, *args: str) -> str:
    t = toolchain(root)
    return subprocess.run([t["aapt"], *args], capture_output=True, text=True, timeout=60).stdout


def apk_report(root: Path, b: dict[str, Any]) -> dict[str, Any]:
    t = toolchain(root)
    apk = root / b["apk"]["path"]
    badging = aapt(root, "dump", "badging", str(apk))
    sig = subprocess.run([t["apksigner"], "verify", "--verbose", str(apk)], capture_output=True, text=True,
                         timeout=120, env=_env(root))
    with zipfile.ZipFile(apk) as z:
        dex = b"".join(z.read(n) for n in z.namelist() if n.endswith(".dex"))
        names = z.namelist()
    pkg = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    return {
        **b["apk"],
        "package": pkg.group(1) if pkg else None, "version_name": pkg.group(3) if pkg else None,
        "min_sdk": int(m.group(1)) if (m := re.search(r"sdkVersion:'(\d+)'", badging)) else None,
        "target_sdk": int(m.group(1)) if (m := re.search(r"targetSdkVersion:'(\d+)'", badging)) else None,
        "launchable": m.group(1) if (m := re.search(r"launchable-activity: name='([^']+)'", badging)) else None,
        "permissions": sorted(re.findall(r"uses-permission: name='([^']+)'", badging)),
        "apksigner_verified": sig.returncode == 0 and "Verifies" in sig.stdout,
        "signature_schemes": sorted(re.findall(r"Verified using (v[\d.]+) scheme[^:]*: true", sig.stdout)),
        "dex_has_fabriccore": b"Lfabric/core/PocketLoomCore;" in dex and b"Lfabric/core/LoomLinkClient;" in dex,
        "dex_has_app": b"Lfabric/pocketloom/MainActivity;" in dex,
        "native_libs": sorted({n.split("/")[1] for n in names if n.startswith("lib/")}),
        "debuggable": "application-debuggable" in badging,
    }


def manifest_tree(root: Path, b: dict[str, Any]) -> str:
    return aapt(root, "dump", "xmltree", str(root / b["apk"]["path"]), "AndroidManifest.xml")


# ----------------------------------------------------------------------------------- static scans

UI_LITERAL = re.compile(r'(setText|setHint|makeText|setTitle|setMessage)\(\s*"[^"]*[A-Za-z]|\.(text|hint)\s*=\s*"[^"]*[A-Za-z]')


def strings_report(root: Path) -> dict[str, Any]:
    app = root / PL / "app" / "src" / "main"
    xml = (app / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    defined = set(re.findall(r'<string name="([a-z0-9_]+)"', xml)) | set(re.findall(r'<string-array name="([a-z0-9_]+)"', xml))
    used: set[str] = set()
    literals: list[str] = []
    for f in sorted(app.rglob("*.kt")):
        src = f.read_text(encoding="utf-8")
        used |= set(re.findall(r"R\.(?:string|array)\.([a-z0-9_]+)", src))
        for i, line in enumerate(src.splitlines(), 1):
            if UI_LITERAL.search(line):
                literals.append(f"{f.relative_to(root)}:{i}: {line.strip()[:100]}")
    manifest = (app / "AndroidManifest.xml").read_text(encoding="utf-8")
    used |= set(re.findall(r"@string/([a-z0-9_]+)", manifest))
    missing = sorted(used - defined)
    return {"ok": not missing and not literals, "defined": len(defined), "used": len(used),
            "missing": missing, "unused": sorted(defined - used), "hardcoded_ui_literals": literals}


NET_KT = re.compile(r"\b(HttpURLConnection|URL\(|Socket\(|ServerSocket|DatagramSocket|OkHttp|WebView)\b")


def offline_scan(root: Path) -> dict[str, Any]:
    """App code opens nothing itself; FabricCore network use is confined to LoomLink.kt (paired-only)."""
    app = sorted((root / PL / "app" / "src").rglob("*.kt"))
    core = sorted((root / PL / "fabriccore" / "src" / "main").rglob("*.kt"))
    app_hits = [str(f.relative_to(root)) for f in app if NET_KT.search(f.read_text(encoding="utf-8"))]
    core_hits = sorted(str(f.relative_to(root)) for f in core if NET_KT.search(f.read_text(encoding="utf-8")))
    allowed = [str((PL / "fabriccore/src/main/kotlin/fabric/core/LoomLink.kt"))]
    return {"ok": not app_hits and core_hits == allowed, "app_network_code": app_hits, "fabriccore_network_files": core_hits}


# ----------------------------------------------------------------------------------- PNG check (independent of Kotlin)

def png_pixels(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    i, w, h, idat = 8, 0, 0, b""
    while i < len(data):
        n, tag = struct.unpack(">I4s", data[i:i + 8])
        body = data[i + 8:i + 8 + n]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype == 6, "RGBA8 expected"
        elif tag == b"IDAT":
            idat += body
        i += 12 + n
    raw = zlib.decompress(idat)
    px = []
    stride = 1 + 4 * w
    for y in range(h):
        row = raw[y * stride:(y + 1) * stride]
        assert row[0] == 0, "filter 0 expected"
        px += [tuple(row[1 + 4 * x:5 + 4 * x]) for x in range(w)]
    return w, h, px


def palette_rgba(root: Path, name: str) -> set[tuple[int, int, int, int]]:
    pal = json.loads((root / "content/patternvault/palettes.json").read_text(encoding="utf-8"))["palettes"][name]["colours"]
    return {(int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), 255) for c in pal}


# ----------------------------------------------------------------------------------- desktop LoomLink harness

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Desktop:
    """Runs forge.loomlink.LinkServer in a thread; restartable on the same port + state dir."""

    def __init__(self, state: Path, port: int | None = None, allow: tuple[str, ...] = ("offload", "sync")) -> None:
        self.state, self.port, self.allow = state, port or free_port(), allow
        self.srv: Any = None
        self.stop: threading.Event | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> "Desktop":
        from forge.loomlink import LinkServer

        ready = threading.Event()
        self.stop = threading.Event()
        self.srv = LinkServer(self.state, node_id="desktop", allow=self.allow, port=self.port)
        self.thread = threading.Thread(target=self.srv.serve, kwargs={"ready": lambda s: ready.set(), "stop": self.stop}, daemon=True)
        self.thread.start()
        assert ready.wait(10), "LinkServer did not start"
        return self

    def halt(self) -> None:
        if self.stop:
            self.stop.set()
            self.thread.join(10)  # type: ignore[union-attr]


def python_link_checks(tmp: Path) -> dict[str, Any]:
    """Desktop server + Python client (both modes): proofs, caps, replay, rotation, offload, sync endpoints."""
    import urllib.error
    import urllib.request

    from forge.loomlink import LinkClient, op_hashchain

    d = Desktop(tmp / "py-desk", allow=("offload", "sync")).start()
    out: dict[str, Any] = {}
    try:
        c = LinkClient(d.srv.url, "py-1")
        code0 = d.srv.code
        r = c.pair(code0, ["offload", "sync", "mirror"])
        out["granted"] = r["granted"]
        out["code_rotated_after_use"] = d.srv.code != code0
        try:
            LinkClient(d.srv.url, "py-2").pair(code0, ["sync"])
            out["reused_code_rejected"] = False
        except (urllib.error.HTTPError, PermissionError):
            out["reused_code_rejected"] = True
        res = c.offload({"id": "j1", "op": "hashchain", "payload": {"seed": "s", "rounds": 500}})
        out["offload_ok"] = res.get("ok") and res["value"]["digest"] == op_hashchain({"seed": "s", "rounds": 500})["digest"]
        # replay the exact same signed request → refused
        raw = json.dumps({"id": "j2", "op": "hashchain", "payload": {}}).encode()
        hdr = {"Content-Type": "application/json", **c._sign("POST", "/offload", raw)}
        def send(h: dict[str, str]) -> int:
            try:
                urllib.request.urlopen(urllib.request.Request(d.srv.url + "/offload", data=raw, headers=h, method="POST"), timeout=5)
                return 200
            except urllib.error.HTTPError as e:
                return e.code
        out["first_signed"] = send(hdr)
        out["replay_status"] = send(hdr)
        out["unsigned_status"] = send({"Content-Type": "application/json"})
        out["unknown_device_status"] = send({**hdr, "X-Loom-Client": "nobody"})
        # five bad proofs rotate the code
        before = d.srv.code
        bad = 0
        for i in range(5):     # a guessing client: hello, then a confirm with a wrong proof
            ev = LinkClient(d.srv.url, f"evil-{i}")
            h = ev._post("/pair/hello", {"client_id": f"evil-{i}", "nc": "00" * 16}, signed=False)
            try:
                ev._post("/pair/confirm", {"client_id": f"evil-{i}", "nc": "00" * 16, "ns": h["ns"], "caps": ["sync"],
                                           "proof": "0" * 64}, signed=False)
            except urllib.error.HTTPError as e:
                bad += e.code == 403
        out["bad_proofs_refused"] = bad
        out["rotated_after_5_fails"] = d.srv.code != before
        # a hello issued before rotation cannot be confirmed afterwards, even with the old code
        stale = LinkClient(d.srv.url, "late")
        from forge.loomlink import _mac
        nc = "11" * 16
        h = stale._post("/pair/hello", {"client_id": "late", "nc": nc}, signed=False)
        old_code = d.srv.code
        d.srv.rotate()
        try:
            stale._post("/pair/confirm", {"client_id": "late", "nc": nc, "ns": h["ns"], "caps": ["sync"],
                                          "proof": _mac(old_code.encode(), "cli", nc, h["ns"], "late")}, signed=False)
            out["stale_hello_rejected"] = False
        except urllib.error.HTTPError:
            out["stale_hello_rejected"] = True
        out["sessions_file_mode"] = oct((tmp / "py-desk" / "paired.json").stat().st_mode & 0o777)
    finally:
        d.halt()
    out["ok"] = (out.get("granted") == ["offload", "sync"] and out["code_rotated_after_use"] and out["reused_code_rejected"]
                 and out["offload_ok"] and out["first_signed"] == 200 and out["replay_status"] == 403
                 and out["unsigned_status"] == 403 and out["unknown_device_status"] == 403
                 and out["bad_proofs_refused"] == 5 and out["rotated_after_5_fails"] and out["stale_hello_rejected"] and out["sessions_file_mode"] == "0o600")
    return out


def sync_fixture_check(root: Path) -> dict[str, Any]:
    from forge.loomlink import canonical, plan_sync

    vec = json.loads((root / "tests/fixtures/loomlink_vectors.json").read_text(encoding="utf-8"))
    bad = [c["name"] for c in vec["sync_plan"]
           if canonical(plan_sync(c["server"], c["phone"], c["phone_id"])) != canonical(c["expected"])]
    return {"ok": not bad, "cases": len(vec["sync_plan"]), "mismatched": bad}


# ----------------------------------------------------------------------------------- per-milestone full checks

def c1_full(root: Path, b: dict[str, Any], tmp: Path) -> dict[str, Any]:
    apk = apk_report(root, b)
    # Only FabricCore + the Kotlin stdlib (whose org.jetbrains:annotations dependency is annotation-only).
    allowed = ("META-INF/", "fabric/", "kotlin/", "org/intellij/lang/annotations/", "org/jetbrains/annotations/")
    with zipfile.ZipFile(root / JAR_REL) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
    tops = sorted({n.split("/")[0] for n in names})
    code, info = jar(root, "info")
    third_party = sorted({n.rsplit("/", 1)[0] for n in names if not n.startswith(allowed)})
    return {"apk": apk, "jar_top_level": tops, "third_party_runtime": third_party, "jar_info": info,
            "core_suites": _suites_ok(b, "JsonTest", "StoreTest", "JobsTest", "TelemetryTest"),
            "ok": (apk["apksigner_verified"] and apk["package"] == PACKAGE and apk["min_sdk"] == 26 and apk["target_sdk"] == 35
                   and apk["launchable"] == "fabric.pocketloom.MainActivity" and apk["dex_has_fabriccore"] and apk["dex_has_app"]
                   and not third_party and code == 0 and info.get("version") == VERSION)}


def c2_full(root: Path, b: dict[str, Any], tmp: Path) -> dict[str, Any]:
    runs = {}
    for home in ("a", "b"):
        out = {}
        for kind, pal in (("cave", "cave_stone"), ("sprite", "hero_teal")):
            code, r = jar(root, "gen", "--kind", kind, "--seed", "100", "--count", "16", "--palette", pal,
                          home=tmp / f"gen-{home}", cores="0,1")
            out[kind] = {"code": code, "items": r}
        runs[home] = out
    a = runs["a"]
    per = {}
    for kind, pal in (("cave", "cave_stone"), ("sprite", "hero_teal")):
        items = a[kind]["items"] if isinstance(a[kind]["items"], list) else []
        other = runs["b"][kind]["items"] if isinstance(runs["b"][kind]["items"], list) else []
        allowed = palette_rgba(root, pal) | {(0, 0, 0, 0)}
        locked, dims = True, set()
        idx = json.loads((tmp / "gen-a" / "store" / "index.json").read_text(encoding="utf-8"))
        for it in items:
            e = idx[it["id"]]
            data = (tmp / "gen-a" / "store" / "objects" / e["sha256"][:2] / e["sha256"]).read_bytes()
            w, h, px = png_pixels(data)
            dims.add((w, h))
            locked &= set(px) <= allowed
        ms = [it["ms"] for it in items]
        per[kind] = {
            "n": len(items), "all_done": all(it["status"] == "done" for it in items),
            "gates_pass": sum(1 for it in items if it["result"]["ok"]),
            "retried": sum(1 for it in items if it["result"]["meta"].get("attempts", 1) > 1),
            "deterministic": [it["result"]["sha256"] for it in items] == [it["result"]["sha256"] for it in other] and bool(items),
            "palette_locked_independent": locked, "dims": sorted(dims),
            "backend": sorted({it["selection"]["backend"] for it in items}),
            "skipped_rungs": sorted({s["rung"] + ": " + s["reason"] for it in items for s in it["selection"]["skipped"]}),
            "ms_mean": round(sum(ms) / max(1, len(ms)), 2), "ms_max": round(max(ms or [0]), 2),
        }
    suites = _suites_ok(b, "LocalForgeTest", "ModelsTest")
    ok = suites["ok"] and all(p["n"] == 16 and p["all_done"] and p["gates_pass"] == 16 and p["deterministic"]
                              and p["palette_locked_independent"] and p["backend"] and all(x.endswith("-cpu") for x in p["backend"])
                              and p["ms_max"] <= GEN_BUDGET_MS for p in per.values())
    return {"cores": "0,1 (taskset)" if shutil.which("taskset") else "unpinned", "budget_ms": GEN_BUDGET_MS,
            "kinds": per, "suites": suites, "onnx": "stub — onnxruntime not bundled; CPU procedural rung always available",
            "ok": ok}


def c3_full(root: Path, b: dict[str, Any], tmp: Path) -> dict[str, Any]:
    tree = manifest_tree(root, b)
    code, st = jar(root, "status", home=tmp / "gen-a")
    prov = re.search(r"E: provider.*?(?=E: (activity|provider|queries)|\Z)", tree, re.S)
    manifest = {
        "launcher": "android.intent.category.LAUNCHER" in tree,
        "loomlink_intent": 'A: android:scheme(0x01010027)="loomlink"' in tree or '"loomlink"' in tree,
        "provider_not_exported": bool(prov) and re.search(r"android:exported\(0x[0-9a-f]+\)=\(type 0x12\)0x0\b", prov.group(0)) is not None,
        "allow_backup_off": re.search(r"android:allowBackup\(0x[0-9a-f]+\)=\(type 0x12\)0x0\b", tree) is not None,
    }
    status_ok = code == 0 and {"store", "models", "offload_pending", "telemetry", "backends"} <= set(st)
    return {"manifest": manifest, "strings": strings_report(root), "offline": offline_scan(root),
            "telemetry_status": {k: st.get(k) for k in ("store", "models", "offload_pending", "telemetry")} if status_ok else st,
            "device_run": "not exercised — no Android device or KVM emulator on this box",
            "ok": all(manifest.values()) and strings_report(root)["ok"] and offline_scan(root)["ok"] and status_ok}


def c4_full(root: Path, b: dict[str, Any], tmp: Path) -> dict[str, Any]:
    img = root / "tests/fixtures/capture_640x480.jpg"
    home = tmp / "cap"
    code, r = jar(root, "capture", "--file", str(img), "--source", "camera", home=home)
    bad = tmp / "not-an-image.txt"
    bad.write_text("hello")
    bcode, br = jar(root, "capture", "--file", str(bad), home=home)
    q = [json.loads(line) for line in (home / "offload.jsonl").read_text(encoding="utf-8").splitlines()] if (home / "offload.jsonl").exists() else []
    e = r.get("entry", {}) if isinstance(r, dict) else {}
    sha = hashlib.sha256(img.read_bytes()).hexdigest()
    stored = home / "store" / "objects" / sha[:2] / sha
    tree = manifest_tree(root, b)
    apk = apk_report(root, b)
    res = {"entry": e, "queued": [x["job"]["op"] for x in q if x["ev"] == "enqueue"],
           "blob_identical": stored.exists() and stored.read_bytes() == img.read_bytes(),
           "non_image_rejected": bcode != 0 and "not an image" in json.dumps(br),
           "image_capture_query": "android.media.action.IMAGE_CAPTURE" in tree,
           "camera_permission": "android.permission.CAMERA" in apk["permissions"],
           "reconstruction": "queued for desktop; RealityLoom/SplatForge reconstruction is C10–C12 (not built)"}
    prov = e.get("provenance", {})
    res["ok"] = (code == 0 and e.get("kind") == "capture" and e.get("media") == "image/jpeg" and prov.get("width") == 640
                 and prov.get("height") == 480 and res["queued"] == ["recon.capture"] and res["blob_identical"]
                 and res["non_image_rejected"] and res["image_capture_query"] and not res["camera_permission"]
                 and _suites_ok(b, "CaptureTest")["ok"])
    return res


def c5_full(root: Path, b: dict[str, Any], tmp: Path) -> dict[str, Any]:
    d = Desktop(tmp / "desk5", allow=("offload", "sync")).start()
    home = tmp / "phone5"
    try:
        wrong = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(8))
        while wrong == d.srv.code:
            wrong = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(8))
        wcode, wres = jar(root, "pair", "--url", d.srv.url, "--code", wrong, "--caps", "offload,sync", home=home)
        uri, code0 = d.srv.uri(), d.srv.code
        pcode, pres = jar(root, "pair", "--uri", uri, "--caps", "offload,sync,mirror", home=home)
        reuse_code, _ = jar(root, "pair", "--uri", uri, home=tmp / "phone5b")
        sess = json.loads((home / "link" / "session.json").read_text(encoding="utf-8")) if (home / "link" / "session.json").exists() else {}
        paired = json.loads((tmp / "desk5" / "paired.json").read_text(encoding="utf-8"))
        node = json.loads((home / "node.json").read_text(encoding="utf-8"))["node_id"]
        key_match = paired.get(node, {}).get("key") == sess.get("key")
    finally:
        d.halt()
    py = python_link_checks(tmp)
    res = {"wrong_code": {"exit": wcode, "error": wres.get("error") if isinstance(wres, dict) else wres},
           "pair": pres, "code_rotated": d.srv.code != code0, "reused_uri_exit": reuse_code,
           "session_key_matches_desktop": key_match, "python_side": py, "suites": _suites_ok(b, "LoomLinkTest"),
           "transport": "HTTP to LAN/Tailscale address; HMAC-signed requests (integrity), no TLS yet (INFERENCES C-7)"}
    res["ok"] = (wcode == 3 and pcode == 0 and pres.get("caps") == ["offload", "sync"] and res["code_rotated"]
                 and reuse_code == 3 and key_match and py["ok"] and res["suites"]["ok"])
    return res


def c6_full(root: Path, b: dict[str, Any], tmp: Path) -> dict[str, Any]:
    from forge.loomlink import canonical, op_hashchain

    port = free_port()
    d = Desktop(tmp / "desk6", port=port).start()
    home = tmp / "phone6"
    r: dict[str, Any] = {}
    try:
        _, r["pair"] = jar(root, "pair", "--uri", d.srv.uri(), home=home)
    finally:
        d.halt()
    # desktop is down: queue work on the phone
    seeds = ["alpha", "beta", "gamma"]
    for s in seeds:
        jar(root, "offload", "--op", "hashchain", "--seed", s, "--rounds", "5000", home=home)
    jar(root, "capture", "--file", str(root / "tests/fixtures/capture_640x480.jpg"), home=home)
    _, r["drain_offline"] = jar(root, "drain", home=home)
    # phone library: two generated assets + a shared id edited on both sides
    jar(root, "gen", "--kind", "sprite", "--seed", "7", "--count", "2", home=home)
    shared_p, shared_d = tmp / "shared_phone.bin", tmp / "shared_desk.bin"
    shared_p.write_bytes(b"phone edit"), shared_d.write_bytes(b"desktop edit")
    jar(root, "put", "--id", "shared", "--file", str(shared_p), home=home)
    d = Desktop(tmp / "desk6", port=port).start()       # back online, same state + port
    try:
        d.srv.store.put("desk_only", "tile", b"desktop asset")
        d.srv.store.put("shared", "sprite", b"desktop edit")
        _, r["drain_online"] = jar(root, "drain", home=home)
        _, r["sync1"] = jar(root, "sync", home=home)
        _, r["sync2"] = jar(root, "sync", home=home)
        _, phone_index = jar(root, "index", home=home)
        desk_index = json.loads(canonical(d.srv.store.entries))
    finally:
        d.halt()
    results = (r["drain_online"] or {}).get("results", {})
    digests = {res["value"]["digest"] for res in results.values() if isinstance(res.get("value"), dict) and "digest" in res["value"]}
    expect = {op_hashchain({"seed": s, "rounds": 5000})["digest"] for s in seeds}
    cap_sha = hashlib.sha256((root / "tests/fixtures/capture_640x480.jpg").read_bytes()).hexdigest()
    cap_blob = tmp / "desk6" / "store" / "objects" / cap_sha[:2] / cap_sha
    node = json.loads((home / "node.json").read_text(encoding="utf-8"))["node_id"]
    s1 = r.get("sync1") or {}
    out = {
        "queued_while_offline": r["drain_offline"],
        "drain_online": {k: v for k, v in (r["drain_online"] or {}).items() if k != "results"},
        "offload_digests_match_desktop": digests == expect,
        "capture_arrived_identical": cap_blob.exists() and cap_blob.read_bytes() == (root / "tests/fixtures/capture_640x480.jpg").read_bytes(),
        "sync1": s1, "sync2": r.get("sync2"),
        "keep_both": f"shared~{node}" in phone_index and f"shared~{node}" in desk_index and "shared" in desk_index,
        "indexes_identical": canonical(phone_index) == canonical(desk_index),
        "phone_assets": len(phone_index), "suites": _suites_ok(b, "SyncPlanTest", "JobsTest"),
        "sync_fixture": sync_fixture_check(root),
    }
    out["ok"] = (r["drain_offline"].get("sent") == 0 and r["drain_offline"].get("pending") == 4
                 and out["drain_online"].get("sent") == 4 and out["drain_online"].get("pending") == 0
                 and out["offload_digests_match_desktop"] and out["capture_arrived_identical"]
                 and any(c.get("resolution") == "keep_both" for c in s1.get("conflicts", []))
                 and out["keep_both"] and out["indexes_identical"]
                 and (r.get("sync2") or {}).get("pushed") == 0 and (r.get("sync2") or {}).get("pulled") == 0
                 and out["suites"]["ok"] and out["sync_fixture"]["ok"])
    return out


# ----------------------------------------------------------------------------------- fast (static) parts

def fast_part(root: Path, ms: str, tmp: Path) -> dict[str, Any]:
    r: dict[str, Any] = {"toolchain": toolchain(root)}
    if ms == "C1":
        pl = root / PL
        need = ["settings.gradle.kts", "gradlew", "gradle/wrapper/gradle-wrapper.properties", "app/build.gradle.kts",
                "fabriccore/build.gradle.kts", "app/src/main/AndroidManifest.xml"]
        r["sources"] = {"ok": all((pl / n).exists() for n in need), "missing": [n for n in need if not (pl / n).exists()]}
    if ms == "C3":
        r["strings"] = strings_report(root)
        r["offline"] = offline_scan(root)
    if ms == "C5":
        r["python_side"] = python_link_checks(tmp)
    if ms == "C6":
        r["sync_fixture"] = sync_fixture_check(root)
    return r


FULL = {"C1": c1_full, "C2": c2_full, "C3": c3_full, "C4": c4_full, "C5": c5_full, "C6": c6_full}


def runner(ms: str):  # noqa: ANN201
    def run(root: Path) -> tuple[int, dict[str, Any]]:
        tmp = Path(tempfile.mkdtemp(prefix=f"fabric-{ms.lower()}-"))
        try:
            full = full_possible(root)
            result: dict[str, Any] = {"mode": "full" if full else "fast"} | fast_part(root, ms, tmp)
            if full:
                b = gradle_build(root)
                result["build"] = {k: v for k, v in b.items() if k != "junit"} | {"junit_tests": b["junit"]["tests"],
                                                                                  "junit_failures": b["junit"]["failures"]}
                if b["ok"] and "apk" in b:
                    if ms == "C3":   # C3 reads telemetry from a home C2 populated; make it self-contained
                        jar(root, "gen", "--kind", "cave", "--seed", "1", "--count", "2", home=tmp / "gen-a")
                    result[ms.lower()] = FULL[ms](root, b, tmp)
            return 0, result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return run


def check(ms: str):  # noqa: ANN201
    def chk(r: dict[str, Any]) -> list[str]:
        errs: list[str] = []
        for k in ("sources", "strings", "offline", "python_side", "sync_fixture"):
            if k in r and not r[k].get("ok"):
                errs.append(f"{k}: {json.dumps(r[k])[:400]}")
        if r.get("mode") == "full":
            if not r.get("build", {}).get("ok"):
                errs.append(f"gradle build failed: {r.get('build', {}).get('log_tail', '')[-800:]}")
            elif r.get("build", {}).get("junit_failures"):
                errs.append(f"{r['build']['junit_failures']} FabricCore unit test failures")
            body = r.get(ms.lower())
            if not body or not body.get("ok"):
                errs.append(f"{ms} checks failed: {json.dumps(body)[:1500]}")
        return errs
    return chk


def perf(ms: str):  # noqa: ANN201
    def p(r: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"mode": r.get("mode")}
        b = r.get("build") or {}
        if b.get("apk"):
            out["apk_bytes"], out["apk_sha256"] = b["apk"]["bytes"], b["apk"]["sha256"]
        if ms == "C2" and r.get("c2"):
            out["gen_ms"] = {k: {"mean": v["ms_mean"], "max": v["ms_max"]} for k, v in r["c2"]["kinds"].items()}
        return out
    return p
