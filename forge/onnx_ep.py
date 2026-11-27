"""ONNX Runtime execution-provider selection — AMD-first with automatic CPU fallback (post-F9, 0.9.2; INFERENCE C-101).

Every forge ONNX rung (DepthAnything V2 dense depth, GIRT policy parity, the persona micro-LM) opens its session through
`session()` here. Selection, best-first, following the GroundWeave ladder (SPEC §9: AMD-first, CPU fallback always):

    rocm      → MIGraphXExecutionProvider, ROCMExecutionProvider   (onnxruntime-rocm / -migraphx wheels, AMD ROCm 6.x)
    directml  → DmlExecutionProvider                               (onnxruntime-directml, Windows)
    cpu       → CPUExecutionProvider                               (always appended, always last)

A GPU provider is only *requested* when (a) the installed onnxruntime build exposes it and (b) GroundWeave reports the
device (`forge.groundweave.detect_devices`, `FORGE_DEVICES` override, `HIP_VISIBLE_DEVICES=-1` hides ROCm). If session
creation with the GPU provider raises (driver/library missing, unsupported op), the session is rebuilt on CPU and the
reason recorded; `run()` failures on the GPU session (e.g. VRAM exhaustion) demote to CPU the same way and rerun once.
`FORGE_ONNX_EP=cpu` forces CPU (bit-reproducible paths and acceptance probes use it), `=rocm` / `=directml` prefers one.

Status honesty: this build box has **no GPU** and the CPU-only onnxruntime wheel, so the ROCm path is
`rocm_ready_unverified` — the selection, fallback and demotion logic is tested against a mocked onnxruntime, the CPU path
against the real one; nothing here has executed on an AMD GPU.
"""

from __future__ import annotations

import os
from typing import Any, Callable

EP_ENV = "FORGE_ONNX_EP"
DEVICE_EPS: dict[str, list[str]] = {
    "rocm": ["MIGraphXExecutionProvider", "ROCMExecutionProvider"],
    "directml": ["DmlExecutionProvider"],
}
CPU = "CPUExecutionProvider"
ORDER = ("rocm", "directml")
STATUS = "rocm_ready_unverified"


def _ort() -> Any:
    import onnxruntime as ort

    return ort


def _devices() -> list[str]:
    try:
        from forge import groundweave

        return list(groundweave.detect_devices())
    except Exception:  # noqa: BLE001 - selection must never fail because device probing did
        return ["cpu"]


def plan(ort: Any = None, devices: list[str] | None = None, prefer: str | None = None) -> dict[str, Any]:
    """Which providers to request, and why. Pure function of the onnxruntime build + devices + env."""
    ort = ort or _ort()
    avail = list(ort.get_available_providers())
    devs = list(devices if devices is not None else _devices())
    want = (prefer or os.environ.get(EP_ENV, "auto")).strip().lower() or "auto"
    skipped: list[dict[str, str]] = []
    if want == "cpu":
        return {"providers": [CPU], "device": "cpu", "requested": want, "available": avail, "devices": devs,
                "skipped": [{"device": d, "why": f"{EP_ENV}=cpu"} for d in ORDER]}
    order = [want] if want in DEVICE_EPS else list(ORDER)
    for dev in order:
        eps = [e for e in DEVICE_EPS[dev] if e in avail]
        if not eps:
            skipped.append({"device": dev, "why": "onnxruntime build has no " + "/".join(DEVICE_EPS[dev])})
            continue
        if dev not in devs:
            skipped.append({"device": dev, "why": "GroundWeave reports no such device"})
            continue
        return {"providers": [*eps, CPU], "device": dev, "requested": want, "available": avail, "devices": devs,
                "skipped": skipped}
    return {"providers": [CPU], "device": "cpu", "requested": want, "available": avail, "devices": devs, "skipped": skipped}


class Session:
    """An onnxruntime InferenceSession that falls back to CPU at creation and demotes to CPU on a failing GPU run."""

    def __init__(self, model: Any, options_fn: Callable[[], Any] | None = None, ort: Any = None,
                 devices: list[str] | None = None, prefer: str | None = None) -> None:
        self._ort = ort or _ort()
        self._model = model
        self._options_fn = options_fn or self._ort.SessionOptions
        self.info = plan(self._ort, devices, prefer)
        self.info["fallback"] = None
        self.info["demoted"] = None
        try:
            self.sess = self._open(self.info["providers"])
        except Exception as e:  # noqa: BLE001 - any provider init failure → CPU
            if self.info["providers"] == [CPU]:
                raise
            self.info["fallback"] = f"{type(e).__name__}: {str(e)[:200]}"
            self.info["device"] = "cpu"
            self.sess = self._open([CPU])
        self.info["active"] = list(self.sess.get_providers())

    def _open(self, providers: list[str]) -> Any:
        return self._ort.InferenceSession(self._model, self._options_fn(), providers=providers)

    @property
    def on_gpu(self) -> bool:
        return bool(self.info.get("active")) and self.info["active"][0] != CPU

    def run(self, *a: Any, **kw: Any) -> Any:
        try:
            return self.sess.run(*a, **kw)
        except Exception as e:  # noqa: BLE001
            if not self.on_gpu:
                raise
            self.info["demoted"] = f"{type(e).__name__}: {str(e)[:200]}"
            self.info["device"] = "cpu"
            self.sess = self._open([CPU])
            self.info["active"] = list(self.sess.get_providers())
            return self.sess.run(*a, **kw)

    def __getattr__(self, name: str) -> Any:     # get_inputs(), get_outputs(), … pass through
        return getattr(self.sess, name)


def session(model: Any, options_fn: Callable[[], Any] | None = None, **kw: Any) -> Session:
    return Session(model, options_fn, **kw)


def report() -> dict[str, Any]:
    """`forge groundweave onnx-ep` / status: what this host would use, honestly labelled."""
    try:
        p = plan()
    except ImportError:
        return {"onnxruntime": None, "status": STATUS, "note": "onnxruntime not installed"}
    ort = _ort()
    return {"onnxruntime": getattr(ort, "__version__", "?"), "selected": p["providers"], "device": p["device"],
            "available": p["available"], "devices": p["devices"], "skipped": p["skipped"], "status": STATUS,
            "verified_on_gpu": False}


# ------------------------------------------------------------------------------------------------ contract self-test

class _FakeSession:
    def __init__(self, providers: list[str], fail_run_on_gpu: bool) -> None:
        self._p, self._fail = list(providers), fail_run_on_gpu

    def get_providers(self) -> list[str]:
        return list(self._p)

    def run(self, outputs: Any, feed: dict[str, Any]) -> list[Any]:
        if self._fail and self._p[0] != CPU:
            raise RuntimeError("hipErrorOutOfMemory (simulated)")
        return [("ran_on", self._p[0], sorted(feed))]


class FakeOrt:
    """TEST DOUBLE of the onnxruntime surface `Session` uses — lets the selection/fallback/demotion contract run on a box
    without a GPU or a ROCm wheel. Never used for real inference."""

    def __init__(self, available: list[str], fail_create: tuple[str, ...] = (), fail_run_on_gpu: bool = False) -> None:
        self.available, self.fail_create, self.fail_run_on_gpu = list(available), fail_create, fail_run_on_gpu
        self.created: list[list[str]] = []

    def get_available_providers(self) -> list[str]:
        return list(self.available)

    class SessionOptions:  # noqa: D106
        pass

    def InferenceSession(self, model: Any, so: Any, providers: list[str]) -> _FakeSession:  # noqa: N802 - mirrors ort
        self.created.append(list(providers))
        if providers[0] in self.fail_create:
            raise RuntimeError(f"Failed to load {providers[0]} (simulated: libamdhip64.so missing)")
        return _FakeSession([p for p in providers if p in self.available], self.fail_run_on_gpu)


def selftest() -> dict[str, Any]:
    """The EP contract against `FakeOrt` (all cases) + the real onnxruntime on this host (CPU). Used by pytest and C11."""
    rocm_eps = DEVICE_EPS["rocm"]
    cases: dict[str, bool] = {}
    old = os.environ.pop(EP_ENV, None)
    try:
        f = FakeOrt([*rocm_eps, CPU])
        s = Session(b"m", ort=f, devices=["cpu", "rocm"])
        cases["rocm_selected_first"] = s.info["providers"] == [*rocm_eps, CPU] and s.on_gpu and s.run(None, {"x": 1})[0][1] == rocm_eps[0]
        s = Session(b"m", ort=FakeOrt([*rocm_eps, CPU]), devices=["cpu"])
        cases["no_device_cpu"] = s.info["providers"] == [CPU] and "GroundWeave" in s.info["skipped"][0]["why"]
        s = Session(b"m", ort=FakeOrt([CPU]), devices=["cpu", "rocm"])
        cases["cpu_wheel_cpu"] = s.info["providers"] == [CPU] and "onnxruntime build" in s.info["skipped"][0]["why"]
        f = FakeOrt([*rocm_eps, CPU], fail_create=(rocm_eps[0],))
        s = Session(b"m", ort=f, devices=["cpu", "rocm"])
        cases["create_failure_falls_back"] = (s.info["active"] == [CPU] and s.info["fallback"] is not None
                                              and f.created == [[*rocm_eps, CPU], [CPU]] and not s.on_gpu)
        s = Session(b"m", ort=FakeOrt([*rocm_eps, CPU], fail_run_on_gpu=True), devices=["cpu", "rocm"])
        out = s.run(None, {"x": 1})
        cases["run_failure_demotes"] = out[0][1] == CPU and s.info["demoted"] is not None and not s.on_gpu
        s = Session(b"m", ort=FakeOrt([*rocm_eps, CPU]), devices=["cpu", "rocm"], prefer="cpu")
        cases["force_cpu"] = s.info["providers"] == [CPU]
        s = Session(b"m", ort=FakeOrt(["DmlExecutionProvider", CPU]), devices=["cpu", "directml"])
        cases["directml"] = s.info["providers"] == ["DmlExecutionProvider", CPU]
        try:
            Session(b"m", ort=FakeOrt([CPU], fail_create=(CPU,)), devices=["cpu"])
            cases["cpu_failure_raises"] = False
        except RuntimeError:
            cases["cpu_failure_raises"] = True
    finally:
        if old is not None:
            os.environ[EP_ENV] = old
    host = report()
    host_ok = host.get("onnxruntime") is None or (host["verified_on_gpu"] is False and host["selected"][-1] == CPU)
    return {"ok": all(cases.values()) and host_ok, "cases": cases, "host": host, "status": STATUS,
            "note": "selection/fallback/demotion proven against a fake onnxruntime; nothing here ran on a GPU"}
