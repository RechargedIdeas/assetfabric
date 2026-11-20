"""Companion acceptance C9–C12: MirrorWeave, LensForge capture, metric depth, SplatForge path (interfaces + labelled stubs).

What "accepted" means here — and what it does NOT mean. These milestones deliver typed contracts, a handful of real CPU
paths that are cheap and spec-grounded, and stubs that **refuse** instead of faking output. `forge accept C9`…`C12` proves:

* the register (`content/companions/c9_c12.yaml`) matches the code: every `real` entry imports, every `stub` entry raises
  `StubError` labelled `[STUB <id> <milestone>]` with its locale key (and Android string where Kotlin has the stub);
* each real path does what its contract says (round-trips, determinism, analytic ground truth, spec routing rule);
* LoomLink exposes the C9 endpoints under the capability model (signed, granted, allow-listed) and the stubs answer 501;
* GroundWeave declares every op (CPU rung proven on 2 pinned cores, byte-identical with GPUs hidden/simulated; `planned` ops
  select nothing and say so);
* Kotlin (FabricCore) reproduces the shared vectors and refuses in its stubs (full mode: JDK 17 + Android SDK, same as C1–C6);
  fast mode runs the Python half only and says so.

Since 0.7.4 (stub batch 1) C9 also proves real desktop paths on real data: X11 capture (Xvfb), CPU VP8/VP9 encode → signed
WebSocket → decode with a PSNR floor, decoder resync after packet loss, phone H.264 packets decoded on the desktop, the
desktop → phone input outbox with per-event MACs verified by Kotlin, and phone → Studio input turned into Qt events.
Rows marked `real_unverified_on_device` have a compiled Android implementation (APK built + lint in full mode) that has
never run on a phone. It does NOT prove anything on a phone or a GPU.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from forge import depth, lensforge, mirrorweave, realityloom, registry
from forge import groundweave as gw
from forge.accept_companions import Desktop, _suites_ok, full_possible, gradle_build, jar
from forge.loomlink import LinkClient
from forge.stubs import StubError, is_stub_message

MS = ("C9", "C10", "C11", "C12")
PERMS = ("offload", "sync", "mirror", "drive_studio")


def _http_err(fn: Any) -> tuple[int, dict[str, Any]]:
    try:
        return 200, fn()
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except ValueError:
            return e.code, {}


def _png(kind: str, w: int = 640, h: int = 480, seed: int = 1) -> bytes:
    g = lensforge.synthetic_gray(w, h, seed)
    if kind == "sharp":
        arr = g
    elif kind == "blurry":
        arr = np.tile(np.linspace(40, 200, w).astype(np.int64), (h, 1))
    elif kind == "dark":
        arr = g // 8
    elif kind == "bright":
        arr = 255 - g // 8
    else:
        raise ValueError(kind)
    return lensforge.png_from_gray(arr)


def _stubs_refuse(ms: str, root: Path) -> dict[str, Any]:
    r = registry.check(root, ms)
    return {"ok": r["ok"], "problems": r["problems"], "stubs": r["stubs"], "real": r["real"],
            "real_unverified_on_device": r["real_unverified_on_device"],
            "refusals": {k: v["message"][:110] for k, v in r["stub_refusals"].items()}}


def _ladder(root: Path, op_cpu: list[str], op_planned: list[str]) -> dict[str, Any]:
    """Selection with and without GPUs present; planned ops select nothing and name their route."""
    rows: dict[str, Any] = {}
    ok = True
    for op in op_cpu:
        a, b = gw.select(op, ["cpu"], root), gw.select(op, ["cpu", *gw.SIMULATED_GPU_DEVICES], root)
        good = a["device"] == "cpu" and b["device"] == "cpu" and a["backend"] == b["backend"]
        rows[op] = {"backend": a["backend"], "device": a["device"], "with_all_gpus_present": b["backend"], "ok": good}
        ok = ok and good
    for op in op_planned:
        s = gw.select(op, ["cpu", *gw.SIMULATED_GPU_DEVICES], root)
        good = s.get("status") == "planned" and s["backend"] is None and s.get("route") in ("loomcluster", "local")
        rows[op] = {"status": s.get("status"), "route": s.get("route"), "ok": good}
        ok = ok and good
    st = gw.check(root)
    return {"ok": ok and st["ok"], "static_ok": st["ok"], "problems": st["problems"], "ops": rows}


def _models_required() -> bool:
    import os
    return os.environ.get("FORGE_REQUIRE_MODELS") == "1"


def _verify(root: Path, *ops: str) -> dict[str, Any]:
    v = gw.verify(root, ops=list(ops))
    allowed = ("ok", "planned") + (() if _models_required() else ("model_absent",))
    return {"ok": v["ok"] and all(x["status"] in allowed for x in v["results"]) and len(v["results"]) == len(ops),
            "cores": v["cores"], "results": [{k: x.get(k) for k in ("op", "status", "backend", "device", "wall_s", "budget_s",
                                                                    "cores", "identical_to_unpinned", "identical_with_simulated_gpu")}
                                             for x in v["results"]]}


# ====================================================================================== C9

def _frames_contract() -> dict[str, Any]:
    png = _png("sharp", 32, 24)
    env = mirrorweave.FrameEnvelope("screen", 5, 123, "screen", "png", 32, 24, png)
    back = mirrorweave.FrameEnvelope.from_wire(json.loads(json.dumps(env.to_wire())))
    errs: dict[str, bool] = {}

    def rejects(name: str, fn: Any, exc: type = ValueError) -> None:
        try:
            fn()
            errs[name] = False
        except exc:
            errs[name] = True
    rejects("bad_stream_id", lambda: mirrorweave.FrameEnvelope("Bad Id", 0, 0, "screen", "png", 0, 0, png))
    rejects("codec_payload_mismatch", lambda: mirrorweave.FrameEnvelope("s", 0, 0, "screen", "jpeg", 0, 0, png))
    rejects("telemetry_must_be_json", lambda: mirrorweave.FrameEnvelope("s", 0, 0, "telemetry", "png", 0, 0, png))
    rejects("oversize", lambda: mirrorweave.FrameEnvelope("s", 0, 0, "screen", "png", 0, 0, png + b"\0" * mirrorweave.MAX_FRAME_BYTES))
    rejects("empty", lambda: mirrorweave.FrameEnvelope("s", 0, 0, "screen", "png", 0, 0, b""))
    rejects("video_kind_needs_video_bytes", lambda: mirrorweave.FrameEnvelope("s", 0, 0, "camera_video", "h264", 0, 0, png))
    rejects("av1_unsupported", lambda: mirrorweave.FrameEnvelope("s", 0, 0, "screen", "av1", 0, 0, png))
    with tempfile.TemporaryDirectory(prefix="mw-hub-") as td:
        hub = mirrorweave.FrameHub(Path(td), ring=3)
        for seq in (0, 1, 4):                                     # 2 and 3 never arrive → 2 dropped
            hub.accept(mirrorweave.FrameEnvelope("s", seq, 1000 + seq * 100, "screen", "png", 0, 0, png))
        rejects("stale_seq", lambda: hub.accept(mirrorweave.FrameEnvelope("s", 4, 2000, "screen", "png", 0, 0, png)))
        rejects("replayed_older_seq", lambda: hub.accept(mirrorweave.FrameEnvelope("s", 2, 2000, "screen", "png", 0, 0, png)))
        for i in range(5, 12):
            hub.accept(mirrorweave.FrameEnvelope("s", i, 1000 + i * 100, "screen", "png", 0, 0, png))
        st = hub.stats()["s"]
        persisted = mirrorweave.load_persisted(Path(td), "s")
        hub_ok = (st["dropped"] == 2 and st["buffered"] == 3 and st["frames"] == 10 and st["last_seq"] == 11
                  and hub.latest("s").seq == 11 and persisted is not None and persisted[1] == png and persisted[0]["seq"] == 11)
    src = [e.seq for e in mirrorweave.StillsSource("cam", [png, png, png], "camera_still", "png", start_seq=7).frames()]
    return {"ok": back == env and all(errs.values()) and hub_ok and src == [7, 8, 9],
            "roundtrip_equal": back == env, "rejections": errs, "hub": {"stats": st, "ok": hub_ok}, "stills_source_seqs": src}


def _mirror_linkloop(root: Path, tmp: Path) -> dict[str, Any]:
    png1, png2 = _png("sharp", 64, 48, 1), _png("sharp", 64, 48, 2)
    tele = json.dumps(lensforge.CaptureTelemetry(device="test", focal_length_mm=6.9, iso=100).to_dict()).encode()
    d = Desktop(tmp / "desk9", allow=PERMS).start()
    out: dict[str, Any] = {}
    try:
        url = d.srv.url
        info = json.loads(urllib.request.urlopen(url + "/mirror/info", timeout=5).read())
        out["public_info"] = {"features": len(info["features"]),
                              "stubs": sum(1 for f in info["features"] if f["status"] == "stub"),
                              "ok": info["milestone"] == "C9" and all("reason" in f for f in info["features"] if f["status"] == "stub")}
        c = LinkClient(url, "phone-a")
        c.pair(d.srv.code, ["mirror", "drive_studio"])
        fr = mirrorweave.StillsSource("screen", [png1, png2], "screen", "png", 64, 48)
        pushed = [c.mirror_frame(e) for e in fr.frames()]
        t = c.mirror_frame(mirrorweave.FrameEnvelope("telemetry", 0, 5, "telemetry", "json", 0, 0, tele))
        latest = c.mirror_latest("screen")
        got = base64.b64decode(latest["frame"]["data_b64"])
        stale = _http_err(lambda: c.mirror_frame(mirrorweave.FrameEnvelope("screen", 1, 9, "screen", "png", 0, 0, png1)))
        q = c.mirror_control(mirrorweave.ControlMessage("desktop", "query", "forge.status"))
        qg = c.mirror_control(mirrorweave.ControlMessage("desktop", "query", "groundweave.show"))
        qs = c.mirror_control(mirrorweave.ControlMessage("desktop", "query", "mirror.stats"))
        bad_q = _http_err(lambda: c.mirror_control(mirrorweave.ControlMessage("desktop", "query", "rm -rf /")))
        android = _http_err(lambda: c.mirror_control(mirrorweave.ControlMessage("android", "input", "tap")))
        focus = _http_err(lambda: c.mirror_control(mirrorweave.ControlMessage("desktop", "focus", "x")))
        studio_ok = c.mirror_control(mirrorweave.ControlMessage("desktop", "input", "key", {"key": "a"}))
        studio_bad = _http_err(lambda: c.mirror_control(mirrorweave.ControlMessage("desktop", "input", "key", {"key": "F13"})))
        mirrorweave.AndroidController(d.srv.state_dir, "phone-a").send(mirrorweave.ControlMessage("android", "input", "tap", {"x": 0.5, "y": 0.5}))
        polled = c.mirror_input_poll()
        out["frames"] = {"pushed": [p["seq"] for p in pushed], "latest_identical": got == png2, "telemetry_ok": t["accepted"],
                         "stale_status": stale[0], "streams": sorted(latest["stats"])}
        out["control"] = {"status_query_ok": q["ok"] and q["value"]["version"] is not None, "groundweave_ok": qg["ok"],
                          "stats_ok": qs["ok"] and "screen" in qs["value"],
                          "not_allowlisted": {"status": bad_q[0], "error": bad_q[1].get("error", "")[:80]}}
        out["remote_refused"] = {"android_input_from_network": android[0], "focus_from_network": focus[0]}
        out["studio_input"] = {"accepted_seq": studio_ok.get("seq"), "spooled": len(d.srv.studio.read()),
                               "not_allowlisted": studio_bad[0]}
        out["input_poll"] = {"events": [e["event"] for e in polled], "signed": all(len(e["sig"]) == 64 for e in polled)}
        # capability model: a device without `mirror`/`drive_studio` is refused; unsigned requests too
        weak = LinkClient(url, "phone-b")
        weak.pair(d.srv.code, ["offload"])
        no_mirror = _http_err(lambda: weak.mirror_frame(mirrorweave.FrameEnvelope("x", 0, 1, "screen", "png", 0, 0, png1)))
        no_drive = _http_err(lambda: weak.mirror_control(mirrorweave.ControlMessage("desktop", "query", "forge.status")))
        req = urllib.request.Request(url + "/mirror/frame", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        unsigned = _http_err(lambda: json.loads(urllib.request.urlopen(req, timeout=5).read()))
        out["capabilities"] = {"no_mirror_cap": no_mirror[0], "no_drive_cap": no_drive[0], "unsigned": unsigned[0]}
        out["ok"] = bool(
            out["public_info"]["ok"] and [p["seq"] for p in pushed] == [0, 1] and got == png2 and stale[0] == 400
            and out["control"]["status_query_ok"] and out["control"]["groundweave_ok"] and out["control"]["stats_ok"]
            and bad_q[0] == 403 and android[0] == 403 and focus[0] == 403
            and studio_ok.get("ok") and len(d.srv.studio.read()) == 1 and studio_bad[0] == 403
            and [e["event"] for e in polled] == [{"type": "tap", "x": 0.5, "y": 0.5}]
            and no_mirror[0] == 403 and no_drive[0] == 403 and unsigned[0] == 403)
    finally:
        d.halt()
    return out


def _kotlin_mirror(root: Path, tmp: Path, b: dict[str, Any]) -> dict[str, Any]:
    png = _png("sharp", 48, 32, 3)
    f = tmp / "kframe.png"
    f.write_bytes(png)
    d = Desktop(tmp / "desk9k", allow=PERMS).start()
    home = tmp / "phone9"
    try:
        pc, pres = jar(root, "pair", "--url", d.srv.url, "--code", d.srv.code, "--caps", ",".join(PERMS), home=home)
        rc0, push = jar(root, "mirror-push", "--file", str(f), "--stream", "kscreen", "--seq", "0", home=home)
        rc1, stale = jar(root, "mirror-push", "--file", str(f), "--stream", "kscreen", "--seq", "0", home=home)
        rc2, q = jar(root, "mirror-query", "--name", "forge.status", home=home)
        rc3, inp = jar(root, "studio-key", "--key", "q", home=home)
        env = d.srv.mirror.latest("kscreen")
        rc4, stubs = jar(root, "stubs")
        vp8 = root / "tests" / "fixtures" / "video" / "tiny_vp8.ivf"
        rc5, vpush = jar(root, "mirror-video-push", "--file", str(vp8), "--codec", "vp8", "--stream", "kvideo", home=home)
        h264 = root / "tests" / "fixtures" / "video" / "tiny_h264.h264"
        rc6, hpush = jar(root, "mirror-video-push", "--file", str(h264), "--codec", "h264", "--stream", "kh264", home=home)
        ctl = mirrorweave.AndroidController(d.srv.state_dir, _kotlin_client_id(home))
        ctl.send(mirrorweave.ControlMessage("android", "input", "swipe", {"x": 0.0, "y": 1.0, "x2": 1.0, "y2": 0.0, "duration_ms": 250}))
        ctl.send(mirrorweave.ControlMessage("android", "input", "key", {"key": "back"}))
        ctl.focus("manual", 0.25)
        rc7, poll = jar(root, "mirror-input-poll", home=home)
        vt = d.srv.mirror.video("kvideo")
        ht = d.srv.mirror.video("kh264")
        try:
            from forge import mirrorvideo as mv
            dec_v = len(mv.decode_packets("vp8", mv.parse_ivf((d.srv.state_dir / "mirror" / "kvideo" / "session.ivf").read_bytes())[1]))
            dec_h = len(mv.decode_packets("h264", [(d.srv.state_dir / "mirror" / "kh264" / "session.h264").read_bytes()]))
        except Exception as e:  # noqa: BLE001
            dec_v = dec_h = f"{type(e).__name__}: {e}"
        studio_rows = d.srv.studio.read()
    finally:
        d.halt()
    performed = poll.get("performed", []) if rc7 == 0 else []
    want_perf = [{"gesture": [{"points": [[0.0, 2399.0], [1079.0, 0.0]], "duration_ms": 250}]}, {"global": "back"},
                 {"focus": "manual", "diopters": 4.0}]
    refused = all(v.get("refused") and str(v.get("message", "")).startswith("[STUB ") for v in stubs.values()) if rc4 == 0 else False
    suites = _suites_ok(b, "C9C12Test")
    res = {"pair_caps": pres.get("caps"), "push": push, "desktop_has_identical_bytes": env is not None and env.data == png,
           "stale_push": {"exit": rc1, "status": stale.get("status")}, "query_ok": rc2 == 0 and q.get("ok") is True,
           "studio_key": {"exit": rc3, "seq": inp.get("seq"), "spooled": [r["event"] for r in studio_rows]},
           "video_push": {"vp8": {"exit": rc5, "pushed": vpush.get("pushed"), "track": vt.stats() if vt else None, "decoded": dec_v},
                          "h264": {"exit": rc6, "pushed": hpush.get("pushed"), "track": ht.stats() if ht else None, "decoded": dec_h}},
           "input_poll": {"exit": rc7, "performed": performed, "expected": want_perf},
           "kotlin_stubs": {"count": len(stubs), "all_refuse": refused}, "suites": suites}
    res["ok"] = bool(pc == 0 and rc0 == 0 and push.get("accepted") and res["desktop_has_identical_bytes"] and rc1 == 3
                     and stale.get("status") == 400 and res["query_ok"] and rc3 == 0
                     and [r["event"] for r in studio_rows] == [{"type": "key", "key": "q", "shift": False}]
                     and rc5 == 0 and vpush.get("pushed") == 8 and dec_v == 8 and rc6 == 0 and hpush.get("pushed") == 8 and dec_h == 8
                     and rc7 == 0 and performed == want_perf and refused and suites["ok"])
    return res


def _kotlin_client_id(home: Path) -> str:
    """FabricCore's node id (= its LoomLink client id), persisted by PocketLoomCore in `<home>/node.json`."""
    return json.loads((home / "node.json").read_text(encoding="utf-8"))["node_id"]


def _apk_has_android_impls(root: Path, b: dict[str, Any]) -> dict[str, Any]:
    """The `real_unverified_on_device` rows' platform classes are in the built APK's manifest/dex, lint has 0 errors.
    This proves the code compiles and is packaged — not that it works on a phone."""
    from forge.packaging import build_tool, find_android_sdk

    apk = root / b["apk"]["path"] if b.get("apk") else None
    sdk = find_android_sdk(root)
    aapt = build_tool(sdk, "aapt") if sdk else None
    if not (apk and apk.exists() and aapt):
        return {"ok": False, "error": "APK or aapt missing"}
    xml = subprocess.run([str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml"], capture_output=True, text=True).stdout
    impls = sorted({f["android_impl"] for f in registry.features(None, root) if f.get("status") == "real_unverified_on_device"})
    import zipfile
    with zipfile.ZipFile(apk) as z:
        dex = b"".join(z.read(n) for n in z.namelist() if n.endswith(".dex"))
    found = {c: (f"Lfabric/pocketloom/{c};".encode() in dex) for c in impls}
    services = {c: (c in xml) for c in ("ScreenMirrorService", "MirrorAccessibilityService")}
    perms = {p: (p in xml) for p in ("FOREGROUND_SERVICE_MEDIA_PROJECTION", "BIND_ACCESSIBILITY_SERVICE", "android.permission.CAMERA")}
    lint_errors = (b.get("lint") or {}).get("errors")
    return {"ok": all(found.values()) and all(services.values()) and all(perms.values()) and lint_errors == 0,
            "classes_in_dex": found, "manifest_services": services, "manifest_permissions": perms, "lint_errors": lint_errors,
            "apk_bytes": b["apk"]["bytes"], "verified_on_device": False}


def _cli_stubs(root: Path, cmds: list[list[str]]) -> dict[str, Any]:
    out = {}
    for argv in cmds:
        p = subprocess.run([sys.executable, "-m", "forge.cli", *argv], cwd=root, capture_output=True, text=True, timeout=60)
        try:
            doc = json.loads(p.stdout)
        except ValueError:
            doc = {}
        out[" ".join(argv)] = {"exit": p.returncode, "stub": doc.get("stub"), "label": is_stub_message(doc.get("message", ""))}
    return {"ok": all(v["exit"] == 3 and v["stub"] and v["label"] for v in out.values()), "commands": out}


def c9_run(root: Path) -> tuple[int, dict[str, Any]]:
    full = full_possible(root)
    tmp = Path(tempfile.mkdtemp(prefix="fabric-c9-"))
    try:
        r: dict[str, Any] = {"mode": "full" if full else "fast"}
        r["register"] = _stubs_refuse("C9", root)
        r["contract"] = _frames_contract()
        r["loomlink"] = _mirror_linkloop(root, tmp)
        r["video"] = _mirror_video(tmp)
        r["ws_transport"] = _mirror_ws(tmp)
        r["desktop_capture"] = _mirror_desktop_capture()
        r["studio"] = _mirror_studio(root, tmp)
        r["cli"] = _mirror_cli(root, tmp)
        r["groundweave"] = _ladder(root, ["mirror.encode"], [])
        r["cpu_2core"] = _verify(root, "mirror.encode")
        if full:
            b = gradle_build(root)
            r["build"] = {"ok": b["ok"], "junit_tests": b["junit"]["tests"], "junit_failures": b["junit"]["failures"],
                          **({"log_tail": b.get("log_tail", "")[-1500:]} if not b["ok"] else {})}
            if b["ok"]:
                r["kotlin_interop"] = _kotlin_mirror(root, tmp, b)
                r["apk"] = _apk_has_android_impls(root, b)
        return 0, r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _rgb_frames(n: int = 20, w: int = 160, h: int = 120) -> list[Any]:
    y, x = np.mgrid[0:h, 0:w]
    out = []
    for i in range(n):
        f = np.stack([(x * 1.5 + i * 3) % 256, (y * 2) % 256, ((x + y) // 2 + i * 5) % 256], -1).astype(np.uint8)
        f[30:60, 20 + i * 3:50 + i * 3] = [255, 40, 40]
        out.append(f)
    return out


PSNR_FLOOR_DB = 28.0     # [INFERENCE C-55] desktop CPU video gate on the synthetic clip at 1.5 Mbit/s


def _mirror_video(tmp: Path) -> dict[str, Any]:
    from forge import mirrorvideo as mv

    av = mv.available()
    if not av["vp8"]:
        return {"ok": False, "error": "system ffmpeg with libvpx is required for C9 video", "available": av}
    fr = _rgb_frames()
    rows: dict[str, Any] = {}
    ok = True
    for codec in ("vp8", "vp9"):
        if not av[codec]:
            rows[codec] = {"ok": False, "error": "encoder missing"}
            ok = False
            continue
        enc = mv.CpuVideoEncoder(160, 120, codec, gop=10)
        pk = enc.encode(fr)
        dec = mv.decode_packets(codec, pk, 160, 120)
        p = min(mv.psnr(a, b) for a, b in zip(fr, dec)) if len(dec) == len(fr) else 0.0
        keys = [i for i, x in enumerate(pk) if mv.is_keyframe(codec, x)]
        good = len(pk) == len(fr) and keys == [0, 10] and p >= PSNR_FLOOR_DB
        rows[codec] = {"ok": good, "packets": len(pk), "bytes": sum(map(len, pk)), "keyframes_at": keys, "min_psnr_db": round(p, 2)}
        ok = ok and good
    # loss + resync on a FrameHub
    pk = mv.CpuVideoEncoder(160, 120, "vp8", gop=10).encode(fr)
    hub = mirrorweave.FrameHub(tmp / "vhub")
    for i, x in enumerate(pk):
        if i not in (3, 4):
            hub.accept(mirrorweave.FrameEnvelope("v", i, i, "screen_video", "vp8", 160, 120, x, mv.is_keyframe("vp8", x)))
    st = hub.video("v").stats()
    import io

    from PIL import Image
    last = np.asarray(Image.open(io.BytesIO(mirrorweave.decode_latest(tmp / "vhub", "v"))).convert("RGB"))
    resync = {"skipped": st["skipped"], "keyframes": st["keyframes"], "latest_psnr_db": round(mv.psnr(last, fr[-1]), 2)}
    resync["ok"] = st["skipped"] == 5 and st["keyframes"] == 2 and resync["latest_psnr_db"] >= PSNR_FLOOR_DB
    return {"ok": ok and resync["ok"], "codecs": rows, "loss_resync": resync, "psnr_floor_db": PSNR_FLOOR_DB}


def _mirror_ws(tmp: Path) -> dict[str, Any]:
    try:
        from forge.mirrorws import MirrorWsClient, MirrorWsServer, pack
    except ImportError as e:
        return {"ok": False, "error": f"websockets missing ({e}); install the `mirror` extra"}
    from forge import mirrorvideo as mv

    d = Desktop(tmp / "deskws", allow=("mirror", "offload")).start()
    ws = MirrorWsServer(d.srv).start()
    out: dict[str, Any] = {}
    try:
        c = LinkClient(d.srv.url, "phone-ws")
        c.pair(d.srv.code, ["mirror"])
        fr = _rgb_frames(15)
        t0 = __import__("time").perf_counter()
        with MirrorWsClient(ws.url, c) as cl:
            acks = [cl.send(e) for e in mirrorweave.VideoStreamSource("wsv", "vp8", 160, 120, rgb_frames=fr).frames()]
            pk0 = mv.CpuVideoEncoder(160, 120, "vp8").encode(fr[:1])[0]
            env = mirrorweave.FrameEnvelope("wsv", 100, 1, "screen_video", "vp8", 160, 120, pk0, True)
            bad = bytearray(pack(c, env))
            bad[-1] ^= 0xFF
            tampered = cl.send_raw(bytes(bad))
            good = pack(c, env)
            first, replay = cl.send_raw(good), cl.send_raw(good)
        wall = __import__("time").perf_counter() - t0
        weak = LinkClient(d.srv.url, "weak-ws")
        weak.pair(d.srv.code, ["offload"])
        try:
            with MirrorWsClient(ws.url, weak):
                no_cap = "accepted"
        except PermissionError:
            no_cap = "refused"
        dec = mv.decode_packets("vp8", mv.parse_ivf((d.srv.state_dir / "mirror" / "wsv" / "session.ivf").read_bytes())[1])
        p = min(mv.psnr(a, b) for a, b in zip(fr, dec)) if len(dec) >= len(fr) else 0.0
        out = {"frames_acked": sum(1 for a in acks if a.get("type") == "ack"), "tampered": tampered.get("status"),
               "replay": replay.get("status"), "first_ok": first.get("type"), "no_mirror_cap": no_cap,
               "decoded_min_psnr_db": round(p, 2), "wall_s_15_frames": round(wall, 3)}
        out["ok"] = (out["frames_acked"] == 15 and tampered.get("status") == 403 and replay.get("status") == 403
                     and first.get("type") == "ack" and no_cap == "refused" and p >= PSNR_FLOOR_DB)
    finally:
        ws.stop()
        d.halt()
    return out


def _mirror_desktop_capture() -> dict[str, Any]:
    import os
    import time

    from forge import mirrorvideo as mv

    if not shutil.which("Xvfb"):
        return {"ok": False, "error": "Xvfb is required to prove desktop capture headless (apt install xvfb)"}
    disp = f":{80 + os.getpid() % 15}"
    x = subprocess.Popen(["Xvfb", disp, "-screen", "0", "320x240x24", "-nolisten", "tcp"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        st = list(mirrorweave.DesktopScreenSource("desk", disp, fps=10, n=3).frames())
        vid = list(mirrorweave.VideoStreamSource("deskv", "vp8", 320, 240, fps=10, display=disp, n=5).frames())
        dec = mv.decode_packets("vp8", [e.data for e in vid], 320, 240)
        out = {"stills": len(st), "still_size": [st[0].width, st[0].height] if st else None, "video_packets": len(vid),
               "first_is_keyframe": bool(vid and vid[0].keyframe), "decoded": len(dec)}
        out["ok"] = len(st) == 3 and out["still_size"] == [320, 240] and len(vid) == 5 and out["first_is_keyframe"] and len(dec) == 5
        return out
    finally:
        x.kill()
        x.wait()


_STUDIO_PROBE = r'''
import os, sys, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "studio")
from pathlib import Path
from PySide6.QtWidgets import QApplication
from assetfabric_studio.app import StudioWindow, StudioInputBridge
from forge.mirrorweave import StudioInputSpool
app = QApplication([])
td = Path(sys.argv[1])
w = StudioWindow(td); w.show(); w.tabs.setCurrentIndex(2); app.processEvents()
sp = StudioInputSpool(td / "mirror" / "studio_input.jsonl")
b = StudioInputBridge(w, sp)
cw = w.centralWidget(); gp = w.console.mapTo(cw, w.console.rect().center())
sp.push({"type": "pointer", "action": "click", "x": gp.x() / (cw.width() - 1), "y": gp.y() / (cw.height() - 1)})
for k in "hi": sp.push({"type": "key", "key": k})
sp.push({"type": "key", "key": "a", "shift": True})
n = b.poll(); typed = w.console.text()
sp.push({"type": "key", "key": "enter"}); b.poll()
print(json.dumps({"n": n, "typed": typed, "log": w.log.toPlainText(), "healthy": w.refresh_status()["healthy"]}))
'''


def _mirror_studio(root: Path, tmp: Path) -> dict[str, Any]:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return {"ok": False, "error": "PySide6 missing — install the `studio` extra to prove Studio input"}
    p = subprocess.run([sys.executable, "-c", _STUDIO_PROBE, str(tmp / "studio")], cwd=root, capture_output=True, text=True,
                       timeout=120)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "exit": p.returncode, "stderr": p.stderr[-600:]}
    out["ok"] = out.get("n") == 4 and out.get("typed") == "hiA" and out.get("log") == "hiA"
    return out


def _mirror_cli(root: Path, tmp: Path) -> dict[str, Any]:
    def cli(*argv: str) -> tuple[int, dict[str, Any]]:
        p = subprocess.run([sys.executable, "-m", "forge.cli", *argv], cwd=root, capture_output=True, text=True, timeout=60)
        try:
            return p.returncode, json.loads(p.stdout)
        except ValueError:
            return p.returncode, {"raw": p.stdout[-200:], "err": p.stderr[-300:]}
    sd = tmp / "cli-state"
    a = cli("mirror", "input", "--state-dir", str(sd), "--device", "phone-a", "swipe", "--x", "0.1", "--y", "0.9", "--x2", "0.1", "--y2", "0.1")
    b = cli("mirror", "input", "--state-dir", str(sd), "--device", "phone-a", "focus", "--mode", "manual", "--distance-m", "0.5")
    bad = cli("mirror", "input", "--state-dir", str(sd), "--device", "phone-a", "key", "--key", "power")
    info = cli("mirror", "info")
    rows = mirrorweave.InputOutbox(sd / "mirror" / "outbox").read("phone-a")
    out = {"queued": [r["event"]["type"] for r in rows], "bad_key_exit": bad[0],
           "info_unverified": [f["id"] for f in info[1].get("features", []) if f.get("status") == "real_unverified_on_device"],
           "info_stubs": [f["id"] for f in info[1].get("features", []) if f.get("status") == "stub"]}
    out["ok"] = a[0] == 0 and b[0] == 0 and bad[0] == 1 and out["queued"] == ["swipe", "focus"] and not out["info_stubs"] \
        and len(out["info_unverified"]) == 4
    return out


# ====================================================================================== C10

def _lens_quality(root: Path) -> dict[str, Any]:
    cases = {"sharp": [], "blurry": ["blurry"], "dark": ["too_dark", "clipped"], "bright": ["too_bright", "clipped"]}
    rows = {}
    ok = True
    for k, want in cases.items():
        a = lensforge.assess(_png(k), "still", root)
        rows[k] = {"verdict": a["verdict"], "reasons": a["reasons"], "sharpness": a["sharpness"], "mean_luma": a["mean_luma"]}
        ok = ok and a["reasons"] == want and a["advisory"] is True
    tiny = lensforge.assess(_png("sharp", 100, 80), "orbit", root)
    rows["tiny_for_orbit"] = {"verdict": tiny["verdict"], "reasons": tiny["reasons"]}
    ok = ok and "low_resolution" in tiny["reasons"]
    again = lensforge.assess(_png("sharp"), "still", root)
    det = again == lensforge.assess(_png("sharp"), "still", root)
    jpg = root / "tests" / "fixtures" / "capture_640x480.jpg"
    try:
        j = lensforge.assess(jpg.read_bytes(), "still", root)
        jpeg = {"ok": j["media"] == "image/jpeg" and (j["width"], j["height"]) == (640, 480), "verdict": j["verdict"], "reasons": j["reasons"]}
    except lensforge.DecodeError as e:
        jpeg = {"ok": False, "error": str(e)}
    junk = lensforge.assess_or_reason(b"not an image")
    return {"ok": ok and det and jpeg["ok"] and junk["verdict"] == "unassessed", "cases": rows, "deterministic": det,
            "jpeg_fixture": jpeg, "junk_input": junk}


def _lens_sets(root: Path) -> dict[str, Any]:
    imgs = [_png("sharp", 640, 480, s) for s in range(1, 4)]
    ok_set = lensforge.assess_set(imgs, "burst", root)
    short = lensforge.assess_set(imgs[:2], "burst", root)
    dup = lensforge.assess_set([imgs[0], imgs[0], imgs[1], imgs[2]], "burst", root)
    mixed = lensforge.assess_set([*imgs, _png("blurry"), b"junk"], "burst", root)
    stub_modes = {}
    for m in ():                                     # no stub capture modes left since 0.7.6 (depth_assist is real)
        try:
            lensforge.assess_set(imgs, m, root)
            stub_modes[m] = "returned"
        except StubError as e:
            stub_modes[m] = "refused" if is_stub_message(str(e)) else "unlabelled"
    da = lensforge.assess_set(imgs, "depth_assist", root)
    ok = (ok_set["verdict"] == "pass" and ok_set["usable_views"] == 3 and ok_set["overlap"] == "not_measured"
          and short["reasons"] == ["too_few_usable_views"] and len(dup["duplicates"]) == 1 and dup["usable_views"] == 3
          and mixed["usable_views"] == 3 and mixed["per_view"][-1]["verdict"] == "unreadable"
          and set(stub_modes.values()) <= {"refused"} and da["reasons"] == ["too_few_usable_views"])
    return {"ok": ok, "burst_ok": ok_set["verdict"], "depth_assist_3_views": da["reasons"], "too_few": short["reasons"], "duplicates": dup["duplicates"],
            "mixed_usable": mixed["usable_views"], "stub_modes": stub_modes, "overlap": ok_set["overlap"]}


def _lens_telemetry() -> dict[str, Any]:
    t = lensforge.CaptureTelemetry(device="Redmi", focal_length_mm=6.9, sensor_width_mm=9.6, iso=100, orientation=6, captured_at_ms=1)
    back = lensforge.CaptureTelemetry.from_dict(json.loads(json.dumps(t.to_dict())))
    bad = {}
    for name, fn in (("iso_zero", lambda: lensforge.CaptureTelemetry(iso=0)), ("orientation", lambda: lensforge.CaptureTelemetry(orientation=9)),
                     ("unknown_field", lambda: lensforge.CaptureTelemetry.from_dict({"gps": 1})),
                     ("bool_not_number", lambda: lensforge.CaptureTelemetry(iso=True))):  # type: ignore[arg-type]
        try:
            fn()
            bad[name] = False
        except ValueError:
            bad[name] = True
    exif: dict[str, Any]
    try:
        import io

        from PIL import Image
        im = Image.new("RGB", (32, 24), (90, 90, 90))
        ex = Image.Exif()
        ex[0x010F], ex[0x0110], ex[0x0112] = "Acme", "Cam 1", 6
        sub = ex.get_ifd(0x8769)
        sub[0x920A], sub[0xA405], sub[0x829A], sub[0x8827] = 6.9, 24, 0.01, 200
        buf = io.BytesIO()
        im.save(buf, "JPEG", exif=ex)
        e = lensforge.read_exif(buf.getvalue())
        exif = {"ok": e.device == "Acme Cam 1" and abs(e.focal_length_mm - 6.9) < 1e-6 and e.focal_length_35mm == 24
                and e.orientation == 6 and e.iso == 200 and e.sensor_width_mm is None, "read": e.to_dict()}
    except ImportError:
        exif = {"ok": True, "skipped": "Pillow not installed (install the `lens` extra)"}
    return {"ok": back == t and all(bad.values()) and exif["ok"], "roundtrip_equal": back == t, "rejects": bad, "exif": exif}


def _lens_offload(root: Path, tmp: Path) -> dict[str, Any]:
    jpg = (root / "tests" / "fixtures" / "capture_640x480.jpg").read_bytes()
    d = Desktop(tmp / "desk10", allow=PERMS).start()
    try:
        c = LinkClient(d.srv.url, "phone-c")
        c.pair(d.srv.code, ["offload"])
        r = c.offload({"id": "j1", "op": "recon.capture", "payload": {"id": "cap_t1", "data_b64": base64.b64encode(jpg).decode(),
                                                                       "media": "image/jpeg"}})
        junk = c.offload({"id": "j2", "op": "recon.capture", "payload": {"id": "cap_t2", "data_b64": base64.b64encode(b"junk").decode()}})
        prov = d.srv.store.entries["cap_t1"]["provenance"]
    finally:
        d.halt()
    q = r["value"]["quality"]
    return {"ok": r["ok"] and r["value"]["reconstruction"] == "stub" and q["width"] == 640 and prov["quality"] == q
            and junk["ok"] and junk["value"]["quality"]["verdict"] == "unassessed",
            "quality": {k: q[k] for k in ("verdict", "reasons", "sharpness")}, "stored_in_provenance": prov["quality"] == q,
            "reconstruction": r["value"]["reconstruction"], "junk_capture": junk["value"]["quality"]["verdict"]}


def make_test_clip(path: Path, seconds: int = 6, size: str = "640x360") -> Path:
    """Test clip with the host ffmpeg (native mpeg4 encoder, LGPL — no x264): 2 s static, 2 s blurred pan, 2 s sharp pan."""
    from forge.mirrorvideo import ffmpeg_bin
    w, h = size.split("x")
    third = seconds // 3
    n = third * 30
    flt = (f"[0:v]trim=end_frame=1,loop=loop={n - 1}:size=1:start=0,setpts=N/30/TB[a];"
           f"[0:v]trim=start_frame={n}:end_frame={2 * n},boxblur=12:2,setpts=N/30/TB[b];"
           f"[0:v]trim=start_frame={2 * n}:end_frame={3 * n},setpts=N/30/TB[c];[a][b][c]concat=n=3:v=1:a=0,fps=30[v]")
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size={w}x{h}:rate=30:duration={seconds}", "-filter_complex", flt, "-map", "[v]",
                    "-r", "30", "-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=120)
    return path


def _lens_video(root: Path, tmp: Path) -> dict[str, Any]:
    """Video capture ingest: frames sampled by ffmpeg, keyframes = sharpest novel frame per second, assessed as a `video`
    set; static and blurred stretches yield no keyframes. Plus the LoomLink `lens.video` offload and the CLI."""
    clip = make_test_clip(tmp / "clip.mp4").read_bytes()
    ing = lensforge.VideoCapture().ingest(clip)
    ts = [k["t_s"] for k in ing["keyframes"]]
    static = [t for t in ts if t < 2.0]
    blurred = [k for k in ing["keyframes"] if 2.0 <= k["t_s"] < 4.0]
    sharp = [t for t in ts if t >= 4.0]
    rejects = {}
    for name, data in (("not_video", b"\x89PNG\r\n\x1a\n" + b"0" * 32), ("truncated_mp4", clip[:2000])):
        try:
            lensforge.VideoCapture().ingest(data)
            rejects[name] = False
        except ValueError:
            rejects[name] = True
    d = Desktop(tmp / "desk10v", allow=("offload",)).start()
    try:
        c = LinkClient(d.srv.url, "phone-v")
        c.pair(d.srv.code, ["offload"])
        r = c.offload({"id": "v1", "op": "lens.video", "payload": {"id": "vid_t1", "data_b64": base64.b64encode(clip).decode(),
                                                                    "media": "video/mp4"}})
        stored = {k: d.srv.store.entries[k]["media"] for k in d.srv.store.entries if k.startswith("vid_t1")}
    finally:
        d.halt()
    p = subprocess.run([sys.executable, "-m", "forge.cli", "lens", "video", str(tmp / "clip.mp4")], cwd=root,
                       capture_output=True, text=True, timeout=120)
    cli = json.loads(p.stdout) if p.returncode == 0 else {}
    v = r.get("value") or {}
    ok = (ing["sampled_frames"] == 12 and len(static) <= 1 and not blurred and len(sharp) == 2
          and all(rejects.values()) and r.get("ok") and len(v.get("keyframes_stored", [])) == len(ing["keyframes"])
          and stored.get("vid_t1") == "video/mp4" and sum(1 for m in stored.values() if m == "image/png") == len(ing["keyframes"])
          and cli.get("keyframes") == ing["keyframes"])
    return {"ok": bool(ok), "sampled_frames": ing["sampled_frames"], "keyframes_t_s": ts, "static_picks": static,
            "blurred_picks": len(blurred), "sharp_picks": sharp, "assessment": {k: ing["assessment"][k] for k in ("verdict", "reasons", "usable_views", "min_views")},
            "rejects": rejects, "offload_keyframes_stored": len(v.get("keyframes_stored", [])), "store_media": sorted(set(stored.values())),
            "cli_exit": p.returncode, "cli_matches": cli.get("keyframes") == ing["keyframes"], "video_entry": stored.get("vid_t1"), "offload_ok": r.get("ok"), "pngs": sum(1 for m in stored.values() if m == "image/png")}


def _kotlin_video(root: Path, tmp: Path) -> dict[str, Any]:
    """FabricCore stores a clip, queues `lens.video`, drains it to a real desktop which extracts keyframes."""
    clip = make_test_clip(tmp / "kclip.mp4")
    d = Desktop(tmp / "desk10k", allow=("offload",)).start()
    home = tmp / "phone10"
    try:
        pc, _ = jar(root, "pair", "--url", d.srv.url, "--code", d.srv.code, "--caps", "offload", home=home)
        rc1, cap = jar(root, "capture-video", "--file", str(clip), "--source", "camera", home=home)
        rc2, dr = jar(root, "drain", home=home)
        keys = [k for k, e in d.srv.store.entries.items() if e.get("media") == "image/png" and k.startswith("vid_")]
        vid = [k for k, e in d.srv.store.entries.items() if e.get("media") == "video/mp4"]
    finally:
        d.halt()
    ok = pc == 0 and rc1 == 0 and rc2 == 0 and dr.get("sent") == 1 and len(vid) == 1 and len(keys) >= 2
    return {"ok": bool(ok), "queued_job": cap.get("job"), "sent": dr.get("sent"), "desktop_video_entries": len(vid),
            "desktop_keyframes": len(keys)}


def _kotlin_suite(b: dict[str, Any]) -> dict[str, Any]:
    s = _suites_ok(b, "C9C12Test")
    return {"ok": s["ok"], **s}


def c10_run(root: Path) -> tuple[int, dict[str, Any]]:
    full = full_possible(root)
    tmp = Path(tempfile.mkdtemp(prefix="fabric-c10-"))
    try:
        r: dict[str, Any] = {"mode": "full" if full else "fast"}
        r["register"] = _stubs_refuse("C10", root)
        r["quality"] = _lens_quality(root)
        r["sets"] = _lens_sets(root)
        r["telemetry"] = _lens_telemetry()
        r["offload"] = _lens_offload(root, tmp)
        r["video"] = _lens_video(root, tmp)
        r["arcore"] = _arcore_coverage(root, tmp)
        r["groundweave"] = _ladder(root, ["lens.assess"], [])
        r["cpu_2core"] = _verify(root, "lens.assess")
        if full:
            b = gradle_build(root)
            r["build"] = {"ok": b["ok"], "junit_tests": b["junit"]["tests"], "junit_failures": b["junit"]["failures"],
                          **({"log_tail": b.get("log_tail", "")[-1500:]} if not b["ok"] else {})}
            if b["ok"]:
                r["kotlin_parity"] = _kotlin_suite(b)
                r["kotlin_video"] = _kotlin_video(root, tmp)
                r["apk"] = _apk_has_android_impls(root, b)
        return 0, r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================================== C11

def _depth_real() -> dict[str, Any]:
    f = depth.focal_px(4000, 6.9, 9.6)
    # analytic ground truth: an object 0.30 m wide at 7.1875 m with f=2875 px spans exactly 120 px
    d = depth.distance_to_object(0.30, 120.0, f)
    far = depth.distance_to_object(0.30, 60.0, f)
    prio = depth.focal_px(640, 4.0, 5.6, 28.0)             # mm+sensor wins over 35 mm-equivalent
    fov = depth.focal_px(1920, hfov_deg=90.0)              # tan(45°) = 1 → f = w/2
    refuses = {}
    for name, fn in (("no_intrinsics", lambda: depth.focal_px(1000)), ("zero_size", lambda: depth.distance_to_object(0, 10, 100)),
                     ("zero_px", lambda: depth.distance_to_object(1, 0, 100))):
        try:
            fn()
            refuses[name] = False
        except ValueError:
            refuses[name] = True
    ok = (abs(f - 2875.0) < 1e-9 and abs(d["distance_m"] - 7.1875) < 1e-6 and d["lo_m"] < d["distance_m"] < d["hi_m"]
          and abs(far["distance_m"] - 2 * d["distance_m"]) < 1e-5 and abs(prio - 4.0 / 5.6 * 640) < 1e-9
          and abs(fov - 960.0) < 1e-9 and all(refuses.values()))
    return {"ok": ok, "focal_px": f, "distance": d, "farther_is_double": abs(far["distance_m"] - 2 * d["distance_m"]) < 1e-5,
            "priority_ok": abs(prio - 4.0 / 5.6 * 640) < 1e-9, "fov_ok": abs(fov - 960.0) < 1e-9, "refuses": refuses}


def _depth_align() -> dict[str, Any]:
    ys, xs = np.mgrid[0:48, 0:64]
    z_true = 2.0 + 0.02 * xs + 0.01 * ys                     # a tilted plane, metres
    rel = 0.37 * (1.0 / z_true) + 0.05                       # an arbitrary affine inverse-depth (DepthAnything-like) map
    anchors = [depth.Anchor(2, 2, float(z_true[2, 2])), depth.Anchor(60, 40, float(z_true[40, 60])), depth.Anchor(30, 20, float(z_true[20, 30]))]
    al = depth.align_inverse_depth(rel, anchors)
    err = float(np.nanmax(np.abs(al["depth_m"] - z_true)))
    bad = {}
    for name, fn in (("one_anchor", lambda: depth.align_inverse_depth(rel, anchors[:1])),
                     ("same_rel_value", lambda: depth.align_inverse_depth(np.ones((4, 4)), [depth.Anchor(0, 0, 1.0), depth.Anchor(1, 1, 2.0)])),
                     ("out_of_bounds", lambda: depth.align_inverse_depth(rel, [depth.Anchor(99, 99, 1.0), depth.Anchor(0, 0, 2.0)])),
                     ("negative_depth", lambda: depth.align_inverse_depth(rel, [depth.Anchor(0, 0, -1.0), depth.Anchor(5, 5, 2.0)])),
                     ("wrong_polarity", lambda: depth.align_inverse_depth(-rel, anchors))):
        try:
            fn()
            bad[name] = False
        except ValueError:
            bad[name] = True
    return {"ok": err < 1e-9 and al["anchor_rmse_m"] < 1e-9 and al["invalid_fraction"] == 0.0 and all(bad.values()),
            "max_abs_error_m": err, "anchor_rmse_m": al["anchor_rmse_m"], "rejects": bad,
            "note": "scales a relative map from ≥2 metric anchors (the dense map comes from DepthAnything V2 Small, check `dense`)"}


DENSE_FLOORS = {"abs_rel_max": 0.10, "delta1_min": 0.90, "spearman_min": 0.90}   # INFERENCES C-61


def _model_ready() -> bool:
    from forge import models
    return models.status(depth.MODEL_ID, verify=True)["ready"]


def _skipped_no_model() -> dict[str, Any]:
    return {"ok": not _models_required(), "skipped": "model_absent",
            "note": f"heavy: run `forge models fetch {depth.MODEL_ID}` (local/full runs; CI skips unless FORGE_REQUIRE_MODELS=1)"}


def _scene_jpeg(sc: dict[str, Any]) -> bytes:
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(sc["rgb"]).save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _depth_dense() -> dict[str, Any]:
    """DepthAnything V2 Small on an analytic ray-cast scene with exact depth: aligned AbsRel / δ1 / Spearman floors,
    the bytes (JPEG) path agrees with the array path, and a 1-thread run is bit-reproducible."""
    if not _model_ready():
        return _skipped_no_model()
    import time as _t
    sc = depth.render_scene(256, 192)
    est = depth.DepthAnythingV2(threads=1)
    t0 = _t.perf_counter()
    rel = est.estimate_rgb(sc["rgb"])
    wall = _t.perf_counter() - t0
    anchors = gw._scene_anchors(sc["depth_m"])
    m = depth.depth_metrics(depth.align_inverse_depth(rel, anchors)["depth_m"], sc["depth_m"])
    rel2 = depth.DepthAnythingV2(threads=1).estimate_rgb(sc["rgb"])
    relj = est.estimate(_scene_jpeg(sc))
    mj = depth.depth_metrics(depth.align_inverse_depth(relj, anchors)["depth_m"], sc["depth_m"])
    two = depth.align_inverse_depth(rel, anchors[:2])            # the minimum: two anchors
    m2 = depth.depth_metrics(two["depth_m"], sc["depth_m"])
    ok = (m["abs_rel"] <= DENSE_FLOORS["abs_rel_max"] and m["delta1"] >= DENSE_FLOORS["delta1_min"]
          and m["spearman"] >= DENSE_FLOORS["spearman_min"] and np.array_equal(rel, rel2)
          and mj["abs_rel"] <= DENSE_FLOORS["abs_rel_max"] and m2["spearman"] >= DENSE_FLOORS["spearman_min"])
    return {"ok": bool(ok), "model": depth.MODEL_ID, "scene": "render_scene(256x192): ground + brick wall + crate, depth 2.6–9.1 m",
            "metrics_12_anchors": m, "metrics_jpeg_path": mj, "metrics_2_anchors": m2, "floors": DENSE_FLOORS,
            "bit_reproducible_1_thread": bool(np.array_equal(rel, rel2)), "infer_s_1_thread": round(wall, 3)}


def _depth_offload(root: Path, tmp: Path) -> dict[str, Any]:
    """Phone → desktop `depth.estimate` over signed LoomLink (Python client here; Kotlin in full mode)."""
    if not _model_ready():
        return _skipped_no_model()
    sc = depth.render_scene(256, 192)
    an = gw._scene_anchors(sc["depth_m"], n=4)
    d = Desktop(tmp / "desk11", allow=("offload",)).start()
    try:
        c = LinkClient(d.srv.url, "phone-c11")
        c.pair(d.srv.code, ["offload"])
        r = c.offload({"id": "d1", "op": "depth.estimate", "payload": {
            "data_b64": base64.b64encode(_scene_jpeg(sc)).decode(), "max_side": 256,
            "anchors": [{"x": a.x, "y": a.y, "depth_m": a.depth_m} for a in an]}})
        bad = c.offload({"id": "d2", "op": "depth.estimate", "payload": {"data_b64": base64.b64encode(b"not an image").decode()}})
    finally:
        d.halt()
    v = r.get("value") or {}
    q = np.frombuffer(base64.b64decode(v.get("rel_u16_b64", "")), dtype="<u2")
    med = (v.get("metric") or {}).get("median_m")
    true_med = float(np.nanmedian(sc["depth_m"]))
    ok = (r.get("ok") is True and v.get("width") == 256 and v.get("height") == 192 and q.size == 256 * 192
          and med is not None and abs(med - true_med) / true_med < 0.1 and bad.get("ok") is False)
    return {"ok": bool(ok), "size": [v.get("width"), v.get("height")], "metric": v.get("metric"), "true_median_m": true_med,
            "bad_image_refused": bad.get("ok") is False, "bad_image_error": str(bad.get("error"))[:100]}


def _kotlin_depth(root: Path, tmp: Path) -> dict[str, Any]:
    if not _model_ready():
        return _skipped_no_model()
    sc = depth.render_scene(256, 192)
    f = tmp / "scene.jpg"
    f.write_bytes(_scene_jpeg(sc))
    an = gw._scene_anchors(sc["depth_m"], n=4)
    d = Desktop(tmp / "desk11k", allow=("offload",)).start()
    home = tmp / "phone11"
    try:
        pc, _ = jar(root, "pair", "--url", d.srv.url, "--code", d.srv.code, "--caps", "offload", home=home)
        rc, out = jar(root, "depth-estimate", "--file", str(f), "--max-side", "256",
                      "--anchors", ",".join(f"{a.x}:{a.y}:{a.depth_m}" for a in an), home=home)
    finally:
        d.halt()
    med = (out.get("metric") or {}).get("median_m") if rc == 0 else None
    true_med = float(np.nanmedian(sc["depth_m"]))
    ok = (pc == 0 and rc == 0 and out.get("width") == 256 and med is not None and abs(med - true_med) / true_med < 0.1
          and out.get("bottom_mean", 0) > out.get("top_mean", 1))        # floor (bottom) is nearer than the wall (top)
    return {"ok": bool(ok), "exit": rc, "width": out.get("width"), "metric_median_m": med, "true_median_m": true_med,
            "bottom_nearer_than_top": out.get("bottom_mean", 0) > out.get("top_mean", 1)}


def _orbit_poses(n: int = 24, r: float = 0.6, h: float = 0.3) -> list[list[float]]:
    """Camera-to-world poses on a circle, each looking at the origin (yaw about +Y; ARCore cameras look down -Z)."""
    import math
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        x, z = r * math.sin(a), r * math.cos(a)          # camera at angle a, looks toward origin → yaw = a
        out.append([x, h, z, 0.0, math.sin(a / 2), 0.0, math.cos(a / 2)])
    return out


def _arcore_coverage(root: Path, tmp: Path) -> dict[str, Any]:
    """C10 `lens.arcore_session` desktop half: pose coverage on an analytic 24-view orbit (known answer) + CLI."""
    import math

    from forge import arcore
    poses = _orbit_poses()
    cov = arcore.coverage(poses)
    want_path = 23 * 2 * 0.6 * math.sin(math.pi / 24)
    pf = tmp / "poses.json"
    pf.write_text(json.dumps(poses))
    p = subprocess.run([sys.executable, "-m", "forge.cli", "lens", "session", "--kind", "arcore", "--poses", str(pf)],
                       cwd=root, capture_output=True, text=True, timeout=60)
    try:
        cli = json.loads(p.stdout)
    except ValueError:
        cli = {}
    still = arcore.coverage([poses[0]] * 3)
    ok = (abs(cov["path_m"] - want_path) < 1e-5 and abs(cov["max_baseline_m"] - 1.2) < 1e-5
          and abs(cov["angular_spread_deg"] - 180.0) < 1e-3 and abs(cov["max_step_deg"] - 15.0) < 1e-3
          and still["angular_spread_deg"] == 0.0 and still["max_baseline_m"] == 0.0 and p.returncode == 0 and cli == cov)
    return {"ok": ok, "orbit": cov, "want_path_m": round(want_path, 6), "static": still, "cli_exit": p.returncode,
            "device": "never run on a phone — synthetic poses (real_unverified_on_device)"}


def _arcore_depth(root: Path, tmp: Path) -> dict[str, Any]:
    """C11 `depth.arcore` desktop half: synthetic DEPTH16 frame (shared Kotlin vectors) + ARCore-anchored dense depth on
    the analytic scene (GT depth quantised to mm at 1/4 resolution, as the Depth API delivers it)."""
    import io

    import numpy as np

    from forge import arcore
    fr = arcore.synthetic_frame(160, 120)
    pl = arcore.payload(fr["depth_mm"], fr["confidence"], [0, 0, 0, 0, 0, 0, 1], {"image_w": 640, "image_h": 480})
    got = depth.ARCoreDepth().ingest(pl)
    vec = json.loads((root / "tests" / "fixtures" / "arcore_vectors.json").read_text())
    shared = got["anchors"] == vec["anchors_160x120_640x480"] and {k: got[k] for k in ("valid_fraction", "min_m", "median_m", "max_m")} == vec["stats_160x120"]
    r: dict[str, Any] = {"shared_vectors": shared, "anchors": len(got["anchors"]), "no_image": got["dense"]}
    if not _model_ready():
        return {**r, **_skipped_no_model(), "ok": shared and not _models_required()}
    from PIL import Image
    sc = depth.render_scene(256, 192)
    gt = sc["depth_m"]
    small = np.nan_to_num(gt[2::4, 2::4], nan=0.0)
    mm = np.clip(np.round(small * 1000), 0, 65535).astype(np.uint16)
    buf = io.BytesIO()
    Image.fromarray(sc["rgb"]).save(buf, "PNG")
    pl = arcore.payload(mm, np.full(mm.shape, 255, np.uint8), [0, 1.5, 0, 0, 0, 0, 1], {"image_w": 256, "image_h": 192},
                        image=buf.getvalue(), media="image/png")
    v = depth.ARCoreDepth(depth.DepthAnythingV2(threads=1)).ingest(pl)
    med_gt = float(np.nanmedian(gt))
    rel_err = abs(v["dense"]["median_m"] - med_gt) / med_gt
    return {**r, "ok": shared and rel_err < 0.1 and v["dense"]["anchor_rmse_m"] < 0.5, "dense": v["dense"],
            "gt_median_m": med_gt, "median_rel_err": round(rel_err, 4)}


def _depth_cli(root: Path, tmp: Path) -> dict[str, Any]:
    from forge import arcore
    fr = arcore.synthetic_frame(64, 48)
    pf = tmp / "arcore.json"
    pf.write_text(json.dumps(arcore.payload(fr["depth_mm"], fr["confidence"], [0, 0, 0, 0, 0, 0, 1], {"image_w": 640, "image_h": 480})))
    pa = subprocess.run([sys.executable, "-m", "forge.cli", "depth", "estimate", str(pf), "--backend", "arcore"],
                        cwd=root, capture_output=True, text=True, timeout=60)
    try:
        ad = json.loads(pa.stdout)
    except ValueError:
        ad = {}
    stub = {"ok": pa.returncode == 0 and ad.get("width") == 64 and len(ad.get("anchors", [])) > 0, "exit": pa.returncode}
    if not _model_ready():
        return {**_skipped_no_model(), "ok": stub["ok"] and not _models_required(), "arcore_cli": stub}
    out = tmp / "d.png"
    p = subprocess.run([sys.executable, "-m", "forge.cli", "depth", "estimate", "tests/fixtures/capture_640x480.jpg",
                        "--anchor", "100,400,1.0", "--anchor", "320,100,3.0", "--out", str(out)],
                       cwd=root, capture_output=True, text=True, timeout=120)
    try:
        doc = json.loads(p.stdout)
    except ValueError:
        doc = {}
    from PIL import Image
    png_ok = out.exists() and Image.open(out).mode.startswith("I") and Image.open(out).size == (640, 480)
    return {"ok": stub["ok"] and p.returncode == 0 and doc.get("width") == 640 and "metric" in doc and png_ok,
            "arcore_cli": stub, "estimate_exit": p.returncode, "metric": doc.get("metric"), "png16": png_ok}


def _model_audit(root: Path) -> dict[str, Any]:
    from forge import models
    return models.audit(root)


def _girt_onnx(root: Path) -> dict[str, Any]:
    """GIRT policy → ONNX → onnxruntime CPU parity with the NumPy/GDScript maths (shares C11's onnxruntime dependency)."""
    try:
        from forge import girt_onnx
        return girt_onnx.parity(root, n=1000)
    except ImportError as e:
        return {"ok": False, "error": f"onnx/onnxruntime missing: {e}"}


def c11_run(root: Path) -> tuple[int, dict[str, Any]]:
    full = full_possible(root)
    tmp = Path(tempfile.mkdtemp(prefix="fabric-c11-"))
    try:
        r: dict[str, Any] = {"mode": "full" if full else "fast", "model_ready": _model_ready()}
        r["register"] = _stubs_refuse("C11", root)
        r["distance"] = _depth_real()
        r["align"] = _depth_align()
        r["dense"] = _depth_dense()
        r["arcore"] = _arcore_depth(root, tmp)
        r["offload"] = _depth_offload(root, tmp)
        r["cli"] = _depth_cli(root, tmp)
        r["model_licences"] = _model_audit(root)
        r["girt_onnx"] = _girt_onnx(root)
        r["groundweave"] = _ladder(root, ["depth.distance", "depth.estimate"], [])
        r["cpu_2core"] = _verify(root, "depth.distance", "depth.estimate")
        if full:
            b = gradle_build(root)
            r["build"] = {"ok": b["ok"], "junit_tests": b["junit"]["tests"], "junit_failures": b["junit"]["failures"],
                          **({"log_tail": b.get("log_tail", "")[-1500:]} if not b["ok"] else {})}
            if b["ok"]:
                r["kotlin_parity"] = _kotlin_suite(b)
                r["kotlin_depth"] = _kotlin_depth(root, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0, r


# ====================================================================================== C12

def _recon_core(root: Path, tmp: Path) -> dict[str, Any]:
    imgs = [_png("sharp", 640, 480, s) for s in range(1, 5)]
    routes = {t: realityloom.route(t) for t in realityloom.TARGETS}
    try:
        realityloom.route("nope")
        unknown = False
    except ValueError:
        unknown = True
    m1 = realityloom.bundle_manifest(imgs, "backdrop", "burst", root)
    m2 = realityloom.bundle_manifest(list(reversed(imgs)), "backdrop", "burst", root)
    same = json.dumps(realityloom.bundle_manifest(imgs, "backdrop", "burst", root), sort_keys=True) == json.dumps(m1, sort_keys=True)
    wb = realityloom.write_bundle(tmp / "bundle", imgs, "backdrop", "burst", root)
    stored = sorted(p.name for p in (tmp / "bundle" / "objects").rglob("*") if p.is_file())
    import hashlib
    on_disk = json.loads((tmp / "bundle" / "bundle.json").read_text(encoding="utf-8")) == wb
    cpu = realityloom.plan(m1, ["cpu"], tools={k: None for k in realityloom.TOOLS})
    gpu = realityloom.plan(m1, ["cpu", "rocm"], tools={k: None for k in realityloom.TOOLS})
    prop = realityloom.plan(realityloom.bundle_manifest(imgs, "hero_prop", "burst", root), ["cpu", "rocm"], tools={})
    few = realityloom.plan(realityloom.bundle_manifest(imgs[:1], "backdrop", "burst", root), ["cpu"], tools={})
    train = next(s for s in gpu["stages"] if s["id"] == "train_splat")
    plan_ok = (cpu["degraded_from"] == "splat" and cpu["effective_route"] == "photogrammetry" and cpu["runnable_today"] is False
               and cpu["blocked_by"] == ["recon.photogrammetry"] and cpu["eta_measured"] is False
               and gpu["effective_route"] == "splat" and train["requires"] == {"device": "rocm"} and train["status"] == "stub"
               and set(gpu["blocked_by"]) == {"recon.photogrammetry", "recon.splatforge", "recon.gdgs_import"}
               and prop["effective_route"] == "photogrammetry" and prop["degraded_from"] is None
               and few["problems"] and few["eta"] == "no runnable route on the available devices"
               and all(s["status"] == "stub" for p in (cpu, gpu) for s in p["stages"] if "blocked_by" in s)
               and all(s["status"] == "real" for p in (cpu, gpu) for s in p["stages"] if "blocked_by" not in s))
    ok = (routes["backdrop"]["route"] == "splat" and routes["hero_prop"]["route"] == "photogrammetry"
          and routes["hero_prop"]["alternatives"] == ["meshweaver"] and unknown
          and m1["capture_set_sha256"] == m2["capture_set_sha256"] and same and m1["usable_views"] == 4
          and on_disk and stored == sorted(set(hashlib.sha256(b).hexdigest() for b in imgs) | {"bundle.json"} - {"bundle.json"}) and plan_ok)
    return {"ok": ok, "routes": {k: v["route"] for k, v in routes.items()}, "bundle_deterministic": same,
            "set_hash_order_independent": m1["capture_set_sha256"] == m2["capture_set_sha256"], "objects_stored": len(stored),
            "plan_cpu_only": {k: cpu[k] for k in ("effective_route", "degraded_from", "runnable_today", "blocked_by", "eta")},
            "plan_with_rocm": {k: gpu[k] for k in ("effective_route", "blocked_by", "eta")}, "plan_too_few_views": few["problems"],
            "plan_ok": plan_ok}


def _recon_ply() -> dict[str, Any]:
    good = realityloom.check_splat_ply(realityloom.make_test_ply(7, 45))
    good0 = realityloom.check_splat_ply(realityloom.make_test_ply(3, 0))
    data = realityloom.make_test_ply(4, 9)
    bad = {}
    for name, blob in (("not_ply", b"hello"), ("ascii_format", data.replace(b"binary_little_endian", b"ascii")),
                       ("truncated_body", data[:-4]), ("double_prop", data.replace(b"property float opacity", b"property double opacity")),
                       ("missing_scale", data.replace(b"scale_1", b"scale_x")), ("odd_sh", realityloom.make_test_ply(2, 5)),
                       ("no_vertices", data.replace(b"element vertex 4", b"element vertex 0"))):
        try:
            realityloom.check_splat_ply(blob)
            bad[name] = False
        except ValueError:
            bad[name] = True
    return {"ok": good["vertices"] == 7 and good["sh_degree"] == 3 and good0["sh_degree"] == 0 and all(bad.values()),
            "valid": [good, good0], "rejects": bad,
            "note": "validator only; the fixture is a header + zeros, not reconstruction output"}


def _recon_cluster(root: Path, tmp: Path) -> dict[str, Any]:
    from forge import loomcluster as lc

    imgs = [_png("sharp", 640, 480, s) for s in range(1, 5)]
    m = realityloom.bundle_manifest(imgs, "backdrop", "burst", root)
    mh = realityloom.bundle_manifest(imgs, "hero_prop", "burst", root)
    with lc.Fleet(tmp / "fleet") as fl:
        fl.add("a", 1, "cpu")
        fl.add("b", 1, "cpu")
        fl.wait_mesh(20)
        no_gpu = realityloom.check_placement(fl.urls["a"], "rocm")
        try:
            realityloom.submit(m, fl.urls["a"])
            r1 = "returned"
        except RuntimeError as e:
            r1 = "refused:no_gpu_node" if "No cluster node advertises rocm" in str(e) else f"wrong:{e}"
        fl.add("g", 1, "cpu,rocm")
        fl.wait_mesh(20)
        gpu = realityloom.check_placement(fl.urls["a"], "rocm")
        try:
            realityloom.submit(m, fl.urls["a"])
            r2 = "returned"
        except StubError as e:
            r2 = "refused:stub" if is_stub_message(str(e)) and e.feature == "recon.splatforge" else f"wrong:{e}"
        try:
            realityloom.submit(mh, fl.urls["a"])
            r3 = "returned"
        except StubError as e:
            r3 = "refused:stub" if e.feature == "recon.splatforge" else f"wrong:{e}"
        sts = {n: lc._http(u + "/status") for n, u in fl.urls.items()}
        queued = sum(s["outstanding"] + s["results"] + s["queue"] + s["running"] for s in sts.values())
    ok = (not no_gpu["ok"] and r1 == "refused:no_gpu_node" and gpu["ok"] and gpu["capable"] == ["g"]
          and r2 == "refused:stub" and r3 == "refused:stub" and queued == 0)
    return {"ok": ok, "cpu_only_fleet": {"capable": no_gpu["capable"], "submit": r1},
            "fleet_with_rocm_node": {"capable": gpu["capable"], "splat_submit": r2, "photogrammetry_submit": r3},
            "jobs_queued_anywhere": queued, "note": "placement check is real (C7 adverts); the trainer behind it is the C12 stub, so nothing is queued"}


def _meshweaver(root: Path, tmp: Path) -> dict[str, Any]:
    """Synthetic splats on a sphere (r = 0.5, σ = 0.03): the mesh must sit on the shell, colours must follow the splats,
    and the CLI must write the same OBJ bytes as the API (deterministic)."""
    import numpy as np

    from forge import splats
    ply = tmp / "sphere.ply"
    ply.write_bytes(splats.sphere_splats(2000))
    m = splats.mesh_from_splats(ply.read_bytes())
    r = np.linalg.norm(m["vertices"], axis=1)
    col_err = float(np.abs(m["colors"] - (0.5 + 0.5 * m["vertices"] / r[:, None])).mean())
    e = np.sort(np.concatenate([m["triangles"][:, [0, 1]], m["triangles"][:, [1, 2]], m["triangles"][:, [2, 0]]]), 1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    p = subprocess.run([sys.executable, "-m", "forge.cli", "recon", "mesh", str(ply), "--out", str(tmp / "cli.obj")],
                       cwd=root, capture_output=True, text=True, timeout=120)
    same = (tmp / "cli.obj").exists() and (tmp / "cli.obj").read_bytes() == splats.write_obj(m)
    ok = (abs(float(np.median(r)) - 0.5) < m["voxel"] and float(np.abs(r - 0.5).max()) < 3 * 0.03 + 2 * m["voxel"]
          and col_err < 0.05 and len(m["triangles"]) > 1000 and float((cnt == 2).mean()) > 0.98 and p.returncode == 0 and same)
    return {"ok": ok, "vertices": len(m["vertices"]), "triangles": len(m["triangles"]), "voxel": round(m["voxel"], 5),
            "median_radius": round(float(np.median(r)), 5), "max_radius_err": round(float(np.abs(r - 0.5).max()), 5),
            "color_mae": round(col_err, 5), "manifold_edge_fraction": round(float((cnt == 2).mean()), 5), "cli_same_bytes": same}


def _gdgs(root: Path, tmp: Path) -> dict[str, Any]:
    """Splat → Godot scene, then Godot loads it: instance count + probe transforms/colours read back from the MultiMesh,
    and (under Xvfb, Mesa llvmpipe) a rendered frame shows the splats with the expected colour bias (front = +z = blue)."""
    import shutil as _sh

    from forge import splats
    ply = tmp / "sphere.ply"
    ply.write_bytes(splats.sphere_splats(2000))
    proj = tmp / "gdproj"
    p = subprocess.run([sys.executable, "-m", "forge.cli", "recon", "godot-import", str(ply), "--project", str(proj), "--verify"],
                       cwd=root, capture_output=True, text=True, timeout=240)
    try:
        doc = json.loads(p.stdout)
    except ValueError:
        return {"ok": False, "exit": p.returncode, "stderr": p.stderr[-800:]}
    g = doc.get("godot", {})
    probes_ok = g.get("count") == doc.get("imported") == 2000 and all(
        all(abs(a - b) < 1e-4 for a, b in zip(gp["pos"], ep["pos"])) and all(abs(a - b) < 4e-3 for a, b in zip(gp["rgba"], ep["rgba"]))
        for gp, ep in zip(g.get("probes", []), doc.get("probe", [])))
    rend = g.get("render")
    has_display = _sh.which("xvfb-run") is not None
    render_ok = (rend is not None and rend["lit"] > 1000 and rend["mean_rgb"][2] > rend["mean_rgb"][0]) if has_display else True
    data_ok = probes_ok if has_display else g.get("count") == 2000      # headless Godot cannot read MultiMesh data back
    return {"ok": bool(g.get("ok") and g.get("loaded") and data_ok and render_ok and g.get("renderer") == "gl_compatibility"),
            "imported": doc.get("imported"), "godot_count": g.get("count"), "probes_match": probes_ok, "render": rend,
            "display": g.get("display"), "xvfb": has_display}


def c12_run(root: Path) -> tuple[int, dict[str, Any]]:
    full = full_possible(root)
    tmp = Path(tempfile.mkdtemp(prefix="fabric-c12-"))
    try:
        r: dict[str, Any] = {"mode": "full" if full else "fast"}
        r["register"] = _stubs_refuse("C12", root)
        r["core"] = _recon_core(root, tmp)
        r["splat_ply"] = _recon_ply()
        r["cluster"] = _recon_cluster(root, tmp)
        r["cli_stubs"] = _cli_stubs(root, [["recon", "train", "--stage", s] for s in ("splat", "photogrammetry")])
        r["meshweaver"] = _meshweaver(root, tmp)
        r["gdgs"] = _gdgs(root, tmp)
        ladder = gw.load_ladder(root)["ops"]
        r["groundweave"] = _ladder(root, ["recon.plan", "recon.mesh", "shuttle.gdgs"], [])
        sp = gw.select("recon.splat", ["cpu"], root)
        r["groundweave"]["recon_splat"] = {"gpu_required": ladder["recon.splat"].get("gpu_required"), "route": sp.get("route"),
                                           "rungs_real": [x["id"] for x in ladder["recon.splat"]["ladder"] if x["impl"] == "real"]}
        r["groundweave"]["ok"] = bool(r["groundweave"]["ok"] and ladder["recon.splat"].get("gpu_required") and sp.get("route") == "loomcluster"
                                      and not r["groundweave"]["recon_splat"]["rungs_real"])
        r["cpu_2core"] = _verify(root, "recon.plan", "recon.mesh", "shuttle.gdgs")
        if full:
            b = gradle_build(root)
            r["build"] = {"ok": b["ok"], "junit_tests": b["junit"]["tests"], "junit_failures": b["junit"]["failures"],
                          **({"log_tail": b.get("log_tail", "")[-1500:]} if not b["ok"] else {})}
            if b["ok"]:
                r["kotlin_parity"] = _kotlin_suite(b)
        return 0, r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------------- hooks

KEYS = {
    "C9": ["register", "contract", "loomlink", "video", "ws_transport", "desktop_capture", "studio", "cli", "groundweave", "cpu_2core"],
    "C10": ["register", "quality", "sets", "telemetry", "offload", "video", "arcore", "groundweave", "cpu_2core"],
    "C11": ["register", "distance", "align", "dense", "arcore", "offload", "cli", "model_licences", "girt_onnx", "groundweave", "cpu_2core"],
    "C12": ["register", "core", "splat_ply", "cluster", "cli_stubs", "meshweaver", "gdgs", "groundweave", "cpu_2core"],
}
FULL_KEYS = {"C9": ["kotlin_interop", "apk"], "C10": ["kotlin_parity", "kotlin_video", "apk"], "C11": ["kotlin_parity", "kotlin_depth"], "C12": ["kotlin_parity"]}


def check(ms: str):  # noqa: ANN201
    def chk(r: dict[str, Any]) -> list[str]:
        errs = []
        for k in KEYS[ms] + (FULL_KEYS[ms] if r.get("mode") == "full" else []):
            if k not in r:
                errs.append(f"{k}: missing" + (f" ({r['build'].get('log_tail', '')[-600:]})" if r.get("build", {}).get("ok") is False else ""))
            elif not r[k].get("ok"):
                errs.append(f"{k}: {json.dumps(r[k], default=str)[:900]}")
        return errs
    return chk


def perf(ms: str):  # noqa: ANN201
    def p(r: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"mode": r.get("mode"), "real": len(r.get("register", {}).get("real", [])),
                               "stubs": len(r.get("register", {}).get("stubs", []))}
        if "cpu_2core" in r:
            out["op_wall_s_2core"] = {x["op"]: x.get("wall_s") for x in r["cpu_2core"]["results"] if x.get("wall_s") is not None}
            out["planned_ops"] = [x["op"] for x in r["cpu_2core"]["results"] if x["status"] == "planned"]
        if r.get("build", {}).get("junit_tests") is not None:
            out["fabriccore_junit_tests"] = r["build"]["junit_tests"]
        return out
    return p


def runner(ms: str):  # noqa: ANN201
    return {"C9": c9_run, "C10": c10_run, "C11": c11_run, "C12": c12_run}[ms]
