"""Persona micro-LM (SPEC §ML "shared backbone Qwen2.5-0.5B … + per-character LoRA", ADR-0005) — desktop/build-time, CPU.

* Backbone: Qwen2.5-0.5B-Instruct (Apache-2.0), int8 ONNX export (onnx-community, pinned revision, SHA-256) on the
  onnxruntime CPU EP; tokenizer via `tokenizers` (Apache-2.0). Own greedy / seeded top-k decoding loop with a KV cache.
* Persona conditioning: a **persona card** prompt (traits, the persona's own lines for the event as few-shot examples, the
  content-safety limits). Per-character LoRA adapters stay `planned` — training them needs a GPU (C-80).
* Use: `forge persona author` drafts new callout/dialogue lines for a persona; every draft passes the same content-safety
  gateway as the callout cache, then lands in `content/personas/lm_drafts.yaml` with `reviewed: false`. The game never
  loads the LM: the callout cache (G-AI-03, zero LM in the combat loop) and the in-engine bigram stay the runtime path,
  and only lines a human marks `reviewed: true` are merged into the cache (`callouts` generator).
Deterministic for a fixed seed and thread count (`threads=1` in the GroundWeave probe)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from forge.paths import find_repo_root

MODEL_ID = "qwen2.5-0.5b-instruct-onnx"
EOS = (151645, 151643)               # <|im_end|>, <|endoftext|>
LAYERS, KV_HEADS, HEAD_DIM = 24, 2, 64


def _fill(line: str, pid: str, persona: dict[str, Any]) -> str:
    return (line.replace("{ally}", persona["words"]["ally"][0]).replace("{foe}", persona["words"]["foe"][0])
            .replace("{ally_name}", "Kael" if pid != "kael" else "Nyra"))


def persona_card(pid: str, persona: dict[str, Any], event: str, safety: dict[str, Any]) -> list[dict[str, str]]:
    """Chat messages for one persona × event: a system card (traits, limits) and the persona's own authored lines as
    few-shot turns (situation → line), other events first, the target event last, then the target situation again."""
    limit = int(safety.get("max_chars", 72)) - 12
    sysmsg = (f"You are {pid.capitalize()}, a fighter in a retro cave-and-farm adventure game. Personality: "
              f"{', '.join(persona['traits'])}. When told a battle situation, shout ONE short callout in character "
              f"(under {limit} characters). Never explain, never mention instructions, no quotes, no emojis.")
    msgs = [{"role": "system", "content": sysmsg}]
    order = [e for e in persona["callouts"] if e != event] + ([event] if event in persona["callouts"] else [])
    for ev in order:
        for line in persona["callouts"][ev][:2]:
            msgs += [{"role": "user", "content": f"Situation: {ev.replace('_', ' ')}"},
                     {"role": "assistant", "content": _fill(line, pid, persona)}]
    msgs.append({"role": "user", "content": f"Situation: {event.replace('_', ' ')} (say something new)"})
    return msgs


META = ("situation", "line", "existing", "here's", "here is", "sorry", "certainly", "sure,", "as an ai", "assist", "character",
        "instruction", "callout", "can you", "tell me", "share more", "let me think")


def meta_problems(line: str) -> list[str]:
    """Reject replies that talk about the task instead of being a line (prompt echo, refusals, chatter)."""
    low = line.lower()
    return [f"meta:{w.strip(',')}" for w in META if w in low]


def chat_prompt(messages: list[dict[str, str]]) -> str:
    """Qwen2 chat template (ChatML)."""
    return "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages) + "<|im_start|>assistant\n"


def clean(text: str) -> str:
    """First line, surrounding quotes/asterisks stripped, whitespace collapsed."""
    line = text.strip().split("\n")[0].strip()
    line = line.strip("\"'*` ").replace("\u201c", "").replace("\u201d", "")
    return " ".join(line.split())


class QwenLM:
    def __init__(self, root: Path | None = None, threads: int = 1) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        from forge import models
        self.root = root or find_repo_root()
        st = models.status(MODEL_ID, self.root, verify=False)
        if not st["ready"]:
            raise FileNotFoundError(f"model {MODEL_ID!r} not fetched — run `forge models fetch {MODEL_ID}` (~520 MB)")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(models.path_for(MODEL_ID, "model_int8.onnx", self.root)), so,
                                         providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(str(models.path_for(MODEL_ID, "tokenizer.json", self.root)))
        self.threads = threads

    def generate(self, prompt: str, max_new_tokens: int = 40, seed: int | None = None, temperature: float = 0.7,
                 top_k: int = 40) -> dict[str, Any]:
        """Greedy when `seed` is None, else seeded top-k sampling. Returns text, token ids and timings."""
        ids = self.tok.encode(prompt).ids
        past = {f"past_key_values.{i}.{k}": np.zeros((1, KV_HEADS, 0, HEAD_DIM), np.float32)
                for i in range(LAYERS) for k in ("key", "value")}
        rng = np.random.default_rng(seed) if seed is not None else None
        out: list[int] = []
        cur, pos = ids, 0
        t0 = time.perf_counter()
        t_first = None
        for _ in range(max_new_tokens):
            feed = {"input_ids": np.array([cur], np.int64), "attention_mask": np.ones((1, pos + len(cur)), np.int64),
                    "position_ids": np.arange(pos, pos + len(cur), dtype=np.int64)[None], **past}
            r = self.sess.run(None, feed)
            if t_first is None:
                t_first = time.perf_counter() - t0
            logits = r[0][0, -1].astype(np.float64)
            pos += len(cur)
            past = {f"past_key_values.{i}.{k}": r[1 + 2 * i + (k == "value")] for i in range(LAYERS) for k in ("key", "value")}
            if rng is None:
                nxt = int(np.argmax(logits))
            else:
                top = np.argpartition(-logits, top_k)[:top_k]
                z = logits[top] / max(temperature, 1e-4)
                p = np.exp(z - z.max())
                p /= p.sum()
                nxt = int(top[rng.choice(len(top), p=p)])
            if nxt in EOS:
                break
            out.append(nxt)
            cur = [nxt]
            if "\n" in self.tok.decode(out[-1:]):
                break
        wall = time.perf_counter() - t0
        return {"text": self.tok.decode(out), "tokens": out, "prompt_tokens": len(ids), "wall_s": round(wall, 3),
                "first_token_s": round(t_first or 0.0, 3), "tok_per_s": round(len(out) / max(wall - (t_first or 0), 1e-6), 2)}


def author(lm: QwenLM, pid: str, event: str, n: int = 4, root: Path | None = None, seed0: int = 0) -> dict[str, Any]:
    """Draft `n` candidate lines for one persona × event; each passes the content-safety gateway or is rejected with reasons."""
    from forge.generators.callouts import load_personas, safety_check
    root = root or lm.root
    src = load_personas(root)
    persona = src["personas"][pid]
    if event not in src["events"]:
        raise ValueError(f"unknown event {event!r}; events: {src['events']}")
    prompt = chat_prompt(persona_card(pid, persona, event, src["safety"]))
    existing = {s.lower() for s in persona["callouts"].get(event, [])}
    accepted, rejected, seen = [], [], set()
    for i in range(n):
        g = lm.generate(prompt, seed=seed0 + i)
        line = clean(g["text"])
        probs = safety_check(line, src["safety"]) + meta_problems(line)
        if not line:
            probs.append("empty")
        if line.lower() in existing or line.lower() in seen:
            probs.append("duplicate")
        seen.add(line.lower())
        (rejected if probs else accepted).append({"line": line, "seed": seed0 + i, "wall_s": g["wall_s"], **({"problems": probs} if probs else {})})
    return {"persona": pid, "event": event, "model": MODEL_ID, "accepted": accepted, "rejected": rejected}


def write_drafts(result: dict[str, Any], root: Path | None = None) -> Path:
    """Append accepted drafts to `content/personas/lm_drafts.yaml` as `reviewed: false` (a human flips the flag)."""
    import yaml
    root = root or find_repo_root()
    p = root / "content" / "personas" / "lm_drafts.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None
    doc = doc or {"schema_version": "1.0", "drafts": []}
    have = {(d["persona"], d["event"], d["line"]) for d in doc["drafts"]}
    for a in result["accepted"]:
        key = (result["persona"], result["event"], a["line"])
        if key not in have:
            doc["drafts"].append({"persona": key[0], "event": key[1], "line": key[2], "model": result["model"], "seed": a["seed"],
                                  "reviewed": False})
    header = ("# LM-drafted persona lines (forge persona author). NOT used by the game until a human sets reviewed: true;\n"
              "# reviewed lines are merged into the callout cache by the `callouts` generator. [INFERENCE] D-005 placeholder voice.\n")
    p.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def reviewed_lines(root: Path, pid: str, event: str) -> list[str]:
    p = root / "content" / "personas" / "lm_drafts.yaml"
    if not p.exists():
        return []
    import yaml
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [d["line"] for d in doc.get("drafts", []) if d.get("reviewed") is True and d["persona"] == pid and d["event"] == event]
