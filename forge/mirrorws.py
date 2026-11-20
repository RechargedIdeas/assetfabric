"""MirrorWeave WebSocket transport (C9) — low-latency frame/video push authenticated with the LoomLink pairing key.

Why a WebSocket next to the HTTP routes: one long-lived connection carries a 15–30 fps packet stream without a TCP/HTTP
round-trip per frame. It is **not** a second trust model: every message is HMAC-signed with the same session key and checked
by `LinkServer.verify` (device known, signature, strictly increasing timestamp, `mirror` capability).

Wire (binary message): `u32be header_len | header JSON | payload`. Header = FrameEnvelope fields minus `data_b64`, plus
`client`, `ts`, `sig` where `sig = HMAC(key, "WS" | "/mirror/ws/frame" | ts | sha256(canonical(meta) + "\\n" + payload))`.
The first message on a connection is a signed text `hello`; frames from any other client id on that socket are refused.
Library: `websockets` (BSD-3-Clause), optional extra `mirror`. [INFERENCE C-54]
"""

from __future__ import annotations

import hashlib
import json
import struct
import threading
from typing import Any

from forge.i18n import t
from forge.loomlink import LinkClient, LinkServer, canonical
from forge.mirrorweave import FrameEnvelope

PATH = "/mirror/ws"
MAX_MSG = 9 * 1024 * 1024


def _meta(env: FrameEnvelope) -> dict[str, Any]:
    return {k: v for k, v in env.to_wire().items() if k != "data_b64"}


def pack(client: LinkClient, env: FrameEnvelope) -> bytes:
    meta = _meta(env)
    raw = canonical(meta).encode() + b"\n" + env.data
    hdr = client._sign("WS", PATH + "/frame", raw)
    head = json.dumps({**meta, "client": hdr["X-Loom-Client"], "ts": hdr["X-Loom-Ts"], "sig": hdr["X-Loom-Sig"]}).encode()
    return struct.pack(">I", len(head)) + head + env.data


def unpack(msg: bytes) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    if len(msg) < 4:
        raise ValueError("short message")
    n = struct.unpack(">I", msg[:4])[0]
    if n > 64 * 1024 or 4 + n > len(msg):
        raise ValueError("bad header length")
    head = json.loads(msg[4:4 + n].decode())
    payload = msg[4 + n:]
    auth = {"X-Loom-Client": str(head.pop("client", "")), "X-Loom-Ts": str(head.pop("ts", "0")),
            "X-Loom-Sig": str(head.pop("sig", ""))}
    return head, auth, payload


class MirrorWsServer:
    """Runs next to a LinkServer (shares its sessions and FrameHub)."""

    def __init__(self, link: LinkServer, bind: str = "127.0.0.1", port: int = 0) -> None:
        self.link, self.bind, self.port = link, bind, port
        self._srv: Any = None
        self.url = ""
        self.accepted = 0
        self.refused = 0

    def _handler(self, ws: Any) -> None:
        if getattr(ws, "request", None) is not None and ws.request.path != PATH:
            ws.close(1008, "bad path")
            return
        try:
            hello = json.loads(ws.recv(timeout=10))
            hdr = {"X-Loom-Client": str(hello.get("client", "")), "X-Loom-Ts": str(hello.get("ts", "0")),
                   "X-Loom-Sig": str(hello.get("sig", ""))}
            cid = self.link.verify("WS", PATH + "/hello", hdr, b"hello", "mirror")
        except Exception as e:  # noqa: BLE001
            self.refused += 1
            ws.send(json.dumps({"type": "error", "error": t("mirror.ws.auth_failed", reason=str(e)[:120])}))
            ws.close(1008, "auth")
            return
        ws.send(json.dumps({"type": "welcome", "node": self.link.node_id, "client": cid}))
        for msg in ws:
            if isinstance(msg, str):
                ws.send(json.dumps({"type": "error", "error": "expected binary frame"}))
                continue
            try:
                meta, auth, payload = unpack(msg)
                if auth["X-Loom-Client"] != cid:
                    raise PermissionError("client id changed on an authenticated socket")
                raw = canonical(meta).encode() + b"\n" + payload
                self.link.verify("WS", PATH + "/frame", auth, raw, "mirror")
                import base64
                env = FrameEnvelope.from_wire({**meta, "data_b64": base64.b64encode(payload).decode()})
                ack = self.link.mirror.accept(env)
                self.accepted += 1
                ws.send(json.dumps({"type": "ack", **ack}))
            except PermissionError as e:
                self.refused += 1
                ws.send(json.dumps({"type": "error", "status": 403, "error": str(e)}))
            except Exception as e:  # noqa: BLE001
                self.refused += 1
                ws.send(json.dumps({"type": "error", "status": 400, "error": f"{type(e).__name__}: {e}"}))

    def start(self) -> "MirrorWsServer":
        from websockets.sync.server import serve

        self._srv = serve(self._handler, self.bind, self.port, max_size=MAX_MSG, compression=None)
        self.port = self._srv.socket.getsockname()[1]
        self.url = f"ws://{self.bind}:{self.port}{PATH}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._srv is not None:
            self._srv.shutdown()


class MirrorWsClient:
    """Python sender (desktop→desktop and tests). PocketLoom pushes the same envelopes over signed HTTP (no WS dependency
    in the APK) — `fabric.core.MirrorClient`."""

    def __init__(self, url: str, link: LinkClient) -> None:
        self.url, self.link, self.ws = url, link, None

    def __enter__(self) -> "MirrorWsClient":
        from websockets.sync.client import connect

        self._cm = connect(self.url, max_size=MAX_MSG, compression=None, open_timeout=10)
        self.ws = self._cm.__enter__()
        hdr = self.link._sign("WS", PATH + "/hello", b"hello")
        self.ws.send(json.dumps({"type": "hello", "client": hdr["X-Loom-Client"], "ts": hdr["X-Loom-Ts"],
                                 "sig": hdr["X-Loom-Sig"]}))
        r = json.loads(self.ws.recv(timeout=10))
        if r.get("type") != "welcome":
            raise PermissionError(r.get("error", "refused"))
        return self

    def __exit__(self, *a: Any) -> None:
        if self.ws is not None:
            self._cm.__exit__(None, None, None)

    def send(self, env: FrameEnvelope) -> dict[str, Any]:
        self.ws.send(pack(self.link, env))
        return json.loads(self.ws.recv(timeout=30))

    def send_raw(self, msg: bytes) -> dict[str, Any]:
        self.ws.send(msg)
        return json.loads(self.ws.recv(timeout=30))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
