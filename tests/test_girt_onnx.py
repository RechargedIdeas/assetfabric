"""GIRT ONNX export: the F3 target policy as an ONNX graph on onnxruntime CPU matches the NumPy/GDScript maths."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("onnxruntime")
pytest.importorskip("onnx")

from forge import girt_onnx  # noqa: E402


def test_onnx_policy_parity(root: Path) -> None:
    r = girt_onnx.parity(root, n=1000)
    assert r["ok"], r
    assert r["max_abs_diff_vs_numpy"] <= 1e-12 and r["same_choice_all_sets"]
    assert r["provider"] == "CPUExecutionProvider"


def test_onnx_export_is_deterministic(root: Path) -> None:
    pol = girt_onnx.load_policy(root)
    assert girt_onnx.to_onnx(pol) == girt_onnx.to_onnx(pol)
