"""Guardian — crash/hang detection + restart with exponential backoff (F4, SPEC §6.3).

Supervises one child process (a Game Zero `--serve` session, a generator worker, ...):

- **crash**: child exits non-zero or by signal  → restart
- **hang**:  the heartbeat file (`status.json`, rewritten every ~0.5 s by the game) is older
             than `hang_s` while the child is alive → SIGKILL the process group → restart
- **clean exit** (rc == 0)                      → stop supervising
- **crash loop**: more than `max_restarts` restarts inside `window_s` → give up (status `gave_up`)

Backoff between restarts: `min(base_s * factor**k, max_s)` where k counts recent restarts.
Restarts append `restart_args` (Game Zero: `--live-resume`, which restores the last session
snapshot, quarantines the in-flight ticket and re-applies committed tickets).
Every event is appended to `<state_dir>/guardian.jsonl` and to telemetry.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Backoff:
    base_s: float = 0.5
    factor: float = 2.0
    max_s: float = 8.0

    def delay(self, k: int) -> float:
        return min(self.base_s * self.factor ** max(0, k), self.max_s)


@dataclass
class GuardianPolicy:
    hang_s: float = 5.0            # heartbeat staleness that counts as a hang
    grace_s: float = 20.0          # startup time before the heartbeat is enforced
    max_restarts: int = 5
    window_s: float = 120.0
    backoff: Backoff = field(default_factory=Backoff)


class Guardian:
    def __init__(self, argv: list[str], state_dir: Path, heartbeat: Path | None = None,
                 restart_args: list[str] | None = None, policy: GuardianPolicy | None = None,
                 log_child: Path | None = None, root: Path | None = None) -> None:
        self.argv = list(argv)
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat = Path(heartbeat) if heartbeat else None
        self.restart_args = list(restart_args or [])
        self.policy = policy or GuardianPolicy()
        self.log_child = log_child
        self.root = root
        self.events: list[dict[str, Any]] = []
        self.restarts: list[float] = []
        self.status = "idle"
        self.proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- bookkeeping ---------------------------------------------------------------
    def _event(self, _name: str, **kw: Any) -> None:
        ev = {"t": round(time.time(), 3), "event": _name, **kw}
        self.events.append(ev)
        with open(self.state_dir / "guardian.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev) + "\n")
        if self.root:
            try:
                from forge.telemetry import TelemetryStore, make_system_event

                TelemetryStore(self.root).emit(make_system_event("guardian." + _name, agent_id="guardian",
                                                                 agent_type="guardian", action_taken=kw,
                                                                 action_source="system"))
            except Exception:   # telemetry must never take the guardian down
                pass

    def _spawn(self, restart: bool) -> None:
        argv = self.argv + (self.restart_args if restart else [])
        out = open(self.log_child, "ab") if self.log_child else subprocess.DEVNULL
        self.proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        self._started = time.monotonic()
        self._event("spawn", pid=self.proc.pid, restart=restart, argv=argv[-6:])

    def _kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait(timeout=10)

    def _heartbeat_age(self) -> float | None:
        if not self.heartbeat or not self.heartbeat.exists():
            return None
        return time.time() - self.heartbeat.stat().st_mtime

    # -- main loop -----------------------------------------------------------------
    def run(self, poll_s: float = 0.1) -> str:
        try:
            return self._run(poll_s)
        except Exception as exc:
            self.status = "error"
            self._event("error", error=repr(exc))
            self._kill()
            return self.status

    def _run(self, poll_s: float) -> str:
        self.status = "running"
        if self.heartbeat and self.heartbeat.exists():
            self.heartbeat.unlink()          # a stale heartbeat from an earlier session is not liveness
        self._spawn(restart=False)
        while not self._stop.is_set():
            time.sleep(poll_s)
            rc = self.proc.poll()
            reason = None
            if rc is not None:
                if rc == 0:
                    self._event("exit", rc=0)
                    self.status = "exited"
                    return self.status
                reason = {"kind": "crash", "rc": rc, "signal": -rc if rc < 0 else None}
            else:
                age = self._heartbeat_age()
                alive_for = time.monotonic() - self._started
                if age is not None and age > self.policy.hang_s:
                    reason = {"kind": "hang", "heartbeat_age_s": round(age, 2)}
                elif age is None and alive_for > self.policy.grace_s:
                    reason = {"kind": "hang", "heartbeat_age_s": None, "note": "no heartbeat within grace"}
            if reason is None:
                continue
            self._kill()
            self._event("failure", **reason)
            now = time.monotonic()
            self.restarts = [t for t in self.restarts if now - t < self.policy.window_s]
            if len(self.restarts) >= self.policy.max_restarts:
                self._event("gave_up", restarts=len(self.restarts))
                self.status = "gave_up"
                return self.status
            delay = self.policy.backoff.delay(len(self.restarts))
            self._event("backoff", delay_s=delay, attempt=len(self.restarts) + 1)
            if self._stop.wait(delay):
                break
            self.restarts.append(time.monotonic())
            if self.heartbeat and self.heartbeat.exists():
                self.heartbeat.unlink()      # the new process must prove liveness itself
            self._spawn(restart=True)
        self._kill()
        self.status = "stopped"
        self._event("stopped")
        return self.status

    def start(self) -> "Guardian":
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def join(self, timeout: float | None = None) -> str:
        if self._thread:
            self._thread.join(timeout)
        return self.status

    def summary(self) -> dict[str, Any]:
        return {"status": self.status, "restarts": len([e for e in self.events if e["event"] == "spawn"]) - 1,
                "failures": [e for e in self.events if e["event"] == "failure"],
                "backoffs": [e["delay_s"] for e in self.events if e["event"] == "backoff"],
                "policy": asdict(self.policy)}
