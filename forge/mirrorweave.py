"""MirrorWeave (C9) — cross-device control + stream, SPEC §9 / §8.

SPEC: "Android screen stream → desktop; desktop remote control of Android; Android remote control of desktop; camera
video/stills/focus/telemetry streaming." Capabilities `mirror` and `drive_studio` were reserved in LoomLink (C5).

What is REAL here (desktop side runs and is tested on this box; Android side is compiled Kotlin, see the register):
  * `FrameEnvelope` — typed, validated wire contract for one frame: stills (png/jpeg/webp), telemetry (json) and **video
    packets** (vp8/vp9 from the desktop CPU encoder, h264 from a phone's MediaCodec). Keyframes are checked from the bitstream.
  * `FrameHub` — desktop sink: per-stream ring buffer, monotonic seq, drop accounting, persisted latest still; video streams go to
    a `VideoTrack` (decoder resync on keyframes after a gap, current GOP persisted and decodable with `decode_latest`).
  * LoomLink routes (forge/loomlink.py): `/mirror/frame`, `/mirror/latest`, `/mirror/control`, `/mirror/input/poll`, `/mirror/info`,
    and the signed WebSocket transport in forge/mirrorws.py.
  * `StillsSource`, `DesktopScreenSource` (X11 capture via system ffmpeg, stills), `VideoStreamSource` (CPU VP8/VP9 video).
  * `AndroidController` — desktop → phone input/focus events, queued in an outbox the phone polls; each event is HMAC-signed with
    the pairing session key at delivery, so the phone injects only what its own desktop queued (Kotlin `InputEvent.verify`).
  * Studio input — phone → desktop key/pointer/scroll events (`drive_studio` capability) validated against an allow-list and
    spooled for the Studio window (studio/assetfabric_studio), which turns them into Qt events.

What is NOT verified here: anything on a phone (MediaProjection, AccessibilityService gestures, Camera2 focus, MediaCodec) —
register state `real_unverified_on_device`. Windows/Wayland desktop capture is not wired (INFERENCE C-51).

Wire/behaviour choices that go beyond the spec are `[INFERENCE]` C-32…C-37 in docs/INFERENCES.md.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol

from forge.i18n import t
from forge.mirrorvideo import VIDEO_CODECS, is_keyframe, sniff_video
from forge.stubs import StubError, refuse  # noqa: F401  (StubError re-exported for callers)

MILESTONE = "C9"
MAX_FRAME_BYTES = 8 * 1024 * 1024            # [INFERENCE C-33] one still / one video packet
RING = 8
GOP_CAP = 600                                 # packets kept per video stream since its last keyframe
STREAM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
STILL_KINDS = ("screen", "camera_still", "telemetry")
VIDEO_KINDS = ("screen_video", "camera_video")
STREAM_KINDS = STILL_KINDS + VIDEO_KINDS
STILL_CODECS = {"png": "png", "jpeg": "jpg", "webp": "webp", "json": "json"}
VIDEO_EXT = {"vp8": "ivf", "vp9": "ivf", "h264": "h264"}
UNSUPPORTED_CODECS = ("av1",)                 # [INFERENCE C-52] no AV1 path: libaom/SVT encode too slow on 2 cores
# phone → desktop read-only queries the `drive_studio` capability may run (no state change, no host command execution)
ALLOWED_QUERIES = ("forge.status", "groundweave.show", "mirror.stats")


def sniff(codec: str, data: bytes) -> bool:
    if codec == "png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if codec == "jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if codec == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if codec in VIDEO_CODECS:
        return sniff_video(codec, data)
    if codec == "json":
        try:
            json.loads(data.decode("utf-8"))
            return True
        except (UnicodeDecodeError, ValueError):
            return False
    return False


@dataclass(frozen=True)
class FrameEnvelope:
    """One frame on the wire. `to_wire` ↔ `from_wire` is the contract shared with fabric.core.FrameEnvelope (Kotlin)."""

    stream: str
    seq: int
    ts_ms: int
    kind: str
    codec: str
    width: int
    height: int
    data: bytes = field(repr=False, default=b"")
    keyframe: bool = False

    def __post_init__(self) -> None:
        if not STREAM_RE.match(self.stream):
            raise ValueError("bad stream id (a-z 0-9 _ -, ≤32)")
        if self.codec in UNSUPPORTED_CODECS:
            raise ValueError(t("mirror.video.unsupported_codec", codec=self.codec))
        if self.kind not in STREAM_KINDS:
            raise ValueError(f"unknown frame kind {self.kind!r}")
        if self.codec not in STILL_CODECS and self.codec not in VIDEO_CODECS:
            raise ValueError(f"unknown codec {self.codec!r}")
        if (self.kind in VIDEO_KINDS) != (self.codec in VIDEO_CODECS):
            raise ValueError("video kinds need a video codec (vp8/vp9/h264) and video codecs need a video kind")
        if self.codec in VIDEO_CODECS and bool(self.keyframe) != is_keyframe(self.codec, self.data):
            raise ValueError("keyframe flag does not match the bitstream")
        if (self.kind == "telemetry") != (self.codec == "json"):
            raise ValueError("telemetry frames must be json and json frames must be telemetry")
        if self.seq < 0 or self.ts_ms < 0 or self.width < 0 or self.height < 0:
            raise ValueError("negative field")
        if not self.data or len(self.data) > MAX_FRAME_BYTES:
            raise ValueError(f"frame must be 1..{MAX_FRAME_BYTES} bytes")
        if not sniff(self.codec, self.data):
            raise ValueError(f"payload is not valid {self.codec}")

    @property
    def is_video(self) -> bool:
        return self.kind in VIDEO_KINDS

    def to_wire(self) -> dict[str, Any]:
        w = {"stream": self.stream, "seq": self.seq, "ts_ms": self.ts_ms, "kind": self.kind, "codec": self.codec,
             "width": self.width, "height": self.height, "data_b64": base64.b64encode(self.data).decode()}
        if self.is_video:
            w["keyframe"] = bool(self.keyframe)
        return w

    @classmethod
    def from_wire(cls, w: dict[str, Any]) -> "FrameEnvelope":
        try:
            raw = base64.b64decode(w["data_b64"], validate=True)
            return cls(str(w["stream"]), int(w["seq"]), int(w["ts_ms"]), str(w["kind"]), str(w["codec"]),
                       int(w.get("width", 0)), int(w.get("height", 0)), raw, bool(w.get("keyframe", False)))
        except KeyError as e:
            raise ValueError(f"missing field {e}") from None


class FrameHub:
    """Desktop-side sink. Frames per stream must arrive with strictly increasing `seq` (a replay/stale frame is refused);
    gaps are counted as drops (a slow link may skip frames — latest wins). The newest frame is persisted so a viewer
    (`forge mirror latest`, Studio) works across restarts."""

    def __init__(self, root: Path, ring: int = RING) -> None:
        self.root, self.ring = Path(root), ring
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._frames: dict[str, deque[FrameEnvelope]] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        self._video: dict[str, VideoTrack] = {}

    def accept(self, env: FrameEnvelope) -> dict[str, Any]:
        with self.lock:
            st = self._stats.setdefault(env.stream, {"frames": 0, "bytes": 0, "dropped": 0, "last_seq": -1,
                                                     "first_ts_ms": env.ts_ms, "last_ts_ms": env.ts_ms})
            if env.seq <= st["last_seq"]:
                raise ValueError(f"stale frame: seq {env.seq} ≤ last {st['last_seq']}")
            gap = st["last_seq"] >= 0 and env.seq != st["last_seq"] + 1
            if st["last_seq"] >= 0:
                st["dropped"] += env.seq - st["last_seq"] - 1
            st.update(last_seq=env.seq, last_ts_ms=env.ts_ms)
            st["frames"] += 1
            st["bytes"] += len(env.data)
            self._frames.setdefault(env.stream, deque(maxlen=self.ring)).append(env)
            if env.is_video:
                tr = self._video.get(env.stream)
                if tr is None:
                    tr = self._video[env.stream] = VideoTrack(self.root / env.stream, env.codec)
                used = tr.add(env, gap)
                st["video"] = tr.stats()
                return {"accepted": True, "seq": env.seq, "dropped_total": st["dropped"], "decodable": used}
            self._persist(env)
            return {"accepted": True, "seq": env.seq, "dropped_total": st["dropped"]}

    def video(self, stream: str) -> "VideoTrack | None":
        with self.lock:
            return self._video.get(stream)

    def latest(self, stream: str) -> FrameEnvelope | None:
        with self.lock:
            q = self._frames.get(stream)
            return q[-1] if q else None

    def streams(self) -> list[str]:
        with self.lock:
            return sorted(self._stats)

    def stats(self) -> dict[str, Any]:
        with self.lock:
            out = {}
            for s, st in self._stats.items():
                span = max(1, st["last_ts_ms"] - st["first_ts_ms"])
                out[s] = {**st, "fps": round((st["frames"] - 1) * 1000 / span, 3) if st["frames"] > 1 else 0.0,
                          "buffered": len(self._frames.get(s, ()))}
            return out

    def _persist(self, env: FrameEnvelope) -> None:
        d = self.root / env.stream
        d.mkdir(parents=True, exist_ok=True)
        ext = STILL_CODECS[env.codec]
        for old in d.glob("latest.*"):
            if old.suffix != f".{ext}" and old.name != "latest.json":
                old.unlink(missing_ok=True)
        tmp = d / f"latest.{ext}.tmp"
        tmp.write_bytes(env.data)
        os.replace(tmp, d / f"latest.{ext}")
        meta = {k: v for k, v in env.to_wire().items() if k != "data_b64"}
        (d / "latest.meta.json").write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")


def load_persisted(root: Path, stream: str) -> tuple[dict[str, Any], bytes] | None:
    d = Path(root) / stream
    meta = d / "latest.meta.json"
    if not meta.exists():
        return None
    m = json.loads(meta.read_text(encoding="utf-8"))
    return m, (d / f"latest.{STILL_CODECS[m['codec']]}").read_bytes()


class VideoTrack:
    """Desktop-side video sink for one stream. Packets before the first keyframe, or after a seq gap until the next keyframe,
    cannot be decoded and are counted as `skipped` (not stored). The current GOP is persisted as `gop.ivf` / `gop.h264` so a
    viewer can decode the newest picture; the whole session is appended to `session.<ext>` [INFERENCE C-53]."""

    def __init__(self, d: Path, codec: str) -> None:
        self.d, self.codec = Path(d), codec
        self.d.mkdir(parents=True, exist_ok=True)
        self.gop: list[bytes] = []
        self.need_key = True
        self.packets = self.keyframes = self.skipped = 0
        self.width = self.height = 0
        (self.d / f"session.{VIDEO_EXT[codec]}").unlink(missing_ok=True)

    def add(self, env: FrameEnvelope, gap: bool) -> bool:
        if env.codec != self.codec:
            raise ValueError(f"stream {env.stream!r} is {self.codec}; got {env.codec}")
        if gap:
            self.need_key = True
        if env.keyframe:
            self.need_key, self.gop = False, []
            self.keyframes += 1
            self.width, self.height = env.width or self.width, env.height or self.height
        if self.need_key:
            self.skipped += 1
            return False
        self.gop = (self.gop + [env.data])[-GOP_CAP:]
        self.packets += 1
        self._persist(env)
        return True

    def _persist(self, env: FrameEnvelope) -> None:
        from forge import mirrorvideo as mv

        ext = VIDEO_EXT[self.codec]
        if ext == "ivf":
            blob = mv.ivf_header(self.codec, self.width or 16, self.height or 16, 30, len(self.gop)) + b"".join(
                mv.ivf_frame(p, i) for i, p in enumerate(self.gop))
            sess = self.d / "session.ivf"
            with open(sess, "ab") as f:
                if f.tell() == 0:
                    f.write(mv.ivf_header(self.codec, self.width or 16, self.height or 16, 30, 0))
                f.write(mv.ivf_frame(env.data, self.packets - 1))
        else:
            blob = b"".join(self.gop)
            with open(self.d / "session.h264", "ab") as f:
                f.write(env.data)
        tmp = self.d / f"gop.{ext}.tmp"
        tmp.write_bytes(blob)
        os.replace(tmp, self.d / f"gop.{ext}")
        meta = {k: v for k, v in env.to_wire().items() if k != "data_b64"}
        (self.d / "latest.meta.json").write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")

    def stats(self) -> dict[str, Any]:
        return {"codec": self.codec, "packets": self.packets, "keyframes": self.keyframes, "skipped": self.skipped,
                "gop_len": len(self.gop), "awaiting_keyframe": self.need_key}


def decode_latest(root: Path, stream: str) -> bytes | None:
    """Decode the newest picture of a persisted video stream to PNG (desktop viewer / `forge mirror latest`)."""
    import io

    from PIL import Image

    from forge import mirrorvideo as mv

    d = Path(root) / stream
    meta_p = d / "latest.meta.json"
    if not meta_p.exists():
        return None
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    codec = meta["codec"]
    if codec not in VIDEO_CODECS:
        return None
    blob = (d / f"gop.{VIDEO_EXT[codec]}").read_bytes()
    pkts = mv.parse_ivf(blob)[1] if VIDEO_EXT[codec] == "ivf" else [blob]
    frames = mv.decode_packets(codec, pkts)
    if not frames:
        return None
    buf = io.BytesIO()
    Image.fromarray(frames[-1]).save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------- input (desktop ⇄ phone)

ANDROID_KEYS = ("back", "home", "recents", "notifications", "quick_settings")
ANDROID_INPUT = ("tap", "long_press", "swipe", "key", "text", "focus")
FOCUS_MODES = ("auto", "manual", "lock", "unlock")
STUDIO_KEYS = tuple("abcdefghijklmnopqrstuvwxyz0123456789") + (
    "space", "enter", "backspace", "tab", "escape", "left", "right", "up", "down", "slash", "minus", "period", "comma")
STUDIO_POINTER = ("move", "down", "up", "click")
MAX_TEXT = 256
OUTBOX_CAP = 256


def _unit(v: Any, name: str) -> float:
    f = float(v)
    if not 0.0 <= f <= 1.0:
        raise ValueError(f"{name} must be in [0,1] (normalised screen coordinates)")
    return round(f, 5)


def validate_android_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Canonical, range-checked desktop → phone event. Shared contract with Kotlin `fabric.core.InputEvent`."""
    typ = ev.get("type")
    if typ not in ANDROID_INPUT:
        raise ValueError(f"type must be one of {ANDROID_INPUT}")
    out: dict[str, Any] = {"type": typ}
    if typ in ("tap", "long_press"):
        out.update(x=_unit(ev["x"], "x"), y=_unit(ev["y"], "y"))
        if typ == "long_press":
            out["duration_ms"] = int(ev.get("duration_ms", 600))
    elif typ == "swipe":
        out.update(x=_unit(ev["x"], "x"), y=_unit(ev["y"], "y"), x2=_unit(ev["x2"], "x2"), y2=_unit(ev["y2"], "y2"),
                   duration_ms=int(ev.get("duration_ms", 300)))
    elif typ == "key":
        if ev.get("key") not in ANDROID_KEYS:
            raise ValueError(f"key must be one of {ANDROID_KEYS}")
        out["key"] = ev["key"]
    elif typ == "text":
        txt = str(ev.get("text", ""))
        if not txt or len(txt) > MAX_TEXT:
            raise ValueError(f"text must be 1..{MAX_TEXT} chars")
        out["text"] = txt
    elif typ == "focus":
        mode = ev.get("mode", "auto")
        if mode not in FOCUS_MODES:
            raise ValueError(f"focus mode must be one of {FOCUS_MODES}")
        out["mode"] = mode
        if mode == "manual":
            dist = float(ev["distance_m"])
            if not 0.05 <= dist <= 1000.0:
                raise ValueError("distance_m must be in [0.05, 1000]")
            out["distance_m"] = round(dist, 4)
        if "x" in ev or "y" in ev:
            out.update(x=_unit(ev["x"], "x"), y=_unit(ev["y"], "y"))
    if "duration_ms" in out and not 1 <= out["duration_ms"] <= 5000:
        raise ValueError("duration_ms must be in [1, 5000]")
    return out


def event_json(ev: dict[str, Any]) -> str:
    from forge.loomlink import canonical

    return canonical(ev)


def event_mac(key: bytes, client: str, seq: int, ev_json: str) -> str:
    """MAC over the exact JSON text the phone receives (no cross-language re-canonicalisation)."""
    from forge.loomlink import _mac

    return _mac(key, "input", client, str(seq), ev_json)


class InputOutbox:
    """Per-device queue of desktop → phone events (file-backed so `forge mirror input` and `forge link serve` can be separate
    processes). The phone fetches with `POST /mirror/input/poll {after}`; the server signs each event with that device's key."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _path(self, device: str) -> Path:
        if not re.match(r"^[A-Za-z0-9._-]{1,64}$", device):
            raise ValueError("bad device id")
        return self.root / f"{device}.jsonl"

    def push(self, device: str, ev: dict[str, Any]) -> int:
        ev = validate_android_event(ev)
        with self.lock:
            rows = self.read(device)
            seq = (rows[-1]["seq"] + 1) if rows else 0
            rows = (rows + [{"seq": seq, "event": ev, "queued_ms": int(time.time() * 1000)}])[-OUTBOX_CAP:]
            tmp = self._path(device).with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
            os.replace(tmp, self._path(device))
            return seq

    def read(self, device: str, after: int = -1) -> list[dict[str, Any]]:
        p = self._path(device)
        if not p.exists():
            return []
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r["seq"] > after]

    def deliver(self, device: str, key: bytes, after: int = -1, limit: int = 32) -> list[dict[str, Any]]:
        out = []
        for r in self.read(device, after)[:limit]:
            ej = event_json(r["event"])
            out.append({"seq": r["seq"], "queued_ms": r["queued_ms"], "event_json": ej, "sig": event_mac(key, device, r["seq"], ej)})
        return out


def validate_studio_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Phone → Studio input event (allow-listed keys, normalised pointer, bounded scroll). Never a command or a path."""
    typ = ev.get("type")
    if typ == "key":
        if ev.get("key") not in STUDIO_KEYS:
            raise PermissionError(t("mirror.studio.key_not_allowed", key=str(ev.get("key"))[:16]))
        return {"type": "key", "key": ev["key"], "shift": bool(ev.get("shift", False))}
    if typ == "pointer":
        if ev.get("action") not in STUDIO_POINTER:
            raise ValueError(f"pointer action must be one of {STUDIO_POINTER}")
        btn = ev.get("button", "left")
        if btn not in ("left", "right"):
            raise ValueError("button must be left|right")
        return {"type": "pointer", "action": ev["action"], "x": _unit(ev["x"], "x"), "y": _unit(ev["y"], "y"), "button": btn}
    if typ == "scroll":
        dy = int(ev.get("dy", 0))
        if not -10 <= dy <= 10 or dy == 0:
            raise ValueError("scroll dy must be a non-zero int in [-10, 10]")
        return {"type": "scroll", "dy": dy}
    raise ValueError("studio input type must be key|pointer|scroll")


class StudioInputSpool:
    """Append-only, seq-numbered spool of validated Studio input events (read by the Studio window)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def push(self, ev: dict[str, Any], device: str = "") -> int:
        ev = validate_studio_event(ev)
        with self.lock:
            rows = self.read()
            seq = (rows[-1]["seq"] + 1) if rows else 0
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"seq": seq, "device": device, "event": ev}, sort_keys=True) + "\n")
            return seq

    def read(self, after: int = -1) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r["seq"] > after]


# ------------------------------------------------------------------------------------------------- control

@dataclass(frozen=True)
class ControlMessage:
    """target: `desktop` (phone → Studio host, REAL for allow-listed queries) | `android` (desktop → phone, STUB)."""

    target: str
    action: str                      # query | input | focus
    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {"target": self.target, "action": self.action, "name": self.name, "args": self.args}

    @classmethod
    def from_wire(cls, w: dict[str, Any]) -> "ControlMessage":
        if w.get("target") not in ("desktop", "android"):
            raise ValueError("target must be desktop|android")
        if w.get("action") not in ("query", "input", "focus"):
            raise ValueError("action must be query|input|focus")
        return cls(w["target"], w["action"], str(w.get("name", "")), dict(w.get("args") or {}))


def handle_control(msg: ControlMessage, hub: FrameHub | None = None, root: Path | None = None,
                   studio: StudioInputSpool | None = None, device: str = "") -> dict[str, Any]:
    """Desktop-side control handler (LoomLink calls it after the `drive_studio` capability check).

    * `desktop/query` — allow-listed read-only queries;
    * `desktop/input` — Studio key/pointer/scroll events, validated and spooled for the Studio window;
    * `android/*` and `*/focus` over the network are refused: desktop → phone events are queued only by the desktop operator
      (`forge mirror input`, `AndroidController`), never relayed from another device."""
    if msg.target == "android" or msg.action == "focus":
        raise PermissionError(t("mirror.control.android_local_only"))
    if msg.action == "input":
        if studio is None:
            raise PermissionError(t("mirror.studio.no_sink"))
        seq = studio.push({**msg.args, "type": msg.name}, device)
        return {"ok": True, "seq": seq}
    if msg.name not in ALLOWED_QUERIES:
        raise PermissionError(t("mirror.control.not_allowlisted", name=msg.name))
    if msg.name == "mirror.stats":
        return {"ok": True, "value": hub.stats() if hub else {}}
    if msg.name == "groundweave.show":
        from forge import groundweave
        return {"ok": True, "value": groundweave.describe(root)}
    from forge.status import collect_status
    st = collect_status(root)
    return {"ok": True, "value": {"healthy": st["healthy"], "version": st["version"], "milestone": st["milestone"]}}


# ------------------------------------------------------------------------------------------------- sources / stubs

class MirrorSource(Protocol):
    """Anything that can produce frames for a stream. Implementations: StillsSource, DesktopScreenSource, VideoStreamSource, ScreenCaptureSource (receiving end)."""

    def frames(self) -> Iterator[FrameEnvelope]: ...


@dataclass
class StillsSource:
    """REAL: streams a sequence of still images as ordered frames (screen captures, camera stills)."""

    stream: str
    images: Iterable[bytes]
    kind: str = "screen"
    codec: str = "png"
    width: int = 0
    height: int = 0
    start_seq: int = 0
    clock: Any = time.time

    def frames(self) -> Iterator[FrameEnvelope]:
        for i, data in enumerate(self.images):
            yield FrameEnvelope(self.stream, self.start_seq + i, int(self.clock() * 1000), self.kind, self.codec,
                                self.width, self.height, data)


@dataclass
class DesktopScreenSource:
    """REAL (desktop): live X11 screen capture as PNG stills (system ffmpeg `x11grab`; Xvfb in tests)."""

    stream: str = "desktop"
    display: str | None = None
    fps: int = 5
    n: int | None = None
    start_seq: int = 0
    clock: Any = time.time

    def frames(self) -> Iterator[FrameEnvelope]:
        from forge.mirrorvideo import DesktopCapture, png_size

        for i, png in enumerate(DesktopCapture(self.display, self.fps).stills(self.n)):
            w, h = png_size(png)
            yield FrameEnvelope(self.stream, self.start_seq + i, int(self.clock() * 1000), "screen", "png", w, h, png)


class ScreenCaptureSource:
    """Phone screen capture. The capture itself is Android-only (MediaProjection, `fabric.pocketloom.ScreenMirrorService`,
    status `real_unverified_on_device`); on the desktop this is the *receiving* end — frames arrive via LoomLink into a FrameHub.
    `frames()` replays what a phone has pushed into `root` (persisted latest still per stream)."""

    def __init__(self, hub: FrameHub | None = None, stream: str = "screen") -> None:
        self.hub, self.stream = hub, stream

    def frames(self) -> Iterator[FrameEnvelope]:
        if self.hub is None:
            raise RuntimeError(t("mirror.capture.android_only"))
        env = self.hub.latest(self.stream)
        if env is not None:
            yield env


@dataclass
class VideoStreamSource:
    """REAL (desktop CPU): video packets from either the live X11 desktop (`display`) or an iterator of RGB frames, encoded
    VP8/VP9 by libvpx through the system ffmpeg. The phone's H.264 (MediaCodec) source is Kotlin (`real_unverified_on_device`)."""

    stream: str = "desktop-video"
    codec: str = "vp8"
    width: int = 0
    height: int = 0
    fps: int = 15
    rgb_frames: Iterable[Any] | None = None
    display: str | None = None
    n: int | None = None
    kind: str = "screen_video"
    start_seq: int = 0
    clock: Any = time.time

    def frames(self) -> Iterator[FrameEnvelope]:
        from forge.mirrorvideo import CpuVideoEncoder, DesktopCapture

        if self.rgb_frames is not None:
            pkts = CpuVideoEncoder(self.width, self.height, self.codec, self.fps).stream(iter(self.rgb_frames))
        else:
            size = (self.width, self.height) if self.width and self.height else None
            pkts = DesktopCapture(self.display, self.fps, size).video(self.codec, self.n)
        for i, p in enumerate(pkts):
            yield FrameEnvelope(self.stream, self.start_seq + i, int(self.clock() * 1000), self.kind, self.codec,
                                self.width, self.height, p, is_keyframe(self.codec, p))


class AndroidController:
    """REAL (desktop side): queue desktop → phone input / focus events for a paired device. Execution on the phone is the
    PocketLoom AccessibilityService / Camera2 controller (`real_unverified_on_device`)."""

    def __init__(self, state_dir: Path | None = None, device: str = "") -> None:
        self.state_dir, self.device = (Path(state_dir) if state_dir else None), device

    def _outbox(self) -> InputOutbox:
        if self.state_dir is None or not self.device:
            raise ValueError(t("mirror.input.need_device"))
        return InputOutbox(self.state_dir / "mirror" / "outbox")

    def send(self, msg: ControlMessage) -> dict[str, Any]:
        if msg.target != "android":
            raise ValueError("AndroidController only sends target=android")
        ev = {**msg.args, "type": msg.name or msg.action}
        return {"ok": True, "device": self.device, "seq": self._outbox().push(self.device, ev)}

    def focus(self, mode: str = "auto", distance_m: float | None = None, x: float | None = None,
              y: float | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"mode": mode}
        if distance_m is not None:
            args["distance_m"] = distance_m
        if x is not None and y is not None:
            args.update(x=x, y=y)
        return self.send(ControlMessage("android", "focus", "focus", args))


# ------------------------------------------------------------------------------------------------- GroundWeave op

def encode_still(data: bytes, kind: str = "screen", stream: str = "probe", seq: int = 0) -> bytes:
    """`mirror.encode` CPU rung: validate + canonical wire encoding of a still (the HW-video rung is planned).
    Deterministic (fixed ts) so GroundWeave `verify` can require byte-identical output across device sets."""
    codec = next(c for c in ("png", "jpeg", "webp") if sniff(c, data))
    env = FrameEnvelope(stream, seq, 0, kind, codec, 0, 0, data)
    return json.dumps(env.to_wire(), sort_keys=True).encode()


__all__ = ["FrameEnvelope", "FrameHub", "VideoTrack", "ControlMessage", "handle_control", "MirrorSource", "StillsSource",
           "DesktopScreenSource", "ScreenCaptureSource", "VideoStreamSource", "AndroidController", "InputOutbox",
           "StudioInputSpool", "validate_android_event", "validate_studio_event", "decode_latest", "ALLOWED_QUERIES"]


STUB_PROBES: dict[str, Any] = {}      # C9 has no stubs left (2026-11-20); the register check still reads this
