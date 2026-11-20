"""MirrorWeave video + desktop capture (C9) — real CPU paths driven through the **system** ffmpeg binary.

* `DesktopCapture` — live desktop screen capture (X11 via ffmpeg `x11grab`), as PNG stills or as a CPU video stream.
* `CpuVideoEncoder` — raw RGB frames → VP8/VP9 packets (libvpx, BSD-3) in realtime mode (no lag frames, so one packet per frame).
* `decode_packets` — packets → RGB frames (verification and the desktop viewer); also decodes H.264 Annex-B from a phone's
  hardware encoder (MediaCodec) with ffmpeg's built-in decoder.
* IVF / VP8 / VP9 / H.264 bitstream helpers (keyframe detection, packet splitting) shared with the WebSocket transport.

ffmpeg is **invoked as a separate program, never linked or redistributed** (BoltPack: THIRD_PARTY_NOTICES §system tools).
We only ask it for libvpx (VP8/VP9, BSD-3) encoding; H.264 *encoding* happens on the phone's hardware encoder. If ffmpeg or
libvpx is missing, `FfmpegMissing` is raised with a locale-keyed reason (no silent fallback, no fake frames).
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import threading
from dataclasses import dataclass
from typing import Iterator

import numpy as np

from forge.i18n import t

VIDEO_CODECS = ("vp8", "vp9", "h264")
CPU_ENCODERS = {"vp8": "libvpx", "vp9": "libvpx-vp9"}
IVF_FOURCC = {"vp8": b"VP80", "vp9": b"VP90"}
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_END = b"IEND\xaeB`\x82"


class FfmpegMissing(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    exe = os.environ.get("FORGE_FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise FfmpegMissing(t("mirror.video.ffmpeg_missing"))
    return exe


def has_encoder(name: str) -> bool:
    try:
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
    except (FfmpegMissing, OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.startswith(" V"))


def available() -> dict[str, bool]:
    try:
        ffmpeg_bin()
        ok = True
    except FfmpegMissing:
        ok = False
    return {"ffmpeg": ok, "vp8": ok and has_encoder("libvpx"), "vp9": ok and has_encoder("libvpx-vp9")}


# ------------------------------------------------------------------------------------------ bitstream helpers

def is_keyframe(codec: str, pkt: bytes) -> bool:
    """Keyframe test from the bitstream itself (the transport never trusts a sender's flag for decoder resync)."""
    if not pkt:
        return False
    if codec == "vp8":                       # RFC 6386 §9.1: frame tag bit0 == 0 → key frame, then start code 9d 01 2a
        return (pkt[0] & 1) == 0 and len(pkt) >= 10 and pkt[3:6] == b"\x9d\x01\x2a"
    if codec == "vp9":                       # VP9 uncompressed header: frame_marker(2) profile(2[+1]) show_existing(1) type(1)
        bits = f"{int.from_bytes(pkt[:2].ljust(2, b'\0'), 'big'):016b}"
        if bits[:2] != "10":
            return False
        profile = int(bits[2]) | (int(bits[3]) << 1)
        i = 4 + (1 if profile == 3 else 0)
        return bits[i] == "0" and bits[i + 1] == "0"      # not show_existing_frame, frame_type == KEY_FRAME
    if codec == "h264":
        return any(n in (5, 7) for n in h264_nal_types(pkt))
    raise ValueError(f"unknown video codec {codec!r}")


def h264_nal_types(data: bytes) -> list[int]:
    types, i, n = [], 0, len(data)
    while i + 3 < n:
        if data[i] == 0 and data[i + 1] == 0 and (data[i + 2] == 1 or (data[i + 2] == 0 and i + 3 < n and data[i + 3] == 1)):
            j = i + (3 if data[i + 2] == 1 else 4)
            if j < n:
                types.append(data[j] & 0x1F)
            i = j
        else:
            i += 1
    return types


def split_h264_aus(data: bytes) -> list[bytes]:
    """Split an Annex-B stream into access units at AUD (NAL 9) start codes (fixtures are encoded with aud=1)."""
    starts, i, n = [], 0, len(data)
    while i + 4 < n:
        if data[i:i + 4] == b"\0\0\0\1" and (data[i + 4] & 0x1F) == 9:
            starts.append(i)
            i += 4
        else:
            i += 1
    starts.append(n)
    return [data[a:b] for a, b in zip(starts, starts[1:]) if b > a]


def sniff_video(codec: str, pkt: bytes) -> bool:
    """Structural check of one packet (cheap; full validity is the decoder's job)."""
    if not pkt:
        return False
    if codec == "vp8":
        return (pkt[0] & 1) == 1 or pkt[3:6] == b"\x9d\x01\x2a"
    if codec == "vp9":
        return (pkt[0] >> 6) == 0b10
    if codec == "h264":
        return pkt[:3] == b"\0\0\1" or pkt[:4] == b"\0\0\0\1"
    return False


def ivf_header(codec: str, w: int, h: int, fps: int, nframes: int = 0) -> bytes:
    return b"DKIF" + struct.pack("<HH4sHHIII", 0, 32, IVF_FOURCC[codec], w, h, fps, 1, nframes) + b"\0" * 4


def ivf_frame(pkt: bytes, pts: int) -> bytes:
    return struct.pack("<IQ", len(pkt), pts) + pkt


def parse_ivf(data: bytes) -> tuple[dict[str, object], list[bytes]]:
    if data[:4] != b"DKIF":
        raise ValueError("not an IVF stream")
    hl = struct.unpack_from("<H", data, 6)[0]
    fourcc, w, h, rate, scale, nf = struct.unpack_from("<4sHHIII", data, 8)
    pkts, i = [], hl
    while i + 12 <= len(data):
        size = struct.unpack_from("<I", data, i)[0]
        pkts.append(data[i + 12:i + 12 + size])
        i += 12 + size
    return {"fourcc": fourcc.decode(), "width": w, "height": h, "rate": rate, "scale": scale}, pkts


class IvfReader:
    """Incremental IVF demuxer over a pipe (ffmpeg stdout): yields one packet per encoded frame."""

    def __init__(self, stream) -> None:  # noqa: ANN001
        self.s = stream
        self.header: dict[str, object] | None = None

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.s.read(n - len(buf))
            if not chunk:
                return buf
            buf += chunk
        return buf

    def packets(self) -> Iterator[bytes]:
        hdr = self._read(32)
        if len(hdr) < 32:
            return
        fourcc, w, h, rate, scale, _ = struct.unpack_from("<4sHHIII", hdr, 8)
        self.header = {"fourcc": fourcc.decode(), "width": w, "height": h, "rate": rate, "scale": scale}
        while True:
            fh = self._read(12)
            if len(fh) < 12:
                return
            size = struct.unpack_from("<I", fh, 0)[0]
            pkt = self._read(size)
            if len(pkt) < size:
                return
            yield pkt


def split_pngs(stream) -> Iterator[bytes]:  # noqa: ANN001
    """Split a concatenated PNG stream (ffmpeg image2pipe) into individual files."""
    buf = b""
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        buf += chunk
        while True:
            end = buf.find(PNG_END)
            if end < 0:
                break
            end += len(PNG_END)
            yield buf[:end]
            buf = buf[end:]


def png_size(png: bytes) -> tuple[int, int]:
    if png[:8] != PNG_SIG:
        raise ValueError("not a PNG")
    return struct.unpack(">II", png[16:24])


# ------------------------------------------------------------------------------------------ encoder / decoder

@dataclass
class CpuVideoEncoder:
    """Raw RGB24 frames in → VP8/VP9 packets out, realtime (one packet per input frame, no lag/alt-ref frames)."""

    width: int
    height: int
    codec: str = "vp8"
    fps: int = 15
    bitrate_k: int = 1500
    gop: int = 30

    def __post_init__(self) -> None:
        if self.codec not in CPU_ENCODERS:
            raise ValueError(t("mirror.video.cpu_codec", codec=self.codec))
        if self.width % 2 or self.height % 2:
            raise ValueError("width/height must be even (yuv420p)")

    def argv(self, src: list[str]) -> list[str]:
        enc = CPU_ENCODERS[self.codec]
        extra = ["-row-mt", "1"] if self.codec == "vp9" else []
        return [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", *src, "-an", "-c:v", enc, "-deadline", "realtime",
                "-cpu-used", "8", "-lag-in-frames", "0", "-auto-alt-ref", "0", "-g", str(self.gop), "-b:v", f"{self.bitrate_k}k",
                "-threads", "2", *extra, "-pix_fmt", "yuv420p", "-f", "ivf", "-flush_packets", "1", "pipe:1"]

    def encode(self, frames: list[np.ndarray]) -> list[bytes]:
        """Batch encode (deterministic for a given ffmpeg/libvpx build)."""
        raw = b"".join(np.ascontiguousarray(f, dtype=np.uint8).tobytes() for f in frames)
        src = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{self.width}x{self.height}", "-r", str(self.fps), "-i", "pipe:0"]
        p = subprocess.run(self.argv(src), input=raw, capture_output=True, timeout=300)
        if p.returncode:
            raise RuntimeError(p.stderr.decode(errors="replace")[-400:])
        return parse_ivf(p.stdout)[1]

    def stream(self, frames: Iterator[np.ndarray]) -> Iterator[bytes]:
        """Streaming encode: packets are yielded as ffmpeg emits them (a writer thread feeds stdin)."""
        src = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{self.width}x{self.height}", "-r", str(self.fps), "-i", "pipe:0"]
        p = subprocess.Popen(self.argv(src), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def feed() -> None:
            try:
                for f in frames:
                    p.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
            except BrokenPipeError:
                pass
            finally:
                try:
                    p.stdin.close()
                except OSError:
                    pass
        th = threading.Thread(target=feed, daemon=True)
        th.start()
        try:
            yield from IvfReader(p.stdout).packets()
        finally:
            th.join(timeout=5)
            p.kill() if p.poll() is None else None
            p.wait()


def decode_packets(codec: str, packets: list[bytes], width: int = 0, height: int = 0) -> list[np.ndarray]:
    """Decode packets back to RGB frames with ffmpeg (VP8/VP9 via IVF, H.264 Annex-B raw)."""
    if codec in IVF_FOURCC:
        data = ivf_header(codec, width or 16, height or 16, 30, len(packets)) + b"".join(
            ivf_frame(p, i) for i, p in enumerate(packets))
        fmt = ["-f", "ivf"]
    elif codec == "h264":
        data, fmt = b"".join(packets), ["-f", "h264"]
    else:
        raise ValueError(f"unknown video codec {codec!r}")
    p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", *fmt, "-i", "pipe:0", "-f", "image2pipe",
                        "-c:v", "png", "pipe:1"], input=data, capture_output=True, timeout=300)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-400:])
    import io
    from PIL import Image

    out = []
    for png in split_pngs(io.BytesIO(p.stdout)):
        out.append(np.asarray(Image.open(io.BytesIO(png)).convert("RGB")))
    return out


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


# ------------------------------------------------------------------------------------------ desktop capture

@dataclass
class DesktopCapture:
    """Live desktop capture from an X11 display through ffmpeg `x11grab` (Linux desktops; Xvfb in tests).

    `stills()` yields PNG frames at `fps`; `video()` yields VP8/VP9 packets encoded on the CPU. Windows (gdigrab/ddagrab) and
    Wayland (PipeWire portal) capture are not wired: `[INFERENCE C-51]`."""

    display: str | None = None
    fps: int = 5
    size: tuple[int, int] | None = None
    offset: tuple[int, int] = (0, 0)

    def _src(self) -> list[str]:
        disp = self.display or os.environ.get("DISPLAY")
        if not disp:
            raise RuntimeError(t("mirror.capture.no_display"))
        src = ["-f", "x11grab", "-draw_mouse", "0", "-framerate", str(self.fps)]
        if self.size:
            src += ["-video_size", f"{self.size[0]}x{self.size[1]}"]
        return src + ["-i", f"{disp}+{self.offset[0]},{self.offset[1]}"]

    def stills(self, n: int | None = None) -> Iterator[bytes]:
        argv = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", *self._src()]
        if n is not None:
            argv += ["-frames:v", str(n)]
        argv += ["-f", "image2pipe", "-c:v", "png", "pipe:1"]
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            yield from split_pngs(p.stdout)
        finally:
            p.kill() if p.poll() is None else None
            err = p.stderr.read().decode(errors="replace") if p.stderr else ""
            rc = p.wait()
            if rc not in (0, -9) and n is not None and err:
                raise RuntimeError(err[-400:])

    def video(self, codec: str = "vp8", n: int | None = None, bitrate_k: int = 1500) -> Iterator[bytes]:
        w, h = self.size or (0, 0)
        enc = CpuVideoEncoder(w or 2, h or 2, codec, self.fps, bitrate_k)
        argv = enc.argv(self._src() + (["-frames:v", str(n)] if n is not None else []))
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            yield from IvfReader(p.stdout).packets()
        finally:
            p.kill() if p.poll() is None else None
            p.wait()
