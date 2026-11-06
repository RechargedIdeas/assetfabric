"""F3: GIRT models (policy, callouts, persona LM) — Python side of the parity contracts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from forge.generators.callouts import load_personas, safety_check, sample, train_bigram
from forge.generators.policy import FEATURES, K, forward, teacher_utility, train
from forge.pipeline import Context, load_briefs, run_brief

AI = Path("games/game-zero/data/generated/ai")


def _brief(root: Path, bid: str) -> dict:
    return {b["id"]: b for b in load_briefs(root)}[bid]


def test_policy_trains_above_gate_and_is_deterministic(root: Path) -> None:
    p1, m1 = train(seed=4, n=1500, epochs=150)
    p2, m2 = train(seed=4, n=1500, epochs=150)
    assert m1 == m2
    assert all(np.array_equal(p1[k], p2[k]) for k in p1)
    assert m1["holdout_acc"] >= 0.85


def test_exported_policy_matches_probe_and_feature_contract(root: Path) -> None:
    pol = json.loads((root / AI / "policy_target.json").read_text())
    assert pol["features"] == FEATURES and pol["k"] == K
    assert pol["metrics"]["holdout_acc"] >= 0.85
    w = {k: np.array(v) for k, v in pol["weights"].items()}
    got = forward(w, np.array(pol["probe"]["inputs"]))[0]
    assert np.allclose(got, pol["probe"]["scores"], atol=1e-5)


def test_teacher_prefers_low_hp_in_range_targets() -> None:
    near_low = np.array([[0.1, 0.2, 0.1, 1 / 3, 0.3, 1, 0]])
    far_full = np.array([[0.9, 1.0, 0.6, 1 / 3, 0.3, 0, 0]])
    assert teacher_utility(near_low)[0] > teacher_utility(far_full)[0]


def test_callout_cache_is_safe_and_covers_every_event(root: Path) -> None:
    out = run_brief(_brief(root, "callouts"), Context.create(root), export=False)
    assert out.ok, [g for g in out.gates if not g.ok]
    data = json.loads(out.artifacts[0].data)
    src = load_personas(root)
    for pid, events in data["callouts"].items():
        for ev in src["events"]:
            assert events[ev], f"{pid} has no {ev} line"
            for line in events[ev]:
                assert not safety_check(line.replace("%ALLY%", "Ally"), src["safety"]), line


def test_safety_gateway_rejects_bad_lines(root: Path) -> None:
    safety = load_personas(root)["safety"]
    assert safety_check("x" * 500, safety) == ["too_long"]
    assert "unresolved_slot" in safety_check("hello {foe}", safety)
    if safety.get("blocklist"):
        assert safety_check(f"you {safety['blocklist'][0]}", safety)


def test_bigram_sampler_deterministic_and_guarded() -> None:
    table = train_bigram(["the cave is dark", "the cave is cold and the cave is dark"])
    a = [sample(table, s) for s in range(1, 20)]
    assert a == [sample(table, s) for s in range(1, 20)]
    assert all(len(x.split()) <= 14 for x in a)
    for x in a:  # repetition guard: no repeated bigram within one utterance
        toks = ["<s>", *x.split()]
        pairs = list(zip(toks, toks[1:]))
        assert len(pairs) == len(set(pairs))
    assert sample(table, 3, start="cave").startswith("cave")


def test_persona_lm_probes_match_sampler(root: Path) -> None:
    lm = json.loads((root / AI / "persona_lm.json").read_text())
    for pid, m in lm["models"].items():
        assert lm["probes"][pid] == [sample(m["bigram"], s) for s in range(1, 6)]
