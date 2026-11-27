# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Build `content/universal/engines_catalog.yaml` from Wikipedia's "List of game engines" + the curated named-tool list.

Only factual table fields are kept (name, alternate names, primary language, release year, scripting, cross-platform,
2D/3D orientation, target platforms, licence); prose columns (notable games, notes) are dropped. The page revision id
and timestamp are recorded for attribution/reproducibility (text: CC BY-SA 4.0, Wikipedia contributors).

    python -m forge.universal.catalog_build fetch     # download the current revision (network) → /tmp
    python -m forge.universal.catalog_build build     # parse + merge curated data → YAML (deterministic)
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

WIKI_TITLE = "List_of_game_engines"
RAW_URL = f"https://en.wikipedia.org/w/index.php?title={WIKI_TITLE}&action=raw"
REV_URL = ("https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles="
           + urllib.parse.quote(WIKI_TITLE) + "&rvprop=ids%7Ctimestamp&format=json")
UA = "AssetFabric-catalog/1.0 (Recharged Ideas; offline catalog build)"
COLUMNS = ("language", "release_year", "scripting", "cross_platform", "orientation", "platforms", "notable_games",
           "license", "notes")


def fetch(dst: Path) -> dict[str, Any]:
    def get(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:   # noqa: S310 — fixed https URLs
            return r.read()
    dst.write_bytes(get(RAW_URL))
    meta = json.loads(get(REV_URL))
    page = next(iter(meta["query"]["pages"].values()))
    rev = page["revisions"][0]
    info = {"title": page["title"], "revid": rev["revid"], "timestamp": rev["timestamp"],
            "url": f"https://en.wikipedia.org/w/index.php?title={WIKI_TITLE}&oldid={rev['revid']}"}
    dst.with_suffix(".json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


# ----------------------------------------------------------------------------- wikitext cleaning

def clean(s: str) -> str:
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"</?[a-zA-Z][^>]*>", "", s)
    for _ in range(4):                                   # nested templates, innermost first
        s = re.sub(r"\{\{\s*(?:open source|free software|Open source)\s*\|([^{}]*)\}\}", r"\1 (open source)", s, flags=re.I)
        s = re.sub(r"\{\{\s*proprietary\s*(?:\|([^{}]*))?\}\}", lambda m: "Proprietary" + (f" ({m.group(1)})" if m.group(1) else ""), s, flags=re.I)
        s = re.sub(r"\{\{\s*(?:yes|y)\s*(?:\|([^{}]*))?\}\}", lambda m: m.group(1) or "Yes", s, flags=re.I)
        s = re.sub(r"\{\{\s*(?:no|n)\s*(?:\|([^{}]*))?\}\}", lambda m: m.group(1) or "No", s, flags=re.I)
        s = re.sub(r"\{\{\s*(?:partial|some)\s*(?:\|([^{}]*))?\}\}", lambda m: m.group(1) or "Partial", s, flags=re.I)
        s = re.sub(r"\{\{\s*(?:small|nowrap|abbr|lang\|[a-z-]+)\s*\|([^{}|]*)(?:\|[^{}]*)?\}\}", r"\1", s, flags=re.I)
        s = re.sub(r"\{\{\s*needs\s*\|([^{}]*)\}\}", r"\1", s, flags=re.I)
        s = re.sub(r"\{\{\s*(?:freeware|free)\s*(?:\|([^{}]*))?\}\}", lambda m: "Freeware" + (f" ({m.group(1)})" if m.group(1) else ""), s, flags=re.I)
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\]", "", s)
    s = s.replace("'''", "").replace("''", "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip(" ,;")


def _cell_text(line: str) -> str:
    body = line[1:]
    # attribute prefix "style=... | value" (only when the first pipe is outside links/templates)
    depth, cut = 0, None
    for i, ch in enumerate(body):
        if body.startswith(("[[", "{{"), i):
            depth += 1
        elif body.startswith(("]]", "}}"), i):
            depth -= 1
        elif ch == "|" and depth == 0:
            cut = i
            break
    if cut is not None and "=" in body[:cut]:
        body = body[cut + 1:]
    return body.strip()


def parse(text: str) -> list[dict[str, Any]]:
    start = text.index("{|")
    end = text.index("|}", start)
    rows = text[start:end].split("\n|-")[1:]
    out = []
    for r in rows:
        lines: list[str] = []
        for ln in r.split("\n"):
            if not ln.strip():
                continue
            if lines and lines[-1].startswith("!") and not ln.startswith(("|", "!")):
                lines[-1] += " " + ln.strip()            # header cell continued on the next line
            else:
                lines.append(ln)
        head = [ln for ln in lines if ln.startswith("!")]
        cells = [ln for ln in lines if ln.startswith("|") and not ln.startswith(("|}", "|-"))]
        if len(head) != 1 or len(cells) < 8:
            continue                                     # header row or malformed
        raw_name = _cell_text(head[0])
        alt = re.findall(r"\{\{small\|\(([^)]*)\)\}\}", raw_name)
        name = clean(re.sub(r"<br\s*/?>.*$", "", re.sub(r"\{\{small\|.*?\}\}", "", raw_name)))
        vals = {COLUMNS[i]: clean(_cell_text(c)) for i, c in enumerate(cells[:len(COLUMNS)])}
        if not name:
            continue
        out.append({"name": name, "alternate_names": [clean(a) for a in alt if clean(a) and clean(a) != name], **vals})
    return out


def dims_of(orientation: str) -> list[str]:
    o = orientation.lower()
    d = []
    if re.search(r"\b2d\b", o) or "2d" in o.replace("2.5d", ""):
        d.append("2d")
    if "2.5d" in o or "isometric" in o or "pseudo-3d" in o:
        d.append("2.5d")
    if re.search(r"3d", o):
        d.append("3d")
    return d or ["unknown"]


def license_class(lic: str) -> str:
    l = lic.lower()
    if "open source" in l or any(k in l for k in ("mit", "gpl", "bsd", "zlib", "apache", "mpl", "artistic", "public domain", "unlicense")):
        return "open_source" if "proprietary" not in l else "mixed"
    if "freeware" in l or "free" in l:
        return "freeware"
    if "proprietary" in l or "commercial" in l:
        return "proprietary"
    return "unknown"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "fetch":
        print(json.dumps(fetch(Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/wiki_engines.txt")), indent=2))
    elif cmd == "build":
        from forge.universal.registry import build_catalog
        src = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/wiki_engines.txt")
        print(json.dumps(build_catalog(src), indent=2))
