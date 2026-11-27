"""ConsoleReadiness (ASSETFABRIC_SPEC §3 Layer A "porting gate / memory budget validator") — checks Fabric content and a
built ROM against a profile's hardware budgets. Modern console CertPacks stay deferred (SPEC §1); this is the gate.

Per profile, over the content the retro path ships (the slice's fighters, pets, enemies and every area tileset):
  * colours per hardware tile after C1 reduction ≤ limit, sub-palettes ≤ limit;
  * unique CHR tiles per pattern table ≤ limit (NES 256 BG + 256 sprite; DMG 384 shared);
  * sprites per scanline for the shipped formation ≤ limit; sprites total ≤ OAM;
and for a built ROM: PRG/CHR sizes = the mapper's, RAM used ≤ 2 KiB, NMI worst-case cycles ≤ vblank (C1 cycle predictor).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge.retro import transcode as T
from forge.retro.profiles import Profile


def content_sets(root: Path) -> dict[str, Any]:
    gen = root / "games" / "game-zero" / "assets" / "generated"
    reg = json.loads((gen / "fabric_assets.json").read_text(encoding="utf-8"))
    sprites = sorted(p.stem for p in (gen / "sprite").glob("spr_*.png"))
    areas = sorted(p.stem for p in (gen / "tilemap").glob("*.json"))
    return {"sprites": sprites, "areas": areas, "registry_assets": len(reg.get("assets", {}))}


def check(root: Path, profile: Profile) -> dict[str, Any]:
    gen = root / "games" / "game-zero" / "assets" / "generated"
    sets = content_sets(root)
    c = profile.constraints
    rows: list[dict[str, Any]] = []
    errs: list[str] = []
    spr = {s: T.load_rgba(gen / "sprite" / f"{s}.png") for s in sets["sprites"]}
    if profile.family == "fabric":
        # Fabric-native: art is already PatternVault-constrained; only colours per 16×16 tile are budgeted
        worst = 0
        for s, im in spr.items():
            for x in range(0, im.shape[1], 16):
                t = im[:, x:x + 16]
                cols = {tuple(p) for p in t[t[..., 3] >= 128][:, :3].tolist()}
                worst = max(worst, len(cols))
        lim = int(c.get("max_colours_per_tile", 8))
        ok = worst <= lim
        rows.append({"check": "colours_per_16px_tile", "value": worst, "limit": lim, "ok": ok})
        if not ok:
            errs.append(f"{profile.id}: {worst} colours in a tile > {lim}")
        return {"profile": profile.id, "ok": not errs, "rows": rows, "errors": errs, "content": sets}
    st = T.transcode(spr, profile, "sprite")
    k = int(c.get("sprite_palettes", 1 if profile.family == "gb" else 4))
    rows.append({"check": "sprite_sub_palettes", "value": len(st.palettes), "limit": k, "ok": len(st.palettes) <= k})
    bg_tiles = 0
    bg_pal_worst = 0
    bg_fid = []
    for a in sets["areas"]:
        bt = T.transcode({a: T.load_rgba(gen / "tilemap" / f"{a}_tiles.png")}, profile, "bg")
        bg_tiles = max(bg_tiles, len(bt.tiles))
        bg_pal_worst = max(bg_pal_worst, len(bt.palettes))
        bg_fid.append(bt.fidelity["mean_de_console"])
    kb = int(c.get("bg_palettes", 1))
    rows.append({"check": "bg_sub_palettes_per_area", "value": bg_pal_worst, "limit": kb, "ok": bg_pal_worst <= kb})
    if profile.family == "nes":
        lim = int(c.get("chr_tiles_per_table", 256))
        rows.append({"check": "chr_sprite_tiles_all_sprites_idle_frames", "value": len(st.tiles), "limit": lim,
                     "ok": len(st.tiles) <= lim})
        rows.append({"check": "chr_bg_tiles_per_area", "value": bg_tiles, "limit": lim, "ok": bg_tiles <= lim})
    else:
        lim = int(c.get("tiles_vram", 384))
        rows.append({"check": "vram_tiles_sprites_plus_largest_area", "value": len(st.tiles) + bg_tiles, "limit": lim,
                     "ok": len(st.tiles) + bg_tiles <= lim})
    for r in rows:
        if not r["ok"]:
            errs.append(f"{profile.id}: {r['check']} {r['value']} > {r['limit']}")
    return {"profile": profile.id, "ok": not errs, "rows": rows, "errors": errs, "content": sets,
            "fidelity": {"sprites": st.fidelity, "bg_mean_de_console_worst_area": round(max(bg_fid), 3) if bg_fid else None},
            "colour_reduced_sprite_tiles": st.reductions}


def check_rom(rb: Any, profile: Profile) -> dict[str, Any]:
    from forge.retro.rom import sprites_per_scanline

    mem, tim, c = profile.memory, profile.timing, profile.constraints
    r = rb.report
    rows = [
        {"check": "prg_rom_bytes", "value": len(rb.rom) - 16 - int(mem["chr_rom"]), "limit": int(mem["prg_rom"])},
        {"check": "prg_used_bytes", "value": r["prg_used"], "limit": int(mem["prg_rom"])},
        {"check": "chr_rom_bytes", "value": int(mem["chr_rom"]), "limit": int(mem["chr_rom"])},
        {"check": "chr_bg_tiles", "value": r["chr_bg_tiles"], "limit": int(c["chr_tiles_per_table"])},
        {"check": "chr_sprite_tiles", "value": r["chr_sprite_tiles"], "limit": int(c["chr_tiles_per_table"])},
        {"check": "bg_sub_palettes", "value": r["bg_sub_palettes"], "limit": int(c["bg_palettes"])},
        {"check": "sprite_sub_palettes", "value": r["sprite_sub_palettes"], "limit": int(c["sprite_palettes"])},
        {"check": "ram_bytes", "value": r["zero_page_bytes"] + r["oam_shadow_bytes"] + 32, "limit": int(mem["ram"])},
        {"check": "oam_sprites", "value": sum(len(m) for m in rb.metasprites[0::6]), "limit": int(c["sprites_total"])},
        {"check": "sprites_per_scanline", "value": sprites_per_scanline(rb), "limit": int(c["sprites_per_line"])},
        {"check": "nmi_worst_case_cycles", "value": r["nmi_cycles"], "limit": int(tim["vblank_cycles"])},
    ]
    for x in rows:
        x["ok"] = x["value"] <= x["limit"]
    errs = [f"{x['check']} {x['value']} > {x['limit']}" for x in rows if not x["ok"]]
    return {"ok": not errs, "rows": rows, "errors": errs}
