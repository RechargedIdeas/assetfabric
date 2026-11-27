"""Companion track acceptance C7 (LoomCluster) and C8 (GroundWeave).

Both run for real on this host with **local loopback nodes** (separate OS processes) — there is no LAN/fleet in CI.
That is the honest scope: the protocol, scheduling, determinism, failure handling and the CPU fallbacks are proven;
cross-machine transport (LAN / Tailscale), a Kotlin cluster peer and real GPU rungs are not (see docs/INFERENCES.md).

* **C7 LoomCluster** — (1) negotiation: adverts, gossip mesh, allocation caps → slots, elected coordinator;
  (2) determinism: the same batch of hashchain + Content Forge `gen` jobs on a 1-node (2 cores pinned, no GPU),
  a 2-node and a 3-node fleet yields byte-identical per-job values and batch digest, equal to a direct local run;
  (3) work stealing with all jobs submitted to the smallest node; (4) failure: SIGKILL a node holding stolen work
  → leases expire, work re-runs elsewhere; failing jobs are retried then reported; unknown ops are rejected;
  (5) checkpointing: the *origin* is SIGKILLed mid-batch and restarted from its journal — recovered work + parked
  results from peers complete the batch; (6) device negotiation: a job that needs a device is placed on the node that
  advertises it and refused when none does; (7) `forge cluster gen --out` lands artifact bytes identical to a local
  build; (8) PocketLoom LoomLink: a paired client's offloaded jobs run on the fleet (Python client always; the
  Kotlin FabricCore client too when the JDK/SDK build is available), and fall back to the desktop when the fleet is gone;
  (9) node auth + blobs (Q6): unsigned / wrongly keyed / tampered / stale / replayed requests get 401, unsigned
  responses are refused, and a 4 MiB artifact made on one node reaches the origin over signed `/blob/<sha256>`.
* **C8 GroundWeave** — ladder rules (every generator kind declared; a real CPU rung last, or `gpu_required` + route);
  selection never picks a planned backend; runtime fallback demotes a failing GPU rung to the CPU rung; every op's
  CPU path runs pinned to 2 cores with GPUs hidden inside its budget and produces output **byte-identical** to the
  unpinned run and to a run with every GPU "present"; `forge build`'s pipeline refuses a generator with no ladder entry;
  GPU-required ops are routed through LoomCluster; PocketLoom's own ladder (C2) is cross-referenced.

Fast mode (``FORGE_ACCEPT_FAST=1``, used by pytest) shrinks the batches and skips the Kotlin hop; the checks are the same.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
from pathlib import Path
from typing import Any

from forge.accept_f6 import fast_mode

GEN_BRIEFS_FULL = ["hero_kael", "enemy_emberling", "cave_01", "mat_cave_stone", "roster", "music_cave", "callouts",
                   "persona_lm", "policy_target", "world", "spr_vex", "cave_boss"]
GEN_BRIEFS_FAST = ["hero_kael", "cave_01", "mat_cave_stone", "roster", "world"]


def _jobs(fast: bool) -> list[dict[str, Any]]:
    briefs = GEN_BRIEFS_FAST if fast else GEN_BRIEFS_FULL
    hc = 12 if fast else 24
    jobs = [{"id": f"hc{i:03d}", "op": "hashchain", "payload": {"seed": i, "rounds": 60000}} for i in range(hc)]
    jobs += [{"id": f"gen:{b}", "op": "gen", "payload": {"brief_id": b}} for b in briefs]
    return jobs


def _reference(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The direct, cluster-free computation every fleet must reproduce."""
    from forge.loomlink import OPS

    return {j["id"]: {"value": OPS[j["op"]](j["payload"])} for j in jobs}


def _mesh_ok(fl: Any) -> bool:
    return fl.wait_mesh(20)


def _by_node(res: dict[str, dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in res.values():
        out[r["node"]] = out.get(r["node"], 0) + 1
    return dict(sorted(out.items()))


def _values_equal(res: dict[str, dict[str, Any]], ref: dict[str, dict[str, Any]]) -> list[str]:
    return [j for j in ref if not res.get(j, {}).get("ok") or res[j].get("value") != ref[j]["value"]]


# ====================================================================================== C7

def _determinism(root: Path, tmp: Path, fast: bool) -> dict[str, Any]:
    from forge import groundweave
    from forge import loomcluster as lc

    jobs = _jobs(fast)
    ref = _reference(jobs)
    ref_digest = lc.batch_digest(ref)
    budgets = {o: float(v.get("budget_s_2core", 0)) for o, v in groundweave.load_ladder(root)["ops"].items()}
    configs = {
        "n1_2core_nogpu": [("a", 2, "cpu", 100, 2)],
        "n2": [("a", 1, "cpu", 100, 0), ("b", 2, "cpu", 100, 0)],
        "n3": [("a", 1, "cpu", 100, 0), ("b", 2, "cpu", 100, 0), ("c", 4, "cpu,vulkan", 100, 0)],
    }
    out: dict[str, Any] = {"jobs": len(jobs), "reference_digest": ref_digest, "runs": {}}
    for name, nodes in configs.items():
        with lc.Fleet(tmp / f"det-{name}") as fl:
            for nid, cores, devs, cap, pin in nodes:
                fl.add(nid, cores, devs, cap, pin)
            mesh = _mesh_ok(fl)
            t0 = time.time()
            res = lc.run_batch(fl.urls["a"], jobs, 180 if not fast else 90)
            wall = time.time() - t0
            st = {n: fl.status(n)["stats"] for n in fl.urls}
        bad = _values_equal(res, ref)
        gen_wall = max((r["wall_s"] for j, r in res.items() if j.startswith("gen:")), default=0.0)
        over = [j for j, r in res.items() if j.startswith("gen:") and r["wall_s"] > budgets.get(
            "gen." + next(b["kind"] for b in _briefs(root) if b["id"] == j.split(":", 1)[1]), 1e9)]
        out["runs"][name] = {
            "nodes": len(nodes), "mesh": mesh, "complete": len(res) == len(jobs), "wrong": bad,
            "batch_digest": lc.batch_digest(res), "wall_s": round(wall, 2), "executed_by_node": _by_node(res),
            "max_gen_job_s": round(gen_wall, 3), "over_budget": over,
            "stolen_in": {n: s["stolen_in"] for n, s in st.items()},
        }
    runs = out["runs"].values()
    digests = {r["batch_digest"] for r in runs} | {ref_digest}
    out["digests_equal"] = len(digests) == 1
    out["spread"] = (out["runs"]["n3"]["executed_by_node"] and len(out["runs"]["n3"]["executed_by_node"]) >= 2
                     and sum(v for k, v in out["runs"]["n3"]["stolen_in"].items() if k != "a") > 0)
    out["ok"] = (all(r["mesh"] and r["complete"] and not r["wrong"] and not r["over_budget"] for r in runs)
                 and out["digests_equal"] and bool(out["spread"]))
    return out


def _briefs(root: Path) -> list[dict[str, Any]]:
    from forge.pipeline import load_briefs

    return load_briefs(root)


def _negotiation(tmp: Path) -> dict[str, Any]:
    from forge import loomcluster as lc

    with lc.Fleet(tmp / "neg") as fl:
        fl.add("a", 2, "cpu", 100)
        fl.add("b", 8, "cpu,vulkan", 25)        # 8 cores but the user capped it at 25 % → 2 slots
        fl.add("c", 4, "cpu,rocm", 50)
        mesh = _mesh_ok(fl)
        adv = {n: lc._http(u + "/advert") for n, u in fl.urls.items()}
        st = {n: fl.status(n) for n in fl.urls}
        # placement: a job needing vulkan submitted to a (no vulkan) is placed on b; rocm → c; nothing → refused
        placed = {}
        for dev in ("vulkan", "rocm"):
            ids = [f"need-{dev}-{i}" for i in range(4)]
            jobs = [{"id": i, "op": "hashchain", "payload": {"seed": i, "rounds": 2000}, "requires": {"device": dev}}
                    for i in ids]
            res = lc.run_batch(fl.urls["a"], jobs, 30)
            placed[dev] = _by_node(res)
        refused = None
        try:
            lc._http(fl.urls["a"] + "/submit", {"id": "need-directml", "op": "hashchain", "payload": {},
                                                "requires": {"device": "directml"}})
        except urllib.error.HTTPError as e:
            refused = {"status": e.code, "error": json.loads(e.read().decode()).get("error")}
        unknown = None
        try:
            lc._http(fl.urls["a"] + "/submit", {"id": "x", "op": "rm-rf", "payload": {}})
        except urllib.error.HTTPError as e:
            unknown = e.code
    slots = {n: a["slots"] for n, a in adv.items()}
    ok = (mesh and slots == {"a": 2, "b": 2, "c": 2}
          and all(s["coordinator"] == "a" for s in st.values())
          and all(len(s["peers"]) == 2 for s in st.values())
          and placed["vulkan"] == {"b": 4} and placed["rocm"] == {"c": 4}
          and refused is not None and refused["status"] == 400 and "no node advertises" in (refused["error"] or "")
          and unknown == 400)
    return {"ok": ok, "slots": slots, "coordinator": {n: s["coordinator"] for n, s in st.items()}, "placed": placed,
            "refused_unadvertised_device": refused, "unknown_op_status": unknown,
            "adverts": {n: {k: a[k] for k in ("cores", "allocation_cap_pct", "devices", "slots")} for n, a in adv.items()}}


def _failures(tmp: Path, fast: bool) -> dict[str, Any]:
    from forge import loomcluster as lc

    rounds, n = (400000, 32) if fast else (400000, 48)
    expect = {f"k{i:03d}": lc.expected_hashchain(i, rounds) for i in range(n)}
    batch = [{"id": j, "op": "hashchain", "payload": {"seed": i, "rounds": rounds}} for i, j in enumerate(expect)]
    out: dict[str, Any] = {}
    # (a) SIGKILL a node that holds stolen work
    with lc.Fleet(tmp / "kill") as fl:
        fl.add("a", 1)
        fl.add("b", 2)
        fl.add("c", 4)
        _mesh_ok(fl)
        killed: dict[str, Any] = {}

        def tick(st: dict[str, Any]) -> None:
            if not killed and st["results"] >= n // 4:
                pre = fl.status("c")
                if pre["queue"] + pre["running"] > 0:
                    fl.kill("c")
                    killed.update(results_at_kill=st["results"], c_held=pre["queue"] + pre["running"])

        t0 = time.time()
        res = lc.run_batch(fl.urls["a"], batch, 90, tick)
        sa = fl.status("a")
        bad = [j for j, d in expect.items() if res.get(j, {}).get("value", {}).get("digest") != d]
        out["kill_node"] = {"ok": bool(killed) and len(res) == n and not bad and sa["stats"]["requeued"] > 0,
                            "killed": killed or None, "completed": len(res), "wrong": bad,
                            "requeued_at_origin": sa["stats"]["requeued"], "lease_s": lc.protocol_config()["lease_s"],
                            "elapsed_s": round(time.time() - t0, 2), "executed_by_node": _by_node(res)}
    # (b) retry + give-up
    with lc.Fleet(tmp / "retry") as fl:
        fl.add("a", 1)
        fl.add("b", 2)
        _mesh_ok(fl)
        m1, m2 = tmp / "flaky1.mark", tmp / "flaky2.mark"
        res = lc.run_batch(fl.urls["a"], [
            {"id": "flaky-recovers", "op": "flaky", "payload": {"marker": str(m1), "fail_first": 2}},
            {"id": "flaky-forever", "op": "flaky", "payload": {"marker": str(m2), "fail_first": 99}},
            {"id": "gen-missing", "op": "gen", "payload": {"brief_id": "no_such_brief"}},
        ], 60)
        rec, forever, missing = res.get("flaky-recovers", {}), res.get("flaky-forever", {}), res.get("gen-missing", {})
        mx = int(lc.protocol_config()["max_attempts"])
        out["retry"] = {
            "ok": (rec.get("ok") and rec.get("attempts") == 3 and not forever.get("ok") and forever.get("attempts") == mx
                   and "induced failure" in forever.get("error", "") and not missing.get("ok")
                   and missing.get("attempts") == mx),
            "recovers_after_attempts": rec.get("attempts"), "gives_up_after": forever.get("attempts"),
            "max_attempts": mx, "bad_brief_error": (missing.get("error") or "")[:120]}
    # (c) origin crash + restart from journal
    with lc.Fleet(tmp / "origin") as fl:
        fl.add("a", 1)
        fl.add("b", 4)
        _mesh_ok(fl)
        total, rr = 24, 1_500_000
        exp = {f"o{i:03d}": lc.expected_hashchain(i, rr) for i in range(total)}
        for i, j in enumerate(exp):
            lc._http(fl.urls["a"] + "/submit", {"id": j, "op": "hashchain", "payload": {"seed": i, "rounds": rr}})
        time.sleep(1.2)
        fl.kill("a")
        time.sleep(float(lc.protocol_config()["http_timeout_s"]) + 1.5)     # long enough for peers to park results
        fl.restart("a")
        res = lc.collect(fl.urls["a"], list(exp), 90)
        sa, sb = fl.status("a"), fl.status("b")
        bad = [j for j, d in exp.items() if res.get(j, {}).get("value", {}).get("digest") != d]
        out["origin_restart"] = {"ok": len(res) == total and not bad and sa["stats"]["recovered"] > 0,
                                 "completed": len(res), "wrong": bad,
                                 "recovered_from_journal": sa["stats"]["recovered"],
                                 "parked_results_redelivered_by_peer": sb["stats"]["redelivered"],
                                 "executed_by_node": _by_node(res)}
    out["ok"] = all(v["ok"] for v in out.values() if isinstance(v, dict))
    return out


def _cli_gen(root: Path, tmp: Path) -> dict[str, Any]:
    """`forge cluster gen --out`: bytes landed from the fleet == a local build of the same briefs."""
    from forge import loomcluster as lc
    from forge.generators import load_all
    from forge.pipeline import Context

    briefs = ["hero_kael", "cave_01", "mat_cave_stone"]
    ctx = Context.create(root)
    allb = {b["id"]: b for b in _briefs(root)}
    local = {b: {a.name: hashlib.sha256(a.data).hexdigest() for a in load_all()[allb[b]["kind"]](allb[b], ctx).artifacts}
             for b in briefs}
    with lc.Fleet(tmp / "cli") as fl:
        fl.add("a", 1)
        fl.add("b", 2)
        _mesh_ok(fl)
        out_dir = tmp / "cli-out"
        argv = [sys.executable, "-m", "forge.cli", "cluster", "gen", "--to", fl.urls["a"], "--out", str(out_dir)]
        for b in briefs:
            argv += ["--brief", b]
        p = subprocess.run(argv, capture_output=True, text=True, cwd=root, timeout=180)
    try:
        rep = json.loads(p.stdout)
    except json.JSONDecodeError:
        rep = {"stdout": p.stdout[-300:], "stderr": p.stderr[-300:]}
    landed = {b: {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((out_dir / b).glob("*"))}
              for b in briefs}
    return {"ok": p.returncode == 0 and landed == local and bool(rep.get("ok")), "exit": p.returncode,
            "files_identical_to_local_build": landed == local, "executed_by_node": rep.get("executed_by_node"),
            "batch_digest": rep.get("batch_digest")}


def _loomlink(root: Path, tmp: Path, fast: bool) -> dict[str, Any]:
    """A paired PocketLoom client's offload runs on the fleet; with the fleet gone the desktop still answers."""
    from forge import loomcluster as lc
    from forge.accept_companions import Desktop, free_port, full_possible, jar
    from forge.loomlink import LinkClient, op_hashchain

    seeds = [f"s{i}" for i in range(6)]
    out: dict[str, Any] = {}
    with lc.Fleet(tmp / "ll") as fl:
        fl.add("a", 1)
        fl.add("b", 2)
        fl.add("c", 2)
        _mesh_ok(fl)
        d = Desktop(tmp / "ll-desk", port=free_port()).start()
        d.srv.cluster = lc.ClusterBridge(fl.urls["a"])
        try:
            cli = LinkClient(d.srv.url, "pyphone")
            cli.pair(d.srv.code, ["offload"])
            jobs = [{"id": f"p{i}", "op": "hashchain", "payload": {"seed": s, "rounds": 20000}} for i, s in enumerate(seeds)]
            jobs.append({"id": "pgen", "op": "gen", "payload": {"brief_id": "hero_kael"}})
            res = {j["id"]: cli.offload(j) for j in jobs}
            want = {j["id"]: op_hashchain(j["payload"])["digest"] for j in jobs if j["op"] == "hashchain"}
            wrong = [i for i, dg in want.items() if res[i].get("value", {}).get("digest") != dg]
            via = {r.get("via") for r in res.values()}
            nodes = sorted({r["node"] for r in res.values()})
            out["python_client"] = {"ok": not wrong and via == {"loomcluster"} and len(nodes) >= 2
                                    and res["pgen"].get("ok") and res["pgen"]["value"]["ok"],
                                    "via": sorted(via), "executed_on": nodes, "wrong": wrong}
            if not fast and full_possible(root):
                from forge.accept_companions import gradle_build

                gradle_build(root)      # fat jar (FabricCore CLI); a no-op when C1–C6 already built it in this process tree
                home = tmp / "kt-phone"
                d2 = Desktop(tmp / "ll-desk2", port=free_port()).start()
                d2.srv.cluster = lc.ClusterBridge(fl.urls["a"])
                try:
                    _, p = jar(root, "pair", "--uri", d2.srv.uri(), home=home)
                    for s in seeds:
                        jar(root, "offload", "--op", "hashchain", "--seed", s, "--rounds", "5000", home=home)
                    _, dr = jar(root, "drain", home=home, timeout=240)
                finally:
                    d2.halt()
                kres = (dr or {}).get("results", {})
                got = {r["value"]["digest"] for r in kres.values() if isinstance(r.get("value"), dict) and "digest" in r["value"]}
                exp = {op_hashchain({"seed": s, "rounds": 5000})["digest"] for s in seeds}
                kvia = {r.get("via") for r in kres.values()}
                knodes = sorted({r.get("node") for r in kres.values()})
                out["kotlin_client"] = {"ok": got == exp and kvia == {"loomcluster"} and len(knodes) >= 2,
                                        "drained": {k: v for k, v in (dr or {}).items() if k != "results"},
                                        "via": sorted(x for x in kvia if x), "executed_on": knodes}
            else:
                out["kotlin_client"] = {"ok": True, "skipped": "fast mode / no JDK+SDK — Python LinkClient only"}
        finally:
            d.halt()
    # fleet gone → graceful local fallback (new bridge pointing at the dead entry)
    d3 = Desktop(tmp / "ll-desk3", port=free_port()).start()
    d3.srv.cluster = lc.ClusterBridge(fl.urls["a"], timeout_s=3.0)
    try:
        cli = LinkClient(d3.srv.url, "pyphone2")
        cli.pair(d3.srv.code, ["offload"])
        r = cli.offload({"id": "fb", "op": "hashchain", "payload": {"seed": "z", "rounds": 1000}})
        out["fleet_down_fallback"] = {"ok": r.get("ok") and r.get("node") == "desktop" and "via" not in r
                                      and r["value"]["digest"] == op_hashchain({"seed": "z", "rounds": 1000})["digest"],
                                      "node": r.get("node")}
    finally:
        d3.halt()
    out["ok"] = all(v["ok"] for v in out.values())
    return out


def _auth_and_blobs(tmp: Path) -> dict[str, Any]:
    """Q6 (C-95/C-96): nodes refuse unsigned / wrongly keyed / tampered / stale / replayed requests and unsigned
    responses; a 4 MiB artifact made on node b travels to the origin a over signed /blob/<sha256>, not in JSON."""
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from forge import loomcluster as lc

    def code(fn: Any) -> Any:
        try:
            fn()
            return 200
        except urllib.error.HTTPError as e:
            return e.code
        except lc.ClusterAuthError:
            return "refused_response"

    def raw_req(url: str, body: bytes, ts: str, nonce: str, sig_body: bytes | None = None) -> Any:
        key = lc.cluster_key()
        path = "/" + url.split("/", 3)[3]
        sig = lc._mac(key, "POST", path, ts, nonce, lc._sha(body if sig_body is None else sig_body))
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "X-Loom-Ts": ts, "X-Loom-Nonce": nonce, "X-Loom-Sig": sig})
        return lambda: urllib.request.urlopen(req, timeout=3).read()

    out: dict[str, Any] = {}
    with lc.Fleet(tmp / "auth") as fl:
        fl.add("a", 1)
        fl.add("b", 1, devices="cpu,directml")
        _mesh_ok(fl)
        a = fl.urls["a"]
        now = str(int(time.time() * 1000))
        body = json.dumps({"op": "hashchain", "id": "ok1", "payload": {"seed": 1, "rounds": 10}}).encode()
        rej = {
            "unsigned_get": code(lambda: lc._http(a + "/status", sign=False)),
            "unsigned_submit": code(lambda: lc._http(a + "/submit", {"op": "hashchain", "payload": {}}, sign=False)),
            "wrong_key": code(lambda: lc._http(a + "/status", key=b"\x01" * 32)),
            "tampered_body": code(raw_req(a + "/submit", body, now, "n-tamper",
                                          sig_body=json.dumps({"op": "hashchain", "id": "other", "payload": {}}).encode())),
            "stale_timestamp": code(raw_req(a + "/submit", body, str(int(time.time() * 1000) - 600_000), "n-stale")),
        }
        first = raw_req(a + "/submit", body, now, "n-replay")
        replay = {"first": code(first), "second": code(first)}

        class Rogue(BaseHTTPRequestHandler):          # answers 200 without a response signature
            def log_message(self, *x: Any) -> None:
                pass

            def do_GET(self) -> None:
                b = b'{"stats": {}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        rogue = ThreadingHTTPServer(("127.0.0.1", 0), Rogue)
        threading.Thread(target=rogue.serve_forever, daemon=True).start()
        unsigned_resp = code(lambda: lc._http(f"http://127.0.0.1:{rogue.server_address[1]}/status"))
        rogue.shutdown()
        st = lc._http(a + "/status")
        # blob: the job needs `directml`, which only b advertises → runs on b, origin a pulls the blob
        size = 4 << 20
        lc._http(a + "/submit", {"id": "blob1", "op": "bytes", "payload": {"seed": "q6", "size": size},
                                 "requires": {"device": "directml"}}, 5.0)
        res = lc.collect(a, ["blob1"], 60).get("blob1", {})
        blob = (res.get("value") or {}).get("blobs", {}).get("blob.bin", {})
        data = lc.fetch_blob(a, blob["sha256"]) if blob else b""
        sa, sb = fl.status("a")["stats"], fl.status("b")["stats"]
        out["blob"] = {"ok": bool(blob) and res.get("node") == "b" and "data_b64" not in res.get("value", {})
                       and len(json.dumps(res)) < 2048 and data == lc.bytes_stream("q6", size) and blob["size"] == size
                       and sa["blobs_in"] >= 1 and sb["blobs_out"] >= 1,
                       "executed_on": res.get("node"), "result_json_bytes": len(json.dumps(res)), "blob_bytes": len(data),
                       "sha256": blob.get("sha256"), "origin_blobs_in": sa["blobs_in"], "executor_blobs_out": sb["blobs_out"],
                       "unknown_blob": code(lambda: lc._http(a + "/blob/" + "0" * 64, raw=True)),
                       "bad_blob_name": code(lambda: lc._http(a + "/blob/..%2Fjournal.jsonl", raw=True))}
        out["blob"]["ok"] = out["blob"]["ok"] and out["blob"]["unknown_blob"] == 404 and out["blob"]["bad_blob_name"] == 404
    out["rejected"] = rej
    out["replay"] = replay
    out["unsigned_response"] = unsigned_resp
    out["auth_rejected_counter"] = st["stats"]["auth_rejected"]
    out["ok"] = (all(v == 401 for v in rej.values()) and replay == {"first": 200, "second": 401}
                 and unsigned_resp == "refused_response" and st["stats"]["auth_rejected"] >= len(rej) + 1 and out["blob"]["ok"])
    return out


def _tls_transport(tmp: Path) -> dict[str, Any]:
    """Post-F9 (0.9.1, C-99): optional TLS 1.3 + mTLS from a private fleet CA, on top of the HMAC fleet auth. Real
    loopback HTTPS: a 2-node fleet meshes, runs, steals and moves a blob over https://; plaintext, no client cert, a
    foreign-CA client cert, an untrusted server CA, a wrong hostname and an http:// downgrade are all refused; HMAC is
    still required inside TLS (unsigned → 401)."""
    import os
    import socket
    import ssl
    import urllib.request

    from forge import cluster_tls as T
    from forge import loomcluster as lc

    tdir, rogue = tmp / "tls", tmp / "tls-rogue"
    issued = T.keygen(tdir, ["a", "b", "operator"])
    T.keygen(rogue, ["operator"])
    out: dict[str, Any] = {"issued": [i["name"] for i in issued["issued"]],
                           "key_modes": sorted({oct(Path(i["key"]).stat().st_mode & 0o777) for i in issued["issued"]}
                                               | {oct((tdir / "ca.key.pem").stat().st_mode & 0o777)})}
    old = {k: os.environ.get(k) for k in (T.DIR_ENV, T.NAME_ENV)}
    os.environ[T.DIR_ENV] = str(tdir)
    os.environ.pop(T.NAME_ENV, None)
    lc.set_tls_identity("operator")

    def attempt(fn: Any) -> Any:
        try:
            fn()
            return 200
        except urllib.error.HTTPError as e:
            return e.code
        except lc.ClusterAuthError:
            return "refused_client_side"
        except (urllib.error.URLError, ssl.SSLError, ConnectionError, OSError, http_client_errors()) as e:
            why = getattr(e, "reason", e)
            return f"refused:{type(why).__name__ if not isinstance(why, str) else type(e).__name__}:{str(why)[:60]}"

    def ctx_with(ca: Path, cert: tuple[Path, Path] | None) -> ssl.SSLContext:
        c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        c.load_verify_locations(cafile=str(ca))
        if cert:
            c.load_cert_chain(*cert)
        return c

    try:
        with lc.Fleet(tmp / "tlsfleet") as fl:
            fl.add("a", 1)
            fl.add("b", 1, devices="cpu,directml")
            mesh = _mesh_ok(fl)
            a, b = fl.urls["a"], fl.urls["b"]
            jobs = [{"id": f"t{i}", "op": "hashchain", "payload": {"seed": i, "rounds": 20000}} for i in range(8)]
            res = lc.run_batch(a, jobs, 60)
            wrong = [j for j, x in res.items() if (x.get("value") or {}).get("digest")
                     != lc.expected_hashchain(int(j[1:]), 20000)]
            size = 1 << 20
            lc._http(a + "/submit", {"id": "tblob", "op": "bytes", "payload": {"seed": "tls", "size": size},
                                     "requires": {"device": "directml"}}, 5.0)
            br = lc.collect(a, ["tblob"], 60).get("tblob", {})
            blob = (br.get("value") or {}).get("blobs", {}).get("blob.bin", {})
            data = lc.fetch_blob(a, blob["sha256"]) if blob else b""
            port = int(a.rsplit(":", 1)[1])
            own = (tdir / "nodes" / "operator.pem", tdir / "nodes" / "operator.key.pem")
            foreign = (rogue / "nodes" / "operator.pem", rogue / "nodes" / "operator.key.pem")
            plain = a.replace("https://", "http://")

            def plain_raw() -> None:
                urllib.request.urlopen(urllib.request.Request(plain + "/status"), timeout=3).read()

            def hostname_mismatch() -> None:
                c = ctx_with(tdir / "ca.pem", own)
                with socket.create_connection(("127.0.0.1", port), timeout=3) as sk, \
                        c.wrap_socket(sk, server_hostname="evil.example") as ss:
                    ss.recv(1)

            refused = {
                "plaintext_to_tls_port": attempt(plain_raw),
                "no_client_cert": attempt(lambda: lc._http(a + "/status", tls_context=ctx_with(tdir / "ca.pem", None))),
                "foreign_ca_client_cert": attempt(lambda: lc._http(a + "/status",
                                                                   tls_context=ctx_with(tdir / "ca.pem", foreign))),
                "untrusted_server_ca": attempt(lambda: lc._http(a + "/status", tls_context=ctx_with(rogue / "ca.pem", own))),
                "hostname_mismatch": attempt(hostname_mismatch),
                "http_downgrade": attempt(lambda: lc._http(plain + "/status")),
            }
            unsigned_in_tls = attempt(lambda: lc._http(a + "/status", sign=False))
            c = ctx_with(tdir / "ca.pem", own)
            with socket.create_connection(("127.0.0.1", port), timeout=3) as sk, \
                    c.wrap_socket(sk, server_hostname="127.0.0.1") as ss:
                hs = {"version": ss.version(), "cipher": ss.cipher()[0], "server_cn": T.peer_name(ss)}
            time.sleep(0.3)
            sa, sb = fl.status("a"), fl.status("b")
            out.update({
                "urls": {"a": a, "b": b}, "mesh": bool(mesh), "transport": [sa.get("transport"), sb.get("transport")],
                "batch": {"jobs": len(jobs), "completed": len(res), "wrong": wrong,
                          "by_node": sorted({x.get("node") for x in res.values()})},
                "blob": {"executed_on": br.get("node"), "bytes": len(data), "ok": data == lc.bytes_stream("tls", size)},
                "refused": refused, "unsigned_inside_tls": unsigned_in_tls, "handshake": hs,
                "tls_rejected_counter": sa["stats"]["tls_rejected"], "auth_rejected_counter": sa["stats"]["auth_rejected"],
            })
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        lc.set_tls_identity(None)
    rf = out.get("refused", {})
    out["ok"] = bool(
        out.get("mesh") and str(out.get("urls", {}).get("a", "")).startswith("https://") and out["transport"] == ["https+mtls", "https+mtls"]
        and out["batch"]["completed"] == len(jobs) and not out["batch"]["wrong"]
        and out["blob"]["ok"] and out["blob"]["executed_on"] == "b"
        and rf and all(v != 200 for v in rf.values()) and rf["http_downgrade"] == "refused_client_side"
        and out["unsigned_inside_tls"] == 401 and out["handshake"]["version"] == "TLSv1.3"
        and out["handshake"]["server_cn"] == "a" and out["tls_rejected_counter"] >= 3
        and out["key_modes"] == ["0o600"])
    return out


def http_client_errors() -> type:
    import http.client

    return http.client.HTTPException


def c7_run(root: Path) -> tuple[int, dict[str, Any]]:
    fast = fast_mode()
    tmp = Path(tempfile.mkdtemp(prefix="fabric-c7-"))
    try:
        r: dict[str, Any] = {"mode": "fast" if fast else "full", "transport": "loopback processes (no LAN)"}
        r["negotiation"] = _negotiation(tmp)
        r["determinism"] = _determinism(root, tmp, fast)
        r["failures"] = _failures(tmp, fast)
        r["cli_gen"] = _cli_gen(root, tmp)
        r["loomlink"] = _loomlink(root, tmp, fast)
        r["auth_blobs"] = _auth_and_blobs(tmp)
        r["tls"] = _tls_transport(tmp)
        r["not_proven"] = ["cross-machine transport (LAN/Tailscale) — TLS/mTLS proven on loopback only "
                           "(docs/cluster-lan-runbook.md); plain http mode stays integrity + authentication only",
                           "Kotlin/PocketLoom as a cluster peer node",
                           "real GPU devices (device placement uses simulated adverts)", "origin loss without restart"]
        return 0, r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================================== C8

def _selection_matrix(root: Path) -> dict[str, Any]:
    from forge import groundweave as gw

    ladder = gw.load_ladder(root)
    rows: dict[str, Any] = {}
    planned = []
    for op_id, op in ladder["ops"].items():
        for st in op["ladder"]:
            if st["impl"] == "planned":
                planned.append(f"{op_id}: {st['id']}@{st['device']}")
        per: dict[str, Any] = {}
        for label, devs in (("cpu_only", ["cpu"]), ("all_gpus_present", ["cpu", *gw.SIMULATED_GPU_DEVICES])):
            try:
                sel = gw.select(op_id, devs, root)
                per[label] = sel.get("backend") or f"route:{sel.get('route')}"
                per[label + "_device"] = sel.get("device")
            except gw.GroundWeaveError as e:
                per[label] = f"ERROR {e}"
        rows[op_id] = per
    bad = [o for o, p in rows.items() if str(p.get("cpu_only", "")).startswith("ERROR")
           or (p.get("cpu_only_device") not in ("cpu", None))]
    gpu_required = [o for o, v in ladder["ops"].items() if v.get("gpu_required")]
    return {"ok": not bad, "bad": bad, "per_op": rows, "planned_gpu_rungs_not_built": planned, "gpu_required_ops": gpu_required}


def _runtime_fallback(root: Path) -> dict[str, Any]:
    """Synthetic ladder (a GPU rung marked real) — proves the demotion logic that real GPU backends will use."""
    from forge import groundweave as gw

    ladder = {"devices": ["rocm", "vulkan", "cpu"], "ops": {"t.op": {"ladder": [
        {"id": "gpu-a", "device": "rocm", "impl": "real"},
        {"id": "gpu-b", "device": "vulkan", "impl": "real"},
        {"id": "cpu-x", "device": "cpu", "impl": "real"}]}}}

    def boom() -> int:
        raise MemoryError("VRAM exhausted")

    cases = {
        "gpu_works": gw.execute("t.op", {"gpu-a": lambda: 7, "cpu-x": lambda: 7}, ["cpu", "rocm"], ladder=ladder),
        "gpu_raises_demotes_to_cpu": gw.execute("t.op", {"gpu-a": boom, "gpu-b": boom, "cpu-x": lambda: 7},
                                                ["cpu", "rocm", "vulkan"], ladder=ladder),
        "no_gpu_present": gw.execute("t.op", {"gpu-a": boom, "cpu-x": lambda: 7}, ["cpu"], ladder=ladder),
        "second_rung": gw.execute("t.op", {"gpu-a": boom, "gpu-b": lambda: 7, "cpu-x": lambda: 7}, ["cpu", "rocm", "vulkan"],
                                  ladder=ladder),
    }
    ok = (cases["gpu_works"]["backend"] == "gpu-a" and not cases["gpu_works"]["fallback"]
          and cases["gpu_raises_demotes_to_cpu"]["backend"] == "cpu-x" and cases["gpu_raises_demotes_to_cpu"]["fallback"]
          and len(cases["gpu_raises_demotes_to_cpu"]["attempts"]) == 3
          and cases["no_gpu_present"]["backend"] == "cpu-x" and len(cases["no_gpu_present"]["attempts"]) == 1
          and cases["second_rung"]["backend"] == "gpu-b")
    return {"ok": ok, "cases": {k: {"backend": v["backend"], "fallback": v["fallback"], "attempts": len(v["attempts"])}
                                for k, v in cases.items()}}


def _pipeline_enforcement(root: Path) -> dict[str, Any]:
    from forge import groundweave as gw
    from forge.pipeline import Context, load_briefs, run_brief

    ctx = Context.create(root)
    brief = next(b for b in load_briefs(root) if b["kind"] == "sprite")
    real = gw.load_ladder
    ladder = json.loads(json.dumps(real(root)))
    del ladder["ops"]["gen.sprite"]
    refused = None
    gw.load_ladder = lambda r=None: ladder          # type: ignore[assignment]
    try:
        run_brief(brief, ctx, export=False)
    except gw.GroundWeaveError as e:
        refused = str(e)[:160]
    finally:
        gw.load_ladder = real                       # type: ignore[assignment]
    return {"ok": bool(refused) and "no GroundWeave op" in refused, "refused": refused}


def _pocketloom_ladder(root: Path) -> dict[str, Any]:
    p = root / "docs" / "acceptance-tests" / "results" / "C2.json"
    if not p.exists():
        return {"ok": True, "skipped": "no recorded C2 result in this checkout"}
    c2 = json.loads(p.read_text(encoding="utf-8")).get("result", {}).get("c2")
    if not c2:
        return {"ok": True, "skipped": "recorded C2 ran in fast mode (no Kotlin generation evidence)"}
    kinds = c2["kinds"]
    cpu = all(all("cpu" in b for b in k["backend"]) for k in kinds.values())
    stub = all(any(s.startswith("onnx") and "stub" in s for s in k["skipped_rungs"]) for k in kinds.values())
    return {"ok": bool(cpu and stub and c2.get("ok")), "backends": {n: k["backend"] for n, k in kinds.items()},
            "onnx_rung": "stub (labelled)", "source": "docs/acceptance-tests/results/C2.json (2-core taskset run)"}


def c8_run(root: Path) -> tuple[int, dict[str, Any]]:
    from forge import groundweave as gw

    fast = fast_mode()
    r: dict[str, Any] = {"mode": "fast" if fast else "full", "host_devices": gw.detect_devices()}
    r["static"] = gw.check(root)
    r["selection"] = _selection_matrix(root)
    r["runtime_fallback"] = _runtime_fallback(root)
    r["pipeline_enforcement"] = _pipeline_enforcement(root)
    r["pocketloom_ladder"] = _pocketloom_ladder(root)
    v = gw.verify(root, ops=None if not fast else [o for o in gw.load_ladder(root)["ops"] if o.startswith("gen.")])
    r["verify"] = v
    from forge import loomcluster as lc
    with tempfile.TemporaryDirectory(prefix="fabric-c8-") as tmp, lc.Fleet(Path(tmp)) as fl:
        fl.add("a", 2, "cpu")
        fl.add("g", 2, "cpu,rocm")
        fl.wait_mesh(20)
        sel = gw.select("recon.splat", ["cpu"], root)
        res = lc.run_batch(fl.urls["a"], [{"id": "splat-stand-in", "op": "hashchain", "payload": {"seed": 1, "rounds": 1000},
                                           "requires": {"device": "rocm"}}], 30)
        r["gpu_required_routing"] = {
            "ok": sel.get("route") == "loomcluster" and res.get("splat-stand-in", {}).get("node") == "g",
            "local_selection": {k: sel.get(k) for k in ("backend", "route", "reason")},
            "placed_on": res.get("splat-stand-in", {}).get("node"),
            "note": "recon.splat has no CPU rung (3DGS needs a GPU); the cluster places it on a node advertising rocm. "
                    "Stand-in op used: SplatForge itself is C12 (not built)."}
    return 0, r


# ----------------------------------------------------------------------------------- hooks

def check(ms: str):  # noqa: ANN201
    keys = {"C7": ["negotiation", "determinism", "failures", "cli_gen", "loomlink", "auth_blobs", "tls"],
            "C8": ["static", "selection", "runtime_fallback", "pipeline_enforcement", "pocketloom_ladder",
                   "verify", "gpu_required_routing"]}[ms]

    def chk(r: dict[str, Any]) -> list[str]:
        errs = []
        for k in keys:
            if k not in r:
                errs.append(f"{k}: missing")
            elif not r[k].get("ok"):
                errs.append(f"{k}: {json.dumps(r[k], default=str)[:700]}")
        return errs
    return chk


def perf(ms: str):  # noqa: ANN201
    def p(r: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"mode": r.get("mode")}
        if ms == "C7" and "determinism" in r:
            out["batch_wall_s"] = {n: x["wall_s"] for n, x in r["determinism"]["runs"].items()}
            out["batch_digest"] = r["determinism"]["reference_digest"]
            out["max_gen_job_s_2core"] = r["determinism"]["runs"]["n1_2core_nogpu"]["max_gen_job_s"]
            out["lease_s"] = r["failures"]["kill_node"]["lease_s"]
        if ms == "C8" and "verify" in r:
            out["op_wall_s_2core"] = {x["op"]: x.get("wall_s") for x in r["verify"]["results"] if x.get("wall_s") is not None}
            out["not_probed"] = [x["op"] for x in r["verify"]["results"] if x["status"] == "not_probed"]
            out["planned_gpu_rungs_not_built"] = len(r["selection"]["planned_gpu_rungs_not_built"])
        return out
    return p


def runner(ms: str):  # noqa: ANN201
    return c7_run if ms == "C7" else c8_run
