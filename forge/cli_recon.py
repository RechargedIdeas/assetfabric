"""`forge mirror | lens | depth | recon …` command groups (C9–C12). Stubs exit 3 with a JSON `{"stub": true, …}` document."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import click

from forge.stubs import StubError

STUB_EXIT = 3


def _emit(obj: Any) -> None:
    click.echo(json.dumps(obj, indent=2, sort_keys=True, default=str))


def _guard(fn: Callable[[], Any]) -> None:
    """Run a command body: print its result; a StubError becomes a labelled refusal (exit 3), other errors exit 1."""
    try:
        _emit(fn())
    except StubError as e:
        _emit({"stub": True, "feature": e.feature, "milestone": e.milestone, "reason_key": e.key, "message": str(e)})
        sys.exit(STUB_EXIT)
    except (ValueError, RuntimeError, PermissionError, OSError) as e:
        _emit({"error": f"{type(e).__name__}: {e}"})
        sys.exit(1)


# --------------------------------------------------------------------------------------------------- mirror (C9)

@click.group("mirror")
def mirror_grp() -> None:
    """MirrorWeave (C9): stills/telemetry stream + allow-listed read-only control over LoomLink. Video/screen/input are stubs."""


@mirror_grp.command("info")
def mirror_info() -> None:
    """What MirrorWeave does (real) and does not do (stub)."""
    from forge import registry
    _emit(registry.descriptor("C9"))


@mirror_grp.command("push")
@click.option("--url", required=True, help="Desktop LoomLink URL (forge link serve --allow offload,sync,mirror,drive_studio).")
@click.option("--code", required=True, help="One-time pairing code shown by `forge link serve`.")
@click.option("--file", "files", type=click.Path(exists=True, dir_okay=False, path_type=Path), multiple=True, required=True)
@click.option("--stream", default="screen")
@click.option("--kind", default="screen", type=click.Choice(["screen", "camera_still", "telemetry"]))
@click.option("--client-id", default="forge-cli")
def mirror_push(url: str, code: str, files: tuple[Path, ...], stream: str, kind: str, client_id: str) -> None:
    """Pair, then push still frames (png/jpeg/webp, or json for telemetry) to the desktop's MirrorWeave sink."""
    from forge.loomlink import LinkClient
    from forge.mirrorweave import StillsSource, sniff

    def run() -> Any:
        c = LinkClient(url, client_id)
        c.pair(code, ["mirror"])
        out = []
        for f in files:
            data = f.read_bytes()
            codec = next((k for k in ("png", "jpeg", "webp", "json") if sniff(k, data)), None)
            if codec is None:
                raise ValueError(f"{f.name}: not png/jpeg/webp/json")
            src = StillsSource(stream, [data], kind, codec, start_seq=len(out) + _seq_offset(c, stream))
            out += [c.mirror_frame(e) for e in src.frames()]
        return out
    _guard(run)


def _seq_offset(c: Any, stream: str) -> int:
    st = c.mirror_latest(stream).get("stats", {}).get(stream)
    return (st["last_seq"] + 1) if st else 0


@mirror_grp.command("latest")
@click.option("--state-dir", type=click.Path(path_type=Path), required=True, help="LoomLink state dir (<dir>/mirror/<stream>/latest.*).")
@click.option("--stream", default="screen")
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Write the latest frame's bytes here.")
def mirror_latest(state_dir: Path, stream: str, out: Path | None) -> None:
    """Read the newest persisted frame of a stream on this desktop."""
    from forge.mirrorweave import load_persisted

    def run() -> Any:
        got = load_persisted(state_dir / "mirror", stream)
        if got is None:
            raise ValueError(f"no frames for stream {stream!r}")
        meta, data = got
        if out:
            out.write_bytes(data)
        return meta
    _guard(run)


@mirror_grp.command("stream")
@click.option("--source", type=click.Choice(["screen", "camera-video"]), required=True)
def mirror_stream(source: str) -> None:
    """Live screen/video streaming — STUB (refuses, exit 3)."""
    from forge import mirrorweave

    def run() -> Any:
        s = mirrorweave.ScreenCaptureSource() if source == "screen" else mirrorweave.VideoStreamSource()
        return next(s.frames())
    _guard(run)


@mirror_grp.command("control")
@click.option("--target", type=click.Choice(["android", "desktop"]), required=True)
@click.option("--action", type=click.Choice(["query", "input", "focus"]), default="query")
@click.option("--name", default="forge.status")
@click.option("--url", default=None)
@click.option("--code", default=None)
@click.option("--client-id", default="forge-cli")
def mirror_control(target: str, action: str, name: str, url: str | None, code: str | None, client_id: str) -> None:
    """Remote control. target=android is a STUB (refuses locally). target=desktop pairs (drive_studio) and runs an allow-listed query."""
    from forge.loomlink import LinkClient
    from forge.mirrorweave import AndroidController, ControlMessage

    def run() -> Any:
        msg = ControlMessage(target, action, name)
        if target == "android":
            return AndroidController().send(msg)
        if not (url and code):
            raise ValueError("--url and --code are required for target=desktop")
        c = LinkClient(url, client_id)
        c.pair(code, ["drive_studio"])
        return c.mirror_control(msg)
    _guard(run)


# --------------------------------------------------------------------------------------------------- lens (C10)

@click.group("lens")
def lens_grp() -> None:
    """LensForge (C10): capture modes, per-image/per-set quality, telemetry. ARCore/video/focus are stubs."""


@lens_grp.command("modes")
def lens_modes() -> None:
    from forge import lensforge
    _emit(lensforge.load_profiles())


@lens_grp.command("assess")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--mode", default="still")
def lens_assess(files: tuple[Path, ...], mode: str) -> None:
    """Quality of one image (or, with several files, of the capture set) against a capture mode. Advisory."""
    from forge import lensforge

    def run() -> Any:
        if len(files) == 1:
            return lensforge.assess(files[0].read_bytes(), mode)
        return lensforge.assess_set([f.read_bytes() for f in files], mode)
    _guard(run)


@lens_grp.command("exif")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def lens_exif(file: Path) -> None:
    """Capture telemetry read from EXIF (missing tags stay absent)."""
    from forge import lensforge
    _guard(lambda: lensforge.read_exif(file.read_bytes()).to_dict())


@lens_grp.command("session")
@click.option("--kind", type=click.Choice(["arcore", "video", "focus"]), required=True)
def lens_session(kind: str) -> None:
    """ARCore / video capture / focus control — STUB (refuses, exit 3)."""
    from forge import lensforge

    def run() -> Any:
        if kind == "arcore":
            return lensforge.ARCoreSession().start()
        if kind == "video":
            return lensforge.VideoCapture().start()
        return lensforge.FocusController().set_focus(1.0)
    _guard(run)


# --------------------------------------------------------------------------------------------------- depth (C11)

@click.group("depth")
def depth_grp() -> None:
    """Metric depth (C11): pinhole monocular distance + scale alignment are real; dense DepthAnything V2 / ARCore are stubs."""


@depth_grp.command("distance")
@click.option("--size-m", type=float, required=True, help="Real size of the object (metres).")
@click.option("--size-px", type=float, required=True, help="Its extent in the image (pixels).")
@click.option("--width-px", type=int, required=True, help="Image width (pixels).")
@click.option("--focal-mm", type=float, default=None)
@click.option("--sensor-width-mm", type=float, default=None)
@click.option("--focal-35mm", type=float, default=None)
@click.option("--hfov-deg", type=float, default=None)
@click.option("--err-px", type=float, default=1.0)
def depth_distance(size_m: float, size_px: float, width_px: int, focal_mm: float | None, sensor_width_mm: float | None,
                   focal_35mm: float | None, hfov_deg: float | None, err_px: float) -> None:
    """Distance to an object of known size (pinhole). Needs optics; refuses rather than guessing a focal length."""
    from forge import depth

    def run() -> Any:
        f = depth.focal_px(width_px, focal_mm, sensor_width_mm, focal_35mm, hfov_deg)
        return {"focal_px": f, **depth.distance_to_object(size_m, size_px, f, err_px)}
    _guard(run)


@depth_grp.command("estimate")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--backend", type=click.Choice(["depthanything", "arcore"]), default="depthanything")
def depth_estimate(file: Path, backend: str) -> None:
    """Dense depth map — STUB (refuses, exit 3): no model or SDK is bundled."""
    from forge import depth

    def run() -> Any:
        est = depth.DepthAnythingV2() if backend == "depthanything" else depth.ARCoreDepth()
        return est.estimate(file.read_bytes())
    _guard(run)


# --------------------------------------------------------------------------------------------------- recon (C12)

@click.group("recon")
def recon_grp() -> None:
    """RealityLoom / SplatForge path (C12): routing, bundle, plan, placement, .ply check are real; training/meshing are stubs."""


@recon_grp.command("route")
@click.argument("target", type=click.Choice(["backdrop", "hero_prop"]))
def recon_route(target: str) -> None:
    from forge import realityloom
    _emit(realityloom.route(target))


@recon_grp.command("tools")
def recon_tools() -> None:
    """Which reconstruction binaries exist on this host (none are bundled)."""
    from forge import realityloom
    _emit(realityloom.detect_tools())


def _images(files: tuple[Path, ...]) -> list[bytes]:
    return [f.read_bytes() for f in files]


@recon_grp.command("bundle")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--target", type=click.Choice(["backdrop", "hero_prop"]), required=True)
@click.option("--mode", default="sweep")
@click.option("--out", type=click.Path(path_type=Path), required=True)
def recon_bundle(files: tuple[Path, ...], target: str, mode: str, out: Path) -> None:
    """Write a content-addressed capture bundle (objects/ + bundle.json) — the input contract of every reconstruction backend."""
    from forge import realityloom
    _guard(lambda: realityloom.write_bundle(out, _images(files), target, mode))


@recon_grp.command("plan")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--target", type=click.Choice(["backdrop", "hero_prop"]), required=True)
@click.option("--mode", default="sweep")
@click.option("--devices", default=None, help="Comma list of devices the fleet offers; default = this host (GroundWeave detection).")
@click.option("--cluster", "cluster_url", default=None, help="LoomCluster node URL: devices are what its nodes advertise.")
def recon_plan(files: tuple[Path, ...], target: str, mode: str, devices: str | None, cluster_url: str | None) -> None:
    """What RealityLoom would do with this capture set, what blocks it today (stubs), and an honest ETA class."""
    from forge import groundweave, realityloom

    def run() -> Any:
        m = realityloom.bundle_manifest(_images(files), target, mode)
        if cluster_url:
            devs = sorted({d for ds in realityloom.cluster_devices(cluster_url).values() for d in ds})
        else:
            devs = devices.split(",") if devices else groundweave.detect_devices()
        return realityloom.plan(m, devs)
    _guard(run)


@recon_grp.command("submit")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--target", type=click.Choice(["backdrop", "hero_prop"]), required=True)
@click.option("--mode", default="sweep")
@click.option("--cluster", "cluster_url", required=True)
def recon_submit(files: tuple[Path, ...], target: str, mode: str, cluster_url: str) -> None:
    """Try to run reconstruction on a cluster: real GPU-placement check, then the SplatForge STUB refusal (nothing is queued)."""
    from forge import realityloom

    def run() -> Any:
        return realityloom.submit(realityloom.bundle_manifest(_images(files), target, mode), cluster_url)
    _guard(run)


@recon_grp.command("check-splat")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def recon_check_splat(file: Path) -> None:
    """Validate a 3D Gaussian Splatting .ply (INRIA/OpenSplat layout)."""
    from forge import realityloom
    _guard(lambda: realityloom.check_splat_ply(file.read_bytes()))


@recon_grp.command("train")
@click.option("--stage", type=click.Choice(["splat", "photogrammetry", "mesh", "godot-import"]), default="splat")
def recon_train(stage: str) -> None:
    """Train / reconstruct / mesh / import — STUB (refuses, exit 3). Nothing here fabricates a reconstruction."""
    from forge import realityloom

    def run() -> Any:
        if stage == "splat":
            return realityloom.SplatForge().train({})
        if stage == "photogrammetry":
            return realityloom.Photogrammetry().run({})
        if stage == "mesh":
            return realityloom.MeshWeaver().convert(Path("x.ply"))
        return realityloom.GdgsImport().into_godot(Path("x.ply"), Path("."))
    _guard(run)
