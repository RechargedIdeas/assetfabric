"""Post-F9 (0.9.1) hardware-verification kit: report format, Android flow against a scripted fake adb, Windows
PowerShell script parse (when pwsh exists), docs. The real runs need the hardware (docs/hardware-verification.md)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "scripts" / "verify-hardware"
sys.path.insert(0, str(KIT))
import hwreport as H  # noqa: E402
import verify_android as VA  # noqa: E402


def test_checklists_unique_and_kinds() -> None:
    d = json.loads((KIT / "checklists.json").read_text(encoding="utf-8"))
    for sec in ("playtest", "android_game", "android_pocketloom", "web"):
        ids = [i["id"] for i in d[sec]]
        assert ids and len(ids) == len(set(ids)), sec
        assert all(i["kind"] in ("yes_no", "number", "text") and i["ask"] for i in d[sec])
    allids = [i["id"] for s in ("android_game", "android_pocketloom") for i in d[s]]
    assert len(allids) == len(set(allids))


def test_report_verdicts() -> None:
    r = H.new_report("web", "t", ["web"])
    assert H.verdict(r) == "incomplete"                       # no checks yet
    H.add(r, "a", True)
    assert H.verdict(r) == "incomplete"                       # manual unanswered
    for m in r["manual"]:
        m["answer"] = "y"
    assert H.verdict(r) == "pass" and not H.validate({**r, "verdict": "pass"})
    r["manual"][0]["answer"] = "no"
    assert H.verdict(r) == "fail"
    r["manual"][0]["answer"] = "y"
    H.add(r, "b", None)
    assert H.verdict(r) == "incomplete"
    H.add(r, "c", False)
    assert H.verdict(r) == "fail"
    assert H.validate({"format": "x"})


def test_android_parsers() -> None:
    assert VA.parse_devices("List of devices attached\nAB12\tdevice\nCD34\tunauthorized\n\n") == ["AB12"]
    ds = ("    versionName=0.7.0\n    requested permissions:\n      android.permission.VIBRATE\n"
          "      android.permission.INTERNET\n    install permissions:\n      android.permission.INTERNET: granted=true\n")
    assert VA.requested_permissions(ds) == ["android.permission.VIBRATE", "android.permission.INTERNET"]
    assert VA.version_name(ds) == "0.7.0"
    assert VA.fabric_result('x\nI godot: FABRIC_RESULT {"a": 1}\n') == {"a": 1}
    assert VA.fabric_result("nothing") is None
    assert VA.crash_lines("E AndroidRuntime: FATAL EXCEPTION: main\nok\n")


def _fake_adb(tmp: Path) -> Path:
    sdk = tmp / "sdk" / "platform-tools"
    sdk.mkdir(parents=True)
    shim = sdk / "adb"
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} {Path(__file__).parent / 'fixtures' / 'fake_adb.py'} \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return tmp / "sdk"


@pytest.mark.skipif(os.name == "nt", reason="POSIX shim")
def test_android_flow_against_fake_adb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANDROID_HOME", str(_fake_adb(tmp_path)))
    monkeypatch.setenv("FAKE_ADB_STATE", str(tmp_path / "state.json"))
    (tmp_path / "apk").mkdir()
    game = tmp_path / "apk" / "GameZero-debug.apk"
    game.write_bytes(b"apk")
    (tmp_path / "apk" / "BUILD.json").write_text(json.dumps({"version": "0.9.1+f9", "verify": {"package": {"version_name": "0.7.0"}}}))
    loom = tmp_path / "pocketloom-0.1.0-c6-debug.apk"
    loom.write_bytes(b"apk")
    rc = VA.main(["--game-apk", str(game), "--pocketloom-apk", str(loom), "--out", str(tmp_path / "out"), "--settle", "0",
                  "--autoplay-timeout", "5"])
    rep = json.loads(next((tmp_path / "out").glob("android-*.json")).read_text())
    assert rc == 0 and not H.validate(rep), H.validate(rep)
    ok = {c["id"]: c["ok"] for c in rep["checks"]}
    assert all(ok.values()), ok
    assert {"game_no_internet_permission", "game_slice_autoplay_on_device", "pocketloom_launch_alive"} <= set(ok)
    assert rep["verdict"] == "incomplete"                     # the manual checklist still needs a person
    # a crashing PocketLoom fails the report
    monkeypatch.setenv("FAKE_CRASH", "com.rechargedideas.pocketloom")
    (tmp_path / "state.json").unlink()
    assert VA.main(["--game-apk", str(game), "--pocketloom-apk", str(loom), "--out", str(tmp_path / "out2"),
                    "--settle", "0", "--no-autoplay"]) == 1


def test_windows_script_parses() -> None:
    pwsh = shutil.which("pwsh") or ("/workspace/tools/pwsh/pwsh" if Path("/workspace/tools/pwsh/pwsh").exists() else None)
    src = (KIT / "verify-windows.ps1").read_text(encoding="utf-8")
    assert "GameZero.console.exe" in src and "--net-report" in src and "--autoplay" in src and "checklists.json" in src
    if not pwsh:
        pytest.skip("pwsh not installed (parse check only runs where PowerShell exists)")
    cmd = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e); "
           "if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }" % (KIT / "verify-windows.ps1"))
    p = subprocess.run([pwsh, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr


def test_docs_and_gitignore(root: Path) -> None:
    doc = (root / "docs/hardware-verification.md").read_text(encoding="utf-8")
    for s in ("verify-windows.ps1", "verify_android.py", "verify_web.py", "hwreport.py"):
        assert s in doc
    assert "/hw-reports/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
