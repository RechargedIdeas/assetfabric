"""GroundWeave (C8) — GPU→CPU fallback ladder, enforced by forge.

`content/groundweave/ladder.yaml` declares, for every forge op, the backends best-first.
Rules (ASSETFABRIC_SPEC §9, hardware-fleet "weakest acceptance contract"):

* every op has a `device: cpu` backend with `impl: real`, **or** declares
  `gpu_required: true` + `route: loomcluster` (the job must go to a node advertising a GPU), **or** — for a capability
  that is specified but not built (C9–C12) — `planned: true` + `route: loomcluster|local` with *every* rung `impl: planned`
  (selection then reports `status: planned`; the module behind it must be a labelled stub that refuses);
* every registered generator kind maps to a declared `gen.<kind>` op — `forge build`
  refuses to run a generator GroundWeave does not know (see `pipeline.run_brief`);
* `forge groundweave verify` runs each op's CPU backend pinned to 2 cores with GPUs
  hidden and fails if it exceeds `budget_s_2core`.

Selection walks the ladder and takes the first backend whose device is detected and whose
implementation exists on this checkout (`impl: real`). `planned` backends are documented
intent only and are never selected.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from forge.paths import find_repo_root

LADDER_PATH = Path("content") / "groundweave" / "ladder.yaml"
DEVICE_ENV = "FORGE_GW_DEVICES"           # comma list forcing the detected device set (e.g. "cpu")
HIDE_GPU_ENV = {"HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1",
                "CUDA_VISIBLE_DEVICES": "-1", "GPU_DEVICE_ORDINAL": "-1", DEVICE_ENV: "cpu"}


SIMULATED_GPU_DEVICES = ("rocm", "directml", "vulkan")   # what `verify` pretends is present (no real GPU needed)


class GroundWeaveError(RuntimeError):
    pass


def load_ladder(root: Path | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    return yaml.safe_load((root / LADDER_PATH).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _probe_devices() -> tuple[str, ...]:
    found = ["cpu"]
    if Path("/dev/kfd").exists() and shutil.which("rocminfo"):
        try:
            out = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=10).stdout
            if "gfx" in out:
                found.append("rocm")
        except (OSError, subprocess.SubprocessError):
            pass
    if shutil.which("vulkaninfo"):
        try:
            out = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True, timeout=10).stdout
            if any(t in out for t in ("PHYSICAL_DEVICE_TYPE_DISCRETE_GPU", "PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU")):
                found.append("vulkan")
        except (OSError, subprocess.SubprocessError):
            pass
    if sys.platform == "win32":
        found.append("directml")   # DirectML ships with Windows 10 1903+; presence ≠ a usable adapter
    return tuple(found)


def detect_devices() -> list[str]:
    forced = os.environ.get(DEVICE_ENV)
    if forced:
        return [d.strip() for d in forced.split(",") if d.strip()]
    devs = list(_probe_devices())
    if os.environ.get("HIP_VISIBLE_DEVICES") == "-1":
        devs = [d for d in devs if d != "rocm"]
    return devs


def check(root: Path | None = None, kinds: list[str] | None = None) -> dict[str, Any]:
    """Static ladder rules. `kinds` defaults to every registered generator kind."""
    ladder = load_ladder(root)
    problems: list[str] = []
    allowed = set(ladder.get("devices", []))
    ops = ladder.get("ops", {})
    for op_id, op in ops.items():
        steps = op.get("ladder") or []
        if not steps:
            problems.append(f"{op_id}: empty ladder")
            continue
        for st in steps:
            if st.get("device") not in allowed:
                problems.append(f"{op_id}: unknown device {st.get('device')!r}")
            if st.get("impl") not in ("real", "planned"):
                problems.append(f"{op_id}: backend {st.get('id')} impl must be real|planned")
            # 0.9.2: a real non-CPU rung must state whether it has run on that device (`verified: false` until a hardware
            # report under hw-reports/ backs it — nothing may imply GPU-proven by omission).
            if st.get("impl") == "real" and st.get("device") != "cpu" and not isinstance(st.get("verified"), bool):
                problems.append(f"{op_id}: real {st.get('device')} backend {st.get('id')} must declare verified: true|false")
            if st.get("verified") is True and not st.get("evidence"):
                problems.append(f"{op_id}: backend {st.get('id')} verified: true needs an evidence path")
        has_cpu = any(st.get("device") == "cpu" and st.get("impl") == "real" for st in steps)
        if op.get("planned"):
            if any(st.get("impl") != "planned" for st in steps):
                problems.append(f"{op_id}: planned op must not claim a real backend")
            if op.get("route") not in ("loomcluster", "local"):
                problems.append(f"{op_id}: planned op must declare route: loomcluster|local")
            continue
        if not has_cpu:
            if not (op.get("gpu_required") and op.get("route") == "loomcluster"):
                problems.append(f"{op_id}: no real CPU backend and not declared gpu_required+route: loomcluster")
        elif steps[-1].get("device") != "cpu":
            problems.append(f"{op_id}: CPU backend must be the last rung of the ladder")
        if has_cpu and "budget_s_2core" not in op:
            problems.append(f"{op_id}: missing budget_s_2core")
    if kinds is None:
        from forge.generators import load_all
        kinds = sorted(load_all())
    declared = {op.get("kind") for op in ops.values() if op.get("kind")}
    for k in kinds:
        if k not in declared:
            problems.append(f"generator kind {k!r} has no GroundWeave op (add gen.{k} to {LADDER_PATH})")
    return {"ok": not problems, "problems": problems, "ops": len(ops), "kinds": kinds}


def select(op_id: str, devices: list[str] | None = None, root: Path | None = None) -> dict[str, Any]:
    ladder = load_ladder(root)
    op = ladder["ops"].get(op_id)
    if op is None:
        raise GroundWeaveError(f"op {op_id!r} is not declared in {LADDER_PATH}")
    devs = devices if devices is not None else detect_devices()
    if op.get("planned"):
        return {"op": op_id, "backend": None, "device": None, "status": "planned", "route": op.get("route"),
                "reason": "planned: specified but not implemented; callers must refuse (labelled stub)"}
    for st in op["ladder"]:
        if st.get("impl") == "real" and st.get("device") in devs:
            top = op["ladder"][0]
            return {"op": op_id, "backend": st["id"], "device": st["device"], "verified": st.get("verified", True),
                    "fallback": st is not top, "top_rung": f"{top['id']}@{top['device']}:{top['impl']}"}
    if op.get("gpu_required"):
        return {"op": op_id, "backend": None, "device": None, "route": op.get("route", "loomcluster"),
                "reason": "gpu_required: no local device; route to a cluster node"}
    raise GroundWeaveError(f"op {op_id!r}: no usable backend for devices {devs}")


def op_for_kind(kind: str, root: Path | None = None) -> str:
    for op_id, op in load_ladder(root).get("ops", {}).items():
        if op.get("kind") == kind:
            return op_id
    raise GroundWeaveError(f"generator kind {kind!r} has no GroundWeave op in {LADDER_PATH} — "
                           "declare its CPU fallback before it can run")


def resolve_kind(kind: str, root: Path | None = None) -> dict[str, Any]:
    """Called by the pipeline before any generator runs (enforcement point)."""
    sel = select(op_for_kind(kind, root), root=root)
    if sel.get("backend") is None:
        raise GroundWeaveError(f"{kind}: GPU-required op cannot run locally ({sel['reason']})")
    return sel


def candidates(op_id: str, devices: list[str] | None = None, root: Path | None = None,
               ladder: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every rung this host can attempt, best-first: device present AND `impl: real`."""
    ladder = ladder or load_ladder(root)
    op = ladder["ops"].get(op_id)
    if op is None:
        raise GroundWeaveError(f"op {op_id!r} is not declared in {LADDER_PATH}")
    devs = devices if devices is not None else detect_devices()
    return [st for st in op["ladder"] if st.get("impl") == "real" and st.get("device") in devs]


def execute(op_id: str, backends: dict[str, Any], devices: list[str] | None = None, root: Path | None = None,
            ladder: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run an op through its ladder with *runtime* fallback.

    `backends` maps a ladder backend id to a callable. The best rung whose device is present is tried first;
    if it raises (driver missing, out of VRAM, bad kernel …) the next rung is tried, down to the CPU rung.
    Returns {value, backend, device, fallback, attempts:[{backend, device, ok, error?}]}."""
    attempts: list[dict[str, Any]] = []
    for st in candidates(op_id, devices, root, ladder):
        fn = backends.get(st["id"])
        if fn is None:
            attempts.append({"backend": st["id"], "device": st["device"], "ok": False, "error": "no implementation bound"})
            continue
        try:
            value = fn()
        except Exception as e:  # noqa: BLE001 — any backend failure demotes to the next rung
            attempts.append({"backend": st["id"], "device": st["device"], "ok": False,
                             "error": f"{type(e).__name__}: {e}"})
            continue
        attempts.append({"backend": st["id"], "device": st["device"], "ok": True})
        return {"value": value, "backend": st["id"], "device": st["device"], "fallback": len(attempts) > 1,
                "attempts": attempts}
    raise GroundWeaveError(f"op {op_id!r}: every rung failed or is unavailable: {attempts}")


# ---------------------------------------------------------------------------------- verify

def _pin(cores: int):
    def fn() -> None:
        try:
            from forge.cpus import physical_core_cpus

            os.sched_setaffinity(0, set(physical_core_cpus(cores)))   # N physical cores, not SMT siblings
        except (AttributeError, OSError):
            pass
    return fn


def _artifact_digest(out: Any) -> str:
    h = hashlib.sha256()
    for a in sorted(out.artifacts, key=lambda a: a.name):
        h.update(a.name.encode() + b"\0" + hashlib.sha256(a.data).digest())
    return h.hexdigest()


def _probe_one(root: Path, brief_id: str) -> dict[str, Any]:
    """Child-side: run one brief's generator (no export) and report timings + an output digest."""
    from forge.pipeline import Context, load_briefs
    from forge.generators import load_all

    briefs = {b["id"]: b for b in load_briefs(root)}
    brief = briefs[brief_id]
    ctx = Context.create(root)
    sel = resolve_kind(brief["kind"], root)
    t0 = time.perf_counter()
    out = load_all()[brief["kind"]](brief, ctx)
    wall = time.perf_counter() - t0
    aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    return {"brief": brief_id, "ok": out.ok, "wall_s": round(wall, 3), "cores": aff,
            "digest": _artifact_digest(out), **sel}


def _probe_runtime(root: Path, name: str) -> dict[str, Any]:
    """Child-side probes for ops that are not Content Forge generators (Godot headless)."""
    from forge import milestones

    t0 = time.perf_counter()
    if name == "girt":       # F3 party-AI increment: GIRT policy + persona LM through the CPU (GDScript) backend
        inc = milestones.INCREMENTS["F3"]
        code, out = milestones.run_godot(root, inc.godot_args, timeout=300)
        res = milestones.parse_output(out)
        res["swapbench"] = milestones.swapbench_run(root, gate_target=False)   # Q3: CPU path + ceiling/parity/fidelity
        errs = inc.check(res) + ([f"godot exit {code}"] if code else [])
        girt = (res.get("ai") or {}).get("girt") or {}
        backends = sorted({r.get("backend") for r in girt.get("registry", [])})
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": "F3", "ok": not errs, "errors": errs, "wall_s": round(wall, 3), "cores": aff,
                "device": "cpu" if backends and not any(("onnx" in (b or "") or "gpu" in (b or "")) for b in backends) else "unknown",
                "backend": ",".join(b for b in backends if b), "policy_p95_us": girt.get("policy_p95_us"),
                "policy_budget_us": girt.get("policy_budget_us"), "policy_fallbacks": girt.get("policy_fallbacks"),
                "digest": hashlib.sha256(json.dumps(girt.get("registry", []), sort_keys=True).encode()).hexdigest()}
    if name == "retro-rom":  # F8 ForgeConsole: transcode + C1 solve + assemble the NES field-demo ROM (pure CPU)
        from forge.retro import profiles as rp, rom as rr

        prof = next(p for p in rp.load(root).values() if p.rom)
        rb = rr.build(root, prof)
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": "retro-rom", "ok": len(rb.rom) == 40976, "wall_s": round(wall, 3), "cores": aff, "device": "cpu",
                "backend": "forgeconsole-cpu", "digest": rb.sha256}
    if name == "balance":    # a reduced G-BAL-01 matrix (12 matchups x 2 seeds) over the sharded headless workers
        from forge.balance import BalanceConfig, run

        agg = run(BalanceConfig(encounter="boss_warden", seeds=2, seed_base=1000, variance=0.20, workers=2), root)
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        enc = agg.get("encounters") or agg.get("total") or agg.get("n")
        return {"brief": "balance-smoke", "ok": bool(enc), "wall_s": round(wall, 3), "cores": aff, "device": "cpu",
                "backend": "godot-headless-shards", "encounters": enc,
                "digest": hashlib.sha256(json.dumps(agg.get("matchups", agg), sort_keys=True, default=str).encode()).hexdigest()}
    if name in ("mirror", "lens", "depth", "recon"):   # C9–C12 CPU rungs: pure-CPU, deterministic, no Godot
        sel = select({"mirror": "mirror.encode", "lens": "lens.assess", "depth": "depth.distance", "recon": "recon.plan"}[name],
                     root=root)
        out = _probe_companion(name, sel.get("backend"))
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": f"{name}-probe", "ok": True, "wall_s": round(wall, 3), "cores": aff, "device": sel["device"],
                "backend": sel["backend"], "digest": hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()}
    if name == "depth-dense":   # DepthAnything V2 Small, onnxruntime CPU EP, 1 intra-op thread → bit-reproducible map
        import numpy as np

        from forge import depth
        sel = select("depth.estimate", root=root)
        sc = depth.render_scene(160, 120)
        est = depth.DepthAnythingV2(threads=1)
        rel = est.estimate_rgb(sc["rgb"])
        ran_on = "cpu" if (est.ep or {}).get("active", ["CPUExecutionProvider"])[0] == "CPUExecutionProvider" else (est.ep or {}).get("device")
        m = depth.depth_metrics(depth.align_inverse_depth(rel, _scene_anchors(sc["depth_m"]))["depth_m"], sc["depth_m"])
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": "depth-dense-probe", "ok": m["abs_rel"] < 0.15, "abs_rel": round(m["abs_rel"], 4),
                "wall_s": round(wall, 3), "cores": aff, "device": ran_on, "selected_device": sel["device"],
                "backend": sel["backend"] if ran_on == sel["device"] else "depthanything-v2-onnx-cpu",
                "onnx_ep": {k: (est.ep or {}).get(k) for k in ("providers", "active", "fallback", "demoted")},
                "digest": hashlib.sha256(np.ascontiguousarray(rel, dtype=np.float32).tobytes()).hexdigest()}
    if name == "sfm":                       # C12 CPU photogrammetry on the rendered 8-view scene (deterministic)
        import numpy as np

        from forge import photogrammetry as pg
        sel = select("recon.sfm", root=root)
        sc = pg.render_views(8, arc_deg=90)
        rec = pg.reconstruct(sc["images"], focal_px=float(sc["K"][0, 0]))
        ev = pg.evaluate(rec, sc["poses"])
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": "sfm-probe", "ok": ev["registered"] == 8 and ev["rot_err_deg_max"] < 2.0, "rot_err_deg_max": round(ev["rot_err_deg_max"], 4),
                "wall_s": round(wall, 3), "cores": aff, "device": sel["device"], "backend": sel["backend"],
                "digest": hashlib.sha256(np.round(rec["points"], 6).tobytes()).hexdigest()}
    if name == "voice":                      # VoiceBridge on the committed synthetic-speech fixtures
        from forge import voice
        sel = select("stt.voice", root=root)
        r = voice.evaluate_fixtures(voice.VoiceBridge(root))
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": "voice-probe", "ok": r["accuracy"] >= 0.85 and r["wrong_action_rate"] <= 0.08, "accuracy": r["accuracy"],
                "wrong_action_rate": r["wrong_action_rate"], "wall_s": round(wall, 3), "cores": aff, "device": sel["device"],
                "backend": sel["backend"], "digest": hashlib.sha256(json.dumps([(x["heard"], x["intent"]) for x in r["rows"]]).encode()).hexdigest()}
    if name == "persona-lm":                 # one greedy persona line, single intra-op thread (deterministic tokens)
        from forge import microlm
        from forge.generators.callouts import load_personas
        sel = select("lm.persona", root=root)
        src = load_personas(root)
        lm = microlm.QwenLM(root, threads=1)
        g = lm.generate(microlm.chat_prompt(microlm.persona_card("kael", src["personas"]["kael"], "low_hp", src["safety"])), max_new_tokens=24)
        line = microlm.clean(g["text"])
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": "persona-lm-probe", "ok": bool(line), "line": line, "tok_per_s": g["tok_per_s"], "wall_s": round(wall, 3),
                "cores": aff, "device": sel["device"], "backend": sel["backend"], "digest": hashlib.sha256(json.dumps(g["tokens"]).encode()).hexdigest()}
    if name == "splat-cpu":                 # C12 tiny-scene CPU 3DGS training on SfM poses (BLAS-free → byte-identical)
        from forge import photogrammetry as pg
        from forge import splattrain as st
        sel = select("recon.splat_cpu", root=root)
        sc = pg.render_views(9, w=160, h=120)
        rec = pg.reconstruct(sc["images"], focal_px=float(sc["K"][0, 0]))
        d = st.from_sfm(sc["images"], rec, 40, holdout=4)
        lo, hi, s0 = st.scene_bounds(rec["points"], None)
        p0 = st.init_gaussians(250, lo, hi, s0, 0, rec["points"], rec["colors"])
        r = st.train(d["train"], d["K"], p0, iters=200)
        ply = st.to_ply(r["params"])
        ok = d["test"] is not None
        gain = (st.psnr(st.render_params(r["params"], d["test"]["R"], d["test"]["t"], d["K"], d["w"], d["h"]), d["test"]["image"])
                - st.psnr(st.render_params(p0, d["test"]["R"], d["test"]["t"], d["K"], d["w"], d["h"]), d["test"]["image"])) if ok else 0.0
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": "splat-cpu-probe", "ok": ok and gain > 6.0, "psnr_gain_holdout_db": round(gain, 3), "wall_s": round(wall, 3),
                "cores": aff, "device": sel["device"], "backend": sel["backend"], "digest": hashlib.sha256(ply).hexdigest()}
    if name in ("recon-mesh", "gdgs"):     # C12 CPU rungs on a synthetic sphere-splat set (deterministic bytes)
        from forge import splats
        sel = select("recon.mesh" if name == "recon-mesh" else "shuttle.gdgs", root=root)
        ply = splats.sphere_splats(1500, seed=2)
        if name == "recon-mesh":
            out = splats.write_obj(splats.mesh_from_splats(ply))
        else:
            out = splats.write_godot_scene(ply, "probe")[0].encode()
        wall = time.perf_counter() - t0
        aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
        return {"brief": f"{name}-probe", "ok": len(out) > 0, "bytes": len(out), "wall_s": round(wall, 3), "cores": aff,
                "device": sel["device"], "backend": sel["backend"], "digest": hashlib.sha256(out).hexdigest()}
    raise GroundWeaveError(f"unknown runtime probe {name!r}")


def _scene_anchors(gt: Any, n: int = 12, seed: int = 1) -> list:
    """Deterministic metric anchors sampled from a ground-truth depth map (the role LensForge/ARCore points play live)."""
    import numpy as np

    from forge.depth import Anchor
    ys, xs = np.where(np.isfinite(gt))
    idx = np.random.default_rng(seed).choice(len(ys), n, replace=False)
    return [Anchor(int(xs[i]), int(ys[i]), float(gt[ys[i], xs[i]])) for i in idx]


def _probe_companion(name: str, backend: str | None = None) -> Any:
    if name == "mirror":
        from forge import lensforge, mirrorweave
        if backend == "mirror-vpx-cpu":     # CPU VP8 video rung: 12 synthetic frames, single-threaded libvpx (deterministic)
            import numpy as np

            from forge.mirrorvideo import CpuVideoEncoder
            y, x = np.mgrid[0:64, 0:96]
            frames = [np.stack([(x * 2 + i * 4) % 256, (y * 3) % 256, ((x + y) + i * 6) % 256], -1).astype(np.uint8)
                      for i in range(12)]
            pk = CpuVideoEncoder(96, 64, "vp8", gop=6, threads=1).encode(frames)
            return hashlib.sha256(b"".join(pk)).hexdigest()
        return mirrorweave.encode_still(lensforge.synthetic_png(96, 64, 3)).decode()
    if name == "lens":
        from forge import lensforge
        return lensforge.probe()
    if name == "depth":
        from forge import depth
        return depth.probe()
    from forge import realityloom
    return realityloom.probe()


def _run_probe(root: Path, probe: str, env: dict[str, str], pin: int | None, timeout: float) -> dict[str, Any]:
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, "-m", "forge.groundweave", "_probe", probe], cwd=root, env=env,
                          capture_output=True, text=True, preexec_fn=_pin(pin) if pin else None, timeout=timeout)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("GW_PROBE ")), None)
    if proc.returncode != 0 or line is None:
        return {"status": "error", "stderr": (proc.stderr or proc.stdout)[-800:]}
    rec = json.loads(line[len("GW_PROBE "):])
    rec["process_s"] = round(time.perf_counter() - t0, 3)
    return rec


def verify(root: Path | None = None, cores: int | None = None, ops: list[str] | None = None,
           compare: bool = True) -> dict[str, Any]:
    """Run every probed op's CPU backend pinned to the weakest node (`cores`, GPUs hidden) against its budget.

    With `compare`, the same probe also runs unpinned with the host's devices visible and the two output digests
    must match — a fallback must not change the artifact (determinism across devices)."""
    root = root or find_repo_root()
    ladder = load_ladder(root)
    cores = cores or int(ladder.get("acceptance_node", {}).get("cores", 2))
    base = {**os.environ, "OMP_NUM_THREADS": str(cores), "OPENBLAS_NUM_THREADS": str(cores),
            "MKL_NUM_THREADS": str(cores)}
    weak = {**base, **HIDE_GPU_ENV}
    free = {k: v for k, v in os.environ.items() if k != DEVICE_ENV}
    simgpu = {**free, DEVICE_ENV: "cpu," + ",".join(d for d in SIMULATED_GPU_DEVICES)}   # every GPU "present"
    results: list[dict[str, Any]] = []
    for op_id, op in ladder["ops"].items():
        if ops and op_id not in ops:
            continue
        probe = op.get("probe_brief")
        if op.get("planned"):
            results.append({"op": op_id, "status": "planned", "route": op.get("route"), "note": op.get("note", "")})
            continue
        if not probe:
            results.append({"op": op_id, "status": "not_probed", "note": op.get("note", "")})
            continue
        if op.get("requires_model"):
            from forge import models
            if not models.status(op["requires_model"], root, verify=False)["ready"]:
                results.append({"op": op_id, "status": "model_absent", "model": op["requires_model"],
                                "note": f"run `forge models fetch {op['requires_model']}` (heavy; local/full runs only)"})
                continue
        timeout = max(60.0, float(op["budget_s_2core"]) * 4)
        rec = _run_probe(root, probe, weak, cores, timeout)
        rec["op"] = op_id
        if rec.get("status") == "error":
            results.append(rec)
            continue
        rec["budget_s"] = op["budget_s_2core"]
        good = rec["ok"] and rec["device"] == "cpu" and rec["wall_s"] <= op["budget_s_2core"]
        if rec.get("policy_budget_us") is not None:      # GIRT: per-tick latency inside the in-engine budget
            good = good and (rec.get("policy_p95_us") or 0) <= rec["policy_budget_us"] and not rec.get("policy_fallbacks")
        if compare:
            free_rec = _run_probe(root, probe, free, None, timeout)
            rec["unpinned_digest"] = free_rec.get("digest")
            rec["unpinned_device"] = free_rec.get("device")
            rec["identical_to_unpinned"] = free_rec.get("digest") == rec["digest"]
            sim_rec = _run_probe(root, probe, simgpu, None, timeout)
            rec["identical_with_simulated_gpu"] = sim_rec.get("digest") == rec["digest"]
            rec["simulated_gpu_selected"] = sim_rec.get("device")
            good = good and rec["identical_to_unpinned"] and rec["identical_with_simulated_gpu"]
        rec["status"] = "ok" if good else "fail"
        results.append(rec)
    allowed = {"ok", "not_probed", "planned"} | (set() if os.environ.get("FORGE_REQUIRE_MODELS") == "1" else {"model_absent"})
    ok = all(r["status"] in allowed for r in results)
    return {"ok": ok, "cores": cores, "gpu_hidden": True, "results": results}


def describe(root: Path | None = None) -> dict[str, Any]:
    ladder = load_ladder(root)
    devs = detect_devices()
    rows = []
    for op_id in ladder["ops"]:
        try:
            rows.append(select(op_id, devs, root))
        except GroundWeaveError as e:
            rows.append({"op": op_id, "error": str(e)})
    return {"devices": devs, "selection": rows}


if __name__ == "__main__":   # child entry for verify()
    if len(sys.argv) == 3 and sys.argv[1] == "_probe":
        _r = find_repo_root()
        _rec = (_probe_runtime(_r, sys.argv[2][len("runtime:"):]) if sys.argv[2].startswith("runtime:")
                else _probe_one(_r, sys.argv[2]))
        print("GW_PROBE " + json.dumps(_rec), flush=True)
    else:
        print("usage: python -m forge.groundweave _probe <brief_id>", file=sys.stderr)
        sys.exit(2)
