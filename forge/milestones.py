"""Milestone ↔ Game Zero increment registry + headless acceptance runner.

Enforces the one-milestone offset (ADR-0016): Fabric F(n) is accepted only when
its Game increment passes a headless Godot acceptance run. Results are written
to `docs/acceptance-tests/results/<F>.json` (tracked) as evidence.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from forge.paths import find_repo_root


@dataclass(frozen=True)
class Increment:
    milestone: str
    increment: str
    godot_args: tuple[str, ...]
    check: Callable[[dict[str, Any]], list[str]] = field(compare=False)
    description: str = ""
    perf: Callable[[dict[str, Any]], dict[str, Any]] | None = field(default=None, compare=False)
    runner: Callable[[Path], tuple[int, dict[str, Any]]] | None = field(default=None, compare=False)


def _need(cond: bool, msg: str, errs: list[str]) -> None:
    if not cond:
        errs.append(msg)


def _f0(r: dict[str, Any]) -> list[str]:
    return [] if r.get("_boot_ok") else ["boot line missing"]


def _f1(r: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    _need(r.get("outcome") == "victory", f"outcome={r.get('outcome')}", errs)
    _need(len(r.get("assets", [])) >= 3, "needs 1 tilemap + 1 character + 1 enemy from Fabric", errs)
    _need(r.get("hits", 0) >= 1, "at least one attack must land", errs)
    return errs


def _f2(r: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    ents = r.get("entities", {})
    fighters = {k: v for k, v in ents.items() if v["kind"] == "fighter"}
    pets = {k: v for k, v in ents.items() if v["kind"] == "pet"}
    enemies = {k: v for k, v in ents.items() if v["kind"] == "enemy"}
    _need(r.get("outcome") == "victory", f"outcome={r.get('outcome')}", errs)
    _need(len(fighters) == 4, f"party of 4 required, got {len(fighters)}", errs)
    _need(len(pets) >= 1, "at least one pet", errs)
    _need(len(enemies) >= 5, f"enemy group >=5, got {len(enemies)}", errs)
    idle = [k for k, v in fighters.items() if v["damage"] + v["healing"] == 0]
    _need(not idle, f"followers must act independently; idle: {idle}", errs)
    idle_pets = [k for k, v in pets.items() if v["damage"] == 0]
    _need(not idle_pets, f"pets must fight; idle: {idle_pets}", errs)
    _need(len(r.get("abilities_used", [])) >= 6, f"codegen abilities used: {r.get('abilities_used')}", errs)
    _need(r.get("abilities_loaded", 0) > 0 and r.get("tres_loaded") == r.get("abilities_loaded"), "ability .tres must all load", errs)
    _need(bool(r.get("music_loaded")), "G1-Audio combat stem must load", errs)
    return errs


SWAP_TARGET_MS = 50.0    # GAME_SPEC §4.1 target (soft; tracked in results "perf")
SWAP_CEILING_MS = 150.0  # hard gate: never a multi-frame hitch beyond ~9 frames


def _f3(r: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    ai = r.get("ai", {})
    girt = ai.get("girt", {})
    _need(r.get("outcome") == "victory", f"outcome={r.get('outcome')}", errs)
    _need(ai.get("brain") == "bt+policy", f"brain={ai.get('brain')}", errs)
    _need(girt.get("policy_calls", 0) > 0, "P-TargetSelect policy never called", errs)
    _need(girt.get("policy_fallbacks", 1) == 0, f"policy fallbacks={girt.get('policy_fallbacks')}", errs)
    # Latency budget: gate the p95, not every call (single over-budget calls are scheduler noise; F7 de-flake).
    _need(float(girt.get("policy_p95_us", 1e9)) <= float(girt.get("policy_budget_us", 500.0)),
          f"policy p95 {girt.get('policy_p95_us')} us > budget {girt.get('policy_budget_us', 500.0)} us", errs)
    _need(girt.get("lm_refused_in_tick", 1) == 0, "LM was invoked inside the combat tick (ADR-0011)", errs)
    _need(ai.get("callouts_total", 0) >= 5, f"callouts_total={ai.get('callouts_total')}", errs)
    _need(len(ai.get("intents", [])) >= 1, "no player intent parsed", errs)
    _need(len(ai.get("swaps", [])) >= 1, "no time-freeze swap happened", errs)
    recs = ai.get("swap_recs", [])
    _need(len(recs) == 4, f"swap advisor must rank 4 fighters, got {len(recs)}", errs)
    _need(len({s for _, s in recs}) > 1, "swap advisor scores are all equal (no signal)", errs)
    _need(ai.get("swap_parity") is True, "threaded swap ranking != serial ranking", errs)
    _need(float(ai.get("swap_wall_ms", 1e9)) <= SWAP_CEILING_MS,
          f"swap_wall_ms={ai.get('swap_wall_ms')} > ceiling {SWAP_CEILING_MS}", errs)
    dlg = ai.get("dialogue", [])
    _need(len(dlg) >= 1 and all(d.get("reply") for d in dlg), "dialogue replies missing/empty", errs)
    probe = _policy_probe()
    st = ai.get("selftest") or []
    _need(bool(probe) and len(st) == len(probe) and all(abs(a - b) < 1e-3 for a, b in zip(st, probe)),
          f"GDScript MLP != numpy probe: {st} vs {probe}", errs)
    lm_probe = _generated("persona_lm.json").get("probes", {})
    _need(bool(lm_probe) and ai.get("lm_selftest") == lm_probe, "GDScript LM sampler != Python sampler probes", errs)
    return errs


def _generated(name: str) -> dict[str, Any]:
    try:
        p = find_repo_root() / "games" / "game-zero" / "data" / "generated" / "ai" / name
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _f3_perf(r: dict[str, Any]) -> dict[str, Any]:
    ai = r.get("ai", {})
    ms = float(ai.get("swap_wall_ms", -1))
    return {"swap_wall_ms": ms, "swap_target_ms": SWAP_TARGET_MS, "swap_target_met": 0 <= ms <= SWAP_TARGET_MS,
            "swap_threaded": ai.get("swap_threaded"), "policy_p95_us": ai.get("girt", {}).get("policy_p95_us"),
            "policy_over_budget": ai.get("girt", {}).get("policy_over_budget"),
            "lm_p95_us": ai.get("girt", {}).get("lm_p95_us"), "field_warm_ms": ai.get("field_warm_ms")}


def _policy_probe() -> list[float]:
    try:
        p = find_repo_root() / "games" / "game-zero" / "data" / "generated" / "ai" / "policy_target.json"
        return [round(float(x), 4) for x in json.loads(p.read_text(encoding="utf-8"))["probe"]["scores"]]
    except (OSError, KeyError, ValueError):
        return []


INCREMENTS: dict[str, Increment] = {
    "F0": Increment("F0", "env-boots", ("--boot-only",), _f0, "Empty Godot boots; forge status healthy"),
    "F1": Increment("F1", "sandbox-encounter", ("--scene=sandbox", "--autoplay"), _f1,
                    "Playable sandbox: 1 char, 1 tilemap, 1 enemy, 1 attack"),
    "F2": Increment("F2", "first-combat", ("--scene=combat", "--autoplay"), _f2,
                    "First combat: party of 4 + pets + enemies, codegen data, G1-Audio stems"),
    "F3": Increment("F3", "party-ai", ("--scene=party", "--autoplay"), _f3,
                    "Party AI: BT + GIRT policy, callouts, intents, dialogue, time-freeze swap advisor", _f3_perf),
}
from forge.accept_f4 import f4_check, f4_perf, f4_run  # noqa: E402  (needs Increment/_need above)

INCREMENTS["F4"] = Increment("F4", "live-tune", ("--scene=live", "--autoplay"), f4_check,
                             "Live tune without a full rebuild: sandboxed regen, atomic hot reload "
                             "(2PC + probe + rollback), snapshots + WAL replay, parallel statecharts, guardian restart",
                             f4_perf, f4_run)
from forge.accept_f5 import f5_check, f5_perf, f5_run  # noqa: E402

INCREMENTS["F5"] = Increment("F5", "first-boss", ("--scene=boss", "--autoplay"), f5_check,
                             "First boss + balance: tier-3 Cave Warden cleared, save/migrate round-trip, "
                             "G-BAL-01 Monte Carlo (2400 fights), soft-lock detection", f5_perf, f5_run)
from forge.accept_f6 import f6_check, f6_perf, f6_run  # noqa: E402

INCREMENTS["F6"] = Increment("F6", "vertical-slice", ("--scene=slice", "--autoplay"), f6_check,
                             "Vertical slice (GAME_SPEC §6.1): select → farm → tunnels → cave → craft → Cave Warden → "
                             "open world → save; quit/reload parity, 12-selection matrix, quest/loot/save parity", f6_perf, f6_run)
from forge.accept_f7 import f7_check, f7_perf, f7_run  # noqa: E402

INCREMENTS["F7"] = Increment("F7", "launch-candidates", ("--net-report",), f7_check,
                             "Desktop + Android + Web launch candidates: Godot 4.3 exports (Linux, Windows, debug APK, Web PWA), "
                             "G-WEB-01, G-SAVE-01 desktop→Android→Web→desktop, G-NET-01, ShuttleLine contract, BoltPack SBOM",
                             f7_perf, f7_run)
ORDER = ["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]

# Companion track (parallel, not an F-gate — BUILD_ORDER.md): PocketLoom C1–C6.
from forge import accept_companions as _ac  # noqa: E402

C_ORDER = ["C1", "C2", "C3", "C4", "C5", "C6"]
_C_DESC = {
    "C1": "PocketLoom / FabricCore: Kotlin core (JobExecutor, store, queue, telemetry) + debug APK (aapt/apksigner verified)",
    "C2": "On-device generation: LocalForge CPU caves/sprites via backend ladder (ONNX rung = labelled stub), 2-core budget",
    "C3": "Standalone UI: Generate / Library / Capture / Link / Telemetry, string resources only, offline by construction",
    "C4": "Local capture: camera intent / import → content-addressed store + capture telemetry + queued recon offload",
    "C5": "Pairing: LoomLink code / loomlink:// QR URI / Tailscale address; HMAC proofs, caps intersection, signed requests",
    "C6": "Offload + sync: durable OffloadQueue drains to desktop; version-vector sync, conflicts keep both",
}
for _m in C_ORDER:
    INCREMENTS[_m] = Increment(_m, "pocketloom", (), _ac.check(_m), _C_DESC[_m], _ac.perf(_m), _ac.runner(_m))

# Companion track C7 LoomCluster + C8 GroundWeave: loopback fleet + CPU-fallback proofs (forge/accept_cluster.py).
from forge import accept_cluster as _acl  # noqa: E402

CL_ORDER = ["C7", "C8"]
_CL_DESC = {
    "C7": "LoomCluster: equal nodes advertise/negotiate, steal work, checkpoint, retry; node-count-independent results; "
          "PocketLoom LoomLink offload runs on the fleet",
    "C8": "GroundWeave: GPU→CPU fallback ladder for every op; 2-core/no-GPU budgets + byte-identical output; pipeline refuses "
          "undeclared generators",
}
for _m in CL_ORDER:
    INCREMENTS[_m] = Increment(_m, "loomcluster" if _m == "C7" else "groundweave", (), _acl.check(_m), _CL_DESC[_m],
                               _acl.perf(_m), _acl.runner(_m))

# Companion track C9–C12: MirrorWeave, LensForge capture, metric depth, SplatForge path — interfaces + labelled stubs, real CPU
# paths where cheap and spec-grounded (forge/accept_c9_c12.py, register: content/companions/c9_c12.yaml).
from forge import accept_c9_c12 as _a9  # noqa: E402

CX_ORDER = ["C9", "C10", "C11", "C12"]
_CX_DESC = {
    "C9": "MirrorWeave: typed frame/control contract, signed LoomLink stills+telemetry stream and allow-listed read-only control; "
          "screen capture, video, input injection are labelled stubs",
    "C10": "LensForge capture: modes + PatternVault capture profiles, integer-exact quality (shared with Kotlin), telemetry contract, "
           "desktop assessment of offloaded captures; ARCore/video/focus are labelled stubs",
    "C11": "Metric depth: pinhole monocular distance + inverse-depth scale alignment (analytic ground truth); dense DepthAnything V2 / "
           "ARCore depth are labelled stubs",
    "C12": "SplatForge path: RealityLoom routing, deterministic capture bundle, honest plan/ETA, cluster GPU-placement check, 3DGS .ply "
           "validator; SplatForge/photogrammetry/MeshWeaver/GDGS import are labelled stubs",
}
_CX_NAME = {"C9": "mirrorweave", "C10": "lensforge", "C11": "metric-depth", "C12": "splatforge-path"}
for _m in CX_ORDER:
    INCREMENTS[_m] = Increment(_m, _CX_NAME[_m], (), _a9.check(_m), _CX_DESC[_m], _a9.perf(_m), _a9.runner(_m))


def register(inc: Increment) -> None:
    INCREMENTS[inc.milestone] = inc


def godot_binary(root: Path) -> str | None:
    env = os.environ.get("GODOT_BIN")
    if env and Path(env).exists():
        return env
    for c in ("godot", "godot4"):
        p = shutil.which(c)
        if p:
            return p
    local = root / "godot-bin" / "godot"
    return str(local) if local.exists() else None


def parse_output(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("FABRIC_RESULT "):
            result.update(json.loads(line[len("FABRIC_RESULT "):]))
    result["_boot_ok"] = "Game Zero F0 boot OK" in text
    return result


def run_godot(root: Path, args: tuple[str, ...], timeout: int = 180) -> tuple[int, str]:
    gb = godot_binary(root)
    if not gb:
        raise FileNotFoundError("Godot binary not found (GODOT_BIN, PATH, or godot-bin/godot)")
    from forge.manifest import load_manifest

    project = root / load_manifest(None, root).game.project_path
    proc = subprocess.run([gb, "--headless", "--path", str(project), "--", *args],
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr


def accept(milestone: str, root: Path | None = None, write: bool = True) -> dict[str, Any]:
    root = root or find_repo_root()
    inc = INCREMENTS[milestone]
    if inc.runner:
        code, result = inc.runner(root)
    else:
        code, out = run_godot(root, inc.godot_args)
        result = parse_output(out)
    errs = inc.check(result)
    if code != 0:
        errs.append(f"godot exit code {code}")
    report = {
        "milestone": milestone, "increment": inc.increment, "description": inc.description,
        "passed": not errs, "errors": errs,
        "perf": inc.perf(result) if inc.perf else {},
        "result": {k: v for k, v in result.items() if not k.startswith("_")},
    }
    if write:
        d = root / "docs" / "acceptance-tests" / "results"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{milestone}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def recorded(root: Path, milestone: str) -> dict[str, Any] | None:
    p = root / "docs" / "acceptance-tests" / "results" / f"{milestone}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def offset_report(root: Path, fabric_milestone: str) -> dict[str, Any]:
    """Fabric may be at most one milestone ahead: all milestones before the current
    one must have a passing recorded Game acceptance."""
    idx = ORDER.index(fabric_milestone) if fabric_milestone in ORDER else 0
    missing = []
    for m in ORDER[:idx]:
        rec = recorded(root, m)
        if m != "F0" and not (rec and rec.get("passed")):
            missing.append(m)
    return {"ok": not missing, "unproven_prior_milestones": missing}
