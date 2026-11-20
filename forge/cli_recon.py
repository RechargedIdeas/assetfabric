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
    """MirrorWeave (C9): stills / CPU video / desktop capture over LoomLink (HTTP or signed WebSocket), desktop → phone input
    and focus (queued, signed per event), phone → Studio input, allow-listed read-only queries."""


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
@click.option("--state-dir", type=click.Path(path_type=Path), required=True, help="LoomLink state dir (<dir>/mirror/<stream>/…).")
@click.option("--stream", default="screen")
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Write the latest still (or decoded video picture, PNG).")
def mirror_latest(state_dir: Path, stream: str, out: Path | None) -> None:
    """Read the newest persisted frame of a stream on this desktop (video streams are decoded with the system ffmpeg)."""
    import json as _json

    from forge.mirrorweave import decode_latest, load_persisted

    def run() -> Any:
        meta_p = state_dir / "mirror" / stream / "latest.meta.json"
        if not meta_p.exists():
            raise ValueError(f"no frames for stream {stream!r}")
        meta = _json.loads(meta_p.read_text(encoding="utf-8"))
        data = decode_latest(state_dir / "mirror", stream) if meta.get("keyframe") is not None else load_persisted(state_dir / "mirror", stream)[1]
        if out and data:
            out.write_bytes(data)
        return meta
    _guard(run)


@mirror_grp.command("stream")
@click.option("--source", type=click.Choice(["desktop", "desktop-video"]), required=True,
              help="desktop = X11 screen stills (PNG); desktop-video = X11 screen as CPU VP8/VP9 video.")
@click.option("--url", required=True, help="Desktop LoomLink URL of the receiver.")
@click.option("--code", required=True, help="One-time pairing code shown by the receiver's `forge link serve`.")
@click.option("--ws", "ws_url", default=None, help="Receiver's MirrorWeave WebSocket URL (forge link serve --ws-port); else HTTP.")
@click.option("--display", default=None, help="X11 display (default $DISPLAY).")
@click.option("--fps", default=5, type=int)
@click.option("--frames", "n", default=50, type=int, help="Stop after N frames.")
@click.option("--codec", default="vp8", type=click.Choice(["vp8", "vp9"]))
@click.option("--size", default=None, help="WxH capture region (video needs even sizes).")
@click.option("--stream", default=None)
@click.option("--client-id", default="forge-cli")
def mirror_stream(source: str, url: str, code: str, ws_url: str | None, display: str | None, fps: int, n: int, codec: str,
                  size: str | None, stream: str | None, client_id: str) -> None:
    """Capture this desktop's screen and stream it to a paired MirrorWeave receiver."""
    from forge import mirrorweave
    from forge.loomlink import LinkClient

    def run() -> Any:
        c = LinkClient(url, client_id)
        c.pair(code, ["mirror"])
        if source == "desktop":
            src: Any = mirrorweave.DesktopScreenSource(stream or "desktop", display, fps, n)
        else:
            w, h = (int(v) for v in size.split("x")) if size else (0, 0)
            src = mirrorweave.VideoStreamSource(stream or "desktop-video", codec, w, h, fps, display=display, n=n)
        acks = []
        if ws_url:
            from forge.mirrorws import MirrorWsClient
            with MirrorWsClient(ws_url, c) as ws:
                acks = [ws.send(e) for e in src.frames()]
        else:
            acks = [c.mirror_frame(e) for e in src.frames()]
        return {"frames": len(acks), "last": acks[-1] if acks else None}
    _guard(run)


@mirror_grp.command("input")
@click.option("--state-dir", type=click.Path(path_type=Path), required=True, help="State dir of the running `forge link serve`.")
@click.option("--device", required=True, help="Paired phone's client id.")
@click.argument("event", type=click.Choice(["tap", "long_press", "swipe", "key", "text", "focus"]))
@click.option("--x", type=float)
@click.option("--y", type=float)
@click.option("--x2", type=float)
@click.option("--y2", type=float)
@click.option("--duration-ms", type=int)
@click.option("--key", "key_name", default=None)
@click.option("--text", default=None)
@click.option("--mode", default="auto", type=click.Choice(["auto", "manual", "lock", "unlock"]))
@click.option("--distance-m", type=float)
def mirror_input(state_dir: Path, device: str, event: str, x: float | None, y: float | None, x2: float | None, y2: float | None,
                 duration_ms: int | None, key_name: str | None, text: str | None, mode: str, distance_m: float | None) -> None:
    """Queue a desktop → phone event (coordinates normalised 0..1). The phone's PocketLoom remote-control service polls it;
    each event is HMAC-signed with that phone's pairing key at delivery."""
    from forge.mirrorweave import AndroidController, ControlMessage

    def run() -> Any:
        args = {k: v for k, v in {"x": x, "y": y, "x2": x2, "y2": y2, "duration_ms": duration_ms, "key": key_name, "text": text,
                                  "distance_m": distance_m}.items() if v is not None}
        if event == "focus":
            args["mode"] = mode
        return AndroidController(state_dir, device).send(ControlMessage("android", "input", event, args))
    _guard(run)


@mirror_grp.command("control")
@click.option("--action", type=click.Choice(["query", "input"]), default="query")
@click.option("--name", default="forge.status", help="query name, or input type key|pointer|scroll")
@click.option("--arg", "args", multiple=True, help="k=v for input events (e.g. key=a, x=0.5)")
@click.option("--url", required=True)
@click.option("--code", required=True)
@click.option("--client-id", default="forge-cli")
def mirror_control(action: str, name: str, args: tuple[str, ...], url: str, code: str, client_id: str) -> None:
    """Drive a desktop over LoomLink (drive_studio): allow-listed read-only queries, or Studio input events."""
    from forge.loomlink import LinkClient
    from forge.mirrorweave import ControlMessage

    def conv(v: str) -> Any:
        for f in (int, float):
            try:
                return f(v)
            except ValueError:
                pass
        return {"true": True, "false": False}.get(v, v)

    def run() -> Any:
        c = LinkClient(url, client_id)
        c.pair(code, ["drive_studio"])
        kv = dict(a.split("=", 1) for a in args)
        return c.mirror_control(ControlMessage("desktop", action, name, {k: conv(v) for k, v in kv.items()}))
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
@click.option("--kind", type=click.Choice(["arcore", "video"]), required=True)
def lens_session(kind: str) -> None:
    """ARCore / video capture — STUB (refuses, exit 3)."""
    from forge import lensforge

    def run() -> Any:
        if kind == "arcore":
            return lensforge.ARCoreSession().start()
        return lensforge.VideoCapture().start()
    _guard(run)


@lens_grp.command("focus")
@click.option("--state-dir", type=click.Path(path_type=Path), required=True, help="State dir of the running `forge link serve`.")
@click.option("--device", required=True, help="Paired phone's client id.")
@click.option("--distance-m", type=float, default=None, help="Manual focus distance; omit for auto-focus.")
@click.option("--x", type=float, default=None)
@click.option("--y", type=float, default=None)
def lens_focus(state_dir: Path, device: str, distance_m: float | None, x: float | None, y: float | None) -> None:
    """Queue a camera focus request for a paired phone (Camera2 on the phone; not verified on a device)."""
    from forge import lensforge

    def run() -> Any:
        fc = lensforge.FocusController(state_dir, device)
        return fc.set_focus(distance_m) if distance_m is not None else fc.auto(x, y)
    _guard(run)


# --------------------------------------------------------------------------------------------------- depth (C11)

@click.group("depth")
def depth_grp() -> None:
    """Metric depth (C11): pinhole distance, scale alignment and dense DepthAnything V2 Small (CPU) are real; ARCore is a stub."""


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
@click.option("--anchor", "anchors", multiple=True, help="metric anchor x,y,metres (≥ 2 → metric depth)")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), help="write a 16-bit PNG (relative, or millimetres with anchors)")
@click.option("--threads", type=int, default=1, show_default=True)
def depth_estimate(file: Path, backend: str, anchors: tuple[str, ...], out: Path | None, threads: int) -> None:
    """Dense depth: DepthAnything V2 Small on onnxruntime CPU (needs `forge models fetch depth-anything-v2-small`);
    `--backend arcore` is a stub (exit 3)."""
    import numpy as np

    from forge import depth

    def run() -> Any:
        if backend == "arcore":
            return depth.ARCoreDepth().estimate(file.read_bytes())
        rel = depth.DepthAnythingV2(threads=threads).estimate(file.read_bytes())
        res: dict[str, Any] = {"model": depth.MODEL_ID, "width": rel.shape[1], "height": rel.shape[0],
                               "rel_min": float(rel.min()), "rel_max": float(rel.max())}
        img = (rel - rel.min()) / max(float(rel.max() - rel.min()), 1e-9) * 65535
        if anchors:
            pts = [depth.Anchor(int(a.split(",")[0]), int(a.split(",")[1]), float(a.split(",")[2])) for a in anchors]
            al = depth.align_inverse_depth(rel, pts)
            d = al["depth_m"]
            res["metric"] = {k: al[k] for k in ("scale", "shift", "anchor_rmse_m", "invalid_fraction")}
            res["metric"].update(median_m=float(np.nanmedian(d)), min_m=float(np.nanmin(d)), max_m=float(np.nanmax(d)))
            img = np.nan_to_num(d * 1000.0, nan=0.0)
        if out:
            from PIL import Image
            Image.fromarray(np.clip(img, 0, 65535).astype(np.uint16)).save(out)
            res["out"] = str(out)
        return res
    _guard(run)


# --------------------------------------------------------------------------------------------------- models

@click.group("models")
def models_grp() -> None:
    """Model weights (content/models/models.yaml): fetched with SHA-256 into store/models/, never committed."""


@models_grp.command("list")
def models_list() -> None:
    from forge import models
    _emit([{**models.status(m, verify=False), "use": s.get("use")} for m, s in models.registry().items()])


@models_grp.command("fetch")
@click.argument("model_id")
def models_fetch(model_id: str) -> None:
    from forge import models
    _guard(lambda: models.fetch(model_id))


@models_grp.command("verify")
@click.argument("model_id")
def models_verify(model_id: str) -> None:
    from forge import models
    st = models.status(model_id)
    _emit(st)
    if not st["ready"]:
        raise SystemExit(1)


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
