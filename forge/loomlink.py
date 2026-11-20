"""LoomLink (C5 pairing) + offload/sync endpoint (C6) — the desktop side of PocketLoom.

Pairing (no ambient authority): the desktop shows a one-time code (and a `loomlink://` URI,
as a terminal QR when the optional `qrcode` package is installed). Both sides prove
knowledge of the code with HMAC-SHA256 over fresh nonces — the code itself never crosses
the wire — and derive a per-device session key. Granted capabilities are the intersection
of what the phone asks for and what the desktop user allows (`--allow`; default
offload + sync). Five failed proofs rotate the code. Every later request is signed:
HMAC(key, METHOD|PATH|ts|sha256(body)) with a ±120 s window and strictly increasing ts.

Transport is plain HTTP on the bind address (LAN or a Tailscale IP — Tailscale already
encrypts and authenticates the path). TLS with a pinned fingerprint for raw-LAN use is a
TODO (see TODO.md); payloads are integrity-protected by the request MAC, not encrypted.

Sync (C6): both sides keep the same content-addressed store format as FabricCore's
`AssetStore` (index.json + objects/aa/<sha>), each entry carrying a version vector `vv`.
Merge per id: dominates → copy; equal → skip; concurrent → **conflict, keep both**: the
desktop copy keeps the id, the phone copy is re-keyed `<id>~<phone_id>` on both sides.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from forge.stubs import StubError

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
MAX_FAILS = 5
CODE_TTL_S = 300          # an unused pairing code expires (limits offline guessing of the 8-char code)
MAX_PENDING = 32
TS_WINDOW_S = 120
DEFAULT_ALLOW = ("offload", "sync")
ALL_CAPS = ("offload", "sync", "drive_studio", "mirror")


def _mac(key: bytes, *parts: str) -> str:
    return hmac.new(key, "|".join(parts).encode(), hashlib.sha256).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


# ------------------------------------------------------------------------- version vectors

def vv_compare(a: dict[str, int], b: dict[str, int]) -> str:
    """'equal' | 'a' (a dominates) | 'b' | 'concurrent'."""
    keys = set(a) | set(b)
    ge = all(a.get(k, 0) >= b.get(k, 0) for k in keys)
    le = all(a.get(k, 0) <= b.get(k, 0) for k in keys)
    if ge and le:
        return "equal"
    if ge:
        return "a"
    if le:
        return "b"
    return "concurrent"


class SyncStore:
    """Python twin of fabric.core.AssetStore (same on-disk format)."""

    def __init__(self, root: Path, node_id: str) -> None:
        self.root, self.node_id = Path(root), node_id
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.lock = threading.RLock()
        self.entries: dict[str, dict[str, Any]] = (
            json.loads(self.index_path.read_text(encoding="utf-8")) if self.index_path.exists() else {})

    def blob_path(self, sha: str) -> Path:
        return self.root / "objects" / sha[:2] / sha

    def put_blob(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        p = self.blob_path(sha)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        return sha

    def read(self, sha: str) -> bytes | None:
        p = self.blob_path(sha)
        return p.read_bytes() if p.exists() else None

    def put(self, aid: str, kind: str, data: bytes, provenance: dict[str, Any] | None = None,
            media: str = "image/png") -> dict[str, Any]:
        with self.lock:
            sha = self.put_blob(data)
            vv = dict((self.entries.get(aid) or {}).get("vv") or {})
            vv[self.node_id] = int(vv.get(self.node_id, 0)) + 1
            e = {"id": aid, "kind": kind, "sha256": sha, "media": media, "size": len(data), "vv": vv,
                 "provenance": provenance or {}, "updated_by": self.node_id}
            self.entries[aid] = e
            self._flush()
            return e

    def install(self, entry: dict[str, Any], data: bytes | None) -> None:
        with self.lock:
            if data is not None and self.put_blob(data) != entry["sha256"]:
                raise ValueError(f"blob digest mismatch for {entry['id']}")
            self.entries[entry["id"]] = dict(entry)
            self._flush()

    def _flush(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(canonical(self.entries), encoding="utf-8")
        os.replace(tmp, self.index_path)


def plan_sync(server: dict[str, dict[str, Any]], phone: dict[str, dict[str, Any]], phone_id: str) -> dict[str, Any]:
    """Deterministic merge plan shared with fabric.core.SyncPlan (Kotlin)."""
    pull, push, conflicts = [], [], []
    for aid in sorted(set(server) | set(phone)):
        s, p = server.get(aid), phone.get(aid)
        if p is None:
            pull.append(s)
            continue
        if s is None:
            push.append(aid)
            continue
        rel = vv_compare(s.get("vv", {}), p.get("vv", {}))
        if rel == "a":
            pull.append(s)
        elif rel == "b":
            push.append(aid)
        elif rel == "concurrent":
            if s["sha256"] == p["sha256"]:   # same bytes: merge vectors, no user-visible conflict
                vv = {k: max(s["vv"].get(k, 0), p["vv"].get(k, 0)) for k in set(s["vv"]) | set(p["vv"])}
                merged = {**s, "vv": vv}
                pull.append(merged)
                conflicts.append({"id": aid, "resolution": "merged_identical"})
            else:
                rid = f"{aid}~{phone_id}"
                conflicts.append({"id": aid, "resolution": "keep_both", "phone_copy": rid})
                push.append(aid)        # phone uploads its copy; server re-keys it to rid
                pull.append(s)          # phone takes the desktop copy under the original id
    return {"pull": pull, "push": push, "conflicts": conflicts}


# ------------------------------------------------------------------------------- ops
# Jobs a paired phone may offload (C6). LoomCluster (C7) will route these across nodes later;
# for now the desktop runs them itself.

def op_hashchain(payload: dict[str, Any]) -> dict[str, Any]:
    """sha256 chain — identical to fabric.core.hashchain (seed rendered with str())."""
    h = str(payload.get("seed", "")).encode()
    for _ in range(int(payload.get("rounds", 20000))):
        h = hashlib.sha256(h).digest()
    return {"digest": h.hex()}


def op_gen(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one desktop Content Forge brief (heavier than LocalForge) and return artifact digests.

    GroundWeave (C8) must know the generator's CPU fallback first. `return_data: true` also returns the artifact
    bytes (base64) so a distributed build can land them on the submitting node."""
    from forge import groundweave
    from forge.generators import load_all
    from forge.pipeline import Context, load_briefs

    ctx = Context.create()
    brief = {b["id"]: b for b in load_briefs(ctx.root)}[payload["brief_id"]]
    groundweave.resolve_kind(brief["kind"], ctx.root)
    out = load_all()[brief["kind"]](brief, ctx)
    res: dict[str, Any] = {"ok": out.ok, "artifacts": {a.name: hashlib.sha256(a.data).hexdigest() for a in out.artifacts}}
    if payload.get("return_data"):
        res["data_b64"] = {a.name: base64.b64encode(a.data).decode() for a in out.artifacts}
    return res


OPS = {"hashchain": op_hashchain, "gen": op_gen}


# ------------------------------------------------------------------------------- server

@dataclass
class LinkServer:
    state_dir: Path
    node_id: str = "desktop"
    allow: tuple[str, ...] = DEFAULT_ALLOW
    bind: str = "127.0.0.1"
    port: int = 0
    code: str = field(default_factory=new_code)
    cluster: Any = None    # loomcluster.ClusterBridge: offloaded hashchain/gen jobs run on the fleet, not just here

    def __post_init__(self) -> None:
        self.state_dir = Path(self.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.fails = 0
        self.code_issued = time.time()
        self.pending: dict[str, dict[str, str]] = {}   # client_id → nonces
        self.sessions_path = self.state_dir / "paired.json"
        self.sessions: dict[str, dict[str, Any]] = (
            json.loads(self.sessions_path.read_text()) if self.sessions_path.exists() else {})
        self.store = SyncStore(self.state_dir / "store", self.node_id)
        self.offload_log = self.state_dir / "offload.jsonl"
        from forge.mirrorweave import FrameHub, InputOutbox, StudioInputSpool   # C9 (lazy: keeps import graph flat)
        self.mirror = FrameHub(self.state_dir / "mirror")
        self.outbox = InputOutbox(self.state_dir / "mirror" / "outbox")         # desktop → phone input/focus events
        self.studio = StudioInputSpool(self.state_dir / "mirror" / "studio_input.jsonl")   # phone → Studio input events
        self.url = ""
        self.events: list[dict[str, Any]] = []
        self.on_event: Any = None   # callable(ev) — the CLI prints pairings / the new code

    def uri(self) -> str:
        q = urllib.parse.urlencode({"u": self.url, "c": self.code, "n": self.node_id})
        return f"loomlink://pair?{q}"

    def rotate(self) -> None:
        self.code, self.fails, self.code_issued = new_code(), 0, time.time()
        self.pending.clear()
        self._emit({"ev": "code_rotated"})

    def _emit(self, ev: dict[str, Any]) -> None:
        self.events.append(ev)
        if self.on_event:
            self.on_event(ev)

    def _save_sessions(self) -> None:
        tmp = self.sessions_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.sessions, indent=2, sort_keys=True))
        os.replace(tmp, self.sessions_path)
        os.chmod(self.sessions_path, 0o600)

    # --- pairing
    def hello(self, body: dict[str, Any]) -> dict[str, Any]:
        cid, nc = str(body["client_id"]), str(body["nc"])
        ns = secrets.token_hex(16)
        with self.lock:
            if time.time() - self.code_issued > CODE_TTL_S:
                self.rotate()
            if len(self.pending) >= MAX_PENDING:
                self.pending.pop(next(iter(self.pending)))
            self.pending[cid] = {"nc": nc, "ns": ns, "code": self.code}
        return {"ns": ns, "server_id": self.node_id,
                "proof": _mac(self.code.encode(), "srv", nc, ns, cid)}

    def confirm(self, body: dict[str, Any]) -> dict[str, Any]:
        cid = str(body["client_id"])
        with self.lock:
            p = self.pending.pop(cid, None)
            if p is None:
                raise PermissionError("no pairing in progress")
            if p["code"] != self.code or time.time() - self.code_issued > CODE_TTL_S:
                raise PermissionError("pairing code expired — use the current code")
            want = _mac(p["code"].encode(), "cli", p["nc"], p["ns"], cid)
            if not hmac.compare_digest(want, str(body.get("proof", ""))):
                self.fails += 1
                if self.fails >= MAX_FAILS:
                    self.rotate()
                raise PermissionError("bad proof")
            key = _mac(p["code"].encode(), "key", p["nc"], p["ns"], cid)
            granted = sorted(set(body.get("caps") or []) & set(self.allow))
            self.sessions[cid] = {"key": key, "caps": granted, "paired_at": time.time(), "last_ts": 0}
            self._save_sessions()
            self.rotate()   # one-time code
            self._emit({"ev": "paired", "client": cid, "caps": granted})
            return {"ok": True, "granted": granted, "server_id": self.node_id}

    # --- signed requests
    def verify(self, method: str, path: str, headers: Any, raw: bytes, cap: str) -> str:
        cid = headers.get("X-Loom-Client") or ""
        ts = headers.get("X-Loom-Ts") or "0"
        sig = headers.get("X-Loom-Sig") or ""
        with self.lock:
            s = self.sessions.get(cid)
            if s is None:
                raise PermissionError("unknown device")
            want = _mac(bytes.fromhex(s["key"]), method, path, ts, hashlib.sha256(raw).hexdigest())
            if not hmac.compare_digest(want, sig):
                raise PermissionError("bad signature")
            t = int(ts)
            if abs(t / 1000 - time.time()) > TS_WINDOW_S or t <= int(s.get("last_ts", 0)):
                raise PermissionError("stale or replayed request")
            s["last_ts"] = t
            if cap not in s["caps"]:
                raise PermissionError(f"capability {cap!r} not granted")
            return cid

    # --- offload / sync
    def offload(self, cid: str, job: dict[str, Any]) -> dict[str, Any]:
        op = job.get("op")
        if op == "recon.capture":
            payload = job.get("payload") or {}
            data = base64.b64decode(payload["data_b64"])
            from forge import lensforge          # C10: real CPU quality assessment; reconstruction itself stays a stub (C12)
            quality = lensforge.assess_or_reason(data)
            e = self.store.put(payload.get("id") or job["id"], "capture", data,
                               {"from": cid, "quality": quality,
                                "note": "stored for RealityLoom — reconstruction (C12 SplatForge) is a labelled stub"},
                               media=payload.get("media", "image/jpeg"))
            res: dict[str, Any] = {"ok": True, "value": {"stored": e["sha256"], "reconstruction": "stub", "quality": quality}}
        elif op in OPS:
            res = self._offload_cluster(job) if self.cluster is not None else None
            if res is None:
                try:
                    res = {"ok": True, "value": OPS[op](job.get("payload") or {})}
                except Exception as ex:  # noqa: BLE001 — reported to the phone, not raised
                    res = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        else:
            res = {"ok": False, "error": f"unsupported op {op!r}"}
        res.setdefault("node", self.node_id)
        res["job_id"] = job["id"]
        with self.offload_log.open("a", encoding="utf-8") as f:
            f.write(canonical({"client": cid, "job": job.get("id"), "op": op, "ok": res["ok"]}) + "\n")
        return res

    def _offload_cluster(self, job: dict[str, Any]) -> dict[str, Any] | None:
        """LoomCluster hand-off (C7): None → fleet unreachable, caller runs the job locally instead."""
        import urllib.error

        try:
            r = self.cluster.run(job)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return None
        r = dict(r)
        r["via"] = "loomcluster"
        return r

    def sync_manifest(self, cid: str, index: dict[str, Any]) -> dict[str, Any]:
        with self.store.lock:
            plan = plan_sync(self.store.entries, index, cid)
            # identical bytes edited on both sides: adopt the merged vector here too, so the next
            # round is a no-op on both ends
            merged = {c["id"] for c in plan["conflicts"] if c["resolution"] == "merged_identical"}
            for e in plan["pull"]:
                if e["id"] in merged:
                    self.store.install(e, None)
        return plan

    def sync_push(self, cid: str, entry: dict[str, Any], data: bytes, conflict_of: str | None) -> dict[str, Any]:
        if conflict_of:
            entry = {**entry, "id": f"{conflict_of}~{cid}", "conflict_of": conflict_of}
        self.store.install(entry, data)
        return {"ok": True, "id": entry["id"]}

    # --- http
    def serve(self, ready: Any = None, stop: threading.Event | None = None) -> None:
        srv_self = self
        stop = stop or threading.Event()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, obj: Any, code: int = 200, raw: bytes | None = None) -> None:
                b = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _raw(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def do_GET(self) -> None:
                try:
                    if self.path == "/link/info":
                        return self._send({"server_id": srv_self.node_id, "allow": list(srv_self.allow)})
                    if self.path == "/mirror/info":      # public, read-only: what MirrorWeave does and does not do
                        from forge import registry
                        return self._send(registry.descriptor("C9"))
                    if self.path.startswith("/sync/blob/"):
                        srv_self.verify("GET", self.path, self.headers, b"", "sync")
                        data = srv_self.store.read(self.path.rsplit("/", 1)[1])
                        return self._send(None, 200, data) if data is not None else self._send({"error": "missing"}, 404)
                    self._send({"error": "not found"}, 404)
                except PermissionError as e:
                    self._send({"error": str(e)}, 403)

            def do_POST(self) -> None:
                raw = self._raw()
                try:
                    body = json.loads(raw.decode() or "{}")
                    if self.path == "/pair/hello":
                        return self._send(srv_self.hello(body))
                    if self.path == "/pair/confirm":
                        return self._send(srv_self.confirm(body))
                    if self.path == "/offload":
                        cid = srv_self.verify("POST", self.path, self.headers, raw, "offload")
                        return self._send(srv_self.offload(cid, body))
                    if self.path == "/mirror/frame":
                        from forge.mirrorweave import FrameEnvelope
                        cid = srv_self.verify("POST", self.path, self.headers, raw, "mirror")
                        return self._send({**srv_self.mirror.accept(FrameEnvelope.from_wire(body)), "node": srv_self.node_id})
                    if self.path == "/mirror/latest":
                        cid = srv_self.verify("POST", self.path, self.headers, raw, "mirror")
                        env = srv_self.mirror.latest(str(body.get("stream", "")))
                        return self._send({"frame": env.to_wire() if env else None, "stats": srv_self.mirror.stats()})
                    if self.path == "/mirror/control":
                        from forge.mirrorweave import ControlMessage, handle_control
                        cid = srv_self.verify("POST", self.path, self.headers, raw, "drive_studio")
                        return self._send(handle_control(ControlMessage.from_wire(body), srv_self.mirror,
                                                         studio=srv_self.studio, device=cid))
                    if self.path == "/mirror/input/poll":     # phone fetches events its desktop queued (signed per event)
                        cid = srv_self.verify("POST", self.path, self.headers, raw, "mirror")
                        key = bytes.fromhex(srv_self.sessions[cid]["key"])
                        return self._send({"events": srv_self.outbox.deliver(cid, key, int(body.get("after", -1)))})
                    if self.path == "/sync/manifest":
                        cid = srv_self.verify("POST", self.path, self.headers, raw, "sync")
                        return self._send(srv_self.sync_manifest(cid, body.get("index", {})))
                    if self.path == "/sync/push":
                        cid = srv_self.verify("POST", self.path, self.headers, raw, "sync")
                        return self._send(srv_self.sync_push(cid, body["entry"], base64.b64decode(body["data_b64"]),
                                                             body.get("conflict_of")))
                    self._send({"error": "not found"}, 404)
                except PermissionError as e:
                    self._send({"error": str(e)}, 403)
                except StubError as e:               # labelled stub (C9–C12): 501, never a fabricated result
                    self._send({"error": str(e), "stub": True, "feature": e.feature, "key": e.key}, 501)
                except Exception as e:  # noqa: BLE001
                    self._send({"error": f"{type(e).__name__}: {e}"}, 400)

        srv = ThreadingHTTPServer((self.bind, self.port), H)
        self.port = srv.server_address[1]
        self.url = f"http://{self.bind}:{self.port}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        if ready:
            ready(self)
        stop.wait()
        srv.shutdown()


def qr_text(data: str) -> str | None:
    """Terminal QR when the optional `qrcode` package is present (no hard dependency)."""
    try:
        import io

        import qrcode  # type: ignore
    except ImportError:
        return None
    q = qrcode.QRCode(border=1)
    q.add_data(data)
    buf = io.StringIO()
    q.print_ascii(out=buf, invert=True)
    return buf.getvalue()


# ------------------------------------------------------------------------ python client
# Used by tests and by desktop↔desktop links; PocketLoom uses fabric.core.LoomLinkClient.

class LinkClient:
    def __init__(self, url: str, client_id: str) -> None:
        self.url, self.client_id, self.key, self.caps = url.rstrip("/"), client_id, b"", []
        self._last_ts = 0  # ms; bumped when two signs share a millisecond (matches Kotlin nextTs)

    def _post(self, path: str, body: dict[str, Any], signed: bool = True) -> dict[str, Any]:
        import urllib.request

        raw = json.dumps(body).encode()
        hdr = {"Content-Type": "application/json"}
        if signed:
            hdr.update(self._sign("POST", path, raw))
        req = urllib.request.Request(self.url + path, data=raw, headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def _sign(self, method: str, path: str, raw: bytes) -> dict[str, str]:
        # Server verify() rejects t <= last_ts (ms). A tight loop can issue two
        # requests in the same millisecond — bump, as Kotlin LoomLinkClient.nextTs does.
        ts_n = time.time_ns() // 1_000_000
        if ts_n <= self._last_ts:
            ts_n = self._last_ts + 1
        self._last_ts = ts_n
        ts = str(ts_n)
        return {"X-Loom-Client": self.client_id, "X-Loom-Ts": ts,
                "X-Loom-Sig": _mac(self.key, method, path, ts, hashlib.sha256(raw).hexdigest())}

    def pair(self, code: str, caps: list[str]) -> dict[str, Any]:
        nc = secrets.token_hex(16)
        h = self._post("/pair/hello", {"client_id": self.client_id, "nc": nc}, signed=False)
        if not hmac.compare_digest(h["proof"], _mac(code.encode(), "srv", nc, h["ns"], self.client_id)):
            raise PermissionError("server failed to prove the pairing code")
        r = self._post("/pair/confirm", {"client_id": self.client_id, "nc": nc, "ns": h["ns"], "caps": caps,
                                         "proof": _mac(code.encode(), "cli", nc, h["ns"], self.client_id)}, signed=False)
        self.key = bytes.fromhex(_mac(code.encode(), "key", nc, h["ns"], self.client_id))
        self.caps = r["granted"]
        return r

    def offload(self, job: dict[str, Any]) -> dict[str, Any]:
        return self._post("/offload", job)

    # C9 MirrorWeave
    def mirror_frame(self, env: Any) -> dict[str, Any]:
        return self._post("/mirror/frame", env.to_wire())

    def mirror_latest(self, stream: str) -> dict[str, Any]:
        return self._post("/mirror/latest", {"stream": stream})

    def mirror_control(self, msg: Any) -> dict[str, Any]:
        return self._post("/mirror/control", msg.to_wire())

    def mirror_input_poll(self, after: int = -1, verify: bool = True) -> list[dict[str, Any]]:
        """Fetch queued desktop → device events; with `verify` every event's HMAC is checked (as the Kotlin client does)."""
        from forge.mirrorweave import event_mac, validate_android_event

        evs = self._post("/mirror/input/poll", {"after": after})["events"]
        if verify:
            for e in evs:
                if not hmac.compare_digest(e["sig"], event_mac(self.key, self.client_id, e["seq"], e["event_json"])):
                    raise PermissionError("input event signature mismatch")
                e["event"] = validate_android_event(json.loads(e["event_json"]))
        return evs
