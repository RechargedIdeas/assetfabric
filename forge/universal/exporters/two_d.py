# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""2D / 2.5D adapters: TexturePacker-style atlas (generic 2D), RPG Maker MV/MZ/VX Ace sheets, Sprite Lamp / Sprite Pro
map packs, Construct 2 sprite strips, Clickteam Fusion frame sequences, AppGameKit atlases (+3D), ePic Character
Generator import, and Godot SpriteFrames text resources."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from forge.universal import ir, maps2d, png, reference
from forge.universal import mesh as M
from forge.universal.exporters.base import Adapter, Pack, finish_verify, read_manifest


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def frames_of(sp: ir.Sprite, atlas: np.ndarray) -> list[np.ndarray]:
    return [atlas[y:y + h, x:x + w] for (x, y, w, h) in sp.frames]


def texturepacker_json(sp: ir.Sprite, scene: ir.Scene, image: str) -> str:
    """TexturePacker 'JSON (Hash)' layout — read by Paper2D, Phaser, PixiJS, Cocos, Defold importers and others."""
    info = png.info(scene.textures[sp.atlas].png)
    frames = {}
    for k, (x, y, w, h) in enumerate(sp.frames):
        frames[f"{sp.id}_{k:02d}"] = {"frame": {"x": x, "y": y, "w": w, "h": h}, "rotated": False, "trimmed": False,
                                      "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h}, "sourceSize": {"w": w, "h": h},
                                      "pivot": {"x": sp.pivot[0], "y": sp.pivot[1]}}
    anims = {n: [f"{sp.id}_{i:02d}" for i in a["frames"]] for n, a in sorted(sp.animations.items())}
    doc = {"frames": frames, "animations": anims,
           "meta": {"app": "AssetFabric", "version": "1.0", "image": image, "format": "RGBA8888",
                    "size": {"w": info["width"], "h": info["height"]}, "scale": "1"}}
    return json.dumps(doc, indent=2, sort_keys=True)


def check_texturepacker_json(doc: dict[str, Any], folder: Path) -> bool:
    img = folder / doc["meta"]["image"]
    if not img.exists():
        return False
    info = png.info(img.read_bytes())
    if (info["width"], info["height"]) != (doc["meta"]["size"]["w"], doc["meta"]["size"]["h"]):
        return False
    for f in doc["frames"].values():
        r = f["frame"]
        if r["x"] < 0 or r["y"] < 0 or r["x"] + r["w"] > info["width"] or r["y"] + r["h"] > info["height"]:
            return False
    return all(n in doc["frames"] for seq in doc.get("animations", {}).values() for n in seq)


def normal_map_is_y_down(img: np.ndarray, sheet: dict[str, Any]) -> bool:
    """Semantic check on an inflated-sprite normal map: with DirectX (Y-down) encoding the upper rim of each frame
    has green < 128 and the lower rim green > 128 (the reverse of OpenGL)."""
    votes = []
    for f in sheet["frames"].values():
        r = f["frame"]
        tile = img[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
        a = tile[..., 3] > 0 if tile.shape[2] == 4 else np.ones(tile.shape[:2], bool)
        ys = np.nonzero(a.any(1))[0]
        if ys.size < 8:
            continue
        top, bot = ys[: ys.size // 4], ys[-ys.size // 4:]
        g = tile[..., 1].astype(float)
        votes.append(g[top][a[top]].mean() < g[bot][a[bot]].mean())
    return bool(votes) and sum(votes) >= 0.75 * len(votes)


def godot_spriteframes(sp: ir.Sprite, atlas_res: str) -> str:
    lines = [f'[gd_resource type="SpriteFrames" load_steps={len(sp.frames) + 2} format=3]', "",
             f'[ext_resource type="Texture2D" path="{atlas_res}" id="1_atlas"]', ""]
    for k, (x, y, w, h) in enumerate(sp.frames):
        lines += [f'[sub_resource type="AtlasTexture" id="AtlasTexture_{k:02d}"]', 'atlas = ExtResource("1_atlas")',
                  f"region = Rect2({x}, {y}, {w}, {h})", ""]
    anims = []
    for name, a in sorted(sp.animations.items()) or [("default", {"frames": list(range(len(sp.frames))), "fps": 5, "loop": True})]:
        fr = ", ".join(f'{{"duration": 1.0, "texture": SubResource("AtlasTexture_{i:02d}")}}' for i in a["frames"])
        anims.append(f'{{"frames": [{fr}], "loop": {str(a.get("loop", True)).lower()}, "name": &"{name}", "speed": {float(a.get("fps", 5))}}}')
    lines += ["[resource]", "animations = [" + ", ".join(anims) + "]", ""]
    return "\n".join(lines)


def _atlas(scene: ir.Scene, sp: ir.Sprite) -> np.ndarray:
    a = png.decode(scene.textures[sp.atlas].png)
    return a if a.shape[2] == 4 else np.dstack([a[..., :3], np.full(a.shape[:2], 255, np.uint8)])


# ============================================================================ generic 2D atlas

class Atlas2DAdapter(Adapter):
    id, name, tier, direction = "atlas2d", "PNG atlas + TexturePacker JSON (generic 2D)", "interchange_pack", "export"
    dims, convention, formats = ("2d", "2.5d"), "gltf", ("png-atlas", "texturepacker-json", "png-frames")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            pk.add(f"{_safe(sid)}.png", scene.textures[sp.atlas].png)
            pk.add(f"{_safe(sid)}.json", texturepacker_json(sp, scene, f"{_safe(sid)}.png"))
            for k, fr in enumerate(frames_of(sp, _atlas(scene, sp))):
                pk.add(f"frames/{_safe(sid)}_{k:02d}.png", png.encode(fr))
            for sem, tid in sorted(sp.maps.items()):
                pk.add(f"{_safe(sid)}_{sem}.png", scene.textures[tid].png)
        if scene.layers:
            pk.add("layers.json", json.dumps({"layers": [scene.layers[k].to_dict() | {"screen_px": list(scene.layers[k].screen_position())}
                                                         for k in sorted(scene.layers)]}, indent=2, sort_keys=True))
        return pk.finish(self, scene, sprites=sorted(scene.sprites))

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        tp = all(check_texturepacker_json(json.loads(p.read_text()), out) for p in out.glob("*.json") if p.name not in ("layers.json", "assetfabric_manifest.json"))
        man = read_manifest(out)
        fr_ok = True
        for sid in man["sprites"]:
            doc = json.loads((out / f"{_safe(sid)}.json").read_text())
            atlas = png.decode((out / doc["meta"]["image"]).read_bytes())
            for k, (name, f) in enumerate(sorted(doc["frames"].items())):
                r = f["frame"]
                fr = png.decode((out / f"frames/{_safe(sid)}_{k:02d}.png").read_bytes())
                fr_ok &= bool(np.array_equal(fr, atlas[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]))
        return finish_verify({"texturepacker_json": tp, "frames_match_atlas": fr_ok}, [], out)


# ============================================================================ RPG Maker

TUNICS = [(46, 110, 168), (168, 52, 46), (60, 140, 70), (140, 70, 160), (200, 160, 40), (40, 150, 150), (110, 110, 110), (220, 110, 160)]


def _recolour(img: np.ndarray, tunic: tuple[int, int, int]) -> np.ndarray:
    out = img.copy()
    m = np.all(img[..., :3] == np.array(maps2d.PALETTE["tunic"], np.uint8), -1)
    out[m, :3] = tunic
    return out


def character_block(frame: int, tunic: tuple[int, int, int] = TUNICS[0]) -> np.ndarray:
    rows = [np.concatenate([_recolour(maps2d.character_frame(frame, d, k), tunic) for k in range(3)], 1) for d in maps2d.DIRECTIONS]
    return np.concatenate(rows, 0)


class RpgMakerAdapter(Adapter):
    id, name, tier, direction = "rpgmaker", "RPG Maker MV / MZ / VX Ace", "interchange_pack", "export"
    dims, convention, formats = ("2d",), "gltf", ("png-character-sheet", "png-tileset")
    SPEC = {"mv_mz": {"frame": 48, "tile": 48, "tileset": (768, 768)}, "vx_ace": {"frame": 32, "tile": 32, "tileset": (512, 512)}}

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        sheets = []
        for ver, spec in self.SPEC.items():
            f = spec["frame"]
            single = character_block(f)                                          # $-prefixed: one character, 3×4 frames
            pk.add(f"{ver}/img/characters/$AF_Hero.png", png.encode(single))
            blocks = [character_block(f, TUNICS[i]) for i in range(8)]           # standard: 4×2 characters
            party = np.concatenate([np.concatenate(blocks[r * 4:(r + 1) * 4], 1) for r in range(2)], 0)
            pk.add(f"{ver}/img/characters/AF_Party.png", png.encode(party))
            t = spec["tile"]
            kinds = ("grass", "stone", "water", "dirt")
            cols, rows = spec["tileset"][0] // t, spec["tileset"][1] // t
            ts = np.concatenate([np.concatenate([maps2d.tile(t, kinds[(c + r) % 4], r * cols + c) for c in range(cols)], 1)
                                 for r in range(rows)], 0)
            pk.add(f"{ver}/img/tilesets/AF_Outside_B.png", png.encode(ts))
            sheets.append({"version": ver, "frame": f, "single": [3 * f, 4 * f], "party": [12 * f, 8 * f],
                           "tileset": list(spec["tileset"]), "tile": t})
        # the scene's own sprites whose frames are exactly MV/MZ-sized 3×4 blocks are exported verbatim
        own = []
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            if len(sp.frames) == 12 and all(w == 48 and h == 48 for (_, _, w, h) in sp.frames):
                pk.add(f"mv_mz/img/characters/${_safe(sid)}.png", scene.textures[sp.atlas].png)
                own.append(sid)
        return pk.finish(self, scene, sheets=sheets, scene_sprites=own,
                         naming="'$' prefix = single-character sheet (3×4 frames); no prefix = 8 characters (4×2 blocks)")

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        man = read_manifest(out)
        errs = []
        dims_ok = grid_ok = tiles_ok = True
        for s in man["sheets"]:
            v, f = s["version"], s["frame"]
            single = png.decode((out / f"{v}/img/characters/$AF_Hero.png").read_bytes())
            party = png.decode((out / f"{v}/img/characters/AF_Party.png").read_bytes())
            ts = png.decode((out / f"{v}/img/tilesets/AF_Outside_B.png").read_bytes())
            dims_ok &= list(single.shape[1::-1]) == s["single"] and list(party.shape[1::-1]) == s["party"] and list(ts.shape[1::-1]) == s["tileset"]
            for img in (single, party):                         # every frame cell must contain a character
                for y in range(0, img.shape[0], f):
                    for x in range(0, img.shape[1], f):
                        grid_ok &= bool((img[y:y + f, x:x + f, 3] > 0).sum() > f * f * 0.1)
            tiles_ok &= bool((ts[..., 3] == 255).all()) and ts.shape[0] % s["tile"] == 0
        if not dims_ok:
            errs.append("sheet dimensions differ from the RPG Maker layout")
        return finish_verify({"sheet_dimensions": dims_ok, "every_frame_cell_filled": grid_ok, "tileset_opaque_grid": tiles_ok}, errs, out)


# ============================================================================ Sprite Lamp / Sprite Pro

class SpriteLampAdapter(Adapter):
    id, name, tier, direction = "spritelamp", "Sprite Lamp / Sprite Pro map pack", "interchange_pack", "both"
    dims, convention = ("2d", "2.5d"), "gltf"
    formats = ("png-diffuse", "png-normal", "png-depth", "png-ambient-occlusion", "png-lighting-profiles")
    MAX_PROFILE_ERR_DEG = 12.0

    def export(self, scene: ir.Scene, out: Path, recipe: maps2d.NormalRecipe | None = None) -> dict[str, Any]:
        pk = Pack(out)
        rec = recipe or maps2d.NormalRecipe()
        listing = []
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            atlas = _atlas(scene, sp)
            alpha = atlas[..., 3]
            h = np.zeros(alpha.shape)
            for (x, y, w, hh) in sp.frames:
                h[y:y + hh, x:x + w] = maps2d.height_from_alpha(alpha[y:y + hh, x:x + w], rec)
            n = maps2d.normals_from_height(h, rec.strength)
            nm = _safe(sid)
            pk.add(f"{nm}_Diffuse.png", png.encode(atlas))
            pk.add(f"{nm}_Normal.png", png.encode(maps2d.encode_normals(n, alpha)))
            pk.add(f"{nm}_Depth.png", png.encode(maps2d.depth_map(h, alpha)))
            pk.add(f"{nm}_AmbientOcclusion.png", png.encode(maps2d.ambient_occlusion(h, alpha)))
            for pname, img in maps2d.lighting_profiles(n, alpha).items():
                pk.add(f"{nm}_{pname}.png", png.encode(img))
            listing.append(nm)
        return pk.finish(self, scene, sprites=listing, normal_encoding="tangent space, OpenGL (+Y up)",
                         recipe={"blur": rec.blur, "strength": rec.strength, "dome": rec.dome})

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        man = read_manifest(out)
        errs = []
        size_ok = prof_ok = depth_ok = True
        errs_deg = {}
        for nm in man["sprites"]:
            imgs = {k: png.decode((out / f"{nm}_{k}.png").read_bytes()) for k in
                    ("Diffuse", "Normal", "Depth", "AmbientOcclusion", *maps2d.PROFILE_DIRS)}
            shapes = {v.shape[:2] for v in imgs.values()}
            size_ok &= len(shapes) == 1
            alpha = imgs["Diffuse"][..., 3] > 0
            n_map = maps2d.decode_normals(imgs["Normal"])
            n_rec = maps2d.normals_from_profiles({k: imgs[k] for k in maps2d.PROFILE_DIRS})
            e = maps2d.angular_error_deg(n_map, n_rec, alpha)
            errs_deg[nm] = round(e["mean"], 3)
            prof_ok &= e["mean"] <= self.MAX_PROFILE_ERR_DEG
            d = imgs["Depth"][..., 0].astype(float)
            depth_ok &= bool(d[alpha].mean() > 0) and bool((d[~alpha] == 0).all())
        return finish_verify({"same_size_maps": size_ok, "profiles_consistent_with_normals": prof_ok, "depth_inside_silhouette": depth_ok},
                             errs, out, profile_normal_error_deg=errs_deg)

    def import_(self, path: Path) -> ir.Scene:
        """Ingest Sprite Lamp lighting profiles (`<name>_Left.png` …) → recovered normal map + sprite."""
        path = Path(path)
        base = path.name.rsplit("_", 1)[0]
        profs = {k: png.decode((path.parent / f"{base}_{k}.png").read_bytes()) for k in maps2d.PROFILE_DIRS}
        alpha = profs["Front"][..., 3]
        n = maps2d.normals_from_profiles(profs)
        diffuse = profs["Front"]
        s = ir.Scene(base, "2d", "gltf")
        s.add(ir.Texture(f"{base}_atlas", png.encode(diffuse), "base_color"))
        s.add(ir.Texture(f"{base}_normal", png.encode(maps2d.encode_normals(n, alpha)), "normal", colorspace="linear"))
        s.add(ir.Sprite(base, f"{base}_atlas", [(0, 0, diffuse.shape[1], diffuse.shape[0])], {"normal": f"{base}_normal"}))
        s.add_node(ir.Node(base, sprite=base))
        return s

    def sample_input(self, out: Path) -> Path:
        fr = maps2d.character_frame(48, "down", 1)
        h = maps2d.height_from_alpha(fr[..., 3])
        for k, img in maps2d.lighting_profiles(maps2d.normals_from_height(h), fr[..., 3]).items():
            (Path(out) / f"sample_{k}.png").write_bytes(png.encode(img))
        return Path(out) / "sample_Front.png"


# ============================================================================ Construct 2 / Clickteam Fusion / AppGameKit

class ConstructAdapter(Adapter):
    id, name, tier, direction = "construct", "Construct 2 / 3 sprite strips", "interchange_pack", "export"
    dims, convention, formats = ("2d",), "gltf", ("png-sprite-strip", "json-strip-descriptor")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        strips = []
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            frs = frames_of(sp, _atlas(scene, sp))
            for an, a in sorted(sp.animations.items()) or [("Default", {"frames": list(range(len(frs))), "fps": 5, "loop": True})]:
                img = np.concatenate([frs[i] for i in a["frames"]], 1)
                fn = f"{_safe(sid)}_{_safe(an)}.png"
                pk.add(fn, png.encode(img))
                fw, fh = frs[a["frames"][0]].shape[1], frs[a["frames"][0]].shape[0]
                strips.append({"sprite": sid, "animation": an, "image": fn, "columns": len(a["frames"]), "rows": 1,
                               "frame_w": fw, "frame_h": fh, "speed": a.get("fps", 5), "loop": a.get("loop", True),
                               "origin_px": [round(sp.pivot[0] * fw), round(sp.pivot[1] * fh)]})
        pk.add("construct_strips.json", json.dumps({"strips": strips, "import": "Animations editor > Import sprite strip (H cells = columns, V cells = rows)"},
                                                   indent=2, sort_keys=True))
        return pk.finish(self, scene, strips=len(strips))

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        doc = json.loads((out / "construct_strips.json").read_text())
        ok = True
        for st in doc["strips"]:
            i = png.info((out / st["image"]).read_bytes())
            ok &= i["width"] == st["columns"] * st["frame_w"] and i["height"] == st["rows"] * st["frame_h"]
        return finish_verify({"strip_geometry": ok and bool(doc["strips"])}, [], out)


FUSION_DIR = {"right": 0, "up": 8, "left": 16, "down": 24}           # Fusion: 32 directions, 0 = east, counter-clockwise


class ClickteamAdapter(Adapter):
    id, name, tier, direction = "clickteam", "Clickteam Fusion 2.5 frame sequences", "interchange_pack", "export"
    dims, convention, formats = ("2d",), "gltf", ("png-frame-sequence", "json-hotspots")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        pk = Pack(out)
        entries = []
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            frs = frames_of(sp, _atlas(scene, sp))
            for an, a in sorted(sp.animations.items()):
                m = re.match(r"(\w+?)_(down|left|right|up)$", an)
                anim, d = (m.group(1), m.group(2)) if m else (an, "right")
                folder = f"{_safe(sid)}/{_safe(anim)}/dir{FUSION_DIR[d]:02d}"
                for k, i in enumerate(a["frames"]):
                    pk.add(f"{folder}/frame_{k:03d}.png", png.encode(frs[i]))
                fw, fh = frs[a["frames"][0]].shape[1], frs[a["frames"][0]].shape[0]
                entries.append({"object": sid, "animation": anim, "direction": FUSION_DIR[d], "folder": folder,
                                "frames": len(a["frames"]), "speed": min(100, int(a.get("fps", 5) * 100 / 60)),
                                "hot_spot": [round(sp.pivot[0] * fw), round(sp.pivot[1] * fh)], "action_point": [fw // 2, fh // 3]})
        pk.add("fusion_animations.json", json.dumps({"animations": entries}, indent=2, sort_keys=True))
        return pk.finish(self, scene, animations=len(entries))

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        doc = json.loads((out / "fusion_animations.json").read_text())
        ok = bool(doc["animations"])
        for e in doc["animations"]:
            files = sorted((out / e["folder"]).glob("frame_*.png"))
            ok &= len(files) == e["frames"] and e["direction"] in FUSION_DIR.values()
            info = png.info(files[0].read_bytes())
            ok &= 0 <= e["hot_spot"][0] <= info["width"] and 0 <= e["hot_spot"][1] <= info["height"]
        return finish_verify({"frame_sequences": ok}, [], out)


class AppGameKitAdapter(Adapter):
    id, name, tier, direction = "appgamekit", "AppGameKit (atlas + subimages.txt, OBJ/.x)", "interchange_pack", "export"
    dims, convention, formats = ("2d", "3d"), "directx-yup", ("png-atlas", "agk-subimages-txt", "obj", "x")

    def export(self, scene: ir.Scene, out: Path) -> dict[str, Any]:
        from forge.universal.exporters.three_d import MeshPackAdapter
        pk = Pack(out)
        for sid in sorted(scene.sprites):
            sp = scene.sprites[sid]
            pk.add(f"media/{_safe(sid)}.png", scene.textures[sp.atlas].png)
            lines = [f"{_safe(sid)}_{k:02d}:{x}:{y}:{w}:{h}" for k, (x, y, w, h) in enumerate(sp.frames)]
            pk.add(f"media/{_safe(sid)} subimages.txt", "\n".join(lines) + "\n")
        sub = MeshPackAdapter()
        sub.id, sub.name, sub.write_x = "appgamekit", self.name, True
        tmp = Pack(Path(out) / "media" / "models")
        man3d = sub.export(scene, tmp.out) if scene.meshes else {"meshes": []}
        # fold the sub-pack's files into this pack's manifest
        for rel, meta in man3d.get("files", {}).items():
            pk.files[f"media/models/{rel}"] = meta
        (Path(out) / "media" / "models" / "assetfabric_manifest.json").unlink(missing_ok=True)
        return pk.finish(self, scene, sprites=sorted(scene.sprites), meshes=man3d.get("meshes", []))

    def verify(self, out: Path) -> dict[str, Any]:
        out = Path(out)
        man = read_manifest(out)
        ok = True
        for sid in man["sprites"]:
            info = png.info((out / f"media/{_safe(sid)}.png").read_bytes())
            for ln in (out / f"media/{_safe(sid)} subimages.txt").read_text().splitlines():
                name, x, y, w, h = ln.split(":")
                ok &= int(x) + int(w) <= info["width"] and int(y) + int(h) <= info["height"] and bool(name)
        from forge.universal.exporters.xfile import read_x
        m_ok = all(read_x((out / "media/models" / it["x"]).read_bytes())[0].n_triangles == it["triangles"] for it in man["meshes"])
        return finish_verify({"subimages_txt": ok, "models_x": m_ok}, [], out)


# ============================================================================ ePic Character Generator (import)

class EpicCharGenAdapter(Adapter):
    id, name, tier, direction = "epic-chargen", "ePic Character Generator import", "interchange_pack", "import"
    dims, convention, formats = ("2d",), "gltf", ("png",)

    def import_(self, path: Path) -> ir.Scene:
        """A PNG character render → IR sprite with generated normal / depth / AO maps (ready for any 2D/2.5D target)."""
        img = png.decode(Path(path).read_bytes())
        if img.shape[2] != 4:
            raise ValueError("ePic Character Generator exports must be RGBA PNG (transparent background)")
        name = _safe(Path(path).stem)
        alpha = img[..., 3]
        h = maps2d.height_from_alpha(alpha)
        n = maps2d.normals_from_height(h)
        s = ir.Scene(name, "2d", "gltf")
        s.add(ir.Texture(f"{name}_atlas", png.encode(img), "base_color", "linear"))
        s.add(ir.Texture(f"{name}_normal", png.encode(maps2d.encode_normals(n, alpha)), "normal", "linear", "linear"))
        s.add(ir.Texture(f"{name}_depth", png.encode(maps2d.depth_map(h, alpha)), "depth", "linear", "linear"))
        s.add(ir.Texture(f"{name}_ao", png.encode(maps2d.ambient_occlusion(h, alpha)), "ao", "linear", "linear"))
        s.add(ir.Sprite(name, f"{name}_atlas", [(0, 0, img.shape[1], img.shape[0])],
                        {"normal": f"{name}_normal", "depth": f"{name}_depth", "ao": f"{name}_ao"}, (0.5, 1.0), 100.0))
        s.add_node(ir.Node(name, sprite=name))
        return s

    def sample_input(self, out: Path) -> Path:
        p = Path(out) / "epic_portrait.png"                 # stand-in render from our own generator (not ePic output)
        p.write_bytes(png.encode(maps2d.character_frame(128, "down", 1)))
        return p


def hero_scene_2d() -> ir.Scene:
    return reference.scene_2d()
