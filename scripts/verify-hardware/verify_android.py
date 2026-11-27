#!/usr/bin/env python3
"""Install + verify Game Zero (debug APK) and PocketLoom on a real Android phone over adb (post-F9, 0.9.1).

    python scripts/verify-hardware/verify_android.py                    # defaults: dist/android + dist/pocketloom APKs
    python scripts/verify-hardware/verify_android.py --serial <id> --out hw-reports --no-autoplay
    python scripts/verify-hardware/hwreport.py answer hw-reports/android-<stamp>.json   # then answer the checklist

Stdlib only (needs `adb` from Android platform-tools: $ANDROID_HOME/platform-tools or PATH; USB debugging on).
What it proves on the device: ABI, install, package/version, Game Zero requests no INTERNET permission, both apps launch
and stay alive with no crash / script error in logcat, a headless `--net-report` + full-slice `--autoplay` run on the
phone's CPU (engine args via the `command_line_params` intent extra — [INFERENCE C-100], reported `null` if the engine
does not pick them up), screenshots. Everything a person must judge goes in the manual checklist.
Nothing here is uploaded anywhere; the report stays on this machine.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import hwreport as H  # noqa: E402

GAME_PKG = "com.rechargedideas.gamezero"
LOOM_PKG = "com.rechargedideas.pocketloom"
CRASH_RE = re.compile(r"FATAL EXCEPTION|SCRIPT ERROR|Fatal signal \d+|ANR in ")


# ----------------------------------------------------------------------------- parsing (unit-tested)

def parse_devices(text: str) -> list[str]:
    return [ln.split()[0] for ln in text.splitlines()[1:] if ln.strip().endswith("device") and "\t" in ln]


def requested_permissions(dumpsys: str) -> list[str]:
    out, on = [], False
    for ln in dumpsys.splitlines():
        s = ln.strip()
        if s.startswith("requested permissions:"):
            on = True
            continue
        if on:
            if not s or s.endswith(":") and not s.startswith("android.permission"):
                break
            out.append(s.split(":")[0].strip())
    return out


def version_name(dumpsys: str) -> str | None:
    m = re.search(r"versionName=(\S+)", dumpsys)
    return m.group(1) if m else None


def fabric_result(logcat: str) -> dict[str, Any] | None:
    for ln in reversed(logcat.splitlines()):
        i = ln.find("FABRIC_RESULT ")
        if i >= 0:
            try:
                return json.loads(ln[i + len("FABRIC_RESULT "):])
            except json.JSONDecodeError:
                continue
    return None


def crash_lines(logcat: str) -> list[str]:
    return [ln.strip()[:200] for ln in logcat.splitlines() if CRASH_RE.search(ln)][:10]


# ----------------------------------------------------------------------------- adb

class Adb:
    def __init__(self, adb: str, serial: str | None) -> None:
        self.base = [adb] + (["-s", serial] if serial else [])

    def run(self, *args: str, timeout: float = 120) -> tuple[int, str]:
        p = subprocess.run([*self.base, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)

    def sh(self, cmd: str, timeout: float = 60) -> str:
        return self.run("shell", cmd, timeout=timeout)[1].strip()


def find_adb() -> str | None:
    for base in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), "/workspace/android-sdk"):
        if base:
            for name in ("adb", "adb.exe"):
                p = Path(base) / "platform-tools" / name
                if p.exists():
                    return str(p)
    return shutil.which("adb")


def _wait_result(a: Adb, timeout_s: float) -> tuple[dict[str, Any] | None, str]:
    t0, log = time.time(), ""
    while time.time() - t0 < timeout_s:
        log = a.run("logcat", "-d", timeout=30)[1]
        r = fabric_result(log)
        if r is not None:
            return r, log
        time.sleep(2)
    return None, log


def _launch_with_args(a: Adb, pkg: str, args: list[str]) -> str:
    comp = a.sh(f"cmd package resolve-activity --brief {pkg}").splitlines()[-1].strip()
    a.run("logcat", "-c")
    # Godot reads `command_line_params` (string array); user args follow "--" like on desktop  [INFERENCE C-100]
    a.sh(f"am start -W -S -n {comp} --esa command_line_params {','.join(['--', *args])}")
    return comp


def _alive(a: Adb, pkg: str) -> bool:
    return bool(a.sh(f"pidof {pkg}"))


def _screencap(a: Adb, out: Path, name: str) -> str | None:
    dev = f"/sdcard/Download/{name}.png"
    a.sh(f"screencap -p {dev}")
    rc, _ = a.run("pull", dev, str(out / f"{name}.png"))
    a.sh(f"rm -f {dev}")
    return str(out / f"{name}.png") if rc == 0 else None


def run(args: argparse.Namespace) -> Path:
    rep = H.new_report("android", "verify_android.py", ["android_game", "android_pocketloom"])
    out = Path(args.out)
    shots = out / "android-screens"
    shots.mkdir(parents=True, exist_ok=True)
    adb = find_adb()
    if not H.add(rep, "adb_found", bool(adb), adb):
        return H.finish(rep, out)
    a = Adb(adb, args.serial)
    devs = parse_devices(a.run("devices")[1])
    if not H.add(rep, "one_device_connected", bool(args.serial) or len(devs) == 1, devs):
        return H.finish(rep, out)
    rep["device"] = {"model": a.sh("getprop ro.product.model"), "android": a.sh("getprop ro.build.version.release"),
                     "sdk": a.sh("getprop ro.build.version.sdk"), "abis": a.sh("getprop ro.product.cpu.abilist")}
    H.add(rep, "abi_arm64", "arm64-v8a" in rep["device"]["abis"], rep["device"]["abis"])
    build = Path(args.game_apk).parent / "BUILD.json"
    bj = json.loads(build.read_text(encoding="utf-8")) if build.exists() else {}
    rep["build_version"] = bj.get("version")
    want = ((bj.get("verify") or {}).get("package") or {}).get("version_name")   # the APK's own versionName
    # ---- Game Zero
    rc, txt = a.run("install", "-r", args.game_apk, timeout=300)
    if H.add(rep, "game_installed", rc == 0 and "Success" in txt, txt.strip()[-200:]):
        ds = a.sh(f"dumpsys package {GAME_PKG}")
        vn = version_name(ds)
        H.add(rep, "game_version_matches_build", vn is not None and (want is None or vn == want),
              {"device": vn, "apk_build_json": want, "build_version": rep["build_version"]})
        perms = requested_permissions(ds)
        H.add(rep, "game_no_internet_permission", "android.permission.INTERNET" not in perms, perms)
        _launch_with_args(a, GAME_PKG, ["--net-report"])
        nr, log = _wait_result(a, 60)
        if nr is None:
            H.add(rep, "game_headless_net_report", None, "no FABRIC_RESULT in logcat: engine args not delivered via intent "
                                                         "extra on this build — play the slice manually")
        else:
            H.add(rep, "game_headless_net_report", bool((nr.get("net") or {}).get("offline_peer")), nr)
            if not args.no_autoplay:
                _launch_with_args(a, GAME_PKG, ["--scene=slice", "--autoplay", "--no-live", "--watchdog=600"])
                sr, log = _wait_result(a, args.autoplay_timeout)
                s = (sr or {}).get("slice") or {}
                H.add(rep, "game_slice_autoplay_on_device", bool(s.get("completed")) and s.get("wipes") == 0 if sr else None,
                      {k: s.get(k) for k in ("completed", "wipes", "game_minutes", "wall_ms", "ticks")} if sr else "timeout")
        H.add(rep, "game_no_crash_in_logcat", not crash_lines(log), crash_lines(log))
        a.sh(f"am force-stop {GAME_PKG}")
        a.run("logcat", "-c")
        a.sh(f"monkey -p {GAME_PKG} -c android.intent.category.LAUNCHER 1")
        time.sleep(args.settle)
        log = a.run("logcat", "-d")[1]
        H.add(rep, "game_gui_launch_alive", _alive(a, GAME_PKG) and not crash_lines(log), crash_lines(log))
        rep["device"]["game_screenshot"] = _screencap(a, shots, "gamezero-select")
    # ---- PocketLoom
    if args.pocketloom_apk:
        rc, txt = a.run("install", "-r", args.pocketloom_apk, timeout=300)
        if H.add(rep, "pocketloom_installed", rc == 0 and "Success" in txt, txt.strip()[-200:]):
            ds = a.sh(f"dumpsys package {LOOM_PKG}")
            rep["device"]["pocketloom_version"] = version_name(ds)
            rep["device"]["pocketloom_permissions"] = requested_permissions(ds)
            a.run("logcat", "-c")
            a.sh(f"monkey -p {LOOM_PKG} -c android.intent.category.LAUNCHER 1")
            time.sleep(args.settle)
            log = a.run("logcat", "-d")[1]
            H.add(rep, "pocketloom_launch_alive", _alive(a, LOOM_PKG) and not crash_lines(log), crash_lines(log))
            rep["device"]["pocketloom_screenshot"] = _screencap(a, shots, "pocketloom-home")
    return H.finish(rep, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game-apk", default=str(ROOT / "dist/android/GameZero-debug.apk"))
    pl = sorted((ROOT / "dist/pocketloom").glob("pocketloom-*-debug.apk"))
    ap.add_argument("--pocketloom-apk", default=str(pl[-1]) if pl else None)
    ap.add_argument("--serial", default=None)
    ap.add_argument("--out", default=str(ROOT / "hw-reports"))
    ap.add_argument("--no-autoplay", action="store_true", help="Skip the full-slice headless run on the phone.")
    ap.add_argument("--autoplay-timeout", type=float, default=600)
    ap.add_argument("--settle", type=float, default=8.0, help="Seconds to wait after a GUI launch.")
    a = ap.parse_args(argv)
    p = run(a)
    rep = json.loads(p.read_text(encoding="utf-8"))
    print(H.summary(rep))
    print(f"\nreport: {p}\nnext:   python {HERE / 'hwreport.py'} answer {p}")
    return 0 if rep["verdict"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
