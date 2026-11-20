"""G-A11Y-01 colour-blind palettes (0.7.10) — PatternVault variants → the game's runtime remap table + a measurable gate.

The game remaps palette colours on screen (games/game-zero/autoload/a11y.gd). This module builds that table from
`content/patternvault/palettes.json` (`colorblind_variants`) and checks that each variant actually separates the colour
pairs the game uses as signals (`a11y_checks`: hostile vs hero, crop growing vs ready, red vs green UI, …) for the
deficiency it is named after.

Simulation: Machado, Oliveira & Fernandes (2009) severity-1.0 matrices on linear sRGB; distance = CIE76 ΔE*ab (D65).
[INFERENCE C-86] GAME_SPEC §6.2 only says "colorblind palette variants"; the pairs, the ΔE floor (`min_delta_e`) and the
choice of deuteranopia + protanopia (the variants PatternVault already had) are ours.
"""

from __future__ import annotations

from typing import Any

from forge.patternvault import PatternVault

MACHADO = {
    "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}


def _hex(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def simulate(hex_colour: str, deficiency: str | None) -> tuple[float, float, float]:
    """sRGB (0..1) as seen with the given deficiency (None = normal vision)."""
    r, g, b = _hex(hex_colour)
    if not deficiency:
        return r, g, b
    lin = (_lin(r), _lin(g), _lin(b))
    m = MACHADO[deficiency]
    return tuple(_unlin(sum(m[i][j] * lin[j] for j in range(3))) for i in range(3))  # type: ignore[return-value]


def _lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_lin(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str, deficiency: str | None = None) -> float:
    la, lb = _lab(simulate(a, deficiency)), _lab(simulate(b, deficiency))
    return sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5


def _colour(vault: PatternVault, ref: str, variant: str | None) -> str:
    name, idx = ref.split(":")
    cols = vault.data["palettes"][name]["colours"]
    if variant:
        cols = vault.data.get("colorblind_variants", {}).get(variant, {}).get(name, cols)
    return cols[int(idx)]


def remap_table(vault: PatternVault) -> dict[str, list[list[str]]]:
    """variant -> [[base hex, variant hex], ...] for every palette colour the variant changes (sorted, unique sources)."""
    out: dict[str, list[list[str]]] = {}
    for v, pals in sorted(vault.data.get("colorblind_variants", {}).items()):
        pairs: dict[str, str] = {}
        for name, cols in sorted(pals.items()):
            base = vault.data["palettes"][name]["colours"]
            for b, c in zip(base, cols):
                if b.lower() != c.lower():
                    prev = pairs.get(b.lower())
                    if prev is not None and prev != c.lower():
                        raise ValueError(f"{v}: {b} maps to both {prev} and {c}")
                    pairs[b.lower()] = c.lower()
        out[v] = [[k, pairs[k]] for k in sorted(pairs)]
    return out


def collateral(vault: PatternVault) -> list[str]:
    """Remapped colours that also occur in a palette the variant does not override the same way (screen-space remap would
    recolour it by accident). Must be empty."""
    out: list[str] = []
    for v, pairs in remap_table(vault).items():
        cv = vault.data.get("colorblind_variants", {}).get(v, {})
        for src, dst in pairs:
            for name, spec in vault.data["palettes"].items():
                for i, c in enumerate(spec["colours"]):
                    if c.lower() == src and (name not in cv or cv[name][i].lower() != dst):
                        out.append(f"{v}: {name}[{i}] {src} would become {dst} without being declared")
    return out


def ui_colours(vault: PatternVault) -> dict[str, str]:
    roles = {k: v for k, v in vault.data.get("ui_roles", {}).items() if not k.startswith("_")}
    return {k: _colour(vault, ref, None).lower() for k, ref in sorted(roles.items())}


def game_table(vault: PatternVault | None = None) -> dict[str, Any]:
    """The `a11y` block of world.json that the game's A11y autoload reads."""
    vault = vault or PatternVault()
    return {"variants": ["default", *vault.variants()], "palettes": remap_table(vault), "ui": ui_colours(vault)}


def report(vault: PatternVault | None = None) -> dict[str, Any]:
    """Per variant × check: ΔE for normal vision, the deficiency on the default palette, and the deficiency on the variant."""
    vault = vault or PatternVault()
    checks = vault.data.get("a11y_checks", {})
    floor = float(checks.get("min_delta_e", 20.0))
    rows: dict[str, Any] = {}
    ok = True
    for v in vault.variants():
        res = []
        for c in checks.get("pairs", []):
            a, b = c["pair"]
            d0 = delta_e(_colour(vault, a, None), _colour(vault, b, None), v)
            d1 = delta_e(_colour(vault, a, v), _colour(vault, b, v), v)
            dn = delta_e(_colour(vault, a, v), _colour(vault, b, v), None)
            good = d1 >= floor and d1 >= d0 - 1e-9
            ok &= good
            res.append({"what": c["what"], "pair": c["pair"], "default_seen": round(d0, 1), "variant_seen": round(d1, 1),
                        "variant_normal_vision": round(dn, 1), "ok": good})
        rows[v] = res
    try:
        table = remap_table(vault)
        unique = True
    except ValueError as exc:
        table, unique = {}, str(exc)
    coll = collateral(vault) if unique is True else []
    return {"min_delta_e": floor, "variants": rows, "table_unique": unique, "pairs": sum(len(t) for t in table.values()),
            "collateral": coll, "ok": ok and unique is True and bool(table) and not coll}
