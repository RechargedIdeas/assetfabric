"""LoomCluster (C7) — equal-node compute clustering: advertise, negotiate, queue, steal.

Every node is the same program (no master/slave; PocketLoom would join as a peer). A node:

* **advertises** its capabilities (cores, devices, RAM, user allocation cap → worker slots)
  on `GET /advert` and exchanges adverts with peers on `POST /hello` (negotiation);
* accepts jobs on any node (`POST /submit`); placement is negotiated from the adverts —
  a job whose GroundWeave op needs a device this node lacks is forwarded to a peer
  advertising it, otherwise it is queued locally;
* runs jobs on `slots` worker threads; an idle worker **steals** from the tail of the
  busiest peer's queue (`POST /steal`, only jobs the thief can run);
* routes results to the job's origin (`POST /result`) and journals every state change
  (`journal.jsonl`) so a restarted node re-queues unfinished work (checkpointing);
* tracks leases on jobs it originated: if the current owner stops answering, the origin
  re-queues the job locally (at-least-once execution; ops are deterministic/idempotent).

A coordinator is elected (lowest live node id) purely for reporting; any node can submit
and every node schedules for itself. Transport is HTTP/JSON on `cluster.protocol.bind`
(loopback by default — LAN/Tailscale exposure is a LoomLink (C5) concern).

Job ops (`OPS`) are deterministic: `hashchain` (CPU work, verifiable) and `gen` (one forge
brief through the GroundWeave-selected backend, returns artifact digests).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

DEFAULTS = {"bind": "127.0.0.1", "heartbeat_s": 0.5, "lease_s": 6.0, "steal_batch": 2,
            "http_timeout_s": 2.0, "max_attempts": 3, "job_timeout_s": 300.0}


def protocol_config(root: Path | None = None) -> dict[str, Any]:
    """`cluster.protocol` from forge.yaml over built-in defaults."""
    import yaml
    from forge.paths import find_repo_root

    cfg = dict(DEFAULTS)
    try:
        raw = yaml.safe_load((root or find_repo_root()).joinpath("forge.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, FileNotFoundError):
        raw = {}
    cfg.update((raw.get("cluster") or {}).get("protocol") or {})
    return cfg


# ------------------------------------------------------------------------------------ ops
# Ops are deterministic functions of their payload (so at-least-once execution and any placement give the
# same value). `hashchain` is pure CPU work with a verifiable digest; `gen` runs one Content Forge brief through
# the GroundWeave-selected backend **in a child process** (true parallelism across a node's slots, no GIL
# contention, and the child sees exactly the devices the node advertises). `flaky` is a diagnostic used by the
# acceptance run to prove retry: it fails its first `fail_first` attempts (counted in a marker file).

def op_hashchain(payload: dict[str, Any]) -> dict[str, Any]:
    from forge.loomlink import op_hashchain as impl

    return impl(payload)


def op_gen_inline(payload: dict[str, Any]) -> dict[str, Any]:
    """Child-side body of `gen` (also what a PocketLoom `gen` offload runs on the desktop)."""
    from forge.loomlink import op_gen

    return op_gen(payload)


def op_gen(payload: dict[str, Any], devices: list[str] | None = None, timeout_s: float = 300.0) -> dict[str, Any]:
    import subprocess
    import sys

    env = dict(os.environ)
    if devices is not None:
        env["FORGE_GW_DEVICES"] = ",".join(devices)       # the child may only use what this node advertises
    p = subprocess.run([sys.executable, "-m", "forge.loomcluster", "_op", "gen", json.dumps(payload)],
                       capture_output=True, text=True, env=env, timeout=timeout_s)
    line = next((l for l in p.stdout.splitlines() if l.startswith("LOOM_OP ")), None)
    if p.returncode != 0 or line is None:
        raise RuntimeError(f"gen child failed rc={p.returncode}: {(p.stderr or p.stdout)[-300:]}")
    return json.loads(line[len("LOOM_OP "):])


def op_flaky(payload: dict[str, Any]) -> dict[str, Any]:
    marker = Path(payload["marker"])
    n = int(marker.read_text() or 0) if marker.exists() else 0
    marker.write_text(str(n + 1))
    if n < int(payload.get("fail_first", 1)):
        raise RuntimeError(f"induced failure {n + 1}/{payload.get('fail_first', 1)}")
    return {"digest": op_hashchain({"seed": payload.get("seed", "flaky"), "rounds": 1000})["digest"], "attempt_seen": n + 1}


OPS: dict[str, Callable[..., dict[str, Any]]] = {"hashchain": op_hashchain, "gen": op_gen, "flaky": op_flaky}
NEEDS_DEVICES = {"gen"}      # ops whose implementation takes the node's advertised device list


def expected_hashchain(seed: Any, rounds: int) -> str:
    return op_hashchain({"seed": seed, "rounds": rounds})["digest"]


def batch_digest(results: dict[str, dict[str, Any]]) -> str:
    """Order-independent digest of a batch: sha256 over (job id, canonical value) sorted by id."""
    h = hashlib.sha256()
    for jid in sorted(results):
        r = results[jid]
        h.update(jid.encode() + b"\0" + json.dumps(r.get("value"), sort_keys=True).encode() + b"\0")
    return h.hexdigest()


# ----------------------------------------------------------------------------------- node

@dataclass
class Caps:
    node_id: str
    cores: int
    devices: list[str]
    ram_gb: float = 0.0
    allocation_cap_pct: int = 100

    @property
    def slots(self) -> int:
        return max(1, (self.cores * self.allocation_cap_pct) // 100)


def _http(url: str, body: dict[str, Any] | None = None, timeout: float = 2.0) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def can_run(job: dict[str, Any], devices: list[str]) -> bool:
    need = (job.get("requires") or {}).get("device")
    return need is None or need in devices


@dataclass
class Node:
    caps: Caps
    state_dir: Path
    peers: list[str] = field(default_factory=list)
    cfg: dict[str, Any] = field(default_factory=lambda: dict(DEFAULTS))
    port: int = 0

    def __post_init__(self) -> None:
        self.lock = threading.RLock()
        self.queue: deque[dict[str, Any]] = deque()
        self.results: dict[str, dict[str, Any]] = {}
        self.outstanding: dict[str, dict[str, Any]] = {}   # jobs I originated → {owner, job, since}
        self.adverts: dict[str, dict[str, Any]] = {}       # peer url → advert
        self.running: dict[str, dict[str, Any]] = {}
        self.undelivered: list[tuple[str, dict[str, Any]]] = []
        self.stats = {"executed": 0, "stolen_in": 0, "stolen_out": 0, "forwarded": 0, "requeued": 0,
                      "recovered": 0, "retried": 0, "redelivered": 0}
        self.stop = threading.Event()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.journal = self.state_dir / "journal.jsonl"
        self.url = ""

    # -- journal / checkpoint
    def _log(self, ev: str, **kw: Any) -> None:
        rec = {"t": round(time.time(), 3), "ev": ev, **kw}
        with self.lock, self.journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def recover(self) -> int:
        """Re-queue jobs this node held (queued/running) but never finished before a restart."""
        if not self.journal.exists():
            return 0
        held: dict[str, dict[str, Any]] = {}
        for line in self.journal.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue   # torn tail write
            ev, jid = rec.get("ev"), rec.get("job", {}).get("id") or rec.get("job_id")
            if ev in ("queued", "stolen_in") and jid:
                held[jid] = rec["job"]
            elif ev in ("done", "stolen_out", "forwarded") and jid:
                held.pop(jid, None)
            elif ev == "result" and jid:
                self.results[jid] = rec["result"]
        for job in held.values():
            self.queue.append(job)
        self.stats["recovered"] = len(held)
        return len(held)

    # -- advert / negotiation
    def advert(self) -> dict[str, Any]:
        with self.lock:
            return {"id": self.caps.node_id, "url": self.url, "cores": self.caps.cores,
                    "devices": self.caps.devices, "ram_gb": self.caps.ram_gb,
                    "allocation_cap_pct": self.caps.allocation_cap_pct, "slots": self.caps.slots,
                    "queue": len(self.queue), "running": len(self.running), "t": time.time()}

    def heartbeat(self) -> None:
        me = self.advert()
        for p in list(dict.fromkeys(self.peers + list(self.adverts))):
            if p == self.url:
                continue
            try:
                adv = _http(p + "/hello", me, self.cfg["http_timeout_s"])
                with self.lock:
                    self.adverts[p] = adv
                    for u in adv.get("peers", []):
                        if u != self.url and u not in self.peers:
                            self.peers.append(u)   # gossip: learn the mesh from any one seed
            except (urllib.error.URLError, OSError, ValueError):
                with self.lock:
                    self.adverts.pop(p, None)

    def coordinator(self) -> str:
        ids = [self.caps.node_id] + [a["id"] for a in self.adverts.values()]
        return min(ids)

    def place(self, job: dict[str, Any]) -> str | None:
        """Negotiated placement: local if this node can run it, else the least-loaded capable peer."""
        if can_run(job, self.caps.devices):
            return None
        best, score = None, None
        for url, adv in self.adverts.items():
            if can_run(job, adv["devices"]):
                s = (adv["queue"] + adv["running"]) / max(1, adv["slots"])
                if score is None or s < score:
                    best, score = url, s
        if best is None:
            raise RuntimeError(f"no node advertises {job.get('requires')}")
        return best

    # -- job lifecycle
    def submit(self, job: dict[str, Any]) -> dict[str, Any]:
        job = {"id": job.get("id") or uuid.uuid4().hex[:12], "origin": job.get("origin") or self.url, **job}
        if job["op"] not in OPS:
            raise ValueError(f"unknown op {job['op']!r}")
        with self.lock:
            if job["origin"] == self.url:
                self.outstanding[job["id"]] = {"owner": self.url, "job": job, "since": time.time()}
        target = self.place(job)
        if target:
            _http(target + "/submit", job, self.cfg["http_timeout_s"])
            with self.lock:
                self.stats["forwarded"] += 1
                if job["id"] in self.outstanding:
                    self.outstanding[job["id"]]["owner"] = target
            self._log("forwarded", job_id=job["id"], to=target)
            return {"id": job["id"], "placed": target}
        with self.lock:
            self.queue.append(job)
        self._log("queued", job=job)
        return {"id": job["id"], "placed": self.url}

    def give(self, thief: str, devices: list[str], n: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with self.lock:
            keep: list[dict[str, Any]] = []
            while self.queue and len(out) < n:
                job = self.queue.pop()               # steal from the tail (owner works the head)
                (out if can_run(job, devices) else keep).append(job)
            self.queue.extend(reversed(keep))
            self.stats["stolen_out"] += len(out)
        for job in out:
            self._log("stolen_out", job_id=job["id"], to=thief)
            # Ownership moves *with* the job, before the thief can run (or die holding) it: the origin's lease
            # must already point at the thief, otherwise a crash right after a steal would strand the job.
            self._transfer_owner(job, thief)
        return out

    def _transfer_owner(self, job: dict[str, Any], owner: str) -> None:
        if job["origin"] == self.url:
            with self.lock:
                if job["id"] in self.outstanding:
                    self.outstanding[job["id"]].update(owner=owner, since=time.time())
            return
        try:
            _http(job["origin"] + "/owner", {"job_id": job["id"], "owner": owner}, self.cfg["http_timeout_s"])
        except (urllib.error.URLError, OSError, ValueError):
            pass

    def _try_steal(self) -> bool:
        victims = sorted(self.adverts.items(), key=lambda kv: -kv[1].get("queue", 0))
        for url, adv in victims:
            if adv.get("queue", 0) <= 0:
                continue
            try:
                got = _http(url + "/steal", {"thief": self.url, "devices": self.caps.devices,
                                             "n": int(self.cfg["steal_batch"])}, self.cfg["http_timeout_s"])
            except (urllib.error.URLError, OSError, ValueError):
                continue
            jobs = got.get("jobs", [])
            if not jobs:
                continue
            with self.lock:
                for job in jobs:
                    self.queue.append(job)
                self.stats["stolen_in"] += len(jobs)
            for job in jobs:
                self._log("stolen_in", job=job, frm=url)
                self._notify_owner(job)
            return True
        return False

    def _notify_owner(self, job: dict[str, Any]) -> None:
        if job["origin"] == self.url:
            with self.lock:
                if job["id"] in self.outstanding:
                    self.outstanding[job["id"]]["owner"] = self.url
            return
        try:
            _http(job["origin"] + "/owner", {"job_id": job["id"], "owner": self.url}, self.cfg["http_timeout_s"])
        except (urllib.error.URLError, OSError, ValueError):
            pass

    def _execute(self, job: dict[str, Any]) -> None:
        with self.lock:
            self.running[job["id"]] = job
        t0 = time.perf_counter()
        attempts = int(job.get("attempts", 0)) + 1
        try:
            fn = OPS[job["op"]]
            payload = job.get("payload") or {}
            if job["op"] in NEEDS_DEVICES:
                value = fn(payload, devices=self.caps.devices, timeout_s=float(self.cfg["job_timeout_s"]))
            else:
                value = fn(payload)
            res = {"ok": True, "value": value}
        except Exception as e:  # noqa: BLE001 — job failure is data, not a node crash
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        res.update(job_id=job["id"], node=self.caps.node_id, attempts=attempts,
                   wall_s=round(time.perf_counter() - t0, 4))
        with self.lock:
            self.running.pop(job["id"], None)
            self.stats["executed"] += 1
            retry = (not res["ok"]) and attempts < int(self.cfg["max_attempts"])
            if retry:
                self.stats["retried"] += 1
                again = {**job, "attempts": attempts}
                self.queue.append(again)           # tail: stealable, so a retry may land on another node
        if retry:
            self._log("queued", job=again, reason="retry", error=res["error"])
            return
        self._log("done", job_id=job["id"])
        self._deliver(job, res)

    def _deliver(self, job: dict[str, Any], res: dict[str, Any]) -> None:
        if job["origin"] == self.url:
            self.accept_result(res)
            return
        for _ in range(3):
            try:
                _http(job["origin"] + "/result", res, self.cfg["http_timeout_s"])
                return
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(0.2)
        with self.lock:                              # origin unreachable: keep it, redeliver on heartbeat
            self.undelivered.append((job["origin"], res))
        self._log("undelivered", job_id=job["id"], origin=job["origin"])

    def _redeliver(self) -> None:
        with self.lock:
            pend, self.undelivered = self.undelivered, []
        for origin, res in pend:
            try:
                _http(origin + "/result", res, self.cfg["http_timeout_s"])
                self.stats["redelivered"] += 1
            except (urllib.error.URLError, OSError, ValueError):
                with self.lock:
                    self.undelivered.append((origin, res))

    def accept_result(self, res: dict[str, Any]) -> None:
        with self.lock:
            first = res["job_id"] not in self.results
            self.results.setdefault(res["job_id"], res)
            self.outstanding.pop(res["job_id"], None)
        if first:
            self._log("result", job_id=res["job_id"], result=res)

    def _check_leases(self) -> None:
        now = time.time()
        live = set(self.adverts) | {self.url}
        with self.lock:
            stale = [(jid, o) for jid, o in self.outstanding.items()
                     if o["owner"] not in live and now - o["since"] > float(self.cfg["lease_s"])]
        for jid, o in stale:
            with self.lock:
                if jid not in self.outstanding:
                    continue
                self.outstanding[jid] = {"owner": self.url, "job": o["job"], "since": now}
                self.queue.append(o["job"])
                self.stats["requeued"] += 1
            self._log("queued", job=o["job"], reason="lease_expired", dead_owner=o["owner"])

    # -- loops
    def _worker(self) -> None:
        while not self.stop.is_set():
            job = None
            with self.lock:
                if self.queue:
                    job = self.queue.popleft()
            if job is not None:
                self._execute(job)
            elif not self._try_steal():
                time.sleep(0.05 + random.random() * 0.05)

    def _maintenance(self) -> None:
        while not self.stop.wait(float(self.cfg["heartbeat_s"])):
            self.heartbeat()
            self._check_leases()
            self._redeliver()

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {**self.advert(), "coordinator": self.coordinator(), "peers": sorted(self.adverts),
                    "stats": dict(self.stats), "results": len(self.results),
                    "outstanding": len(self.outstanding)}

    def serve(self, ready: Callable[["Node"], None] | None = None) -> None:
        node = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, obj: Any, code: int = 200) -> None:
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _body(self) -> dict[str, Any]:
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n).decode() or "{}") if n else {}

            def do_GET(self) -> None:
                if self.path == "/advert":
                    self._send(node.advert())
                elif self.path == "/status":
                    self._send(node.status())
                elif self.path.startswith("/result/"):
                    with node.lock:
                        r = node.results.get(self.path.rsplit("/", 1)[1])
                    self._send(r or {"pending": True}, 200 if r else 202)
                elif self.path == "/results":
                    with node.lock:
                        self._send({"results": list(node.results.values())})
                else:
                    self._send({"error": "not found"}, 404)

            def do_POST(self) -> None:
                try:
                    body = self._body()
                    if self.path == "/hello":
                        with node.lock:
                            if body.get("url"):
                                node.adverts[body["url"]] = body
                        self._send({**node.advert(), "peers": sorted(node.adverts)})
                    elif self.path == "/submit":
                        self._send(node.submit(body))
                    elif self.path == "/steal":
                        self._send({"jobs": node.give(body["thief"], body.get("devices", ["cpu"]), int(body.get("n", 1)))})
                    elif self.path == "/result":
                        node.accept_result(body)
                        self._send({"ok": True})
                    elif self.path == "/owner":
                        with node.lock:
                            o = node.outstanding.get(body["job_id"])
                            if o:
                                o.update(owner=body["owner"], since=time.time())
                        self._send({"ok": True})
                    elif self.path == "/shutdown":
                        self._send({"ok": True})
                        node.stop.set()
                    else:
                        self._send({"error": "not found"}, 404)
                except Exception as e:  # noqa: BLE001
                    self._send({"error": f"{type(e).__name__}: {e}"}, 400)

        srv = ThreadingHTTPServer((self.cfg["bind"], self.port), H)
        self.port = srv.server_address[1]
        self.url = f"http://{self.cfg['bind']}:{self.port}"
        self.recover()
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.heartbeat()
        for _ in range(self.caps.slots):
            threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._maintenance, daemon=True).start()
        self._log("up", url=self.url, caps=self.advert())
        if ready:
            ready(self)
        self.stop.wait()
        srv.shutdown()


def pin_cpus(n: int) -> list[int]:
    """Restrict this process (and every child it spawns) to the first n CPUs it may use."""
    try:
        cpus = sorted(os.sched_getaffinity(0))[:n]
        os.sched_setaffinity(0, set(cpus))
        return cpus
    except (AttributeError, OSError):
        return []


def local_caps(node_id: str, cores: int | None = None, devices: list[str] | None = None,
               cap_pct: int = 100) -> Caps:
    from forge import groundweave
    ram = 0.0
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        pass
    return Caps(node_id, cores or os.cpu_count() or 1, devices or groundweave.detect_devices(),
                round(ram, 1), cap_pct)


# ------------------------------------------------------------------- multi-process demo

def free_port() -> int:
    import socket

    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


def spawn_node(node_id: str, cores: int, state_dir: Path, peers: list[str], devices: str = "cpu",
               cap_pct: int = 100, port: int = 0, pin: int = 0):
    import subprocess
    import sys

    state_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "forge.loomcluster", "node", "--id", node_id, "--cores", str(cores),
           "--devices", devices, "--cap", str(cap_pct), "--state-dir", str(state_dir), "--port", str(port)]
    if pin:
        cmd += ["--pin", str(pin)]
    for p in peers:
        cmd += ["--peer", p]
    err = (state_dir / "stderr.log").open("ab")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line.startswith("LOOM_READY "):
            return proc, line.split()[1]
        if proc.poll() is not None:
            break
    proc.kill()
    raise RuntimeError(f"node {node_id} failed to start: {(state_dir / 'stderr.log').read_text()[-500:]}")


class Fleet:
    """A set of local loopback nodes (separate processes) — how C7 is proven without a LAN."""

    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root)
        self.procs: dict[str, Any] = {}
        self.urls: dict[str, str] = {}
        self.spec: dict[str, dict[str, Any]] = {}

    def add(self, node_id: str, cores: int = 1, devices: str = "cpu", cap_pct: int = 100, pin: int = 0,
            port: int = 0, seed: str | None = None) -> str:
        self.spec[node_id] = dict(cores=cores, devices=devices, cap_pct=cap_pct, pin=pin, port=port)
        peers = [seed] if seed else ([next(iter(self.urls.values()))] if self.urls else [])
        proc, url = spawn_node(node_id, cores, self.state_root / node_id, peers, devices, cap_pct, port, pin)
        self.procs[node_id], self.urls[node_id] = proc, url
        return url

    def kill(self, node_id: str) -> None:
        import signal

        p = self.procs[node_id]
        if p.poll() is None:
            p.send_signal(signal.SIGKILL)
            p.wait()

    def restart(self, node_id: str) -> str:
        """Start a killed node again on the same port and state dir (journal recovery)."""
        sp = dict(self.spec[node_id])
        port = int(self.urls[node_id].rsplit(":", 1)[1])
        peers = [u for n, u in self.urls.items() if n != node_id]
        proc, url = spawn_node(node_id, sp["cores"], self.state_root / node_id, peers, sp["devices"], sp["cap_pct"],
                               port, sp["pin"])
        self.procs[node_id] = proc
        return url

    def wait_mesh(self, timeout_s: float = 15.0) -> bool:
        want = {n: len(self.urls) - 1 for n in self.urls if self.procs[n].poll() is None}
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if all(len(_http(self.urls[n] + "/status")["peers"]) >= w for n, w in want.items()):
                    return True
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.1)
        return False

    def status(self, node_id: str) -> dict[str, Any]:
        return _http(self.urls[node_id] + "/status")

    def close(self) -> None:
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except Exception:  # noqa: BLE001
                    p.kill()
        for p in self.procs.values():
            if p.stdout:
                p.stdout.close()

    def __enter__(self) -> "Fleet":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()


def collect(url: str, ids: list[str], timeout_s: float = 120.0, poll_s: float = 0.1,
            tick: Callable[[dict[str, Any]], None] | None = None) -> dict[str, dict[str, Any]]:
    """Poll the origin node until every job id has a result (or time runs out)."""
    deadline = time.time() + timeout_s
    want, got = set(ids), {}
    while time.time() < deadline:
        st = _http(url + "/status")
        if tick:
            tick(st)
        if st["results"] >= len(want):
            got = {r["job_id"]: r for r in _http(url + "/results")["results"] if r["job_id"] in want}
            if set(got) >= want:
                return got
        time.sleep(poll_s)
    return got


def run_batch(url: str, jobs: list[dict[str, Any]], timeout_s: float = 120.0,
              tick: Callable[[dict[str, Any]], None] | None = None) -> dict[str, dict[str, Any]]:
    """Submit every job to one node (the origin) and collect results; ordering of execution is irrelevant."""
    for j in jobs:
        _http(url + "/submit", j, 5.0)
    return collect(url, [j["id"] for j in jobs], timeout_s, tick=tick)


# --------------------------------------------------------------- LoomLink (PocketLoom) bridge

class ClusterBridge:
    """Lets the paired desktop's LoomLink offload endpoint hand a phone's jobs to the fleet.

    Each offloaded job is placed on the next live node (round-robin over the entry node's mesh) with that node as
    origin, and the bridge blocks until the result is back — same request/response shape the phone already uses."""

    def __init__(self, entry_url: str, timeout_s: float = 120.0) -> None:
        self.entry, self.timeout_s, self._i = entry_url.rstrip("/"), timeout_s, 0
        self._lock = threading.Lock()

    def nodes(self) -> list[str]:
        st = _http(self.entry + "/status", timeout=3.0)
        return sorted({self.entry, *st["peers"]})

    def run(self, job: dict[str, Any]) -> dict[str, Any]:
        urls = self.nodes()
        with self._lock:
            url = urls[self._i % len(urls)]
            self._i += 1
        jid = job.get("id") or uuid.uuid4().hex[:12]
        _http(url + "/submit", {"op": job["op"], "payload": job.get("payload") or {}, "id": jid,
                                **({"requires": job["requires"]} if job.get("requires") else {})}, 5.0)
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            r = _http(url + f"/result/{jid}", timeout=3.0)
            if not r.get("pending"):
                return r
            time.sleep(0.05)
        raise TimeoutError(f"cluster job {jid} not finished in {self.timeout_s}s")


def demo(state_root: Path, jobs: int = 48, rounds: int = 150000, kill: bool = True,
         timeout_s: float = 120.0) -> dict[str, Any]:
    """Three equal processes (1, 2, 4 slots). All jobs submitted to the 1-slot node; the others
    must steal them. Optionally SIGKILL the biggest node mid-run: its leases expire at the
    origin and the work is re-executed elsewhere. Every digest is verified."""
    import shutil

    shutil.rmtree(state_root, ignore_errors=True)
    with Fleet(state_root) as fl:
        ua = fl.add("a", 1)
        fl.add("b", 2)
        fl.add("c", 4)
        fl.wait_mesh()
        expect = {f"job{i:03d}": expected_hashchain(i, rounds) for i in range(jobs)}
        t0 = time.time()
        killed: dict[str, Any] = {}

        def tick(st: dict[str, Any]) -> None:
            if kill and not killed and st["results"] >= jobs // 4:
                pre = fl.status("c")
                if pre["queue"] + pre["running"] > 0:        # kill c while it holds stolen work
                    fl.kill("c")
                    killed.update(results_at_kill=st["results"], c_held=pre["queue"] + pre["running"])

        batch = [{"id": jid, "op": "hashchain", "payload": {"seed": i, "rounds": rounds}}
                 for i, jid in enumerate(expect)]
        results = run_batch(ua, batch, timeout_s, tick)
        elapsed = time.time() - t0
        wrong = [j for j, d in expect.items() if results.get(j, {}).get("value", {}).get("digest") != d]
        by_node: dict[str, int] = {}
        for r in results.values():
            by_node[r["node"]] = by_node.get(r["node"], 0) + 1
        sa, sb = fl.status("a"), fl.status("b")
        ok = (len(results) == jobs and not wrong and len(by_node) >= 2 and sb["stats"]["stolen_in"] > 0
              and (not kill or (bool(killed) and sa["stats"]["requeued"] > 0)))
        return {"ok": ok, "jobs": jobs, "completed": len(results), "wrong": wrong, "elapsed_s": round(elapsed, 2),
                "executed_by_node": dict(sorted(by_node.items())), "coordinator": sa["coordinator"],
                "a": sa["stats"], "b": sb["stats"], "killed": killed or None}


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m forge.loomcluster")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("node")
    n.add_argument("--id", required=True)
    n.add_argument("--cores", type=int, default=None)
    n.add_argument("--devices", default=None, help="comma list; default = GroundWeave detection")
    n.add_argument("--cap", type=int, default=100, help="allocation cap %% of cores")
    n.add_argument("--state-dir", required=True)
    n.add_argument("--port", type=int, default=0)
    n.add_argument("--peer", action="append", default=[])
    n.add_argument("--pin", type=int, default=0, help="Pin this node (and its job children) to N CPUs.")
    o = sub.add_parser("_op")        # child entry: run one op in isolation
    o.add_argument("name")
    o.add_argument("payload")
    a = ap.parse_args(argv)
    if a.cmd == "_op":
        if a.name != "gen":
            return 2
        print("LOOM_OP " + json.dumps(op_gen_inline(json.loads(a.payload))), flush=True)
        return 0
    if a.pin:
        pin_cpus(a.pin)
    caps = local_caps(a.id, a.cores, a.devices.split(",") if a.devices else None, a.cap)
    node = Node(caps, Path(a.state_dir), list(a.peer), protocol_config(), a.port)
    node.serve(ready=lambda nd: print(f"LOOM_READY {nd.url}", flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
