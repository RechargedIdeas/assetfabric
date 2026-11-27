"""GIRT ONNX export (F3 policy → ONNX) with onnxruntime parity — desktop tooling for the planned in-engine ONNX rung.

The F3 target-selection policy (`games/game-zero/data/generated/ai/policy_target.json`, mlp-7-H-1-tanh) is exported as a
float64 ONNX graph (MatMul → Add → Tanh → MatMul → Add → Squeeze) and run on the onnxruntime CPU execution provider.
`parity` compares it with the NumPy reference (`forge.generators.policy.forward`, float64 — the same maths as the GDScript
`_mlp_score`) and with the scores the GDScript probe recorded in the policy file.

What this does NOT do: run ONNX inside Godot. The `runtime.girt` ladder's `onnxruntime-gdextension@vulkan` rung needs a
GDExtension build + a GPU and stays `planned`; the game keeps the GDScript MLP (INFERENCES C-63)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

POLICY = Path("games") / "game-zero" / "data" / "generated" / "ai" / "policy_target.json"


def load_policy(root: Path) -> dict[str, Any]:
    return json.loads((root / POLICY).read_text(encoding="utf-8"))


def to_onnx(policy: dict[str, Any]) -> bytes:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    w = {k: np.asarray(v, dtype=np.float64) for k, v in policy["weights"].items()}
    nfeat, hidden = w["w1"].shape
    inits = [numpy_helper.from_array(w["w1"], "w1"), numpy_helper.from_array(w["b1"], "b1"),
             numpy_helper.from_array(w["w2"], "w2"), numpy_helper.from_array(w["b2"], "b2"),
             numpy_helper.from_array(np.array([1], dtype=np.int64), "ax1")]
    nodes = [helper.make_node("MatMul", ["x", "w1"], ["h0"]), helper.make_node("Add", ["h0", "b1"], ["h1"]),
             helper.make_node("Tanh", ["h1"], ["h"]), helper.make_node("MatMul", ["h", "w2"], ["o0"]),
             helper.make_node("Add", ["o0", "b2"], ["o1"]), helper.make_node("Squeeze", ["o1", "ax1"], ["scores"])]
    g = helper.make_graph(nodes, f"girt_{policy.get('model_id', 'policy')}",
                          [helper.make_tensor_value_info("x", TensorProto.DOUBLE, ["n", nfeat])],
                          [helper.make_tensor_value_info("scores", TensorProto.DOUBLE, ["n"])], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)], producer_name="assetfabric-girt")
    m.ir_version = 8
    m.metadata_props.append(onnx.StringStringEntryProto(key="arch", value=str(policy.get("arch"))))
    m.metadata_props.append(onnx.StringStringEntryProto(key="model_id", value=str(policy.get("model_id"))))
    onnx.checker.check_model(m)
    return m.SerializeToString()


def session(model: bytes, prefer: str = "cpu"):  # noqa: ANN201
    """CPU by default on purpose: the parity gate compares float32 outputs to the NumPy forward at 1e-5 and the policy is a
    few-KB MLP where GPU dispatch costs more than the math. `prefer="auto"` goes through `forge.onnx_ep` AMD-first
    selection (CPU fallback) for experiments; the combat tick never calls ONNX either way (GDScript forward)."""
    import onnxruntime as ort

    from forge import onnx_ep

    def options():  # noqa: ANN202
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.log_severity_level = 3
        return so
    return onnx_ep.session(model, options, ort=ort, prefer=prefer)


def parity(root: Path, n: int = 2000, seed: int = 3) -> dict[str, Any]:
    from forge.generators.policy import K, forward, sample_sets
    pol = load_policy(root)
    model = to_onnx(pol)
    sess = session(model)
    params = {k: np.asarray(v, dtype=np.float64) for k, v in pol["weights"].items()}
    x = sample_sets(np.random.default_rng(seed), n).reshape(-1, 7)             # n sets × K candidates
    onnx_s = sess.run(None, {"x": x})[0]
    ref = forward(params, x)[0]
    probe_x = np.asarray(pol["probe"]["inputs"], dtype=np.float64)
    probe_onnx = sess.run(None, {"x": probe_x})[0]
    choice_onnx = onnx_s.reshape(n, K).argmax(axis=1)
    choice_ref = ref.reshape(n, K).argmax(axis=1)
    max_abs = float(np.max(np.abs(onnx_s - ref)))
    probe_err = float(np.max(np.abs(probe_onnx - np.asarray(pol["probe"]["scores"]))))
    return {"ok": max_abs <= 1e-12 and probe_err <= 1e-6 and bool((choice_onnx == choice_ref).all()),
            "model_bytes": len(model), "arch": pol.get("arch"), "candidates": int(x.shape[0]), "max_abs_diff_vs_numpy": max_abs,
            "max_abs_diff_vs_gdscript_probe": probe_err, "same_choice_all_sets": bool((choice_onnx == choice_ref).all()),
            "provider": "CPUExecutionProvider", "dtype": "float64"}
