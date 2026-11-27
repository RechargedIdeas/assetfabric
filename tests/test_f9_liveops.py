"""F9 LiveOps readiness — forge side units: flag manifest, bundle rules, signatures, rollback, save classify, scrubber,
diagnostics schema, readiness checklist, CLI, and source guards on the game side (no network, consent never remote)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge import liveops as L
from forge import save as S
from forge.live import GAME_DATA_REL

pytest.importorskip("cryptography")


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, str]]:
    d = tmp_path_factory.mktemp("keys")
    return {"a": L.keygen(d, "a"), "b": L.keygen(d, "b")}


def _gd(root: Path) -> dict:
    return json.loads((root / GAME_DATA_REL).read_text(encoding="utf-8"))


def test_flag_manifest_safe_defaults_and_locale(root: Path) -> None:
    raw = L.load_flags(root)
    assert L.validate_flags(raw, L.locale_en(root)) == []
    d = L.defaults(root)
    for n, f in raw["flags"].items():
        assert d[n] is (f["kind"] == "kill_switch"), n          # kill switches on, consent off
    assert "diagnostics" in d and d["diagnostics"] is False


def test_flag_manifest_rejects_unsafe_defaults() -> None:
    bad = {"bundle_format": L.PAYLOAD_FORMAT, "bundle_schema": L.SCHEMA,
           "flags": {"x": {"kind": "kill_switch", "default": False, "label_key": "liveops.flag.x", "note_key": "liveops.flag.x.n"},
                     "y": {"kind": "consent", "default": True, "label_key": "Share!", "note_key": "liveops.flag.y.n"}}}
    errs = L.validate_flags(bad, {})
    assert any("x: a kill switch defaults to on" in e for e in errs)
    assert any("y: a consent flag defaults to off" in e for e in errs)
    assert any("label_key must be a locale key" in e for e in errs)


def test_generated_manifest_in_sync_and_knobs_exclude_sim(root: Path) -> None:
    gm = json.loads((root / L.MANIFEST_REL).read_text(encoding="utf-8"))
    assert gm == L.game_manifest(root)
    assert gm["knobs"] and not any(k.startswith("sim.") for k in gm["knobs"])


def test_sign_verify_roundtrip_and_refusals(root: Path, keys) -> None:
    pa, pb = Path(keys["a"]["private"]), Path(keys["b"]["private"])
    pub = Path(keys["a"]["public"])
    good = L.sign(L.make_payload(3, flags={"adaptive_music": False}, patches=[{"path": "enemies.emberling.stats.hp", "value": 30}]), pa)
    assert L.verify(good, pub, root)["ok"]
    assert L.verify(good, pub, root, min_serial=3)["errors"][0].startswith("serial 3 is not newer")
    assert L.verify(dict(good, payload=good["payload"].replace("30", "31")), pub, root)["errors"] == ["signature invalid"]
    assert "does not match the pinned key" in L.verify(L.sign(json.loads(good["payload"]), pb), pub, root)["errors"][0]
    assert L.verify(dict(good, sig="!!notbase64"), pub, root)["errors"] == ["signature invalid"]
    assert not L.verify({"format": "zip"}, pub, root)["ok"]


@pytest.mark.parametrize("payload,needle", [
    (dict(flags={"diagnostics": True}), "consent is the player's decision"),
    (dict(flags={"double_xp": True}), "unknown"),
    (dict(flags={"retro_styles": "off"}), "must be a bool"),
    (dict(patches=[{"path": "sim.leash", "value": 64}]), "dev-only"),
    (dict(patches=[{"path": "enemies.emberling.stats.hp", "value": 99999}]), "outside"),
    (dict(patches=[{"path": "enemies.emberling.stats.hp", "value": True}]), "finite number"),
    (dict(patches=[{"path": "enemies.yeti.stats.hp", "value": 10}]), "no such numeric field"),
    (dict(patches=[{"path": "areas.field.biome", "value": 1}]), "not a balance knob"),
    (dict(build_min="1.0.0"), "build_min"),
    (dict(build_max="0.8.9"), "build_max"),
])
def test_payload_rules(root: Path, payload: dict, needle: str) -> None:
    p = L.make_payload(1, **payload)
    errs = L.validate_payload(p, L.game_manifest(root), _gd(root), "0.9.0+f9")
    assert any(needle in e for e in errs), errs


def test_payload_refuses_content_keys(root: Path) -> None:
    p = {**L.make_payload(1), "content": {"areas": {}}}
    assert any("unknown keys" in e for e in L.validate_payload(p, L.game_manifest(root), _gd(root), "0.9.0"))


def test_version_tuple() -> None:
    assert L.version_tuple("0.9.0+f9") == (0, 9, 0)
    assert L.version_tuple("1.2") == (1, 2, 0)
    assert L.version_tuple("0.10.1-rc1") == (0, 10, 1)


def test_key_id_matches_pem_body(keys) -> None:
    pem = Path(keys["a"]["public"]).read_text()
    assert L.key_id(pem) == keys["a"]["key_id"] and len(keys["a"]["key_id"]) == 16
    assert oct(Path(keys["a"]["private"]).stat().st_mode & 0o777) == "0o600"


def test_rollback_is_roll_forward(root: Path, keys) -> None:
    pa, pub = Path(keys["a"]["private"]), Path(keys["a"]["public"])
    b5 = L.sign(L.make_payload(5, patches=[{"path": "abilities.claw.power", "value": 3}]), pa)
    rb = L.rollback_bundle(b5, 9, pa)
    p = json.loads(rb["payload"])
    assert p["serial"] == 9 and p["patches"] == json.loads(b5["payload"])["patches"]
    assert L.verify(rb, pub, root, min_serial=8)["ok"]
    d = json.loads(L.rollback_bundle(None, 10, pa)["payload"])
    assert d["flags"] == {} and d["patches"] == []


def test_install_and_device_status(tmp_path: Path, keys) -> None:
    b = L.sign(L.make_payload(1), Path(keys["a"]["private"]))
    L.install(b, tmp_path)
    st = L.device_status(tmp_path)
    assert st["inbox"] is True and st["active"] is None and st["rejected"] == []


def test_save_classify_newer_is_never_overwritten() -> None:
    cur = S.new_save("kael", {"kael": 1}, ["ember_fox"])
    assert S.classify(cur) == "current"
    assert S.classify(S.FIXTURES["v1"]) == "migratable"
    newer = {**cur, "version": S.CURRENT + 1}
    assert S.classify(newer) == "newer" and not S.safe_to_overwrite(newer)
    assert S.classify({**cur, "checksum": "0"}) == "invalid"
    assert S.classify("x") == "invalid"


def test_scrub_removes_pii() -> None:
    raw = ("/home/bob/.local/share/godot x C:\\Users\\bob\\AppData bob@example.org 10.0.0.7 "
           "aa:bb:cc:dd:ee:ff " + "a" * 40 + " host bob-pc")
    out, counts = L.scrub(raw, ["bob", "bob-pc"])
    for leak in ("bob", "example.org", "10.0.0.7", "aa:bb:cc", "a" * 40):
        assert leak not in out, (leak, out)
    assert counts["mac"] == 1 and counts["email"] == 1


def test_diag_export_needs_consent_and_validates(tmp_path: Path, root: Path) -> None:
    f = tmp_path / "log.txt"
    f.write_text("user carol at /home/carol/x\n")
    with pytest.raises(PermissionError):
        L.diag_export([f], tmp_path / "d.json", consent=False)
    b = L.diag_export([f], tmp_path / "d.json", consent=True, extra_words=["carol"], created="2026-11-27T00:00:00Z")
    assert L.validate_diag(b, root) == [] and b["uploaded"] is False and "carol" not in json.dumps(b)


def test_readiness_has_no_failures(root: Path) -> None:
    r = L.readiness(root)
    assert r["ok"], r["failed"]
    assert {"production_public_key", "live_service"} <= set(r["user_gated"])


def test_game_side_source_guards(root: Path) -> None:
    src = (root / "games/game-zero/autoload/liveops.gd").read_text(encoding="utf-8")
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    assert not re.search(r"HTTPRequest|HTTPClient|StreamPeerTCP|PacketPeerUDP|WebSocketPeer|ENetMultiplayerPeer", code)
    assert "OS.is_debug_build() and str(Fabric.arg(\"liveops-pubkey\"" in src   # test keys only in debug builds
    assert '"consent"' in src and "a bundle cannot set it" in src
    order = re.findall(r'^(\w+)="\*res://autoload/', (root / "games/game-zero/project.godot").read_text(), re.M)
    assert order.index("Live") < order.index("LiveOps") < order.index("Retro")


def test_cli_bundle_verify_rollback(tmp_path: Path, keys) -> None:
    from forge.cli import main

    r = CliRunner()
    out = tmp_path / "b.json"
    res = r.invoke(main, ["liveops", "bundle", "--serial", "2", "--flag", "adaptive_music=off", "--set",
                          "enemies.emberling.stats.hp=26", "--key", keys["a"]["private"], "--out", str(out)])
    assert res.exit_code == 0, res.output
    res = r.invoke(main, ["liveops", "verify", str(out), "--pub", keys["a"]["public"]])
    assert res.exit_code == 0 and json.loads(res.output)["ok"]
    res = r.invoke(main, ["liveops", "bundle", "--serial", "3", "--flag", "diagnostics=on", "--key", keys["a"]["private"],
                          "--out", str(tmp_path / "bad.json")])
    assert res.exit_code == 1 and not (tmp_path / "bad.json").exists()
    res = r.invoke(main, ["liveops", "rollback", "--to", "defaults", "--serial", "4", "--key", keys["a"]["private"],
                          "--out", str(tmp_path / "rb.json")])
    assert res.exit_code == 0
    res = r.invoke(main, ["liveops", "diag-export", str(out), "--out", str(tmp_path / "d.json")])
    assert res.exit_code == 1
