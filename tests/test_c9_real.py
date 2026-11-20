"""C9 MirrorWeave real paths (2026-11-20): CPU video, signed WebSocket transport, desktop capture, phone input outbox, Studio."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from forge import mirrorvideo as mv
from forge import mirrorweave as mw

ROOT = Path(__file__).resolve().parents[1]
needs_vpx = pytest.mark.skipif(not mv.available()["vp8"], reason="system ffmpeg with libvpx required")


def frames(n: int = 20, w: int = 160, h: int = 120) -> list[np.ndarray]:
    y, x = np.mgrid[0:h, 0:w]
    out = []
    for i in range(n):
        f = np.stack([(x * 1.5 + i * 3) % 256, (y * 2) % 256, ((x + y) // 2 + i * 5) % 256], -1).astype(np.uint8)
        f[30:60, 20 + i * 3:50 + i * 3] = [255, 40, 40]
        out.append(f)
    return out


def test_bitstream_keyframes_on_committed_fixtures() -> None:
    v = json.loads((ROOT / "tests/fixtures/c9_c12_vectors.json").read_text())["video"]
    for codec, rows in v.items():
        assert [r["keyframe"] for r in rows] == [True, False, False, False, True, False, False, False], codec


@needs_vpx
@pytest.mark.parametrize("codec", ["vp8", "vp9"])
def test_cpu_encode_decode_round_trip_quality(codec: str) -> None:
    fr = frames()
    enc = mv.CpuVideoEncoder(160, 120, codec, gop=10)
    pk = enc.encode(fr)
    assert len(pk) == len(fr) and [mv.is_keyframe(codec, p) for p in pk][::10] == [True, True]
    dec = mv.decode_packets(codec, pk, 160, 120)
    assert len(dec) == len(fr) and min(mv.psnr(a, b) for a, b in zip(fr, dec)) >= 28.0
    assert list(enc.stream(iter(fr))) == pk          # streaming == batch (same build, fixed threads)


@needs_vpx
def test_video_track_resyncs_on_keyframe_after_gap(tmp_path: Path) -> None:
    fr = frames(20)
    pk = mv.CpuVideoEncoder(160, 120, "vp8", gop=10).encode(fr)
    hub = mw.FrameHub(tmp_path)
    acks = []
    for i, p in enumerate(pk):
        if i in (3, 4):                     # lose two packets → undecodable until the next keyframe (index 10)
            continue
        acks.append(hub.accept(mw.FrameEnvelope("v", i, i, "screen_video", "vp8", 160, 120, p, mv.is_keyframe("vp8", p))))
    st = hub.video("v").stats()
    assert st["skipped"] == 5 and st["keyframes"] == 2 and hub.stats()["v"]["dropped"] == 2
    assert [a["decodable"] for a in acks][:4] == [True, True, True, False]
    png = mw.decode_latest(tmp_path, "v")
    from PIL import Image
    import io
    got = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
    assert mv.psnr(got, fr[-1]) >= 28.0
    with pytest.raises(ValueError, match="keyframe flag"):
        mw.FrameEnvelope("v", 99, 0, "screen_video", "vp8", 0, 0, pk[1], True)


def test_h264_fixture_decodes_on_the_desktop(tmp_path: Path) -> None:
    if not mv.available()["ffmpeg"]:
        pytest.skip("ffmpeg required")
    aus = mv.split_h264_aus((ROOT / "tests/fixtures/video/tiny_h264.h264").read_bytes())
    hub = mw.FrameHub(tmp_path)
    for i, p in enumerate(aus):
        hub.accept(mw.FrameEnvelope("phone", i, i, "screen_video", "h264", 32, 32, p, mv.is_keyframe("h264", p)))
    assert len(mv.decode_packets("h264", [(tmp_path / "phone" / "session.h264").read_bytes()])) == 8
    assert mw.decode_latest(tmp_path, "phone")[:8] == mv.PNG_SIG


@needs_vpx
def test_websocket_transport_is_signed_and_capability_checked(tmp_path: Path) -> None:
    pytest.importorskip("websockets")
    from forge.accept_companions import Desktop
    from forge.loomlink import LinkClient
    from forge.mirrorws import MirrorWsClient, MirrorWsServer, pack

    d = Desktop(tmp_path / "d", allow=("mirror", "offload")).start()
    ws = MirrorWsServer(d.srv).start()
    try:
        c = LinkClient(d.srv.url, "phone-a")
        c.pair(d.srv.code, ["mirror"])
        fr = frames(12)
        with MirrorWsClient(ws.url, c) as cl:
            acks = [cl.send(e) for e in mw.VideoStreamSource("vid", "vp8", 160, 120, rgb_frames=fr).frames()]
            assert all(a["type"] == "ack" for a in acks)
            env = mw.FrameEnvelope("vid", 12, 1, "screen_video", "vp8", 160, 120, *(lambda p: (p, mv.is_keyframe("vp8", p)))(
                mv.CpuVideoEncoder(160, 120, "vp8").encode(fr[:1])[0]))
            msg = bytearray(pack(c, env))
            msg[-1] ^= 0xFF                                    # tamper with the payload → signature fails
            assert cl.send_raw(bytes(msg))["status"] == 403
            replay = pack(c, env)
            assert cl.send_raw(replay)["type"] == "ack"
            assert cl.send_raw(replay)["status"] == 403        # same timestamp again → replay refused
        weak = LinkClient(d.srv.url, "weak")
        weak.pair(d.srv.code, ["offload"])
        with pytest.raises(PermissionError):
            with MirrorWsClient(ws.url, weak):
                pass
        assert ws.accepted == 13 and ws.refused >= 3
        dec = mv.decode_packets("vp8", mv.parse_ivf((d.srv.state_dir / "mirror" / "vid" / "session.ivf").read_bytes())[1])
        assert min(mv.psnr(a, b) for a, b in zip(fr, dec)) >= 28.0
    finally:
        ws.stop()
        d.halt()


def test_input_outbox_signs_per_event_and_client_verifies(tmp_path: Path) -> None:
    from forge.accept_companions import Desktop
    from forge.loomlink import LinkClient

    d = Desktop(tmp_path / "d", allow=("mirror",)).start()
    try:
        c = LinkClient(d.srv.url, "phone-a")
        c.pair(d.srv.code, ["mirror"])
        ctl = mw.AndroidController(d.srv.state_dir, "phone-a")
        ctl.send(mw.ControlMessage("android", "input", "swipe", {"x": 0.1, "y": 0.9, "x2": 0.1, "y2": 0.1}))
        ctl.focus("manual", 0.4, 0.5, 0.5)
        with pytest.raises(ValueError):
            ctl.send(mw.ControlMessage("android", "input", "key", {"key": "power"}))
        evs = c.mirror_input_poll()
        assert [e["event"]["type"] for e in evs] == ["swipe", "focus"] and evs[1]["event"]["distance_m"] == 0.4
        assert c.mirror_input_poll(after=evs[-1]["seq"]) == []
        raw = c._post("/mirror/input/poll", {"after": -1})["events"]     # a different key (another desktop / MITM) ≠ sig
        assert all(e["sig"] != mw.event_mac(b"\x01" * 32, "phone-a", e["seq"], e["event_json"]) for e in raw)
        assert all(e["sig"] != mw.event_mac(c.key, "phone-b", e["seq"], e["event_json"]) for e in raw)
    finally:
        d.halt()


def test_desktop_capture_from_xvfb() -> None:
    if not (shutil.which("Xvfb") and mv.available()["vp8"]):
        pytest.skip("Xvfb + ffmpeg/libvpx required")
    disp = f":{70 + os.getpid() % 20}"
    x = subprocess.Popen(["Xvfb", disp, "-screen", "0", "320x240x24", "-nolisten", "tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        st = list(mw.DesktopScreenSource("desk", disp, fps=10, n=3).frames())
        assert [e.seq for e in st] == [0, 1, 2] and (st[0].width, st[0].height) == (320, 240)
        vid = list(mw.VideoStreamSource("deskv", "vp8", 320, 240, fps=10, display=disp, n=5).frames())
        assert len(vid) == 5 and vid[0].keyframe and not vid[1].keyframe
    finally:
        x.kill()
        x.wait()


def test_studio_receives_remote_input_as_qt_events(tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    code = r'''
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
    p = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-800:]
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out == {"n": 4, "typed": "hiA", "log": "hiA", "healthy": out["healthy"]}


# ----------------------------------------------------------------------------- C10 video capture ingest (0.7.5)

@needs_vpx
def test_video_ingest_keeps_sharp_novel_frames(tmp_path: Path) -> None:
    from forge import lensforge
    from forge.accept_c9_c12 import make_test_clip
    clip = make_test_clip(tmp_path / "c.mp4").read_bytes()
    out = lensforge.VideoCapture().ingest(clip)
    ts = [k["t_s"] for k in out["keyframes"]]
    assert out["sampled_frames"] == 12 and ts == [0.0, 4.0, 5.0]      # static stretch → 1, blurred → 0, sharp pan → 1/s
    assert out["assessment"]["reasons"] == ["too_few_usable_views"]    # 640x360 < video profile's 1280 px: warned, not hidden
    with pytest.raises(ValueError):
        lensforge.VideoCapture().ingest(clip[:1500])
