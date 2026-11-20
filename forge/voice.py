"""VoiceBridge (F3 voice intents, ADR-0006): offline Vosk STT constrained to the game's closed intent grammar.

* STT: Vosk (`vosk` wheel, Apache-2.0) with `vosk-small-en-us-0.15` (Apache-2.0, ~41 MB zip, fetched with SHA-256 by
  `forge models fetch`, never committed). The recogniser is given a **closed grammar** — exactly the phrases the intent
  grammar can act on (+ `[unk]`) — so the decoder cannot hallucinate outside the vocabulary (ADR-0006 "grammar-constrained").
* Intent: `parse` is a line-for-line mirror of `games/game-zero/ai/intent_grammar.gd` (`VERBS` are read from that file, so
  the two can never drift); typed and spoken commands go through the same parser and the same CascadeHub `intent` topic.
* Audio: 16 kHz mono 16-bit PCM WAV (other rates/channels are converted with the system ffmpeg when present).

No LLM, nothing in the combat tick: transcription happens on the input path, the tick sees only the parsed intent.
Measured only on synthetic speech (espeak-ng) — real microphones/accents are untested (INFERENCES B4)."""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from forge.paths import find_repo_root

MODEL_ID = "vosk-small-en-us-0.15"
RATE = 16000
GRAMMAR_GD = "games/game-zero/ai/intent_grammar.gd"


@lru_cache(maxsize=4)
def verbs(root: Path | None = None) -> dict[str, list[str]]:
    """`VERBS` parsed from the GDScript intent grammar (single source of truth)."""
    src = ((root or find_repo_root()) / GRAMMAR_GD).read_text(encoding="utf-8")
    body = src[src.index("const VERBS := {"):]
    body = body[: body.index("}") + 1]
    out: dict[str, list[str]] = {}
    for m in re.finditer(r'"(\w+)":\s*\[([^\]]*)\]', body):
        out[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
    if not out:
        raise ValueError(f"could not read VERBS from {GRAMMAR_GD}")
    return out


def parse(text: str, enemy_kinds: list[str], party: list[str], root: Path | None = None) -> dict[str, Any]:
    """Mirror of `IntentGrammar.parse` (GDScript): first verb match wins; focus needs a target kind; swap takes a party id."""
    t = text.lower().strip()
    for intent, words in verbs(root).items():
        for w in words:
            if t.startswith(w) or (" " + w + " ") in (" " + t + " "):
                out: dict[str, Any] = {"intent": intent, "text": text}
                if intent == "focus":
                    for k in enemy_kinds:
                        plain = k.replace("_", " ")
                        if plain in t or k in t or plain.split(" ")[-1] in t:
                            out["target_kind"] = k
                    if "target_kind" not in out:
                        return {"intent": "unknown", "text": text}
                elif intent == "swap":
                    for p in party:
                        if p in t:
                            out["to"] = p
                return out
    return {"intent": "unknown", "text": text}


def roster(root: Path | None = None) -> tuple[list[str], list[str]]:
    root = root or find_repo_root()
    e = yaml.safe_load((root / "content/roster/enemies.yaml").read_text(encoding="utf-8"))["enemies"]
    f = yaml.safe_load((root / "content/roster/fighters.yaml").read_text(encoding="utf-8"))["fighters"]
    return [x["id"] for x in e], [x["id"] for x in f]


def grammar_phrases(enemy_kinds: list[str], party: list[str], root: Path | None = None) -> list[str]:
    """Every phrase the intent grammar acts on: bare verbs, `<focus verb> [the] <enemy>`, `<swap verb> [to] <fighter>`."""
    vb = verbs(root)
    ph: list[str] = []
    for intent, words in vb.items():
        for w in words:
            if intent == "focus":
                for k in enemy_kinds:
                    plain = k.replace("_", " ")
                    ph += [f"{w} {plain}", f"{w} the {plain}"]
            elif intent == "swap":
                ph.append(w)
                for p in party:
                    ph += [f"{w} {p}", f"{w} to {p}"]
            else:
                ph.append(w)
    return sorted(set(ph))


def _pcm16k(data: bytes) -> bytes:
    """16 kHz mono s16le PCM frames from a WAV (ffmpeg converts anything else)."""
    with wave.open(io.BytesIO(data)) as w:
        if w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2:
            return w.readframes(w.getnframes())
    ff = shutil.which("ffmpeg")
    if not ff:
        raise ValueError("WAV is not 16 kHz mono 16-bit and ffmpeg is not installed to convert it")
    p = subprocess.run([ff, "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
                       input=data, capture_output=True, timeout=60, check=True)
    return p.stdout


class VoiceBridge:
    """One shared recogniser per process (ADR-0006: one Vosk instance), grammar from the live roster."""

    def __init__(self, root: Path | None = None, enemy_kinds: list[str] | None = None, party: list[str] | None = None,
                 constrained: bool = True, min_conf: float = 0.7) -> None:
        from forge import models
        self.root = root or find_repo_root()
        ek, pt = roster(self.root)
        self.enemy_kinds, self.party = enemy_kinds or ek, party or pt
        self.model_dir = models.unpacked(MODEL_ID, root=self.root)
        self.constrained, self.min_conf = constrained, min_conf
        self.grammar, self.aliases, self.oov = self._fit_vocabulary(grammar_phrases(self.enemy_kinds, self.party, self.root))

    def _fit_vocabulary(self, phrases: list[str]) -> tuple[list[str], dict[str, str], list[str]]:
        """Keep the grammar inside the model's lexicon: a word the model does not know (e.g. `emberling`) is spoken as two
        known words (`ember ling`) and mapped back after decoding; a word with no such split is dropped and reported."""
        from vosk import _c
        model = self._model(str(self.model_dir))

        def known(w: str) -> bool:
            return _c.vosk_model_find_word(model._handle, w.encode()) >= 0
        alias: dict[str, str] = {}
        oov: list[str] = []
        out: list[str] = []
        for ph in phrases:
            words = []
            for w in ph.split():
                if known(w):
                    words.append(w)
                    continue
                split = next((f"{w[:i]} {w[i:]}" for i in range(2, len(w) - 1) if known(w[:i]) and known(w[i:])), None)
                if split is None:
                    oov.append(w)
                    words = []
                    break
                alias[split] = w
                words.append(split)
            if words:
                out.append(" ".join(words))
        return sorted(set(out)), alias, sorted(set(oov))

    @staticmethod
    @lru_cache(maxsize=2)
    def _model(path: str) -> Any:
        import vosk
        vosk.SetLogLevel(-2)                   # errors only (Kaldi verbosity: -1 warnings, 0 info)
        return vosk.Model(path)

    def transcribe(self, wav: bytes) -> dict[str, Any]:
        import vosk
        model = self._model(str(self.model_dir))
        rec = (vosk.KaldiRecognizer(model, RATE, json.dumps(self.grammar + ["[unk]"])) if self.constrained
               else vosk.KaldiRecognizer(model, RATE))
        pad = b"\x00\x00" * (RATE * 3 // 10)    # 300 ms of silence each side: lets the feature pipeline settle before speech
        pcm = _pcm16k(wav)
        pcm_in = pad + pcm + pad
        rec.SetWords(True)
        for i in range(0, len(pcm_in), 8000):
            rec.AcceptWaveform(pcm_in[i:i + 8000])
        r = json.loads(rec.FinalResult())
        words = [w for w in r.get("result", []) if w.get("word") != "[unk]"]
        conf = min((float(w.get("conf", 0.0)) for w in words), default=0.0)
        text = " ".join(r.get("text", "").replace("[unk]", "").split())
        for spoken, word in self.aliases.items():
            text = re.sub(rf"\b{spoken}\b", word, text)
        return {"text": text, "min_word_conf": round(conf, 3), "seconds_audio": round(len(pcm) / 2 / RATE, 3),
                "constrained": self.constrained}

    def intent(self, wav: bytes) -> dict[str, Any]:
        """Transcript → intent. Any word under `min_conf` makes the whole command `unknown` (reason `low_confidence`): asking
        again is safer than acting on a mishearing (a misheard `hold` must not become `go`)."""
        tr = self.transcribe(wav)
        base = {"transcript": tr["text"], "min_word_conf": tr["min_word_conf"], "seconds_audio": tr["seconds_audio"]}
        if tr["text"] and tr["min_word_conf"] < self.min_conf:
            return {"intent": "unknown", "text": tr["text"], "reason": "low_confidence", **base}
        return {**parse(tr["text"], self.enemy_kinds, self.party, self.root), **base}


def synthesize(text: str, voice: str = "en-us", speed: int = 150) -> bytes:
    """Test helper: espeak-ng (system tool, GPL — test-time only, never shipped) → 16 kHz mono WAV."""
    es = shutil.which("espeak-ng") or shutil.which("espeak")
    if not es:
        raise FileNotFoundError("espeak-ng is not installed (test/acceptance helper only)")
    raw = subprocess.run([es, "-v", voice, "-s", str(speed), "--stdout", text], capture_output=True, timeout=30, check=True).stdout
    pcm = _pcm16k(raw)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return b.getvalue()


COMMAND_SET = [  # (spoken text, expected intent, expected slot) — the evaluation set for tests/probe
    ("focus the emberling", "focus", "emberling"), ("attack cave mite", "focus", "cave_mite"), ("regroup", "regroup", None),
    ("fall back", "regroup", None), ("defend", "defensive", None), ("hold", "defensive", None), ("charge", "aggressive", None),
    ("push", "aggressive", None), ("swap to kael", "swap", "kael"), ("switch nyra", "swap", "nyra"),
]


def evaluate(bridge: VoiceBridge, voices: tuple[str, ...] = ("en-us", "en-gb"), speeds: tuple[int, ...] = (140, 175)) -> dict[str, Any]:
    rows, hits, wrong = [], 0, 0
    for v in voices:
        for sp in speeds:
            for text, want, slot in COMMAND_SET:
                if slot and slot not in bridge.enemy_kinds + bridge.party:
                    continue
                r = bridge.intent(synthesize(text, v, sp))
                got_slot = r.get("target_kind") or r.get("to")
                ok = r["intent"] == want and (slot is None or got_slot == slot)
                hits += ok
                wrong += (not ok) and r["intent"] != "unknown"          # acted on a mishearing (worse than a re-ask)
                rows.append({"said": text, "voice": v, "speed": sp, "heard": r["transcript"], "conf": r["min_word_conf"],
                             "intent": r["intent"], "ok": ok})
    n = max(1, len(rows))
    return {"accuracy": round(hits / n, 4), "wrong_action_rate": round(wrong / n, 4), "n": len(rows), "rows": rows}


def fixture_set(root: Path | None = None) -> list[dict[str, Any]]:
    """The committed synthetic-speech fixtures (`tests/fixtures/voice/`, espeak-ng output) — used where espeak is absent."""
    d = (root or find_repo_root()) / "tests" / "fixtures" / "voice"
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return [{**it, "wav": (d / it["file"]).read_bytes()} for it in man["items"]]


def evaluate_fixtures(bridge: VoiceBridge, root: Path | None = None) -> dict[str, Any]:
    rows, hits, wrong = [], 0, 0
    for it in fixture_set(root or bridge.root):
        r = bridge.intent(it["wav"])
        got = r.get("target_kind") or r.get("to")
        ok = r["intent"] == it["intent"] and (it["slot"] is None or got == it["slot"])
        hits += ok
        wrong += (not ok) and r["intent"] != "unknown"
        rows.append({"file": it["file"], "said": it["said"], "heard": r["transcript"], "conf": r["min_word_conf"], "intent": r["intent"], "ok": ok})
    n = max(1, len(rows))
    return {"accuracy": round(hits / n, 4), "wrong_action_rate": round(wrong / n, 4), "n": len(rows), "rows": rows}
