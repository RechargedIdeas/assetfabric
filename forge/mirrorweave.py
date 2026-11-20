"""MirrorWeave (C9) — cross-device control + stream, SPEC §9 / §8.

SPEC: "Android screen stream → desktop; desktop remote control of Android; Android remote control of desktop; camera
video/stills/focus/telemetry streaming." Capabilities `mirror` and `drive_studio` were reserved in LoomLink (C5).

What is REAL here (CPU only, stdlib + numpy-free, signed LoomLink transport):
  * `FrameEnvelope` — typed, validated wire contract for one frame (screen / camera still / telemetry), JSON + base64.
  * `FrameHub` — desktop sink: per-stream ring buffer, monotonic-seq enforcement, drop accounting, persisted latest frame.
  * LoomLink routes (forge/loomlink.py): `POST /mirror/frame` (cap `mirror`), `POST /mirror/latest` (cap `mirror`),
    `POST /mirror/control` (cap `drive_studio`, **allow-listed read-only queries only**), `GET /mirror/info` (public descriptor).
  * `StillsSource` — a real MirrorSource that streams still images (screen captures or camera stills) frame by frame.
    This is also the CPU fallback rung of GroundWeave op `mirror.encode` (stills; video encoding is the planned GPU rung).

What is a STUB (interface only; refuses with `StubError`, never fakes output):
  * live Android screen capture (MediaProjection), H.264/WebRTC video streaming, camera video,
  * desktop→Android remote input (tap/swipe/key injection), Android→desktop *input* into the Studio GUI (Studio is a stub),
  * camera focus control (CameraX/Camera2).

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

from forge.stubs import StubError, refuse

MILESTONE = "C9"
MAX_FRAME_BYTES = 8 * 1024 * 1024            # [INFERENCE C-33] one still; video chunks are a stub
RING = 8
STREAM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
STREAM_KINDS = ("screen", "camera_still", "telemetry")        # REAL kinds
STUB_KINDS = ("camera_video",)                                # contract reserved, refuses
STILL_CODECS = {"png": "png", "jpeg": "jpg", "webp": "webp", "json": "json"}
STUB_CODECS = ("h264", "vp9", "av1")
# phone → desktop read-only queries the `drive_studio` capability may run (no state change, no host command execution)
ALLOWED_QUERIES = ("forge.status", "groundweave.show", "mirror.stats")


def sniff(codec: str, data: bytes) -> bool:
    if codec == "png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if codec == "jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if codec == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
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

    def __post_init__(self) -> None:
        if not STREAM_RE.match(self.stream):
            raise ValueError("bad stream id (a-z 0-9 _ -, ≤32)")
        if self.kind in STUB_KINDS or self.codec in STUB_CODECS:
            refuse("mirror.video_stream", "stub.mirror.video_codec", MILESTONE, codec=self.codec)
        if self.kind not in STREAM_KINDS:
            raise ValueError(f"unknown frame kind {self.kind!r}")
        if self.codec not in STILL_CODECS:
            raise ValueError(f"unknown codec {self.codec!r}")
        if (self.kind == "telemetry") != (self.codec == "json"):
            raise ValueError("telemetry frames must be json and json frames must be telemetry")
        if self.seq < 0 or self.ts_ms < 0 or self.width < 0 or self.height < 0:
            raise ValueError("negative field")
        if not self.data or len(self.data) > MAX_FRAME_BYTES:
            raise ValueError(f"frame must be 1..{MAX_FRAME_BYTES} bytes")
        if not sniff(self.codec, self.data):
            raise ValueError(f"payload is not valid {self.codec}")

    def to_wire(self) -> dict[str, Any]:
        return {"stream": self.stream, "seq": self.seq, "ts_ms": self.ts_ms, "kind": self.kind, "codec": self.codec,
                "width": self.width, "height": self.height, "data_b64": base64.b64encode(self.data).decode()}

    @classmethod
    def from_wire(cls, w: dict[str, Any]) -> "FrameEnvelope":
        try:
            raw = base64.b64decode(w["data_b64"], validate=True)
            return cls(str(w["stream"]), int(w["seq"]), int(w["ts_ms"]), str(w["kind"]), str(w["codec"]),
                       int(w.get("width", 0)), int(w.get("height", 0)), raw)
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

    def accept(self, env: FrameEnvelope) -> dict[str, Any]:
        with self.lock:
            st = self._stats.setdefault(env.stream, {"frames": 0, "bytes": 0, "dropped": 0, "last_seq": -1,
                                                     "first_ts_ms": env.ts_ms, "last_ts_ms": env.ts_ms})
            if env.seq <= st["last_seq"]:
                raise ValueError(f"stale frame: seq {env.seq} ≤ last {st['last_seq']}")
            if st["last_seq"] >= 0:
                st["dropped"] += env.seq - st["last_seq"] - 1
            st.update(last_seq=env.seq, last_ts_ms=env.ts_ms)
            st["frames"] += 1
            st["bytes"] += len(env.data)
            self._frames.setdefault(env.stream, deque(maxlen=self.ring)).append(env)
            self._persist(env)
            return {"accepted": True, "seq": env.seq, "dropped_total": st["dropped"]}

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


def handle_control(msg: ControlMessage, hub: FrameHub | None = None, root: Path | None = None) -> dict[str, Any]:
    """Desktop-side control handler (called by LoomLink after the `drive_studio` capability check)."""
    if msg.target == "android":
        return AndroidController().send(msg)                       # raises StubError
    if msg.action == "input":
        refuse("mirror.studio_input", "stub.mirror.studio_input", MILESTONE)
    if msg.action == "focus":
        refuse("mirror.camera_focus", "stub.mirror.camera_focus", MILESTONE)
    if msg.name not in ALLOWED_QUERIES:
        from forge.i18n import t
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
    """Anything that can produce frames for a stream. Implementations: StillsSource (real), ScreenCaptureSource (stub)."""

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


class ScreenCaptureSource:
    """STUB: live Android screen capture needs MediaProjection (an Android foreground service + user consent) — not built."""

    def frames(self) -> Iterator[FrameEnvelope]:
        refuse("mirror.screen_capture", "stub.mirror.screen_capture", MILESTONE)


class VideoStreamSource:
    """STUB: H.264/WebRTC camera/screen video (hardware encoder rung of `mirror.encode`) — not built."""

    def frames(self) -> Iterator[FrameEnvelope]:
        refuse("mirror.video_stream", "stub.mirror.video_codec", MILESTONE, codec="h264")


class AndroidController:
    """STUB: desktop → Android remote control (tap/swipe/key). Needs an AccessibilityService or adb bridge on the phone."""

    def send(self, msg: ControlMessage) -> dict[str, Any]:
        refuse("mirror.android_input", "stub.mirror.android_input", MILESTONE)


# ------------------------------------------------------------------------------------------------- GroundWeave op

def encode_still(data: bytes, kind: str = "screen", stream: str = "probe", seq: int = 0) -> bytes:
    """`mirror.encode` CPU rung: validate + canonical wire encoding of a still (the HW-video rung is planned).
    Deterministic (fixed ts) so GroundWeave `verify` can require byte-identical output across device sets."""
    codec = next(c for c in ("png", "jpeg", "webp") if sniff(c, data))
    env = FrameEnvelope(stream, seq, 0, kind, codec, 0, 0, data)
    return json.dumps(env.to_wire(), sort_keys=True).encode()


__all__ = ["FrameEnvelope", "FrameHub", "ControlMessage", "handle_control", "MirrorSource", "StillsSource",
           "ScreenCaptureSource", "VideoStreamSource", "AndroidController", "StubError", "ALLOWED_QUERIES"]
