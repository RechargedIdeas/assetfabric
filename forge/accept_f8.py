"""F8 acceptance: "Retro / console-style" (ASSETFABRIC_SPEC §13 F8 — optional, scope confirmed by the Producer, t59u).

What the spec defines for F8 and where it is proven (docs/acceptance-tests/F8.md has the full mapping):
  §6.1 ForgeConsole path (1) "real ROMs in emulators" — Console Profile Registry, ConstraintCompiler/AssetTranscoder
       (+ C1 sub-palette solver), CodeGen/ROMBuilder (own 6502 assembler), EmulatorHarness (cynes, headless);
  §6.1 path (2) "console-style Godot authenticity profiles/shaders" + GAME_SPEC §4.6 global pixelation/quantisation
       post-process — R1 Retro Render Compiler data (LUTs), the in-game post-process, Q1 Pixel Stability (camera/scale
       policy + shimmer predictor), V1 Retro Validation Harness (frame gates), R2 authenticity (fidelity delta +
       discriminator), ConsoleReadiness budgets (§3 Layer A), C1 cycle predictor (NMI vblank budget);
  console-first input (GAME_SPEC §3 cross-input): the whole flow is driven with a gamepad only.
Deferred by the spec and not built: fantasy consoles (PICO-8/TIC-80), CertPack / licensed console SKUs.

Checks (both modes; F8 has no slow half — the whole run is ~30 s):
 1. registry + R1 data — the `retro` generator's gates (registry, exact LUT bins, a11y signal pairs, Q1 policy).
 2. ConsoleReadiness — every shipped sprite + area tileset fits each profile's tile / sub-palette / CHR / VRAM budget.
 3. ROMBuilder — iNES NROM ROM built twice byte-identically; PRG/CHR/RAM/OAM/scanline/NMI-cycle budgets.
 4. EmulatorHarness — the ROM boots in cynes without a CPU jam; boot frame = reference render (bijective colour
    partition, every pixel); d-pad moves the party in all four directions with walk frames + facing; deterministic.
 5. Console-first flow (headless Godot): pad Start → Settings → display style → nes-style live (integer stretch, Q1
    camera zoom) → scanlines on/off → colour-blind palette inside the retro pass → pad B → pad A starts → pad walks
    the leader → settings in the save; a fresh process restores them.
 6. V1 frames (Godot under Xvfb, skipped without a display): per profile × palette — block uniformity 1.0, palette
    conformance 1.0, shader output == forge's model pixel-for-pixel, sub-pixel motion leaves the frame identical (Q1),
    the colour-blind variant changes the frame, scanline structure (nes), `off` = untouched modern frame.
 7. R2 — discriminator held-out accuracy and a score per retro capture; fidelity delta (ΔE) of the transcoded art.
 8. Presentation only — the F2 first-combat run gives the same state hash under every profile (no gameplay change).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from forge.accept_f4 import _godot_argv

R2_MIN_HOLDOUT = 0.95
FIDELITY_MAX_MEAN_DE = {"nes-style": 25.0, "gb-style": 12.0}    # [INFERENCE F8-9] ceilings over today's values


def _retrocheck(argv: list[str], timeout: int = 180) -> dict[str, Any]:
    from forge.milestones import parse_output

    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    r = parse_output(p.stdout + p.stderr).get("retro", {})
    r["_exit"] = p.returncode
    r["_script_errors"] = (p.stdout + p.stderr).count("SCRIPT ERROR")
    return r


def generator_part(root: Path) -> dict[str, Any]:
    from forge.generators import load_all
    from forge.pipeline import Context, load_briefs

    ctx = Context.create(root)
    brief = next(b for b in load_briefs(root) if b["kind"] == "retro")
    out = load_all()["retro"](brief, ctx)
    on_disk = {}
    gen = root / "games" / "game-zero" / "assets" / "generated" / "retro"
    for a in out.artifacts:
        f = gen / a.name
        on_disk[a.name] = f.exists() and f.read_bytes() == a.data
    return {"gates": {g.gate: g.ok for g in out.gates}, "details": {g.gate: g.details for g in out.gates if not g.ok},
            "artifacts_match_tree": on_disk, "c1_overrides": out.meta.get("c1_overrides"),
            "collapsed_with_shape_cue": out.meta.get("collapsed_with_shape_cue")}


def rom_part(root: Path) -> dict[str, Any]:
    from forge.retro import emulator, profiles, readiness, rom

    profs = profiles.load(root)
    out: dict[str, Any] = {"readiness": {pid: readiness.check(root, p) for pid, p in profs.items()}}
    for pid, p in profs.items():
        if not p.rom:
            continue
        a, b = rom.build(root, p), rom.build(root, p)
        r: dict[str, Any] = {"profile": pid, "bytes": len(a.rom), "sha256": a.sha256, "deterministic": a.rom == b.rom,
                             "report": a.report, "budgets": readiness.check_rom(a, p)}
        if emulator.available():
            em = emulator.run(a, p)
            em.pop("frame0", None)
            r["emulator"] = em
        else:
            r["emulator"] = {"skipped": "cynes not installed (pip install cynes)"}
        out.setdefault("roms", {})[pid] = r
    return out


def godot_part(root: Path, tmp: Path) -> dict[str, Any]:
    d = tmp / "retro"
    conf = _retrocheck(_godot_argv(root, "--scene=retrocheck", "--phase=configure", f"--save-dir={d}"))
    ver = _retrocheck(_godot_argv(root, "--scene=retrocheck", "--phase=verify", f"--save-dir={d}"))
    return {"configure": {k: conf.get(k) for k in ("steps", "errors", "_exit", "_script_errors")},
            "verify": {k: ver.get(k) for k in ("steps", "errors", "settings", "_exit", "_script_errors")}}


def render_part(root: Path, tmp: Path) -> dict[str, Any]:
    from forge.manifest import load_manifest
    from forge.milestones import godot_binary
    from forge.retro import png, profiles, validate as V

    xvfb = shutil.which("xvfb-run")
    if not xvfb:
        return {"skipped": "no xvfb-run on this host"}
    project = root / load_manifest(None, root).game.project_path
    cap = tmp / "retro-cap"
    cap.mkdir(parents=True, exist_ok=True)
    argv = [xvfb, "-a", "-s", "-screen 0 1280x720x24", godot_binary(root) or "godot", "--path", str(project),
            "--rendering-driver", "opengl3", "--", "--scene=retrocheck", "--phase=render", f"--save-dir={tmp / 'retro-r'}",
            f"--capture={cap / 'c'}"]
    rc = _retrocheck(argv, timeout=240)
    res: dict[str, Any] = {"display": rc.get("display"), "errors": rc.get("errors"), "_exit": rc.get("_exit"),
                           "_script_errors": rc.get("_script_errors"), "frames": {}}
    caps = rc.get("captures") or {}
    tables = rc.get("a11y_tables") or {}
    profs = profiles.load(root)
    gen = root / "games" / "game-zero" / "assets" / "generated" / "retro"
    from forge.retro import transcode as T

    art = [T.load_rgba(p) for p in sorted((root / "games/game-zero/assets/generated/sprite").glob("spr_*.png"))]
    models = {}
    retro_frames: dict[str, np.ndarray] = {}
    for key, meta in sorted(caps.items()):
        pid, var = meta["profile"], meta["palette"]
        src = png.read(cap / f"c_{key}_source.png")
        ret = png.read(cap / f"c_{key}_retro.png")
        row: dict[str, Any] = {"camera": meta.get("camera"), "zoom": meta.get("zoom"), "size": list(ret.shape[:2][::-1])}
        if pid == "off":
            row["unchanged_vs_source"] = V.exact_match(ret, src)
            res["frames"][key] = row
            continue
        p = profs[pid]
        lut = png.read(gen / f"{pid}_lut.png")[..., :3]
        remap = [tuple(x) for x in tables.get(var, [])] if var != "default" else None
        model = V.model_pass(src, p.scale, lut, remap)
        row.update({
            "scale": p.scale, "block_uniformity": V.block_uniformity(ret, p.scale),
            "palette_conformance": V.palette_conformance(ret, p.palette),
            "shader_exact": V.exact_match(ret, model),
            "subpixel_identical": V.exact_match(ret, png.read(cap / f"c_{key}_subpixel.png")),
            "colours_on_screen": int(len(np.unique(ret[..., :3].reshape(-1, 3), axis=0))),
        })
        if remap:
            row["a11y_changes_frame"] = 1.0 - V.exact_match(model, V.model_pass(src, p.scale, lut, None))
            row["a11y_effect_required"] = p.match == "lab"     # a 4-shade lightness profile may legitimately absorb
            #                                                    the hue swap; its signal pairs are gated by the generator
        if (cap / f"c_{key}_scan.png").exists():
            row["scanlines"] = V.scanline_structure(ret, png.read(cap / f"c_{key}_scan.png"), p.scale,
                                                    float(meta.get("scanline_strength", 0.35)))
        if pid not in models:
            models[pid] = V.train_discriminator(art, p.palette, lut, p.scale)
        row["r2_authenticity"] = V.authenticity(ret, p.scale, p.palette, models[pid])
        retro_frames[key] = ret
        res["frames"][key] = row
    res["r2"] = {pid: {k: m[k] for k in ("holdout_accuracy", "train", "holdout")} for pid, m in models.items()}
    if "off__default" in caps and models:     # a non-retro control: the modern frame, judged as nes-style
        off = png.read(cap / "c_off__default_retro.png")
        p = profs["nes-style"]
        res["r2_control_modern_as_nes"] = V.authenticity(off, p.scale, p.palette, models["nes-style"])
    return res


def invariance_part(root: Path) -> dict[str, Any]:
    from forge.milestones import INCREMENTS, parse_output, run_godot
    from forge.retro import profiles

    args = INCREMENTS["F2"].godot_args
    rows = {}
    for pid in ["off", *profiles.order(root)[1:]]:
        code, out = run_godot(root, args + ((f"--retro={pid}",) if pid != "off" else ()))
        r = parse_output(out)
        rows[pid] = {"exit": code, "state_hash": r.get("state_hash"), "outcome": r.get("outcome")}
    hashes = {v["state_hash"] for v in rows.values()}
    return {"runs": rows, "identical": len(hashes) == 1 and None not in hashes}


def f8_run(root: Path) -> tuple[int, dict[str, Any]]:
    import time

    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        result: dict[str, Any] = {"generator": generator_part(root)}
        result["timing_s"] = {"generator": round(time.perf_counter() - t0, 2)}
        t = time.perf_counter()
        result.update(rom_part(root))
        result["timing_s"]["rom_readiness_emulator"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        result["console_first"] = godot_part(root, tmp)
        result["invariance"] = invariance_part(root)
        result["timing_s"]["godot_headless"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        result["render"] = render_part(root, tmp)
        result["timing_s"]["render_v1_r2"] = round(time.perf_counter() - t, 2)
    result["timing_s"]["total"] = round(time.perf_counter() - t0, 2)
    return 0, result


def f8_check(r: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    g = r.get("generator", {})
    for gate, ok in (g.get("gates") or {}).items():
        if not ok:
            errs.append(f"retro generator gate {gate} failed: {g.get('details', {}).get(gate)}")
    if not g.get("gates"):
        errs.append("retro generator produced no gates")
    stale = [k for k, v in (g.get("artifacts_match_tree") or {}).items() if not v]
    if stale:
        errs.append(f"generated retro files out of date (run `forge build`): {stale}")
    for pid, rd in (r.get("readiness") or {}).items():
        if not rd.get("ok"):
            errs.append(f"ConsoleReadiness {pid}: {rd.get('errors')}")
        lim = FIDELITY_MAX_MEAN_DE.get(pid)
        fid = (rd.get("fidelity") or {}).get("sprites") or {}
        if lim is not None and fid.get("mean_de_console", 1e9) > lim:
            errs.append(f"R2 fidelity {pid}: mean {fid.get('mean_de_console')} > {lim}")
    roms = r.get("roms") or {}
    if not roms:
        errs.append("no ROM built")
    for pid, rr in roms.items():
        if not rr.get("deterministic"):
            errs.append(f"ROM {pid} not byte-identical across builds")
        if not rr.get("budgets", {}).get("ok"):
            errs.append(f"ROM {pid} budgets: {rr.get('budgets', {}).get('errors')}")
        em = rr.get("emulator") or {}
        if "skipped" in em:
            errs.append(f"EmulatorHarness skipped: {em['skipped']}")
            continue
        boot = em.get("boot") or {}
        if boot.get("crashed") or em.get("crashed"):
            errs.append("ROM jammed the CPU in the emulator")
        if boot.get("match") != 1.0 or not boot.get("bijective"):
            errs.append(f"boot frame != reference render: {boot}")
        for mv in em.get("moves") or []:
            want = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}[mv["input"]]
            along = mv["moved"][0] * want[0] + mv["moved"][1] * want[1]
            if mv.get("match") != 1.0 or not mv.get("bijective") or not 26 <= along <= 32:
                errs.append(f"d-pad {mv['input']}: moved {mv['moved']} match {mv.get('match')}")
        if len(em.get("walk_frames_seen") or []) < 2:
            errs.append(f"walk animation not seen: {em.get('walk_frames_seen')}")
        if (em.get("release") or {}).get("match") != 1.0 or (em.get("release") or {}).get("frame") != 0:
            errs.append(f"release (idle) frame mismatch: {em.get('release')}")
        if not em.get("deterministic"):
            errs.append("emulator run not deterministic")
    cf = r.get("console_first") or {}
    for ph in ("configure", "verify"):
        x = cf.get(ph) or {}
        if x.get("errors") or not x.get("steps") or x.get("_exit") or x.get("_script_errors"):
            errs.append(f"console-first {ph}: errors={x.get('errors')} exit={x.get('_exit')} script_errors={x.get('_script_errors')}")
    inv = r.get("invariance") or {}
    if not inv.get("identical"):
        errs.append(f"retro profiles changed gameplay: {inv.get('runs')}")
    rd = r.get("render") or {}
    if "skipped" not in rd:
        if rd.get("errors") or rd.get("_exit") or rd.get("_script_errors"):
            errs.append(f"render phase: errors={rd.get('errors')} exit={rd.get('_exit')}")
        frames = rd.get("frames") or {}
        if len(frames) < 7:
            errs.append(f"expected 7 captures (3 profiles × 2 palettes + off), got {len(frames)}")
        for k, f in frames.items():
            if k.startswith("off__"):
                if f.get("unchanged_vs_source") != 1.0:
                    errs.append(f"{k}: modern presentation changed")
                continue
            for m in ("block_uniformity", "palette_conformance", "shader_exact", "subpixel_identical"):
                if f.get(m) != 1.0:
                    errs.append(f"V1 {k}: {m}={f.get(m)}")
            if f.get("a11y_effect_required") and not f.get("a11y_changes_frame", 0) > 0:
                errs.append(f"V1 {k}: colour-blind variant had no effect in the retro pass")
            sc = f.get("scanlines")
            if sc and (sc["top_rows_unchanged"] != 1.0 or sc["bottom_rows_darkened"] != 1.0):
                errs.append(f"V1 {k}: scanline structure {sc}")
            if f.get("r2_authenticity", 0) < 0.5:
                errs.append(f"R2 {k}: authenticity {f.get('r2_authenticity')} < 0.5")
        for pid, m in (rd.get("r2") or {}).items():
            if m["holdout_accuracy"] < R2_MIN_HOLDOUT:
                errs.append(f"R2 discriminator {pid}: held-out accuracy {m['holdout_accuracy']} < {R2_MIN_HOLDOUT}")
    return errs


def f8_perf(r: dict[str, Any]) -> dict[str, Any]:
    roms = r.get("roms") or {}
    rr = next(iter(roms.values()), {})
    em = rr.get("emulator") or {}
    frames = (r.get("render") or {}).get("frames") or {}
    return {
        "profiles": sorted((r.get("readiness") or {}).keys()),
        "rom_bytes": rr.get("bytes"), "rom_sha256": rr.get("sha256"),
        "rom_prg_used": (rr.get("report") or {}).get("prg_used"),
        "rom_nmi_cycles": (rr.get("report") or {}).get("nmi_cycles"),
        "rom_chr_tiles": [(rr.get("report") or {}).get("chr_bg_tiles"), (rr.get("report") or {}).get("chr_sprite_tiles")],
        "emulator_boot_match": (em.get("boot") or {}).get("match"),
        "emulator_moves": [m["moved"] for m in em.get("moves") or []],
        "fidelity_mean_de": {pid: ((x.get("fidelity") or {}).get("sprites") or {}).get("mean_de_console")
                             for pid, x in (r.get("readiness") or {}).items()},
        "v1_frames_checked": sum(1 for k in frames if not k.startswith("off__")),
        "r2_holdout": {pid: m["holdout_accuracy"] for pid, m in ((r.get("render") or {}).get("r2") or {}).items()},
        "r2_min_capture": min((f.get("r2_authenticity", 1.0) for k, f in frames.items() if not k.startswith("off__")), default=None),
        "r2_control_modern_as_nes": (r.get("render") or {}).get("r2_control_modern_as_nes"),
        "timing_s": r.get("timing_s"),
    }
