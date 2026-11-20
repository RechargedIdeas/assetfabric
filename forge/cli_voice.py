"""`forge voice …` (VoiceBridge, offline Vosk STT → closed intent grammar) and `forge persona …` (persona micro-LM drafts)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from forge.cli_recon import _emit, _guard


@click.group("voice")
def voice_grp() -> None:
    """VoiceBridge (F3, ADR-0006): offline Vosk STT constrained to the intent grammar. Needs `forge models fetch vosk-small-en-us-0.15`."""


@voice_grp.command("grammar")
def voice_grammar() -> None:
    """The closed phrase list the recogniser is constrained to (from intent_grammar.gd + the roster), with lexicon aliases."""
    from forge import voice

    def run() -> Any:
        ek, pt = voice.roster()
        out: dict[str, Any] = {"verbs": voice.verbs(), "enemy_kinds": ek, "party": pt, "phrases": voice.grammar_phrases(ek, pt)}
        try:
            b = voice.VoiceBridge()
            out.update(fitted=len(b.grammar), aliases=b.aliases, oov=b.oov)
        except FileNotFoundError as e:
            out["model"] = str(e)
        return out
    _guard(run)


@voice_grp.command("transcribe")
@click.argument("wav", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--free", is_flag=True, help="Unconstrained decoding (no grammar) — for comparison only.")
def voice_transcribe(wav: Path, free: bool) -> None:
    """WAV → text (16 kHz mono preferred; ffmpeg converts other formats)."""
    from forge import voice
    _guard(lambda: voice.VoiceBridge(constrained=not free).transcribe(wav.read_bytes()))


@voice_grp.command("intent")
@click.argument("wav", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--min-conf", type=float, default=0.7, show_default=True, help="Below this word confidence the command is `unknown`.")
def voice_intent(wav: Path, min_conf: float) -> None:
    """WAV → intent JSON (same parser and output shape as a typed command)."""
    from forge import voice
    _guard(lambda: voice.VoiceBridge(min_conf=min_conf).intent(wav.read_bytes()))


@voice_grp.command("eval")
@click.option("--synth", is_flag=True, help="Synthesise the command set with espeak-ng (4 voices × 2 speeds) instead of the fixtures.")
def voice_eval(synth: bool) -> None:
    """Intent accuracy + wrong-action rate on synthetic speech (committed fixtures, or fresh espeak-ng renders)."""
    from forge import voice

    def run() -> Any:
        b = voice.VoiceBridge()
        r = voice.evaluate(b, ("en-us", "en-gb", "en-us+m3", "en-us+f2"), (140, 175)) if synth else voice.evaluate_fixtures(b)
        return {k: v for k, v in r.items() if k != "rows"} | {"misses": [x for x in r["rows"] if not x["ok"]]}
    _guard(run)


@click.group("persona")
def persona_grp() -> None:
    """Persona micro-LM (Qwen2.5-0.5B-Instruct int8 ONNX, CPU): drafts lines for human review. Never runs in the game."""


@persona_grp.command("author")
@click.option("--persona", "pid", required=True)
@click.option("--event", required=True)
@click.option("-n", "n", type=int, default=4, show_default=True)
@click.option("--seed", type=int, default=0, show_default=True)
@click.option("--threads", type=int, default=2, show_default=True)
@click.option("--write", is_flag=True, help="Append accepted drafts to content/personas/lm_drafts.yaml (reviewed: false).")
def persona_author(pid: str, event: str, n: int, seed: int, threads: int, write: bool) -> None:
    """Draft N new lines for PERSONA × EVENT; each passes the content-safety gateway + a meta-chatter filter or is rejected."""
    from forge import microlm

    def run() -> Any:
        r = microlm.author(microlm.QwenLM(threads=threads), pid, event, n, seed0=seed)
        if write:
            r["written"] = str(microlm.write_drafts(r))
        return r
    _guard(run)
