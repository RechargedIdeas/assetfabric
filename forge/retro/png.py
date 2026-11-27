"""Minimal dependency-free PNG I/O for the retro path (8-bit RGB / RGBA, non-interlaced) — numpy arrays in and out.
Deterministic encoder (fixed zlib level, no ancillary chunks) so LUT/CHR previews are byte-stable for `forge build`."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np


def encode(img: np.ndarray) -> bytes:
    img = np.ascontiguousarray(img.astype(np.uint8))
    h, w = img.shape[:2]
    ch = 1 if img.ndim == 2 else img.shape[2]
    ctype = {1: 0, 3: 2, 4: 6}[ch]
    raw = np.concatenate([np.zeros((h, 1), dtype=np.uint8), img.reshape(h, w * ch)], axis=1).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def decode(data: bytes) -> np.ndarray:
    """→ (H, W, 4) uint8 RGBA (RGB inputs get alpha 255; palette PNGs are expanded)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat = 8, b""
    w = h = ctype = 0
    plte = trns = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", body)
            if depth != 8 or inter:
                raise ValueError("only 8-bit non-interlaced PNGs")
        elif tag == b"PLTE":
            plte = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3)
        elif tag == b"tRNS":
            trns = np.frombuffer(body, dtype=np.uint8)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8)
    stride = w * bpp
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)].astype(np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:
            cur = np.zeros(stride, dtype=np.int32)
            for x in range(stride):
                a = cur[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                if f == 1:
                    v = a
                elif f == 3:
                    v = (a + b) // 2
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    v = a if pa <= pb and pa <= pc else b if pb <= pc else c
                cur[x] = (line[x] + v) & 255
        out[y] = cur
        prev = cur
    px = out.reshape(h, w, bpp)
    if ctype == 6:
        return px
    rgba = np.full((h, w, 4), 255, dtype=np.uint8)
    if ctype == 2:
        rgba[..., :3] = px
    elif ctype == 0:
        rgba[..., :3] = px[..., :1]
    elif ctype == 4:
        rgba[..., :3] = px[..., :1]
        rgba[..., 3] = px[..., 1]
    elif ctype == 3:
        rgba[..., :3] = plte[px[..., 0]]
        if trns is not None:
            a = np.full(len(plte), 255, dtype=np.uint8)
            a[:len(trns)] = trns
            rgba[..., 3] = a[px[..., 0]]
    return rgba


def read(path: Path) -> np.ndarray:
    return decode(Path(path).read_bytes())


def write(path: Path, img: np.ndarray) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(encode(img))
