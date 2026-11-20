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

It does NOT prove: live screen/video streaming, input injection, ARCore, dense depth, any reconstruction, anything on a phone
or a GPU. Those are stubs by design (SPEC §13 lists C9–C12 as milestones; their full feature set is future work).
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


def _verify(root: Path, *ops: str) -> dict[str, Any]:
    v = gw.verify(root, ops=list(ops))
    return {"ok": v["ok"] and all(x["status"] in ("ok", "planned") for x in v["results"]) and len(v["results"]) == len(ops),
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
    rejects("video_is_stub", lambda: mirrorweave.FrameEnvelope("s", 0, 0, "camera_video", "h264", 0, 0, png), StubError)
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
        studio = _http_err(lambda: c.mirror_control(mirrorweave.ControlMessage("desktop", "input", "key")))
        focus = _http_err(lambda: c.mirror_control(mirrorweave.ControlMessage("desktop", "focus", "x")))
        out["frames"] = {"pushed": [p["seq"] for p in pushed], "latest_identical": got == png2, "telemetry_ok": t["accepted"],
                         "stale_status": stale[0], "streams": sorted(latest["stats"])}
        out["control"] = {"status_query_ok": q["ok"] and q["value"]["version"] is not None, "groundweave_ok": qg["ok"],
                          "stats_ok": qs["ok"] and "screen" in qs["value"],
                          "not_allowlisted": {"status": bad_q[0], "error": bad_q[1].get("error", "")[:80]}}
        out["stubs_501"] = {k: {"status": v[0], "stub": v[1].get("stub"), "label": is_stub_message(v[1].get("error", "")),
                                "key": v[1].get("key")} for k, v in (("android_input", android), ("studio_input", studio),
                                                                      ("camera_focus", focus))}
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
            and bad_q[0] == 403 and all(v["status"] == 501 and v["stub"] and v["label"] for v in out["stubs_501"].values())
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
        rc3, inp = jar(root, "mirror-query", "--action", "input", "--name", "tap", home=home)
        env = d.srv.mirror.latest("kscreen")
        rc4, stubs = jar(root, "stubs")
    finally:
        d.halt()
    refused = all(v.get("refused") and str(v.get("message", "")).startswith("[STUB ") for v in stubs.values()) if rc4 == 0 else False
    suites = _suites_ok(b, "C9C12Test")
    res = {"pair_caps": pres.get("caps"), "push": push, "desktop_has_identical_bytes": env is not None and env.data == png,
           "stale_push": {"exit": rc1, "status": stale.get("status")}, "query_ok": rc2 == 0 and q.get("ok") is True,
           "studio_input_stub": {"exit": rc3, "status": inp.get("status"), "label": str(inp.get("error", ""))[:40]},
           "kotlin_stubs": {"count": len(stubs), "all_refuse": refused}, "suites": suites}
    res["ok"] = bool(pc == 0 and rc0 == 0 and push.get("accepted") and res["desktop_has_identical_bytes"] and rc1 == 3
                     and stale.get("status") == 400 and res["query_ok"] and rc3 == 3 and inp.get("status") == 501
                     and "[STUB" in str(inp.get("error", "")) and refused and suites["ok"])
    return res


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
        r["cli_stubs"] = _cli_stubs(root, [["mirror", "stream", "--source", "screen"], ["mirror", "stream", "--source", "camera-video"],
                                           ["mirror", "control", "--target", "android"]])
        r["groundweave"] = _ladder(root, ["mirror.encode"], [])
        r["cpu_2core"] = _verify(root, "mirror.encode")
        if full:
            b = gradle_build(root)
            r["build"] = {"ok": b["ok"], "junit_tests": b["junit"]["tests"], "junit_failures": b["junit"]["failures"],
                          **({"log_tail": b.get("log_tail", "")[-1500:]} if not b["ok"] else {})}
            if b["ok"]:
                r["kotlin_interop"] = _kotlin_mirror(root, tmp, b)
        return 0, r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
    for m in ("video", "depth_assist"):
        try:
            lensforge.assess_set(imgs, m, root)
            stub_modes[m] = "returned"
        except StubError as e:
            stub_modes[m] = "refused" if is_stub_message(str(e)) else "unlabelled"
    ok = (ok_set["verdict"] == "pass" and ok_set["usable_views"] == 3 and ok_set["overlap"] == "not_measured"
          and short["reasons"] == ["too_few_usable_views"] and len(dup["duplicates"]) == 1 and dup["usable_views"] == 3
          and mixed["usable_views"] == 3 and mixed["per_view"][-1]["verdict"] == "unreadable"
          and set(stub_modes.values()) == {"refused"})
    return {"ok": ok, "burst_ok": ok_set["verdict"], "too_few": short["reasons"], "duplicates": dup["duplicates"],
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
        r["cli_stubs"] = _cli_stubs(root, [["lens", "session", "--kind", "arcore"], ["lens", "session", "--kind", "video"],
                                           ["lens", "session", "--kind", "focus"]])
        r["groundweave"] = _ladder(root, ["lens.assess"], [])
        r["cpu_2core"] = _verify(root, "lens.assess")
        if full:
            b = gradle_build(root)
            r["build"] = {"ok": b["ok"], "junit_tests": b["junit"]["tests"], "junit_failures": b["junit"]["failures"],
                          **({"log_tail": b.get("log_tail", "")[-1500:]} if not b["ok"] else {})}
            if b["ok"]:
                r["kotlin_parity"] = _kotlin_suite(b)
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
            "note": "scales a relative map from ≥2 metric anchors; producing the relative map is the DepthAnything V2 stub"}


def c11_run(root: Path) -> tuple[int, dict[str, Any]]:
    full = full_possible(root)
    r: dict[str, Any] = {"mode": "full" if full else "fast"}
    r["register"] = _stubs_refuse("C11", root)
    r["distance"] = _depth_real()
    r["align"] = _depth_align()
    try:
        depth.DepthAnythingV2().estimate(_png("sharp", 16, 16))
        dense = {"ok": False, "error": "returned a map"}
    except StubError as e:
        dense = {"ok": is_stub_message(str(e)) and e.key == "stub.depth.model_missing", "message": str(e)[:120]}
    r["dense_refuses"] = dense
    r["cli_stubs"] = _cli_stubs(root, [["depth", "estimate", "tests/fixtures/capture_640x480.jpg"],
                                       ["depth", "estimate", "tests/fixtures/capture_640x480.jpg", "--backend", "arcore"]])
    r["groundweave"] = _ladder(root, ["depth.distance"], ["depth.estimate"])
    r["cpu_2core"] = _verify(root, "depth.distance", "depth.estimate")
    if full:
        b = gradle_build(root)
        r["build"] = {"ok": b["ok"], "junit_tests": b["junit"]["tests"], "junit_failures": b["junit"]["failures"],
                      **({"log_tail": b.get("log_tail", "")[-1500:]} if not b["ok"] else {})}
        if b["ok"]:
            r["kotlin_parity"] = _kotlin_suite(b)
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


def c12_run(root: Path) -> tuple[int, dict[str, Any]]:
    full = full_possible(root)
    tmp = Path(tempfile.mkdtemp(prefix="fabric-c12-"))
    try:
        r: dict[str, Any] = {"mode": "full" if full else "fast"}
        r["register"] = _stubs_refuse("C12", root)
        r["core"] = _recon_core(root, tmp)
        r["splat_ply"] = _recon_ply()
        r["cluster"] = _recon_cluster(root, tmp)
        r["cli_stubs"] = _cli_stubs(root, [["recon", "train", "--stage", s] for s in ("splat", "photogrammetry", "mesh", "godot-import")])
        ladder = gw.load_ladder(root)["ops"]
        r["groundweave"] = _ladder(root, ["recon.plan"], ["recon.mesh", "shuttle.gdgs"])
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
    "C9": ["register", "contract", "loomlink", "cli_stubs", "groundweave", "cpu_2core"],
    "C10": ["register", "quality", "sets", "telemetry", "offload", "cli_stubs", "groundweave", "cpu_2core"],
    "C11": ["register", "distance", "align", "dense_refuses", "cli_stubs", "groundweave", "cpu_2core"],
    "C12": ["register", "core", "splat_ply", "cluster", "cli_stubs", "groundweave", "cpu_2core"],
}
FULL_KEYS = {"C9": ["kotlin_interop"], "C10": ["kotlin_parity"], "C11": ["kotlin_parity"], "C12": ["kotlin_parity"]}


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
