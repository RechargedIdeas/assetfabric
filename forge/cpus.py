"""Pick CPUs for "N cores" measurements (weakest node = 2 cores, no GPU).

"2 cores" means two *physical* cores. On SMT hosts (e.g. GitHub's 4-vCPU runners = 2 cores x 2 threads) the first two
logical CPUs are often hyper-thread siblings of one core, so pinning `0,1` would measure a 1-core machine. We take one
logical CPU per physical core (Linux sysfs `thread_siblings_list`) and fall back to the plain affinity order elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path


def _siblings(cpu: int) -> frozenset[int]:
    p = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
    try:
        out: set[int] = set()
        for part in p.read_text().strip().split(","):
            a, _, b = part.partition("-")
            out.update(range(int(a), int(b or a) + 1))
        return frozenset(out)
    except (OSError, ValueError):
        return frozenset({cpu})


def affinity() -> list[int]:
    return sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else list(range(os.cpu_count() or 1))


def physical_core_cpus(n: int, avail: list[int] | None = None) -> list[int]:
    """Up to `n` logical CPUs from `avail` (default: our affinity), each on a different physical core.

    If fewer than `n` distinct cores are available, siblings fill the rest (still `n` CPUs, never more)."""
    avail = affinity() if avail is None else sorted(avail)
    picked: list[int] = []
    seen: set[frozenset[int]] = set()
    for c in avail:
        sib = _siblings(c)
        if sib not in seen:
            seen.add(sib)
            picked.append(c)
        if len(picked) == n:
            return picked
    for c in avail:
        if len(picked) == n:
            break
        if c not in picked:
            picked.append(c)
    return picked


def smt_siblings_pinned(cpus: list[int]) -> bool:
    """True when two of `cpus` share a physical core."""
    groups = [_siblings(c) for c in cpus]
    return len(set(groups)) < len(groups)
