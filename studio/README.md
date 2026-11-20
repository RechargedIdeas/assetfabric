# AssetFabric Studio

Desktop authoring UI: **Python + PySide6** (optional extra `studio`, LGPL-3.0 wheel, dynamically imported).

```bash
uv pip install -e ".[studio]"
python -m assetfabric_studio [--state-dir <forge link serve state dir>]
```

Tabs (all text from `locales/en.json` `studio.*`):

| Tab | What it does |
|---|---|
| Status | `forge status` summary |
| Mirror | newest frame a paired phone pushed (MirrorWeave C9; still or decoded video) |
| Console | remote Studio input from a paired phone lands here; plain text is echoed; `/help /status /models /palettes /intent <text>` run from a closed **read-only** allow-list (INFERENCES C-81) |
| Swatches | SwatchStudio view of every PatternVault palette and colour-blind variant |
| Voice | VoiceBridge: transcribe a WAV with Vosk (closed intent grammar) → intent; `model_absent` until `forge models fetch vosk-small-en-us-0.15` |
| Persona | persona micro-LM drafts (Qwen2.5-0.5B ONNX) for review; Studio writes nothing (`forge persona author --write` queues drafts) |

Not built: character creator, sandbox panel, embedded shell, MCP host, ACP agent (TODO.md). Tests run it offscreen
(`QT_QPA_PLATFORM=offscreen`): `tests/test_c9_real.py`, `tests/test_b4_voice_lm.py`.
