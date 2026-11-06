"""Dependency-free RGBA image + PNG codec (F1).

Pure Python so generators run on the weakest acceptance node (2 cores, no GPU)
without Pillow/NumPy. Images are small (8-bit era), so speed is fine.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

RGBA = tuple[int, int, int, int]
TRANSPARENT: RGBA = (0, 0, 0, 0)


def hex_to_rgba(value: str) -> RGBA:
    v = value.lstrip("#")
    if len(v) == 6:
        v += "ff"
    if len(v) != 8:
        raise ValueError(f"bad colour {value!r}")
    return tuple(int(v[i : i + 2], 16) for i in range(0, 8, 2))  # type: ignore[return-value]


def rgba_to_hex(c: RGBA) -> str:
    return "#" + "".join(f"{x:02x}" for x in c[:3]) + ("" if c[3] == 255 else f"{c[3]:02x}")


@dataclass
class Image:
    width: int
    height: int
    pixels: list[RGBA] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.pixels:
            self.pixels = [TRANSPARENT] * (self.width * self.height)
        if len(self.pixels) != self.width * self.height:
            raise ValueError("pixel buffer size mismatch")

    def get(self, x: int, y: int) -> RGBA:
        return self.pixels[y * self.width + x]

    def set(self, x: int, y: int, c: RGBA) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y * self.width + x] = c

    def blit(self, src: "Image", dx: int, dy: int) -> None:
        for y in range(src.height):
            for x in range(src.width):
                c = src.get(x, y)
                if c[3]:
                    self.set(dx + x, dy + y, c)

    def colours(self, include_transparent: bool = False) -> set[RGBA]:
        return {p for p in self.pixels if include_transparent or p[3] > 0}

    def to_png(self) -> bytes:
        raw = bytearray()
        for y in range(self.height):
            raw.append(0)  # filter: none
            for x in range(self.width):
                raw.extend(self.get(x, y))
        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", self.width, self.height, 8, 6, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")

    @classmethod
    def from_png(cls, data: bytes) -> "Image":
        """Decode 8-bit RGBA, non-interlaced PNGs (what `to_png` writes)."""
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a PNG")
        pos, idat, w = 8, b"", 0
        h = 0
        while pos < len(data):
            (length,) = struct.unpack(">I", data[pos : pos + 4])
            tag = data[pos + 4 : pos + 8]
            body = data[pos + 8 : pos + 8 + length]
            if tag == b"IHDR":
                w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
                if depth != 8 or ctype != 6 or interlace:
                    raise ValueError("only 8-bit RGBA non-interlaced supported")
            elif tag == b"IDAT":
                idat += body
            pos += 12 + length
        raw = zlib.decompress(idat)
        stride = w * 4
        out: list[RGBA] = []
        prev = bytearray(stride)
        i = 0
        for _ in range(h):
            ftype = raw[i]
            line = bytearray(raw[i + 1 : i + 1 + stride])
            i += 1 + stride
            for x in range(stride):
                a = line[x - 4] if x >= 4 else 0
                b = prev[x]
                c = prev[x - 4] if x >= 4 else 0
                if ftype == 1:
                    line[x] = (line[x] + a) & 255
                elif ftype == 2:
                    line[x] = (line[x] + b) & 255
                elif ftype == 3:
                    line[x] = (line[x] + (a + b) // 2) & 255
                elif ftype == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if pa <= pb and pa <= pc else b if pb <= pc else c
                    line[x] = (line[x] + pr) & 255
            out.extend(tuple(line[j : j + 4]) for j in range(0, stride, 4))  # type: ignore[misc]
            prev = line
        return cls(w, h, out)
