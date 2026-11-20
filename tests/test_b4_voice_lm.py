"""Stub batch 4 (0.7.8): VoiceBridge (Vosk STT → closed intent grammar) and the persona micro-LM (Qwen2.5-0.5B ONNX, CPU).
Model-backed tests skip without the fetched weights (CI); `forge groundweave verify` runs them where the weights exist."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from forge import microlm, models, voice


def _ready(mid: str, root: Path) -> bool:
    return models.status(mid, root, verify=False)["ready"]


def test_verbs_come_from_the_gdscript_grammar_and_parse_mirrors_it(root: Path) -> None:
    v = voice.verbs(root)
    assert v["focus"] == ["focus", "target", "attack", "hit"] and v["swap"] == ["swap", "switch"]
    ek, pt = voice.roster(root)
    assert voice.parse("focus the cave mite", ek, pt, root) == {"intent": "focus", "text": "focus the cave mite", "target_kind": "cave_mite"}
    assert voice.parse("attack", ek, pt, root)["intent"] == "unknown"              # focus needs a target (as in GDScript)
    assert voice.parse("swap to nyra", ek, pt, root)["to"] == "nyra"
    assert voice.parse("Fall back now", ek, pt, root)["intent"] == "regroup"
    assert voice.parse("dance", ek, pt, root)["intent"] == "unknown"


def test_grammar_phrases_cover_every_intent(root: Path) -> None:
    ek, pt = voice.roster(root)
    ph = voice.grammar_phrases(ek, pt, root)
    for want in ("focus the emberling", "attack cave mite", "regroup", "fall back", "hold", "charge", "swap to kael", "switch"):
        assert want in ph
    assert all(voice.parse(p, ek, pt, root)["intent"] != "unknown" for p in ph if p not in ("swap", "switch"))


def test_model_registry_is_pinned_and_commercially_licensed(root: Path) -> None:
    a = models.audit(root)
    assert a["ok"], a["problems"]
    reg = models.registry(root)
    assert reg["vosk-small-en-us-0.15"]["licence"] == reg["qwen2.5-0.5b-instruct-onnx"]["licence"] == "Apache-2.0"


@pytest.mark.skipif(importlib.util.find_spec("vosk") is None, reason="vosk not installed")
def test_voicebridge_on_synthetic_speech_fixtures(root: Path) -> None:
    if not _ready(voice.MODEL_ID, root):
        pytest.skip("Vosk model not fetched (forge models fetch vosk-small-en-us-0.15)")
    b = voice.VoiceBridge(root)
    assert b.aliases == {"em berling": "emberling"} and not b.oov
    r = voice.evaluate_fixtures(b, root)
    assert r["n"] == 20 and r["accuracy"] >= 0.85 and r["wrong_action_rate"] <= 0.08, r
    swap = b.intent((root / "tests/fixtures/voice/08_en-us.wav").read_bytes())
    assert (swap["intent"], swap["to"]) == ("swap", "kael")


def test_persona_card_and_filters_without_model(root: Path) -> None:
    from forge.generators.callouts import load_personas
    src = load_personas(root)
    msgs = microlm.persona_card("kael", src["personas"]["kael"], "low_hp", src["safety"])
    assert msgs[0]["role"] == "system" and "steady" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "Situation: low hp (say something new)"}
    assert msgs[-2]["role"] == "assistant" and "{" not in "".join(m["content"] for m in msgs)
    p = microlm.chat_prompt(msgs)
    assert p.startswith("<|im_start|>system\n") and p.endswith("<|im_start|>assistant\n")
    assert microlm.clean('"Hold the line!"\nmore') == "Hold the line!"
    assert microlm.meta_problems("Sure, here's a different line:") and not microlm.meta_problems("Shields up!")


def test_reviewed_drafts_only(tmp_path: Path) -> None:
    (tmp_path / "content" / "personas").mkdir(parents=True)
    r = {"persona": "kael", "event": "kill", "model": microlm.MODEL_ID, "accepted": [{"line": "Down you go.", "seed": 0}, {"line": "Next.", "seed": 1}]}
    p = microlm.write_drafts(r, tmp_path)
    microlm.write_drafts(r, tmp_path)                                   # idempotent
    assert p.read_text().count("Down you go.") == 1
    assert microlm.reviewed_lines(tmp_path, "kael", "kill") == []       # nothing reaches the game unreviewed
    p.write_text(p.read_text().replace("reviewed: false", "reviewed: true", 1))
    assert microlm.reviewed_lines(tmp_path, "kael", "kill") == ["Down you go."]


@pytest.mark.skipif(importlib.util.find_spec("onnxruntime") is None or importlib.util.find_spec("tokenizers") is None,
                    reason="onnxruntime/tokenizers not installed")
def test_micro_lm_drafts_pass_the_gateway_and_are_deterministic(root: Path) -> None:
    if not _ready(microlm.MODEL_ID, root):
        pytest.skip("Qwen2.5-0.5B ONNX not fetched (forge models fetch qwen2.5-0.5b-instruct-onnx)")
    lm = microlm.QwenLM(root, threads=1)
    a = microlm.author(lm, "kael", "low_hp", n=3, root=root)
    b = microlm.author(lm, "kael", "low_hp", n=3, root=root)
    assert [x["line"] for x in a["accepted"]] == [x["line"] for x in b["accepted"]]
    assert a["accepted"], a
    from forge.generators.callouts import load_personas, safety_check
    safety = load_personas(root)["safety"]
    assert all(not safety_check(x["line"], safety) and not microlm.meta_problems(x["line"]) for x in a["accepted"])


def test_studio_swatches_slash_commands_and_voice_tab(root: Path, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    import json
    import subprocess
    import sys
    code = r'''
import os, sys, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "studio")
from pathlib import Path
from PySide6.QtWidgets import QApplication
from assetfabric_studio.app import StudioWindow
app = QApplication([])
w = StudioWindow(Path(sys.argv[1])); w.show(); app.processEvents()
tabs = [w.tabs.tabText(i) for i in range(w.tabs.count())]
cell = w.swatch_cells["hero_teal"][2].styleSheet()
out = {"tabs": tabs, "hero_cells": len(w.swatch_cells["hero_teal"]), "cell": cell,
       "variants": sorted(k for k in w.swatch_cells if "·" in k),
       "intent": json.loads(w.slash("/intent focus the cave mite")), "deny": w.slash("/rm -rf /"),
       "palettes": w.slash("/palettes"), "models": json.loads(w.slash("/models"))}
w.console.setText("/status"); w._submit()
out["log"] = w.log.toPlainText().splitlines()[0]
wav = Path("tests/fixtures/voice/08_en-us.wav")
out["voice"] = w.voice_intent(wav)
print(json.dumps(out))
'''
    p = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-800:]
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["tabs"] == ["Status", "Mirror", "Console", "Swatches", "Voice", "Persona"]
    assert out["hero_cells"] == 6 and "#3fa7a0" in out["cell"]
    assert out["variants"] == ["deuteranopia · enemy_ember", "protanopia · enemy_ember"]
    assert out["intent"] == {"intent": "focus", "target_kind": "cave_mite", "text": "focus the cave mite"}
    assert out["deny"].startswith("Unknown or not allowed: /rm") and "hero_teal" in out["palettes"]
    assert set(out["models"]) >= {"vosk-small-en-us-0.15", "qwen2.5-0.5b-instruct-onnx"} and out["log"] == "/status"
    v = out["voice"]
    assert v.get("status") == "model_absent" or (v["intent"], v["to"]) == ("swap", "kael")
