#!/usr/bin/env python3
"""Hardware-verification report format + checker (post-F9, 0.9.1). Stdlib only, so it runs on any machine.

    python scripts/verify-hardware/hwreport.py check  <report.json> [...]   # validate + verdict (exit 0 pass / 2 incomplete / 1 fail)
    python scripts/verify-hardware/hwreport.py answer <report.json>         # answer the manual checklist interactively

A report is what verify-windows.ps1 / verify_android.py / verify_web.py write:
{"format": "assetfabric-hw-report", "schema": 1, "target": "windows|android|web", "tool": "...", "build_version": "...",
 "started": "<ISO-8601>", "device": {...}, "checks": [{"id", "ok": true|false|null, "detail"}],
 "manual": [{"id", "ask", "kind", "answer"}], "verdict": "pass|fail|incomplete"}

Automated checks prove what a script can observe on the device; the manual list is what only a person can judge. A
report is `pass` only when every automated check is ok AND every manual item is answered (and no yes/no is "no").
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

FORMAT = "assetfabric-hw-report"
TARGETS = ("windows", "android", "web")
HERE = Path(__file__).resolve().parent


def checklist(section: str) -> list[dict[str, Any]]:
    d = json.loads((HERE / "checklists.json").read_text(encoding="utf-8"))
    return [{**i, "answer": None} for i in d[section]]


def new_report(target: str, tool: str, manual_sections: list[str]) -> dict[str, Any]:
    man: list[dict[str, Any]] = []
    for s in manual_sections:
        man += [{**i, "section": s} for i in checklist(s)]
    return {"format": FORMAT, "schema": 1, "target": target, "tool": tool, "build_version": None,
            "started": _dt.datetime.now().astimezone().isoformat(timespec="seconds"), "device": {}, "checks": [],
            "manual": man, "verdict": "incomplete"}


def add(rep: dict[str, Any], cid: str, ok: bool | None, detail: Any = None) -> bool | None:
    rep["checks"].append({"id": cid, "ok": ok, "detail": detail})
    return ok


def _negative(item: dict[str, Any]) -> bool:
    a = item.get("answer")
    return item.get("kind") == "yes_no" and isinstance(a, str) and a.strip().lower() in ("n", "no", "false")


def verdict(rep: dict[str, Any]) -> str:
    checks = rep.get("checks") or []
    if any(c.get("ok") is False for c in checks) or any(_negative(m) for m in rep.get("manual") or []):
        return "fail"
    if not checks or any(c.get("ok") is None for c in checks) or any(m.get("answer") in (None, "") for m in rep.get("manual") or []):
        return "incomplete"
    return "pass"


def validate(rep: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(rep, dict):
        return ["not a JSON object"]
    if rep.get("format") != FORMAT or rep.get("schema") != 1:
        errs.append("format/schema")
    if rep.get("target") not in TARGETS:
        errs.append(f"target {rep.get('target')!r}")
    for k in ("tool", "started"):
        if not isinstance(rep.get(k), str) or not rep.get(k):
            errs.append(f"missing {k}")
    if not isinstance(rep.get("checks"), list):
        errs.append("checks must be a list")
    else:
        seen = set()
        for c in rep["checks"]:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str) or c.get("ok") not in (True, False, None):
                errs.append(f"bad check {c!r}"[:120])
            elif c["id"] in seen:
                errs.append(f"duplicate check {c['id']}")
            else:
                seen.add(c["id"])
    if not isinstance(rep.get("manual"), list) or any(not isinstance(m, dict) or "id" not in m for m in rep.get("manual", [])):
        errs.append("manual must be a list of {id, ask, kind, answer}")
    if rep.get("verdict") not in ("pass", "fail", "incomplete"):
        errs.append("verdict")
    return errs


def finish(rep: dict[str, Any], out_dir: Path) -> Path:
    rep["verdict"] = verdict(rep)
    rep["finished"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    p = out_dir / f"{rep['target']}-{stamp}.json"
    p.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def summary(rep: dict[str, Any]) -> str:
    lines = [f"{rep.get('target')} · build {rep.get('build_version')} · verdict {verdict(rep).upper()}"]
    for c in rep.get("checks", []):
        mark = {True: "PASS", False: "FAIL", None: "----"}[c.get("ok")]
        d = c.get("detail")
        lines.append(f"  [{mark}] {c['id']}" + (f" — {json.dumps(d, ensure_ascii=False)[:140]}" if d not in (None, "") else ""))
    unanswered = [m["id"] for m in rep.get("manual", []) if m.get("answer") in (None, "")]
    lines.append(f"  manual: {len(rep.get('manual', [])) - len(unanswered)}/{len(rep.get('manual', []))} answered"
                 + (f" (open: {', '.join(unanswered)})" if unanswered else ""))
    return "\n".join(lines)


def _check(paths: list[str]) -> int:
    sev = {"pass": 0, "incomplete": 1, "fail": 2}
    worst = "pass"
    for p in paths:
        rep = json.loads(Path(p).read_text(encoding="utf-8-sig"))
        errs = validate(rep)
        if errs:
            print(f"{p}: INVALID — {'; '.join(errs)}")
            worst = "fail"
            continue
        print(summary(rep))
        v = verdict(rep)
        if rep.get("verdict") != v:
            print(f"  note: stored verdict {rep.get('verdict')!r} != recomputed {v!r}")
        worst = v if sev[v] > sev[worst] else worst
    return {"pass": 0, "incomplete": 2, "fail": 1}[worst]


def _answer(path: str) -> int:
    p = Path(path)
    rep = json.loads(p.read_text(encoding="utf-8-sig"))
    for m in rep.get("manual", []):
        if m.get("answer") not in (None, ""):
            continue
        hint = " [y/n]" if m.get("kind") == "yes_no" else ""
        a = input(f"{m['ask']}{hint} (enter = skip): ").strip()
        if a:
            m["answer"] = a
    rep["verdict"] = verdict(rep)
    p.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(summary(rep))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "check":
        return _check(argv[1:])
    if len(argv) == 2 and argv[0] == "answer":
        return _answer(argv[1])
    print(__doc__)
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
