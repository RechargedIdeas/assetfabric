"""Substrate sandbox — isolated execution for generator jobs and authoring code (F4).

SPEC §6.2 names three isolation kernels (Firecracker, gVisor, Microsandbox). Each is
probed at runtime and used only when it is genuinely available; on hosts without them
the orchestrator falls back down an honest ladder (GroundWeave principle):

| tier          | isolation                                                                     |
|---------------|-------------------------------------------------------------------------------|
| `firecracker` | micro-VM — needs a readable/writable `/dev/kvm` + `firecracker` binary        |
| `gvisor`      | user-space kernel — needs `runsc`                                             |
| `bwrap`       | Linux namespaces (user/pid/net/ipc/uts), read-only root, private /tmp,        |
|               | only the scratch dir writable, no network, + rlimits                          |
| `process`     | subprocess + rlimits (CPU, address space, file size, fds), scrubbed env,      |
|               | scratch cwd, in-worker audit hook that refuses sockets. Best effort: it does  |
|               | NOT stop a hostile native extension from writing outside the scratch dir.     |

The firecracker / gvisor tiers are *detected* but have no launcher yet: they report
`available=False` with a reason (see `docs/SUBSTRATE.md`, [INFERENCE] F4-1).

Lifecycle (SPEC §6.2): CREATED → PROVISIONING → RUNNING → (SNAPSHOTTING|RESTORING) → TERMINATED.
Every transition is audited to telemetry with `sandbox_id` + `profile`.
"""

from __future__ import annotations

import base64
import io
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from forge.paths import find_repo_root
from forge.telemetry import TelemetryStore, make_system_event

TIERS = ("firecracker", "gvisor", "bwrap", "process")


class SandboxState(str, Enum):
    CREATED = "CREATED"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    SNAPSHOTTING = "SNAPSHOTTING"
    RESTORING = "RESTORING"
    TERMINATED = "TERMINATED"


@dataclass(frozen=True)
class Limits:
    cpu_s: int = 60          # RLIMIT_CPU (SIGXCPU → killed)
    mem_mb: int = 2048       # RLIMIT_AS
    wall_s: float = 120.0    # parent-side wall clock → SIGKILL of the process group
    fsize_mb: int = 64       # RLIMIT_FSIZE (largest single file the job may write)
    nofile: int = 256        # RLIMIT_NOFILE
    network: bool = False    # allow network? (never for generator jobs)


PROFILES: dict[str, Limits] = {
    "gen": Limits(),                                         # generator jobs
    "short": Limits(cpu_s=10, mem_mb=1024, wall_s=20.0),     # quick checks / tests
    "train": Limits(cpu_s=900, mem_mb=8192, wall_s=1800.0),  # offline policy training
}


@dataclass
class SandboxResult:
    sandbox_id: str
    tier: str
    returncode: int
    stdout: str
    stderr: str
    wall_ms: float
    cpu_s: float          # reaped-children CPU; bwrap's pid namespace hides the inner process → ~0 there
    max_rss_kb: int
    killed: str | None = None     # "wall" | "cpu" | "signal:<n>" | None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.killed is None

    def json(self) -> Any:
        """Last JSON line on stdout (the worker protocol), or None."""
        for line in reversed(self.stdout.strip().splitlines()):
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    return None
        return None


# ----------------------------------------------------------------------------- detection

def _kvm_usable() -> tuple[bool, str]:
    p = Path("/dev/kvm")
    if not p.exists():
        return False, "/dev/kvm absent"
    if not os.access(p, os.R_OK | os.W_OK):
        return False, "/dev/kvm present but not accessible to this user"
    return True, "ok"


def _bwrap_works() -> tuple[bool, str]:
    exe = shutil.which("bwrap")
    if not exe:
        return False, "bwrap not installed"
    try:
        r = subprocess.run([exe, "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev",
                            "--proc", "/proc", "--tmpfs", "/tmp", "true"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"bwrap probe failed: {exc}"
    if r.returncode != 0:
        return False, "bwrap cannot create namespaces: " + r.stderr.decode(errors="replace").strip()[:160]
    return True, "ok"


def detect_tiers() -> dict[str, dict[str, Any]]:
    kvm_ok, kvm_why = _kvm_usable()
    fc = shutil.which("firecracker")
    runsc = shutil.which("runsc")
    bw_ok, bw_why = _bwrap_works()
    return {
        "firecracker": {"available": False, "launcher": False,
                        "reason": (kvm_why if not kvm_ok else ("firecracker binary missing" if not fc else
                                   "launcher not implemented (needs guest kernel + rootfs image)"))},
        "gvisor": {"available": False, "launcher": False,
                   "reason": "runsc missing" if not runsc else "launcher not implemented"},
        "bwrap": {"available": bw_ok, "launcher": True, "reason": bw_why},
        "process": {"available": hasattr(resource, "setrlimit"), "launcher": True, "reason": "ok"},
    }


def best_tier(prefer: str = "auto") -> str:
    tiers = detect_tiers()
    if prefer != "auto":
        if not tiers.get(prefer, {}).get("available"):
            raise RuntimeError(f"sandbox tier {prefer!r} unavailable: {tiers.get(prefer, {}).get('reason', 'unknown tier')}")
        return prefer
    for t in TIERS:
        if tiers[t]["available"] and tiers[t]["launcher"]:
            return t
    raise RuntimeError("no sandbox tier available")


# ----------------------------------------------------------------------------- sandbox

def _preexec(limits: Limits):
    def fn() -> None:
        os.setsid()
        mb = 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s + 2))
        resource.setrlimit(resource.RLIMIT_AS, (limits.mem_mb * mb, limits.mem_mb * mb))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.fsize_mb * mb, limits.fsize_mb * mb))
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.nofile, limits.nofile))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return fn


@dataclass
class Sandbox:
    """One isolated execution environment with a private scratch directory."""

    tier: str = "auto"
    profile: str = "gen"
    limits: Limits | None = None
    root: Path | None = None
    id: str = field(default_factory=lambda: "sbx-" + uuid.uuid4().hex[:12])
    state: SandboxState = SandboxState.CREATED
    history: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = self.root or find_repo_root()
        self.limits = self.limits or PROFILES[self.profile]
        self.tier = best_tier(self.tier)
        self.scratch: Path | None = None
        self._telemetry = TelemetryStore(self.root)
        self._transition(SandboxState.CREATED)

    # -- lifecycle -------------------------------------------------------------------
    def _transition(self, s: SandboxState, **extra: Any) -> None:
        self.state = s
        self.history.append(s.value)
        ev = make_system_event("sandbox." + s.value.lower(), agent_id=self.id, agent_type="sandbox",
                               action_taken={"tier": self.tier, **extra}, action_source="system")
        ev.sandbox_id = self.id
        ev.profile = self.profile
        self._telemetry.emit(ev)

    def provision(self) -> "Sandbox":
        if self.scratch is None:
            self._transition(SandboxState.PROVISIONING)
            self.scratch = Path(tempfile.mkdtemp(prefix=f"{self.id}-"))
        return self

    def __enter__(self) -> "Sandbox":
        return self.provision()

    def __exit__(self, *exc: Any) -> None:
        self.terminate()

    def terminate(self) -> None:
        if self.state == SandboxState.TERMINATED:
            return
        if self.scratch and self.scratch.exists():
            shutil.rmtree(self.scratch, ignore_errors=True)
        self._transition(SandboxState.TERMINATED)

    # -- disk snapshots (Microsandbox-style, scratch dir only) -------------------------
    def snapshot(self) -> bytes:
        assert self.scratch is not None
        self._transition(SandboxState.SNAPSHOTTING)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for p in sorted(self.scratch.rglob("*")):
                tar.add(p, arcname=str(p.relative_to(self.scratch)), recursive=False)
        self._transition(SandboxState.RUNNING)
        return buf.getvalue()

    def restore(self, blob: bytes) -> None:
        assert self.scratch is not None
        self._transition(SandboxState.RESTORING)
        for p in self.scratch.iterdir():
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            tar.extractall(self.scratch, filter="data")
        self._transition(SandboxState.RUNNING)

    # -- execution ---------------------------------------------------------------------
    def _argv(self, inner: list[str]) -> list[str]:
        assert self.scratch is not None
        if self.tier == "bwrap":
            argv = ["bwrap", "--die-with-parent", "--new-session", "--unshare-all",
                    "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                    "--bind", str(self.scratch), "/tmp/work", "--chdir", "/tmp/work", "--clearenv",
                    "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp/work",
                    "--setenv", "PYTHONPATH", str(self.root), "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                    "--setenv", "FABRIC_SANDBOX", f"bwrap:{self.id}"]
            if self.limits.network:
                argv.insert(argv.index("--unshare-all") + 1, "--share-net")
            return argv + ["--", *inner]
        return inner

    def _env(self) -> dict[str, str]:
        return {"PATH": "/usr/bin:/bin", "HOME": str(self.scratch), "PYTHONPATH": str(self.root),
                "PYTHONDONTWRITEBYTECODE": "1", "FABRIC_SANDBOX": f"process:{self.id}",
                "FABRIC_NO_NETWORK": "0" if self.limits.network else "1", "LANG": "C.UTF-8",
                "TMPDIR": str(self.scratch)}   # tempfile → scratch, so the write allow-list is only the scratch dir

    def run(self, inner: list[str], stdin: str = "") -> SandboxResult:
        self.provision()
        self._transition(SandboxState.RUNNING, argv0=Path(inner[0]).name)
        lim = self.limits
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        t0 = time.perf_counter()
        proc = subprocess.Popen(self._argv(inner), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=self.scratch, env=self._env(),
                                preexec_fn=_preexec(lim), text=True)
        killed = None
        try:
            out, err = proc.communicate(stdin, timeout=lim.wall_s)
        except subprocess.TimeoutExpired:
            killed = "wall"
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        wall = (time.perf_counter() - t0) * 1000
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        rc = proc.returncode
        sig = -rc if rc < 0 else (rc - 128 if self.tier == "bwrap" and rc > 128 else 0)  # bwrap relays 128+signo
        if killed is None and sig:
            killed = "cpu" if sig == signal.SIGXCPU else f"signal:{sig}"
        res = SandboxResult(self.id, self.tier, rc, out, err, round(wall, 2),
                            round((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime), 3),
                            int(after.ru_maxrss), killed)
        self._transition(SandboxState.RUNNING, rc=rc, killed=killed, wall_ms=res.wall_ms)
        return res

    def python(self, request: dict[str, Any]) -> SandboxResult:
        """Run the forge sandbox worker with a JSON request on stdin."""
        return self.run([sys.executable, "-s", "-m", "forge.sandbox_worker"], json.dumps(request))


# ----------------------------------------------------------------------------- generator jobs

def generate(brief: dict[str, Any], root: Path | None = None, tier: str = "auto", profile: str = "gen"):
    """Run one generator brief inside a sandbox; returns a GeneratorOutput identical to in-process."""
    from forge.gates import GateResult
    from forge.generators import Artifact, GeneratorOutput

    root = root or find_repo_root()
    with Sandbox(tier=tier, profile=profile, root=root) as sb:
        res = sb.python({"op": "generate", "brief": brief, "root": str(root)})
    payload = res.json()
    if not res.ok or not payload or not payload.get("ok_protocol"):
        raise RuntimeError(f"sandboxed generator failed (tier={res.tier}, rc={res.returncode}, killed={res.killed}): "
                           + (res.stderr.strip().splitlines() or ["no stderr"])[-1][:300])
    arts = [Artifact(a["name"], base64.b64decode(a["data"]), a["media_type"]) for a in payload["artifacts"]]
    gates = [GateResult(**g) for g in payload["gates"]]
    meta = dict(payload["meta"])
    meta["sandbox"] = {"id": res.sandbox_id, "tier": res.tier, "wall_ms": res.wall_ms, "cpu_s": res.cpu_s}
    return GeneratorOutput(arts, gates, meta)


def describe() -> dict[str, Any]:
    tiers = detect_tiers()
    try:
        chosen = best_tier()
    except RuntimeError:
        chosen = None
    return {"tiers": tiers, "selected": chosen, "profiles": {k: asdict(v) for k, v in PROFILES.items()}}
