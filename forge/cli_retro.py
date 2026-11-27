"""`forge retro …` — F8 ForgeConsole: profiles, ConsoleReadiness, ROM build, emulator proof, shimmer predictor."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from forge.cli_recon import _guard
from forge.paths import find_repo_root


@click.group("retro")
def retro_grp() -> None:
    """Retro / console-style path (F8): Console Profile Registry, R1/Q1/V1/R2, ConsoleReadiness, ROMBuilder, EmulatorHarness."""


@retro_grp.command("profiles")
def retro_profiles() -> None:
    """The Console Profile Registry (content/retro/profiles.yaml) resolved: logical size, integer scale, palette size."""
    from forge.retro import profiles

    def run() -> Any:
        root = find_repo_root()
        return {pid: p.table() | {"constraints": p.constraints, "memory": p.memory, "rom": bool(p.rom)}
                for pid, p in profiles.load(root).items()}
    _guard(run)


@retro_grp.command("readiness")
@click.option("--profile", "pid", default="", help="One profile (default: all).")
def retro_readiness(pid: str) -> None:
    """ConsoleReadiness: shipped sprites + area tilesets vs each profile's tile / sub-palette / CHR / VRAM budgets."""
    from forge.retro import profiles, readiness

    def run() -> Any:
        root = find_repo_root()
        return {k: readiness.check(root, p) for k, p in profiles.load(root).items() if not pid or k == pid}
    _guard(run)


@retro_grp.command("rom")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=Path("dist/retro/game-zero-field.nes"),
              show_default=True, help="Where to write the iNES ROM (dist/ is git-ignored).")
@click.option("--chr-preview", is_flag=True, help="Also write the CHR tables as a PNG next to the ROM.")
def retro_rom(out: Path, chr_preview: bool) -> None:
    """Build the Game Zero field-demo NES ROM from Fabric content (AssetTranscoder + C1 + 6502 ROMBuilder)."""
    from forge.retro import profiles, readiness, rom

    def run() -> Any:
        root = find_repo_root()
        p = next(x for x in profiles.load(root).values() if x.rom)
        rb = rom.build(root, p)
        dest = out if out.is_absolute() else root / out
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(rb.rom)
        res: dict[str, Any] = {"rom": str(dest), "bytes": len(rb.rom), "sha256": rb.sha256, "report": rb.report,
                               "budgets": readiness.check_rom(rb, p)}
        if chr_preview:
            import numpy as np

            from forge.retro import png
            grey = np.array([[0, 0, 0], [85, 85, 85], [170, 170, 170], [255, 255, 255]], dtype=np.uint8)
            img = np.zeros((128, 256, 3), dtype=np.uint8)
            for half, tiles in enumerate((rb.background.tiles, rb.sprites.tiles)):
                for k, t in enumerate(tiles[:256]):
                    y, x = (k // 16) * 8, half * 128 + (k % 16) * 8
                    img[y:y + 8, x:x + 8] = grey[t]
            prev = dest.with_suffix(".chr.png")
            png.write(prev, img)
            res["chr_preview"] = str(prev)
        return res
    _guard(run)


@retro_grp.command("emulate")
@click.option("--frames-png", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the boot frame as a PNG.")
def retro_emulate(frames_png: Path | None) -> None:
    """Boot the ROM in the headless EmulatorHarness (cynes) and prove frames + d-pad input against the reference."""
    from forge.retro import emulator, profiles, rom

    def run() -> Any:
        if not emulator.available():
            raise RuntimeError("cynes is not installed: pip install cynes (dev extra)")
        root = find_repo_root()
        p = next(x for x in profiles.load(root).values() if x.rom)
        res = emulator.run(rom.build(root, p), p)
        f0 = res.pop("frame0")
        if frames_png:
            from forge.retro import png
            png.write(frames_png, f0)
            res["boot_png"] = str(frames_png)
        return res
    _guard(run)


@retro_grp.command("shimmer")
@click.argument("texel_scale", type=float)
@click.option("--snap/--no-snap", default=True, help="Whole-logical-pixel positions (the Q1 camera policy).")
def retro_shimmer(texel_scale: float, snap: bool) -> None:
    """Q1 shimmer predictor: logical pixels per texel → shimmer (shape changes per step) + texel loss."""
    from forge.retro.validate import shimmer
    _guard(lambda: shimmer(texel_scale, snap))
