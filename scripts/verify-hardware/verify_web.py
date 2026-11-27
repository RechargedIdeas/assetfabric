#!/usr/bin/env python3
"""Verify the Game Zero `web` (threads) and `web-nothreads` builds on a PUBLIC HTTPS host (post-F9, 0.9.1).

    # upload dist/web/ and dist/web-nothreads/ to your host first (docs/hardware-verification.md §Web), then:
    python scripts/verify-hardware/verify_web.py --web https://example.org/gamezero/ --nothreads https://example.org/gz-st/
    python scripts/verify-hardware/hwreport.py answer hw-reports/web-<stamp>.json      # Firefox / Safari / PWA items

Runs from the forge venv (needs the `package` extra: Playwright driving the system Chrome — the same harness as
`forge accept F7`). Per variant: HTTPS + certificate, HTTP 200 for the runtime files, wasm MIME type, COOP/COEP
(required for `web`, not needed for `web-nothreads`), headless-Chrome boot with 0 script errors, service worker
registered + runtime cached, offline reload from the SW cache, IndexedDB save round-trip (nothreads also runs the
swap advisor's serial path). `--self-test` serves the local dist/ folders over loopback HTTP instead (no public host) —
that proves the script, not the host.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import hwreport as H  # noqa: E402

RUNTIME = ("index.html", "index.js", "index.wasm", "index.pck", "index.service.worker.js", "index.manifest.json")


def _get(url: str, method: str = "GET") -> tuple[int, dict[str, str]]:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "assetfabric-verify-web/1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - user-given host
            if method == "GET":
                r.read(1024)
            return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}


def tls_info(url: str) -> dict[str, Any]:
    u = urllib.parse.urlsplit(url)
    ctx = ssl.create_default_context()
    with socket.create_connection((u.hostname, u.port or 443), timeout=15) as sk, ctx.wrap_socket(sk, server_hostname=u.hostname) as ss:
        c = ss.getpeercert()
        issuer = dict(x[0] for x in c.get("issuer", ()))
        return {"version": ss.version(), "issuer": issuer.get("organizationName") or issuer.get("commonName"),
                "not_after": c.get("notAfter")}


def check_variant(rep: dict[str, Any], name: str, base: str, threads: bool, allow_http: bool, wh: Any) -> None:
    from forge.accept_f7 import _b64, remap_save

    base = base if base.endswith("/") else base + "/"
    p = f"{name}."
    https = base.startswith("https://")
    H.add(rep, p + "https", True if https else (None if allow_http else False), base)
    if https:
        try:
            H.add(rep, p + "tls_certificate_valid", True, tls_info(base))
        except (ssl.SSLError, OSError) as e:
            H.add(rep, p + "tls_certificate_valid", False, f"{type(e).__name__}: {e}")
    codes, hdrs = {}, {}
    for f in RUNTIME:
        codes[f], hdrs[f] = _get(base + f, "GET" if f == "index.html" else "HEAD")
    H.add(rep, p + "runtime_files_200", all(c == 200 for c in codes.values()), codes)
    H.add(rep, p + "wasm_mime", hdrs["index.wasm"].get("content-type", "").startswith("application/wasm"),
          hdrs["index.wasm"].get("content-type"))
    iso = {f: {k: hdrs[f].get(k) for k in ("cross-origin-opener-policy", "cross-origin-embedder-policy")} for f in
           ("index.html", "index.wasm", "index.pck")}
    if threads:
        H.add(rep, p + "coop_coep_headers", all(v["cross-origin-opener-policy"] == "same-origin"
                                                and v["cross-origin-embedder-policy"] == "require-corp" for v in iso.values()), iso)
    else:
        rep["device"].setdefault("isolation_headers", {})[name] = iso
    first = wh.run(base, ["--net-report"])
    on = wh.run(base, ["--net-report"], settle_sw=True)
    pg = on.get("page") or {}
    H.add(rep, p + "boots", bool(on["boot_ok"]) and on["script_errors"] == 0,
          {"first_wall_s": first.get("wall_s"), "wall_s": on.get("wall_s"), "error": on.get("error"),
           "version": (on["result"] or {}).get("version")})
    rep["build_version"] = rep["build_version"] or (on["result"] or {}).get("version")
    H.add(rep, p + "net_dormant", bool(((on["result"] or {}).get("net") or {}).get("offline_peer")), None)
    if threads:
        H.add(rep, p + "cross_origin_isolated", bool(pg.get("isolated")) and bool(pg.get("sab")),
              {"isolated": pg.get("isolated"), "sab": pg.get("sab")})
    H.add(rep, p + "service_worker", bool(pg.get("sw_registered")) and {"index.wasm", "index.pck"} <= set(pg.get("cached", [])),
          {"registered": pg.get("sw_registered"), "cached": sorted(pg.get("cached", []))[:12]})
    if not threads:
        sb = wh.run(base, ["--scene=swapbench", "--reps=1"], wait_for="SWAPBENCH", timeout_s=240)
        sbr = json.loads(sb["marker_lines"][0].split(" ", 1)[1]) if sb["marker_lines"] else {}
        H.add(rep, p + "swap_advisor_serial", bool(sbr) and sbr.get("parity") is True and sb["script_errors"] == 0,
              {k: sbr.get(k) for k in ("states", "parity")} if sbr else sb.get("error"))
    sv = wh.run(base, ["--scene=savecheck", f"--import-b64={_b64(remap_save())}", "--rewrite"])
    off = wh.run(base, ["--scene=savecheck"], offline=True)
    a, b = (sv["result"] or {}).get("savecheck") or {}, (off["result"] or {}).get("savecheck") or {}
    H.add(rep, p + "save_roundtrip_indexeddb", bool(a.get("loaded")) and a.get("reloaded_equal") is True, None)
    H.add(rep, p + "offline_reload", bool(off["boot_ok"]) and bool((off.get("page") or {}).get("sw_controller"))
          and bool(b.get("loaded")) and b.get("loaded") == a.get("loaded"), {"error": off.get("error")})


def run(args: argparse.Namespace) -> Path:
    from forge.pwa import WebHarness

    rep = H.new_report("web", "verify_web.py", ["web"])
    rep["device"] = {"mode": "self-test (loopback, local dist/)" if args.self_test else "public host",
                     "web": args.web, "nothreads": args.nothreads}
    if args.web:
        with WebHarness() as wh:
            check_variant(rep, "web", args.web, True, args.allow_http, wh)
    if args.nothreads:                       # fresh profile: the nothreads SW must not inherit the threads build's cache
        with WebHarness() as wh2:
            check_variant(rep, "web_nothreads", args.nothreads, False, args.allow_http, wh2)
    return H.finish(rep, Path(args.out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--web", help="Public HTTPS base URL of dist/web/ (threads; host must send COOP/COEP).")
    ap.add_argument("--nothreads", help="Public HTTPS base URL of dist/web-nothreads/ (any static host).")
    ap.add_argument("--out", default=str(ROOT / "hw-reports"))
    ap.add_argument("--allow-http", action="store_true", help="Do not fail plain http:// (local testing only).")
    ap.add_argument("--self-test", action="store_true", help="Serve local dist/web + dist/web-nothreads on loopback.")
    a = ap.parse_args(argv)
    if a.self_test:
        from forge.pwa import LocalHost

        a.allow_http = True
        with LocalHost(ROOT / "dist/web", isolation=True) as h1, LocalHost(ROOT / "dist/web-nothreads", isolation=False) as h2:
            a.web, a.nothreads = h1.url, h2.url
            p = run(a)
    else:
        if not (a.web or a.nothreads):
            ap.error("give --web and/or --nothreads (or --self-test)")
        p = run(a)
    rep = json.loads(p.read_text(encoding="utf-8"))
    print(H.summary(rep))
    print(f"\nreport: {p}\nnext:   python {HERE / 'hwreport.py'} answer {p}")
    return 0 if rep["verdict"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
