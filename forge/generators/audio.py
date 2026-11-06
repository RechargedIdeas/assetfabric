"""G1-Audio (procedural chiptune backend) — macro-state stems + SFX as WAV.

Channels: pulse lead (duty 12.5/25/50 %), triangle bass, LFSR noise drums —
NES-style. Stems per macro state (ambient / tension / combat / boss) share key
and tempo so F6 adaptive music can crossfade. CPU-only, deterministic.
Gates: no clipping, exact duration, loop seam (ends near zero), budget.
`[INFERENCE]` arrangement rules are original; chat only fixed "chiptune stems
remixable by macro state".
"""

from __future__ import annotations

import io
import math
import random
import struct
import time
import wave
from typing import Any

from forge.gates import GateResult, budget_gate
from forge.generators import Artifact, GeneratorOutput, register

SCALES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11], "dorian": [0, 2, 3, 5, 7, 9, 10]}
STATES = {
    #           bpm_mul lead  bass  drums  density  scale   duty
    "ambient": (0.6,    0.5,  0.8,  0.0,   0.35,    "dorian", 0.5),
    "tension": (0.85,   0.4,  1.0,  0.35,  0.45,    "minor",  0.25),
    "combat":  (1.0,    0.8,  1.0,  1.0,   0.7,     "minor",  0.25),
    "boss":    (1.15,   0.9,  1.0,  1.0,   0.85,    "minor",  0.125),
}


def _freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _wav(samples: list[float], rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples))
    return buf.getvalue()


class _Noise:
    def __init__(self) -> None:
        self.reg = 1

    def step(self) -> float:
        bit = (self.reg ^ (self.reg >> 1)) & 1
        self.reg = (self.reg >> 1) | (bit << 14)
        return 1.0 if self.reg & 1 else -1.0


def render_stem(state: str, *, bpm: int, root_midi: int, seconds: float, rate: int, seed: str) -> list[float]:
    bpm_mul, lead_g, bass_g, drum_g, density, scale_name, duty = STATES[state]
    tempo = bpm * bpm_mul
    step_s = 60.0 / tempo / 4  # 16th notes
    n = int(seconds * rate)
    steps = max(1, int(round(seconds / step_s)))
    step_len = n / steps
    rng = random.Random(f"G1-Audio:{seed}:{state}")
    scale = SCALES[scale_name]
    # phrase: lead notes per step (None = rest), bass per beat
    lead = []
    deg = 0
    for i in range(steps):
        if rng.random() < density:
            deg = max(-3, min(9, deg + rng.choice([-2, -1, -1, 0, 1, 1, 2, 3])))
            octave, idx = divmod(deg, len(scale))
            lead.append(root_midi + 12 + 12 * octave + scale[idx])
        else:
            lead.append(None)
    prog = [0, 5, 3, 4] if scale_name != "major" else [0, 3, 4, 0]
    out = [0.0] * n
    noise = _Noise()
    phase_l = phase_b = 0.0
    for i in range(n):
        st = min(int(i / step_len), steps - 1)
        t_in = (i - st * step_len) / step_len  # 0..1 within step
        s = 0.0
        note = lead[st]
        if note is not None and lead_g:
            phase_l = (phase_l + _freq(note) / rate) % 1.0
            env = max(0.0, 1.0 - t_in * 0.9)
            s += lead_g * 0.22 * env * (1.0 if phase_l < duty else -1.0)
        if bass_g:
            beat = st // 4
            chord = prog[(beat // 4) % len(prog)]
            bnote = root_midi - 12 + scale[chord % len(scale)]
            phase_b = (phase_b + _freq(bnote) / rate) % 1.0
            tri = 4 * abs(phase_b - 0.5) - 1
            s += bass_g * 0.28 * tri
        if drum_g:
            pos = st % 16
            kick = pos in (0, 8) or (state == "boss" and pos in (0, 6, 8, 14))
            snare = pos in (4, 12)
            hat = pos % 2 == 1
            nz = noise.step()
            if kick:
                f = 110 * (1 - t_in) + 40
                s += drum_g * 0.35 * math.sin(2 * math.pi * f * t_in * step_len / rate) * (1 - t_in)
            if snare:
                s += drum_g * 0.18 * nz * max(0.0, 1 - t_in * 1.6)
            if hat and t_in < 0.25:
                s += drum_g * 0.06 * nz
        out[i] = s
    # 5 ms fades so the loop seam is click-free
    fade = int(rate * 0.005)
    for i in range(fade):
        g = i / fade
        out[i] *= g
        out[n - 1 - i] *= g
    return out


def render_sfx(kind: str, rate: int) -> list[float]:
    n = int(rate * {"hit": 0.12, "swing": 0.1, "defeat": 0.45, "heal": 0.3}[kind])
    noise = _Noise()
    out = []
    ph = 0.0
    for i in range(n):
        t = i / n
        if kind == "hit":
            v = 0.5 * noise.step() * (1 - t) ** 2
        elif kind == "swing":
            ph = (ph + (900 - 700 * t) / rate) % 1
            v = 0.3 * (1 if ph < 0.5 else -1) * (1 - t)
        elif kind == "defeat":
            ph = (ph + (440 * (1 - 0.7 * t)) / rate) % 1
            v = 0.35 * (1 if ph < 0.25 else -1) * (1 - t)
        else:  # heal
            ph = (ph + _freq(72 + 12 * t) / rate) % 1
            v = 0.3 * (4 * abs(ph - 0.5) - 1) * (1 - t)
        out.append(v)
    return out


@register("audio")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    rate = int(brief.get("rate", 22050))
    seconds = float(brief.get("seconds", 4.0))
    arts: list[Artifact] = []
    peaks: dict[str, float] = {}
    seams: dict[str, float] = {}
    durations: dict[str, float] = {}
    for state in brief.get("stems", list(STATES)):
        smp = render_stem(state, bpm=int(brief.get("bpm", 132)), root_midi=int(brief.get("root_midi", 45)),
                          seconds=seconds, rate=rate, seed=f"{brief['id']}:{brief.get('seed', 0)}")
        peaks[state] = max(abs(x) for x in smp)
        seams[state] = abs(smp[-1] - smp[0])
        durations[state] = len(smp) / rate
        arts.append(Artifact(f"{brief['id']}_{state}.wav", _wav(smp, rate), "audio/wav"))
    for sfx in brief.get("sfx", []):
        smp = render_sfx(sfx, rate)
        peaks[f"sfx_{sfx}"] = max(abs(x) for x in smp)
        arts.append(Artifact(f"sfx_{sfx}.wav", _wav(smp, rate), "audio/wav"))
    elapsed = (time.perf_counter() - t0) * 1000
    gates = [
        GateResult("no_clipping", all(p <= 0.98 for p in peaks.values()), {k: round(v, 3) for k, v in peaks.items()}),
        GateResult("loop_seam", all(s < 0.02 for s in seams.values()), {k: round(v, 4) for k, v in seams.items()}),
        GateResult("duration", all(abs(d - seconds) < 1 / rate * 2 for d in durations.values()), durations),
        budget_gate(elapsed, sum(len(a.data) for a in arts), float(brief.get("budget_ms", 15000)), 2 * 1024 * 1024),
    ]
    return GeneratorOutput(arts, gates, {"kind": "audio", "rate": rate, "seconds": seconds, "stems": list(STATES),
                                         "model_id": "G1-Audio", "model_version": "chiptune-1"})
