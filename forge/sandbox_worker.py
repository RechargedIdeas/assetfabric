"""Sandbox worker entry point: `python -m forge.sandbox_worker` reads one JSON request
on stdin and prints one JSON line on stdout. Runs *inside* a Sandbox (see forge.sandbox).

Requests:
  {"op": "generate", "brief": {...}, "root": "/repo"}  → artifacts (base64) + gates + meta
  {"op": "exec", "code": "..."}                         → runs code; used by limit tests

In the `process` tier the worker installs a CPython audit hook (PEP 578) that refuses
socket creation/connection and writes outside the scratch dir / $TMPDIR. This guards
Python-level code only; the `bwrap` tier enforces the same with kernel namespaces.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _install_guards() -> None:
    mode = os.environ.get("FABRIC_SANDBOX", "")
    if not mode.startswith("process:"):
        return   # bwrap tier: kernel namespaces do the work
    no_net = os.environ.get("FABRIC_NO_NETWORK", "1") == "1"
    allowed = [os.path.realpath(os.getcwd()), os.path.realpath(tempfile.gettempdir()), "/dev/null"]

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if no_net and event in ("socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo"):
            if event == "socket.__new__" and len(args) > 1 and args[1] == 1:   # AF_UNIX allowed
                return
            raise PermissionError(f"sandbox: network disabled ({event})")
        if event == "open" and len(args) >= 2 and isinstance(args[0], (str, bytes, os.PathLike)):
            m = args[1]
            writing = (isinstance(m, str) and any(c in m for c in "wax+")) or \
                      (isinstance(m, int) and m & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writing:
                p = os.path.realpath(os.fsdecode(args[0]))
                if not any(p == a or p.startswith(a + os.sep) for a in allowed):
                    raise PermissionError(f"sandbox: write outside scratch refused ({p})")

    sys.addaudithook(hook)


class _Ctx:
    def __init__(self, root: Path) -> None:
        from forge.patternvault import PatternVault

        self.root = root
        self.vault = PatternVault(root)


def _generate(req: dict[str, Any]) -> dict[str, Any]:
    from forge.generators import load_all

    brief = req["brief"]
    gens = load_all()
    out = gens[brief["kind"]](brief, _Ctx(Path(req["root"])))
    return {
        "ok_protocol": True,
        "artifacts": [{"name": a.name, "media_type": a.media_type, "data": base64.b64encode(a.data).decode()} for a in out.artifacts],
        "gates": [{"gate": g.gate, "ok": g.ok, "detail": g.detail} for g in out.gates],
        "meta": out.meta,
    }


def main() -> int:
    _install_guards()
    req = json.loads(sys.stdin.read() or "{}")
    op = req.get("op")
    if op == "generate":
        res = _generate(req)
    elif op == "exec":
        scope: dict[str, Any] = {}
        exec(compile(req["code"], "<sandbox>", "exec"), scope)   # noqa: S102 — this *is* the sandbox
        res = {"ok_protocol": True, "result": scope.get("result")}
    else:
        res = {"ok_protocol": False, "error": f"unknown op {op!r}"}
    sys.stdout.write(json.dumps(res, default=str) + "\n")
    return 0 if res.get("ok_protocol") else 2


if __name__ == "__main__":
    raise SystemExit(main())
