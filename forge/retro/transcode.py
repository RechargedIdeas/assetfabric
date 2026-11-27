"""AssetTranscoder + C1 console constraint solver (ASSETFABRIC_SPEC §5.1 "C1 Console constraint solvers / palette",
§6.1 ForgeConsole AssetTranscoder).

Turns Fabric sprites / tilesets (palette-constrained RGBA PNGs) into tile-console data for a profile:

1. quantise every opaque pixel to the profile palette (CIELAB nearest, or lightness for the DMG);
2. split into the profile's hardware tiles (8×8) and cap each tile at the profile's colours per tile, merging the
   least-used colour into its perceptually nearest neighbour until it fits;
3. **sub-palette solve** — pack the tiles' colour sets into at most N sub-palettes of K colours: first-fit packing of
   compatible sets, then repeatedly merge the pair of sub-palettes whose merge (reduced back to K colours) costs the
   least pixel-weighted ΔE, until the count fits; every tile then takes the sub-palette that reproduces it best;
4. dedupe identical tiles (sprites also as H / V / HV flips — the NES OAM can flip, its background cannot);
5. report the fidelity delta (R2): mean / p95 ΔE*ab between source pixels and what the console shows.

Deterministic: no randomness, ties broken by sorted order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

from forge.retro.colour import delta_e, nearest, srgb_to_lab
from forge.retro.profiles import Profile


def load_rgba(path: Path) -> np.ndarray:
    from forge.retro.png import read

    return read(path)


@dataclass
class TileSet:
    """Result of transcoding a set of images for one layer (sprites or background)."""
    tiles: list[np.ndarray]                 # unique 8×8 tiles, values 0..3 (0 = transparent / universal bg)
    palettes: list[list[int]]               # sub-palettes: K profile palette indices each (slot 1..K)
    maps: dict[str, list[dict[str, Any]]]   # image id -> per-tile placements {x, y, tile, pal, hflip, vflip}
    universal: int | None                   # background: shared colour index (slot 0)
    fidelity: dict[str, float] = field(default_factory=dict)
    reductions: int = 0                     # tiles that had more colours than allowed

    def report(self) -> dict[str, Any]:
        return {"unique_tiles": len(self.tiles), "sub_palettes": len(self.palettes), "fidelity": self.fidelity,
                "colour_reduced_tiles": self.reductions, "universal": self.universal}


def _lab_table(profile: Profile) -> np.ndarray:
    return srgb_to_lab(profile.palette)


def _reduce(hist: dict[int, int], k: int, lab: np.ndarray) -> tuple[list[int], float]:
    """Merge least-used colours into their nearest kept colour until ≤ k remain. Returns (kept, ΔE·pixels cost)."""
    keep = dict(hist)
    cost = 0.0
    while len(keep) > k:
        victim = min(sorted(keep), key=lambda c: (keep[c], c))
        others = [c for c in sorted(keep) if c != victim]
        d = [float(np.linalg.norm(lab[victim] - lab[o])) for o in others]
        tgt = others[int(np.argmin(d))]
        cost += keep[victim] * min(d)
        keep[tgt] += keep.pop(victim)
    return sorted(keep), cost


def _fit_cost(hist: dict[int, int], pal: list[int], lab: np.ndarray) -> float:
    return sum(n * min(float(np.linalg.norm(lab[c] - lab[p])) for p in pal) for c, n in hist.items())


def solve_subpalettes(hists: list[dict[int, int]], k: int, n_max: int, lab: np.ndarray) -> list[list[int]]:
    """C1 sub-palette solver. hists: per-tile colour histograms (already ≤ k colours each)."""
    groups: list[dict[int, int]] = []
    for h in sorted(hists, key=lambda h: (-len(h), sorted(h))):
        if not h:
            continue
        for g in groups:
            if len(set(g) | set(h)) <= k:
                for c, n in h.items():
                    g[c] = g.get(c, 0) + n
                break
        else:
            groups.append(dict(h))
    while len(groups) > n_max:
        best = None
        for i, j in combinations(range(len(groups)), 2):
            merged: dict[int, int] = dict(groups[i])
            for c, n in groups[j].items():
                merged[c] = merged.get(c, 0) + n
            kept, cost = _reduce(merged, k, lab)
            if best is None or cost < best[0]:
                best = (cost, i, j, merged)
        _, i, j, merged = best  # type: ignore[misc]
        kept, _ = _reduce(merged, k, lab)
        groups = [g for x, g in enumerate(groups) if x not in (i, j)] + [{c: merged.get(c, 0) for c in kept}]
    return [sorted(g) for g in groups] or [[]]


def fidelity_de(src: np.ndarray, shown: np.ndarray, profile: Profile) -> np.ndarray:
    """Per-pixel fidelity error. CIE76 ΔE*ab, except for lightness-matched (monochrome) profiles, where hue loss is the
    point and the error is |ΔL*| after stretching the source L* onto the palette's L* range."""
    if profile.match != "lightness":
        return delta_e(src, shown)
    pl = srgb_to_lab(profile.palette)[:, 0]
    lo, hi = pl.min(), pl.max()
    return np.abs(lo + srgb_to_lab(src)[..., 0] / 100.0 * (hi - lo) - srgb_to_lab(shown)[..., 0])


def _tiles(idx: np.ndarray, opaque: np.ndarray, t: int) -> list[tuple[int, int, np.ndarray, np.ndarray]]:
    h, w = idx.shape
    return [(x, y, idx[y:y + t, x:x + t], opaque[y:y + t, x:x + t]) for y in range(0, h, t) for x in range(0, w, t)]


def _key(a: np.ndarray) -> bytes:
    return a.astype(np.uint8).tobytes()


def transcode(images: dict[str, np.ndarray], profile: Profile, layer: str = "sprite",
              universal: int | None = None) -> TileSet:
    """images: id -> RGBA uint8 (H, W, 4), sizes multiples of the tile. layer: "sprite" | "bg"."""
    c = profile.constraints
    t = int(c.get("tile", 8))
    if layer == "sprite":
        k, n_max = int(c.get("sprite_colours", 3)), int(c.get("sprite_palettes", 1 if profile.family == "gb" else 4))
    else:
        k, n_max = int(c.get("bg_colours", 3)), int(c.get("bg_palettes", 1))
    pal = profile.palette
    lab = _lab_table(profile)
    quant: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for iid in sorted(images):
        im = images[iid]
        opaque = im[..., 3] >= 128
        q = nearest(im[..., :3], pal, profile.match)
        quant[iid] = (q, opaque)
    if layer == "bg" and universal is None:
        counts: dict[int, int] = {}
        for q, op in quant.values():
            for v, n in zip(*np.unique(q[op], return_counts=True)):
                counts[int(v)] = counts.get(int(v), 0) + int(n)
        universal = max(sorted(counts), key=lambda v: counts[v]) if counts else 0
    # per-tile histograms, capped at k colours (bg: universal colour is free in every tile, slot 0)
    tile_rows: list[tuple[str, int, int, np.ndarray, np.ndarray, dict[int, int], np.ndarray]] = []
    reductions = 0
    for iid in sorted(quant):
        q, op = quant[iid]
        unit = int(c.get("attribute_block", t)) if layer == "bg" else t
        rgb = images[iid][..., :3]
        for x, y, tq, to in _tiles(q, op, unit):
            vals, cnt = np.unique(tq[to], return_counts=True)
            hist = {int(v): int(n) for v, n in zip(vals, cnt) if not (layer == "bg" and int(v) == universal)}
            if len(hist) > k:
                reductions += 1
                kept, _ = _reduce(hist, k, lab)
                hist = {cc: 0 for cc in kept} | {cc: n for cc, n in hist.items() if cc in kept}
            tile_rows.append((iid, x, y, tq, to, hist, rgb[y:y + unit, x:x + unit].reshape(-1, 3)))
    palettes = solve_subpalettes([r[5] for r in tile_rows], k, n_max, lab)
    uniq: dict[bytes, int] = {}
    tiles: list[np.ndarray] = []
    maps: dict[str, list[dict[str, Any]]] = {iid: [] for iid in quant}
    err_px: list[np.ndarray] = []
    for iid, x0, y0, tq, to, hist, orig in tile_rows:
        full = {int(v): int(n) for v, n in zip(*np.unique(tq[to], return_counts=True))}
        choice = min(range(len(palettes)), key=lambda i: (_fit_cost(
            {cc: n for cc, n in full.items() if not (layer == "bg" and cc == universal)}, palettes[i] or [0], lab), i))
        sub = palettes[choice]
        slots = ([universal] if layer == "bg" else []) + sub
        # map each pixel to the nearest colour available in this tile (slot 0 = transparent for sprites)
        flat = tq.reshape(-1)
        opq = to.reshape(-1)
        out = np.zeros_like(flat)
        shown = np.zeros((flat.size, 3), dtype=np.uint8)
        src = np.zeros((flat.size, 3), dtype=np.uint8)
        for i, (v, o) in enumerate(zip(flat, opq)):
            if layer == "sprite" and not o:
                continue
            if layer == "bg" and not o:
                v = universal
            avail = slots if layer == "bg" else sub
            d = [float(np.linalg.norm(lab[v] - lab[a])) for a in avail]
            j = int(np.argmin(d))
            out[i] = j if layer == "bg" else j + 1
            shown[i] = pal[avail[j]]
            src[i] = orig[i] if o else pal[v]
        sel = opq if layer == "sprite" else slice(None)
        err_px.append(fidelity_de(src[sel], shown[sel], profile))
        block = out.reshape(tq.shape)
        for sy in range(0, block.shape[0], t):
            for sx in range(0, block.shape[1], t):
                tile = block[sy:sy + t, sx:sx + t]
                variants = [(tile, False, False)]
                if layer == "sprite":
                    variants += [(tile[:, ::-1], True, False), (tile[::-1, :], False, True), (tile[::-1, ::-1], True, True)]
                hit = None
                for v, hf, vf in variants:
                    if _key(v) in uniq:
                        hit = (uniq[_key(v)], hf, vf)
                        break
                if hit is None:
                    uniq[_key(tile)] = len(tiles)
                    tiles.append(tile.copy())
                    hit = (len(tiles) - 1, False, False)
                maps[iid].append({"x": x0 + sx, "y": y0 + sy, "tile": hit[0], "pal": choice, "hflip": hit[1], "vflip": hit[2]})
    e = np.concatenate(err_px) if err_px else np.zeros(1)
    # quantisation-only error (palette snap before tile / sub-palette limits) for the R2 fidelity delta
    q_err = []
    for iid in sorted(images):
        im = images[iid]
        op = im[..., 3] >= 128
        q_err.append(fidelity_de(im[..., :3][op], pal[quant[iid][0][op]], profile))
    qe = np.concatenate(q_err) if q_err else np.zeros(1)
    fid = {"metric": "dL*" if profile.match == "lightness" else "dE76", "mean_de_quantise": round(float(qe.mean()), 3), "mean_de_console": round(float(e.mean()), 3),
           "p95_de_console": round(float(np.percentile(e, 95)), 3), "pixels": int(e.size)}
    return TileSet(tiles, palettes, maps, universal, fid, reductions)


def chr_bytes(tile: np.ndarray) -> bytes:
    """NES/GB-style 2bpp planar 8×8 tile (NES layout: 8 bytes plane 0, then 8 bytes plane 1; MSB = left pixel)."""
    p0 = bytearray(8)
    p1 = bytearray(8)
    for y in range(8):
        for x in range(8):
            v = int(tile[y, x])
            p0[y] |= (v & 1) << (7 - x)
            p1[y] |= ((v >> 1) & 1) << (7 - x)
    return bytes(p0 + p1)


def render(ts: TileSet, iid: str, profile: Profile, w: int, h: int) -> np.ndarray:
    """What the console shows for one transcoded image (RGBA; transparent sprite pixels alpha 0)."""
    pal = profile.palette
    out = np.zeros((h, w, 4), dtype=np.uint8)
    for m in ts.maps[iid]:
        tile = ts.tiles[m["tile"]]
        if m["hflip"]:
            tile = tile[:, ::-1]
        if m["vflip"]:
            tile = tile[::-1, :]
        sub = ts.palettes[m["pal"]]
        slots = ([ts.universal] + sub) if ts.universal is not None else ([0] + sub)
        for y in range(tile.shape[0]):
            for x in range(tile.shape[1]):
                v = int(tile[y, x])
                if ts.universal is None and v == 0:
                    continue
                ci = slots[v] if v < len(slots) else slots[-1]
                out[m["y"] + y, m["x"] + x, :3] = pal[ci]
                out[m["y"] + y, m["x"] + x, 3] = 255
    return out


def solve_signal_overrides(pairs: list[tuple[str, str, bool]], palette: np.ndarray, match: str,
                           colours: list[str]) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """C1 signal-preserving quantiser. pairs: (hex a, hex b, has_shape_cue) — colours that must stay distinguishable.
    Starts from the nearest-colour mapping of `colours` and greedily moves single colours to another palette entry
    (cheapest perceptual error first) while that strictly reduces the number of collapsed pairs without a shape cue.
    Returns (overrides hex -> palette index, pairs still collapsed)."""
    from forge.retro.colour import hex_rgb

    arr = np.array([hex_rgb(h) for h in colours], dtype=np.uint8)
    base = dict(zip(colours, nearest(arr, palette, match).tolist()))
    pl = srgb_to_lab(palette)
    lo, hi = pl[:, 0].min(), pl[:, 0].max()

    def err(h: str, k: int) -> float:
        lab = srgb_to_lab(np.array(hex_rgb(h), dtype=np.uint8))
        if match == "lightness":
            return float(abs(lo + lab[0] / 100.0 * (hi - lo) - pl[k, 0]))
        return float(np.linalg.norm(lab - pl[k]))

    def fails(m: dict[str, int]) -> list[tuple[str, str]]:
        return sorted({(a, b) for a, b, cue in pairs if not cue and m[a] == m[b]})

    m = dict(base)
    over: dict[str, int] = {}
    for _ in range(32):
        f = fails(m)
        if not f:
            break
        a, b = f[0]
        best = None
        for h in sorted((a, b)):
            for k in range(len(palette)):
                if k == m[h]:
                    continue
                m2 = dict(m)
                m2[h] = k
                if len(fails(m2)) < len(f):
                    cost = err(h, k)
                    if best is None or cost < best[0]:
                        best = (cost, h, k)
        if best is None:
            break
        m[best[1]] = best[2]
        over[best[1]] = best[2]
    return over, fails(m)
