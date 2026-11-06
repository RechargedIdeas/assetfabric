"""Target-selection policy (F3) — tiny MLP scorer trained on CPU with NumPy.

Per-candidate features (shared by Python + GDScript, see FEATURES):
  dist/128, hp_ratio, hp/100, tier/3, atk/10, in_range, threatens_low_ally
A shared scorer (7→H→1, tanh) ranks up to K candidates; softmax over them.
Trained by behaviour cloning of a focus-fire teacher (`teacher_utility`).
`[INFERENCE]` BC-from-teacher stands in for the chat's PPO self-play loop until the
RL harness lands; weights are plain JSON (ONNX-exportable later via GIRT).
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np

from forge.gates import GateResult, budget_gate
from forge.generators import Artifact, GeneratorOutput, register

FEATURES = ["dist", "hp_ratio", "hp", "tier", "atk", "in_range", "threatens_low_ally"]
K = 4


def teacher_utility(f: np.ndarray) -> np.ndarray:
    """Focus fire: prefer in-range, wounded, dangerous targets that threaten a weak ally."""
    dist, hp_ratio, hp, tier, atk, in_range, threat = (f[..., i] for i in range(7))
    return 2.0 * in_range + 1.6 * (1 - hp_ratio) - 0.6 * hp + 0.9 * atk + 1.2 * threat - 1.4 * dist + 0.2 * tier


def sample_sets(rng: np.random.Generator, n: int) -> np.ndarray:
    x = np.zeros((n, K, 7))
    x[..., 0] = rng.uniform(0, 1.2, (n, K))
    x[..., 1] = rng.uniform(0.05, 1, (n, K))
    x[..., 2] = rng.uniform(0.1, 0.8, (n, K))
    x[..., 3] = rng.integers(1, 4, (n, K)) / 3
    x[..., 4] = rng.uniform(0.2, 0.8, (n, K))
    x[..., 5] = (x[..., 0] < 0.25).astype(float)
    x[..., 6] = (rng.uniform(0, 1, (n, K)) < 0.2).astype(float)
    return x


def forward(params: dict[str, np.ndarray], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h = np.tanh(x @ params["w1"] + params["b1"])
    return (h @ params["w2"] + params["b2"])[..., 0], h


def train(seed: int = 0, n: int = 4000, hidden: int = 12, epochs: int = 300, lr: float = 0.05) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    rng = np.random.default_rng(seed)
    x = sample_sets(rng, n)
    y = teacher_utility(x).argmax(axis=1)
    split = int(n * 0.8)
    params = {"w1": rng.normal(0, 0.5, (7, hidden)), "b1": np.zeros(hidden), "w2": rng.normal(0, 0.5, (hidden, 1)), "b2": np.zeros(1)}
    xt, yt = x[:split], y[:split]
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v_ = {k: np.zeros_like(v) for k, v in params.items()}
    for ep in range(1, epochs + 1):
        logits, h = forward(params, xt)
        logits = logits - logits.max(axis=1, keepdims=True)
        p = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
        g = p.copy()
        g[np.arange(len(yt)), yt] -= 1
        g /= len(yt)                                   # dL/dlogit  (N,K)
        grads = {
            "w2": np.einsum("nkh,nk->h", h, g)[:, None],
            "b2": np.array([g.sum()]),
        }
        dh = g[..., None] * params["w2"][:, 0] * (1 - h ** 2)   # (N,K,H)
        grads["w1"] = np.einsum("nki,nkh->ih", xt, dh)
        grads["b1"] = dh.sum(axis=(0, 1))
        for k in params:  # Adam
            m[k] = 0.9 * m[k] + 0.1 * grads[k]
            v_[k] = 0.999 * v_[k] + 0.001 * grads[k] ** 2
            params[k] -= lr * (m[k] / (1 - 0.9 ** ep)) / (np.sqrt(v_[k] / (1 - 0.999 ** ep)) + 1e-8)
    def acc(xs: np.ndarray, ys: np.ndarray) -> float:
        return float((forward(params, xs)[0].argmax(axis=1) == ys).mean())
    return params, {"train_acc": acc(xt, yt), "holdout_acc": acc(x[split:], y[split:])}


@register("policy")
def generate(brief: dict[str, Any], ctx: Any) -> GeneratorOutput:
    t0 = time.perf_counter()
    params, metrics = train(int(brief.get("seed", 0)), int(brief.get("samples", 4000)), int(brief.get("hidden", 12)), int(brief.get("epochs", 300)))
    probe = np.array([[0.1, 0.3, 0.2, 1 / 3, 0.4, 1, 0], [0.9, 1.0, 0.6, 2 / 3, 0.5, 0, 0], [0.2, 0.8, 0.3, 1 / 3, 0.3, 1, 1]])
    weights = {k: np.round(v, 6).tolist() for k, v in params.items()}
    rounded = {k: np.array(v) for k, v in weights.items()}
    data = {"schema_version": "1.0", "model_id": brief.get("model_id", "P-TargetSelect"), "version": 1, "features": FEATURES, "k": K,
            "arch": "mlp-7-%d-1-tanh" % params["w1"].shape[1], "weights": weights, "metrics": {k: round(v, 4) for k, v in metrics.items()},
            "probe": {"inputs": probe.tolist(), "scores": np.round(forward(rounded, probe)[0], 6).tolist()}}
    blob = (json.dumps(data, indent=1, sort_keys=True) + "\n").encode()
    elapsed = (time.perf_counter() - t0) * 1000
    gates = [GateResult("holdout_accuracy", metrics["holdout_acc"] >= float(brief.get("min_holdout_acc", 0.85)), metrics),
             budget_gate(elapsed, len(blob), float(brief.get("budget_ms", 20000)), 64 * 1024)]
    return GeneratorOutput([Artifact(f"{brief['id']}.json", blob, "application/json")], gates,
                           {"kind": "policy", "model_id": data["model_id"], "model_version": "bc-1", "metrics": data["metrics"]})
