"""Shared Python ↔ Kotlin test vectors for C9–C12 (`tests/fixtures/c9_c12_vectors.json`).

Python is the reference implementation; FabricCore's JUnit tests (`C9C12Test`) must reproduce every number. A pytest
(`tests/test_c9_c12.py`) regenerates this file in memory and fails if the committed copy drifted."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from forge import depth, lensforge, mirrorvideo, mirrorweave, realityloom
from forge.paths import find_repo_root

PATH = Path("tests") / "fixtures" / "c9_c12_vectors.json"
VIDEO_DIR = Path("tests") / "fixtures" / "video"     # tiny committed VP8/VP9/H.264 streams (ffmpeg testsrc2, 32x32, 8 frames)


def make_vectors() -> dict[str, Any]:
    lens = []
    for w, h, seed in ((64, 48, 1), (64, 48, 2), (3, 3, 0), (2, 2, 4), (100, 7, 5), (31, 29, 9)):
        m = lensforge.gray_metrics(lensforge.synthetic_gray(w, h, seed))
        lens.append({"w": w, "h": h, "seed": seed, **{k: round(v, 9) for k, v in m.items()}})
    luma = [[r, g, b, (299 * r + 587 * g + 114 * b) // 1000] for r, g, b in
            ((0, 0, 0), (255, 255, 255), (255, 0, 0), (12, 200, 99), (1, 2, 3))]
    focal = []
    for kw in ({"image_width_px": 4000, "focal_length_mm": 6.9, "sensor_width_mm": 9.6},
               {"image_width_px": 4000, "focal_length_35mm": 24.0},
               {"image_width_px": 1920, "hfov_deg": 70.0},
               {"image_width_px": 640, "focal_length_mm": 4.0, "sensor_width_mm": 5.6, "focal_length_35mm": 28.0}):
        focal.append({**kw, "expected": round(depth.focal_px(**kw), 9)})
    dist = []
    for real, px, f, err in ((0.30, 120.0, 2875.0, 1.0), (1.8, 400.0, 1500.5, 2.0), (0.1, 1.0, 1000.0, 1.0)):
        d = depth.distance_to_object(real, px, f, err)
        dist.append({"real_size_m": real, "size_px": px, "focal_px": f, "err_px": err,
                     "distance_m": d["distance_m"], "lo_m": d["lo_m"], "hi_m": d["hi_m"]})
    routes = [{"target": t, "route": realityloom.route(t)["route"], "alternatives": realityloom.route(t)["alternatives"]}
              for t in realityloom.TARGETS]
    png = lensforge.synthetic_png(16, 12, 1)
    frames = [{"codec": "png", "data_b64": base64.b64encode(png).decode(), "valid": True},
              {"codec": "jpeg", "data_b64": base64.b64encode(png).decode(), "valid": False},
              {"codec": "json", "data_b64": base64.b64encode(b'{"iso": 100}').decode(), "valid": True},
              {"codec": "json", "data_b64": base64.b64encode(b"{nope").decode(), "valid": False}]
    root = find_repo_root()
    video: dict[str, Any] = {}
    for codec, name in (("vp8", "tiny_vp8.ivf"), ("vp9", "tiny_vp9.ivf"), ("h264", "tiny_h264.h264")):
        raw = (root / VIDEO_DIR / name).read_bytes()
        pkts = mirrorvideo.parse_ivf(raw)[1] if name.endswith(".ivf") else mirrorvideo.split_h264_aus(raw)
        video[codec] = [{"data_b64": base64.b64encode(p).decode(), "keyframe": mirrorvideo.is_keyframe(codec, p),
                         "sniff": mirrorvideo.sniff_video(codec, p)} for p in pkts]
    key = bytes(range(32))
    events = []
    for i, ev in enumerate(({"type": "tap", "x": 0.5, "y": 0.25}, {"type": "swipe", "x": 0.1, "y": 0.9, "x2": 0.1, "y2": 0.1,
                                                                     "duration_ms": 250},
                            {"type": "key", "key": "back"}, {"type": "text", "text": "héllo \"q\""},
                            {"type": "focus", "mode": "manual", "distance_m": 0.35, "x": 0.5, "y": 0.5})):
        ej = mirrorweave.event_json(mirrorweave.validate_android_event(ev))
        events.append({"seq": i, "event_json": ej, "sig": mirrorweave.event_mac(key, "phone-v", i, ej)})
    return {"schema": "c9_c12_vectors/2", "lens_gray": lens, "luma": luma, "focal_px": focal, "distance": dist,
            "route": routes, "frames": frames, "max_frame_bytes": mirrorweave.MAX_FRAME_BYTES, "video": video,
            "input": {"key_hex": key.hex(), "client": "phone-v", "events": events}}


def write(root: Path | None = None) -> Path:
    p = (root or find_repo_root()) / PATH
    p.write_text(json.dumps(make_vectors(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


if __name__ == "__main__":
    print(write())
