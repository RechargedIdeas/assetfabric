"""PatternVault — versioned palettes / patterns (F1).

Palettes live in `content/patternvault/palettes.json` (tracked, versioned).
Colour-blind variants support G-A11Y-01 later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from forge.imaging import RGBA, hex_to_rgba
from forge.paths import find_repo_root


@dataclass(frozen=True)
class Palette:
    name: str
    version: int
    colours: tuple[RGBA, ...]
    description: str = ""

    def __getitem__(self, i: int) -> RGBA:
        return self.colours[i]

    def __len__(self) -> int:
        return len(self.colours)

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


class PatternVault:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or find_repo_root()
        self.path = self.root / "content" / "patternvault" / "palettes.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def names(self) -> list[str]:
        return sorted(self.data["palettes"])

    def get(self, name: str, variant: str | None = None) -> Palette:
        spec = self.data["palettes"][name]
        cols = spec["colours"]
        if variant:
            cols = self.data.get("colorblind_variants", {}).get(variant, {}).get(name, cols)
        return Palette(name, int(spec["version"]), tuple(hex_to_rgba(c) for c in cols), spec.get("description", ""))

    def variants(self) -> list[str]:
        return sorted(self.data.get("colorblind_variants", {}))
