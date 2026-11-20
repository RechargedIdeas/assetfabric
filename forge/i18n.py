"""Locale lookup for forge's own user-facing messages (no hard-coded strings — keys live in locales/en.json).

Only the English catalogue exists (D-005 / F6 note: translations are a later localisation pass); `t()` fails loudly on a
missing key so `forge accept C9..C12` and the unit tests catch an unregistered message."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from forge.paths import find_repo_root


@lru_cache(maxsize=4)
def _catalogue(root: str, lang: str) -> dict[str, str]:
    return json.loads((Path(root) / "locales" / f"{lang}.json").read_text(encoding="utf-8"))


def catalogue(root: Path | None = None, lang: str = "en") -> dict[str, str]:
    return _catalogue(str(root or find_repo_root()), lang)


def t(key: str, root: Path | None = None, lang: str = "en", **kw: object) -> str:
    cat = catalogue(root, lang)
    if key not in cat:
        raise KeyError(f"locale key {key!r} missing from locales/{lang}.json")
    return cat[key].format(**kw) if kw else cat[key]
