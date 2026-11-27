#!/usr/bin/env python3
"""A scripted stand-in for `adb` (tests only): one arm64 phone that installs, launches and logs like a real device.
State lives in $FAKE_ADB_STATE (JSON). It proves verify_android.py's flow + parsing, not a phone."""
import json
import os
import sys
from pathlib import Path

st_path = Path(os.environ["FAKE_ADB_STATE"])
st = json.loads(st_path.read_text()) if st_path.exists() else {"installed": [], "log": "", "running": []}
a = sys.argv[1:]
if a[:1] == ["-s"]:
    a = a[2:]
out, rc = "", 0
GAME, LOOM = "com.rechargedideas.gamezero", "com.rechargedideas.pocketloom"
if a == ["devices"]:
    out = "List of devices attached\nFAKE123\tdevice\n"
elif a[:1] == ["install"]:
    pkg = GAME if "GameZero" in a[-1] else LOOM
    st["installed"].append(pkg)
    out = "Performing Streamed Install\nSuccess\n"
elif a[:1] == ["pull"]:
    Path(a[2]).write_bytes(b"\x89PNG fake")
elif a[:1] == ["logcat"]:
    if "-c" in a:
        st["log"] = ""
    else:
        out = st["log"]
elif a[:1] == ["shell"]:
    cmd = a[1]
    if cmd.startswith("getprop"):
        out = {"ro.product.model": "Redmi Note 12 Pro 5G", "ro.build.version.release": "14", "ro.build.version.sdk": "34",
               "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a,armeabi"}[cmd.split()[1]]
    elif cmd.startswith("dumpsys package"):
        pkg = cmd.split()[-1]
        perms = ["android.permission.VIBRATE"] if pkg == GAME else ["android.permission.INTERNET", "android.permission.CAMERA"]
        out = (f"Packages:\n  Package [{pkg}]\n    versionCode=7 minSdk=21 targetSdk=34\n    versionName={os.environ.get('FAKE_VN', '0.7.0')}\n"
               "    requested permissions:\n" + "".join(f"      {p}\n" for p in perms) + "    install permissions:\n")
    elif cmd.startswith("cmd package resolve-activity"):
        out = "priority=0 preferredOrder=0\ncom.rechargedideas.gamezero/com.godot.game.GodotApp\n"
    elif cmd.startswith("am start"):
        st["running"] = [GAME]
        if "--net-report" in cmd:
            st["log"] += 'I godot   : FABRIC_RESULT {"net":{"offline_peer":true},"version":"0.9.1+f9"}\n'
        elif "--autoplay" in cmd:
            st["log"] += 'I godot   : FABRIC_RESULT {"slice":{"completed":true,"wipes":0,"game_minutes":7.5,"wall_ms":41000,"ticks":27217}}\n'
    elif cmd.startswith("monkey"):
        pkg = cmd.split()[2]
        st["running"] = [pkg]
        if os.environ.get("FAKE_CRASH") == pkg:
            st["log"] += "E AndroidRuntime: FATAL EXCEPTION: main\n"
            st["running"] = []
    elif cmd.startswith("pidof"):
        out = "4242" if cmd.split()[1] in st["running"] else ""
    elif cmd.startswith("am force-stop"):
        st["running"] = []
st_path.write_text(json.dumps(st))
sys.stdout.write(out)
sys.exit(rc)
