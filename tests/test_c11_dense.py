"""C11 dense depth (DepthAnything V2 Small, onnxruntime CPU). Heavy: needs `forge models fetch depth-anything-v2-small`
(~99 MB, SHA-256 pinned) — skipped when the weights are absent (CI), run locally and by `forge accept C11`."""
from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest

from forge import depth, models
from forge import groundweave as gw

pytest.importorskip("onnxruntime")
needs_model = pytest.mark.skipif(not models.status(depth.MODEL_ID, verify=False)["ready"],
                                 reason="DepthAnything V2 Small weights not fetched (heavy; local/full only)")


def test_registry_entry_is_commercially_licensed_and_pinned(root: Path) -> None:
    spec = models.registry(root)[depth.MODEL_ID]
    assert spec["licence"] == "Apache-2.0" and "CC-BY-NC" in spec["forbidden_siblings"]
    f = spec["files"][0]
    assert len(f["sha256"]) == 64 and "/resolve/" in f["url"] and "/main/" not in f["url"]   # pinned revision


@needs_model
def test_dense_depth_on_analytic_scene() -> None:
    sc = depth.render_scene(256, 192)
    rel = depth.DepthAnythingV2(threads=1).estimate_rgb(sc["rgb"])
    assert rel.shape == (192, 256) and rel.dtype == np.float32
    m = depth.depth_metrics(depth.align_inverse_depth(rel, gw._scene_anchors(sc["depth_m"]))["depth_m"], sc["depth_m"])
    assert m["abs_rel"] < 0.10 and m["delta1"] > 0.90 and m["spearman"] > 0.90
    assert np.array_equal(rel, depth.DepthAnythingV2(threads=1).estimate_rgb(sc["rgb"]))   # 1 thread → bit-reproducible


@needs_model
def test_offload_payload_round_trip() -> None:
    import io

    from PIL import Image
    sc = depth.render_scene(128, 96)
    buf = io.BytesIO()
    Image.fromarray(sc["rgb"]).save(buf, "PNG")
    an = gw._scene_anchors(sc["depth_m"], n=4)
    v = depth.offload_estimate({"data_b64": base64.b64encode(buf.getvalue()).decode(),
                                "anchors": [{"x": a.x, "y": a.y, "depth_m": a.depth_m} for a in an]})
    q = np.frombuffer(base64.b64decode(v["rel_u16_b64"]), dtype="<u2").reshape(96, 128)
    assert q.max() == 65535 and q.min() == 0
    assert abs(v["metric"]["median_m"] - float(np.nanmedian(sc["depth_m"]))) / float(np.nanmedian(sc["depth_m"])) < 0.1


def test_model_registry_licence_audit(root: Path) -> None:
    a = models.audit(root)
    assert a["ok"], a["problems"]
