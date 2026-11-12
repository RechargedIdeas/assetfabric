"""GroundWeave (C8) — GPU→CPU fallback ladder, enforced by forge.

`content/groundweave/ladder.yaml` declares, for every forge op, the backends best-first.
Rules (ASSETFABRIC_SPEC §9, hardware-fleet "weakest acceptance contract"):

* every op has a `device: cpu` backend with `impl: real`, **or** declares
  `gpu_required: true` + `route: loomcluster` (the job must go to a node advertising a GPU);
* every registered generator kind maps to a declared `gen.<kind>` op — `forge build`
  refuses to run a generator GroundWeave does not know (see `pipeline.run_brief`);
* `forge groundweave verify` runs each op's CPU backend pinned to 2 cores with GPUs
  hidden and fails if it exceeds `budget_s_2core`.

Selection walks the ladder and takes the first backend whose device is detected and whose
implementation exists on this checkout (`impl: real`). `planned` backends are documented
intent only and are never selected.
"""

from __future__ import annotations

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
        has_cpu = any(st.get("device") == "cpu" and st.get("impl") == "real" for st in steps)
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
    for st in op["ladder"]:
        if st.get("impl") == "real" and st.get("device") in devs:
            return {"op": op_id, "backend": st["id"], "device": st["device"],
                    "fallback": st is not op["ladder"][0]}
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


# ---------------------------------------------------------------------------------- verify

def _pin(cores: int):
    def fn() -> None:
        try:
            avail = sorted(os.sched_getaffinity(0))
            os.sched_setaffinity(0, set(avail[:cores]))
        except (AttributeError, OSError):
            pass
    return fn


def _probe_one(root: Path, brief_id: str) -> dict[str, Any]:
    """Child-side: run one brief's generator (no export) and report timings."""
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
    return {"brief": brief_id, "ok": out.ok, "wall_s": round(wall, 3), "cores": aff, **sel}


def verify(root: Path | None = None, cores: int | None = None, ops: list[str] | None = None) -> dict[str, Any]:
    root = root or find_repo_root()
    ladder = load_ladder(root)
    cores = cores or int(ladder.get("acceptance_node", {}).get("cores", 2))
    env = {**os.environ, **HIDE_GPU_ENV, "OMP_NUM_THREADS": str(cores), "OPENBLAS_NUM_THREADS": str(cores),
           "MKL_NUM_THREADS": str(cores)}
    results: list[dict[str, Any]] = []
    for op_id, op in ladder["ops"].items():
        if ops and op_id not in ops:
            continue
        probe = op.get("probe_brief")
        if not probe:
            results.append({"op": op_id, "status": "no_probe", "note": op.get("note", "")})
            continue
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, "-m", "forge.groundweave", "_probe", probe],
                              cwd=root, env=env, capture_output=True, text=True, preexec_fn=_pin(cores),
                              timeout=max(60.0, float(op["budget_s_2core"]) * 4))
        total = time.perf_counter() - t0
        line = next((l for l in proc.stdout.splitlines() if l.startswith("GW_PROBE ")), None)
        if proc.returncode != 0 or line is None:
            results.append({"op": op_id, "status": "error", "stderr": proc.stderr[-800:]})
            continue
        rec = json.loads(line[len("GW_PROBE "):])
        rec.update(op=op_id, budget_s=op["budget_s_2core"], process_s=round(total, 3))
        rec["status"] = "ok" if rec["ok"] and rec["device"] == "cpu" and rec["wall_s"] <= op["budget_s_2core"] else "fail"
        results.append(rec)
    ok = all(r["status"] in ("ok", "no_probe") for r in results)
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
        print("GW_PROBE " + json.dumps(_probe_one(find_repo_root(), sys.argv[2])), flush=True)
    else:
        print("usage: python -m forge.groundweave _probe <brief_id>", file=sys.stderr)
        sys.exit(2)
