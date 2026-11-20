"""Content pipeline: brief → generator → gates → store → Godot export (F1).

Godot binding (ShuttleLine Godot target): artifacts are written under
`games/game-zero/assets/generated/<kind>/` and registered in
`games/game-zero/assets/generated/fabric_assets.json`, which the game's
`Fabric` autoload reads — zero manual wiring (G-FAB-01).
The registry is deterministic (no timestamps) so regenerated output can be
diffed against the committed copy (determinism gate).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from forge.generators import GeneratorOutput, load_all
from forge.manifest import load_manifest
from forge.orchestrator import JobOrchestrator, run_pending
from forge.patternvault import PatternVault
from forge.paths import find_repo_root
from forge.store import AssetStore
from forge.telemetry import TelemetryStore, make_system_event

REGISTRY_NAME = "fabric_assets.json"


@dataclass
class Context:
    root: Path
    vault: PatternVault
    store: AssetStore
    telemetry: TelemetryStore

    @classmethod
    def create(cls, root: Path | None = None) -> "Context":
        root = root or find_repo_root()
        return cls(root, PatternVault(root), AssetStore(root), TelemetryStore(root))

    @property
    def game_root(self) -> Path:
        return self.root / load_manifest(None, self.root).game.project_path

    @property
    def export_root(self) -> Path:
        return self.game_root / "assets" / "generated"


def load_briefs(root: Path, pattern: str = "**/*.yaml") -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    for path in sorted((root / "content" / "briefs").glob(pattern)):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        items = raw.get("briefs", [raw]) if isinstance(raw, dict) else raw
        for b in items:
            b = dict(b)
            b.setdefault("_source", str(path.relative_to(root)))
            briefs.append(b)
    # Expansion: a codegen brief with `derive_sprites: true` yields one sprite brief per roster unit.
    for b in list(briefs):
        if b.get("kind") == "codegen" and b.get("derive_sprites"):
            from forge.generators.codegen import sprite_briefs

            briefs.extend(sprite_briefs(root, b.get("source", "content/roster")))
    ids = [b["id"] for b in briefs]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate brief ids: {sorted(dupes)}")
    return briefs


def _read_registry(ctx: Context) -> dict[str, Any]:
    path = ctx.export_root / REGISTRY_NAME
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": "1.0", "generator": "assetfabric-forge", "assets": {}}


def _write_registry(ctx: Context, reg: dict[str, Any]) -> None:
    ctx.export_root.mkdir(parents=True, exist_ok=True)
    (ctx.export_root / ".gdignore").write_text("", encoding="utf-8")  # runtime-loaded, skip editor import
    reg["assets"] = dict(sorted(reg["assets"].items()))
    (ctx.export_root / REGISTRY_NAME).write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_brief(brief: dict[str, Any], ctx: Context, export: bool = True, sandbox: str | None = None) -> GeneratorOutput:
    """`sandbox`: None → in-process (trusted first-party generators); "auto"/"bwrap"/"process"
    → run the generator inside a forge.sandbox tier (F4). Output is byte-identical either way."""
    gens = load_all()
    kind = brief["kind"]
    if kind not in gens:
        raise KeyError(f"no generator registered for kind {kind!r} (have {sorted(gens)})")
    from forge import groundweave

    groundweave.resolve_kind(kind, ctx.root)   # GroundWeave (C8): refuse a generator with no declared CPU fallback
    t0 = time.perf_counter()
    if sandbox:
        from forge import sandbox as sbx

        out = sbx.generate(brief, ctx.root, tier=sandbox)
    else:
        out = gens[kind](brief, ctx)
    elapsed = (time.perf_counter() - t0) * 1000
    files: dict[str, dict[str, str]] = {}
    if out.ok:
        sub = brief.get("export_dir", kind)
        base = brief.get("export_base", "assets/generated")
        for art in out.artifacts:
            bundle = ctx.store.put(
                art.data,
                media_type=art.media_type,
                provenance={
                    "brief_id": brief["id"], "brief_source": brief.get("_source"), "generator": kind,
                    "model_id": out.meta.get("model_id"), "model_version": out.meta.get("model_version"),
                    "seed": brief.get("seed"), "gates": [g.gate for g in out.gates],
                },
            )
            rel = f"{base}/{sub}/{art.name}" if sub else f"{base}/{art.name}"
            if export:
                dest = ctx.game_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(art.data)
            files[art.name] = {"res": f"res://{rel}", "sha256": bundle.digest}
        if export:
            reg = _read_registry(ctx)
            meta = {k: v for k, v in out.meta.items()}
            reg["assets"][brief["id"]] = {"kind": kind, "files": files, "meta": meta, "tags": brief.get("tags", [])}
            _write_registry(ctx, reg)
    ctx.telemetry.emit(make_system_event(
        "forge.generate", agent_id=f"gen:{kind}", agent_type="generator",
        action_taken={"brief": brief["id"], "ok": out.ok, "gates": {g.gate: g.ok for g in out.gates}},
        action_source="system", inference_latency_ms=round(elapsed, 2),
        sandbox_id=out.meta.get("sandbox", {}).get("id"),
        model_id=out.meta.get("model_id"), model_version=out.meta.get("model_version"),
    ))
    out.meta["files"] = files
    out.meta["elapsed_ms"] = round(elapsed, 2)
    return out


def build_all(root: Path | None = None, pattern: str = "**/*.yaml", export: bool = True,
              sandbox: str | None = None) -> dict[str, Any]:
    """Queue every brief on the orchestrator and run them (deterministic order)."""
    ctx = Context.create(root)
    orch = JobOrchestrator(ctx.root)
    briefs = {b["id"]: b for b in load_briefs(ctx.root, pattern)}
    for b in briefs.values():
        orch.enqueue(f"gen.{b['kind']}", {"brief_id": b["id"]})
    report: dict[str, Any] = {"ok": True, "assets": {}, "sandbox": sandbox}

    def handler(job: Any) -> GeneratorOutput:
        return run_brief(briefs[job.payload["brief_id"]], ctx, export=export, sandbox=sandbox)

    for job, res in run_pending(orch, handler, kinds={f"gen.{b['kind']}" for b in briefs.values()}):
        bid = job.payload.get("brief_id")
        if bid not in briefs:
            continue
        if isinstance(res, Exception):
            report["assets"][bid] = {"ok": False, "error": str(res)}
            report["ok"] = False
            continue
        report["assets"][bid] = {"ok": res.ok, "gates": {g.gate: g.ok for g in res.gates}, "elapsed_ms": res.meta["elapsed_ms"]}
        report["ok"] &= res.ok
    return report
