"""Parallel statecharts (F4) — Python twin of `games/game-zero/sim/statechart.gd`.

Same JSON, same semantics (see the GDScript header). Python adds **static analysis**
used as a build gate (soft-lock detection before anything runs, F5/F6):

- unreachable states (no path from the initial state),
- dead ends (non-final state with no outgoing transition),
- traps (states from which no final state is reachable),
- dangling targets.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Callable

Guard = Callable[[str, str, str], bool]


class StateChart:
    def __init__(self, chart: dict[str, Any], guard: Guard | None = None) -> None:
        self.id = str(chart.get("id", "chart"))
        self.regions: dict[str, Any] = chart["regions"]
        self.guard = guard
        self.order = sorted(self.regions)
        self.active = {r: str(self.regions[r]["initial"]) for r in self.order}
        self.trace: list[dict[str, Any]] = []
        self.tick = 0

    def send(self, event: str) -> list[dict[str, Any]]:
        taken = []
        for r in self.order:
            cur = self.active[r]
            on = self.regions[r]["states"].get(cur, {}).get("on", {})
            if event not in on:
                continue
            tr = on[event]
            target, guard = (str(tr["target"]), str(tr.get("guard", ""))) if isinstance(tr, dict) else (str(tr), "")
            if guard and not (self.guard and self.guard(guard, r, cur)):
                continue
            self.active[r] = target
            rec = {"tick": self.tick, "region": r, "from": cur, "to": target, "event": event}
            self.trace.append(rec)
            taken.append(rec)
        return taken

    def is_final(self, region: str) -> bool:
        return bool(self.regions[region]["states"].get(self.active[region], {}).get("final", False))

    def done(self) -> bool:
        return all(self.is_final(r) for r in self.order)


def _targets(st: dict[str, Any]) -> list[str]:
    return [str(t["target"]) if isinstance(t, dict) else str(t) for t in st.get("on", {}).values()]


def analyze(chart: dict[str, Any]) -> dict[str, Any]:
    """Static soft-lock analysis per region. `ok` is False on any finding."""
    report: dict[str, Any] = {"id": chart.get("id"), "regions": {}, "ok": True}
    for name, m in sorted(chart["regions"].items()):
        states: dict[str, Any] = m["states"]
        dangling = sorted({t for s in states.values() for t in _targets(s) if t not in states})
        seen = {m["initial"]}
        q = deque([m["initial"]])
        while q:
            for t in _targets(states.get(q.popleft(), {})):
                if t in states and t not in seen:
                    seen.add(t)
                    q.append(t)
        unreachable = sorted(set(states) - seen)
        finals = {s for s, d in states.items() if d.get("final")}
        dead_ends = sorted(s for s, d in states.items() if not d.get("final") and not _targets(d))
        # reverse reachability from finals
        rev: dict[str, set[str]] = {s: set() for s in states}
        for s, d in states.items():
            for t in _targets(d):
                if t in rev:
                    rev[t].add(s)
        can_finish = set(finals)
        q = deque(finals)
        while q:
            for p in rev[q.popleft()]:
                if p not in can_finish:
                    can_finish.add(p)
                    q.append(p)
        traps = sorted(s for s in seen if s not in can_finish) if finals else []
        r = {"unreachable": unreachable, "dead_ends": dead_ends, "traps": traps, "dangling": dangling,
             "has_final": bool(finals), "initial_ok": m["initial"] in states}
        r["ok"] = not (unreachable or dead_ends or traps or dangling) and r["initial_ok"]
        report["regions"][name] = r
        report["ok"] &= r["ok"]
    return report


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
