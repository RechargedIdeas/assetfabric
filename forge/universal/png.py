# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Minimal, deterministic NumPy PNG codec (8-bit greyscale / RGB / RGBA, non-interlaced).

Encoding always uses filter 0 and zlib level 9, so identical arrays give identical bytes. Decoding handles all five
PNG row filters so files written by other tools (OpenSCAD, Blender, Pillow) can be checked too."""

from __future__ import annotations

import struct
import zlib

import numpy as np

_SIG = b"\x89PNG\r\n\x1a\n"
_CT = {1: 0, 3: 2, 4: 6, 2: 4}          # channels -> colour type
_CH = {0: 1, 2: 3, 6: 4, 4: 2}


def encode(img: np.ndarray) -> bytes:
    a = np.asarray(img)
    if a.dtype != np.uint8:
        raise ValueError("PNG encode expects uint8")
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, c = a.shape
    if c not in _CT:
        raise ValueError(f"unsupported channel count {c}")
    raw = np.concatenate([np.zeros((h, 1), np.uint8), a.reshape(h, w * c)], axis=1).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, _CT[c], 0, 0, 0)
    return _SIG + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def info(data: bytes) -> dict[str, int]:
    if data[:8] != _SIG or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    w, h, bd, ct = struct.unpack(">IIBB", data[16:26])
    return {"width": w, "height": h, "bit_depth": bd, "colour_type": ct, "channels": _CH.get(ct, 0)}


def decode(data: bytes) -> np.ndarray:
    """Return an (h, w, c) uint8 array. Verifies every chunk CRC."""
    if data[:8] != _SIG:
        raise ValueError("not a PNG")
    pos, idat, hdr = 8, b"", None
    while pos < len(data):
        (n,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        (crc,) = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])
        if zlib.crc32(tag + body) & 0xFFFFFFFF != crc:
            raise ValueError(f"bad CRC in {tag!r}")
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + n
    if hdr is None:
        raise ValueError("missing IHDR")
    w, h, bd, ct, _, _, interlace = hdr
    if bd != 8 or ct not in _CH or interlace:
        raise ValueError(f"unsupported PNG (bit depth {bd}, colour type {ct}, interlace {interlace})")
    c = _CH[ct]
    stride = w * c
    raw = np.frombuffer(zlib.decompress(idat), np.uint8)
    if raw.size != h * (stride + 1):
        raise ValueError("IDAT size mismatch")
    rows = raw.reshape(h, stride + 1)
    out = np.zeros((h, stride), np.int32)
    prev = np.zeros(stride, np.int32)
    for y in range(h):
        f, line = int(rows[y, 0]), rows[y, 1:].astype(np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 0xFF
        else:
            cur = np.zeros(stride, np.int32)
            for i in range(stride):
                left = cur[i - c] if i >= c else 0
                up = prev[i]
                ul = prev[i - c] if i >= c else 0
                if f == 1:
                    p = left
                elif f == 3:
                    p = (left + up) >> 1
                elif f == 4:
                    pa, pb, pc = abs(up - ul), abs(left - ul), abs(left + up - 2 * ul)
                    p = left if pa <= pb and pa <= pc else (up if pb <= pc else ul)
                else:
                    raise ValueError(f"bad filter {f}")
                cur[i] = (int(line[i]) + p) & 0xFF
        out[y] = cur
        prev = cur
    return out.astype(np.uint8).reshape(h, w, c)
