"""Generator registry. Each generator: (brief, ctx) -> GeneratorOutput.

F1 ships procedural CPU backends (GroundWeave-friendly). ONNX backends for
G1-Sprite Tiny/Medium and G1-Tile NCA plug in behind the same interface later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from forge.gates import GateResult


@dataclass
class Artifact:
    name: str            # logical file name, e.g. "hero.png"
    data: bytes
    media_type: str


@dataclass
class GeneratorOutput:
    artifacts: list[Artifact]
    gates: list[GateResult]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(g.ok for g in self.gates)


GeneratorFn = Callable[[dict[str, Any], Any], GeneratorOutput]
REGISTRY: dict[str, GeneratorFn] = {}


def register(kind: str) -> Callable[[GeneratorFn], GeneratorFn]:
    def deco(fn: GeneratorFn) -> GeneratorFn:
        REGISTRY[kind] = fn
        return fn
    return deco


def load_all() -> dict[str, GeneratorFn]:
    from forge.generators import dyeworks, sprite, tile  # noqa: F401
    try:
        from forge.generators import audio, callouts, codegen, liveops, policy, retro, world  # noqa: F401  (F2+, world F6, retro F8, liveops F9)
    except ImportError:
        pass
    return REGISTRY
