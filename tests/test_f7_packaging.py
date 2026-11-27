"""F7 packaging units (no export templates needed): presets, ShuttleLine, BoltPack audit, PWAPipeline helpers, readers."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from forge.accept_f7 import net_scan, presets_report, targets_report
from forge.boltpack import audit
from forge.packaging import TARGETS, pe_info, read_pck
from forge.pwa import BUDGET_BYTES, HOOK_MARK, budget, patch_html, patch_sw, sw_report
from forge.shuttleline import ADAPTERS, SCHEMA, check_sources, contract


def test_presets_cover_every_target(root: Path) -> None:
    rep = presets_report(root)
    assert rep["ok"], rep
    assert set(rep["presets"]) == {t.preset for t in TARGETS.values()}


def test_manifest_declares_targets(root: Path) -> None:
    assert targets_report(root)["ok"]


def test_game_scripts_use_no_network_api(root: Path) -> None:
    rep = net_scan(root)
    assert rep["ok"], rep["network_api_uses"]


def test_shuttleline_contract_matches_sources(root: Path) -> None:
    c = contract(root)
    assert c["schema"] == SCHEMA and c["counts"]["files"] > 0
    assert ADAPTERS["godot"]["status"] == "real" and ADAPTERS["unity"]["status"] == "not built"
    rep = check_sources(root)
    assert rep["ok"], rep


def test_bolt_audit_rejects_copyleft_and_unknown() -> None:
    def bom(*lics: str) -> dict:
        return {"components": [{"name": f"c{i}", "licenses": [{"expression": x}]} for i, x in enumerate(lics)]}
    assert audit(bom("MIT", "Expat and Zlib", "public-domain or Unlicense"))["ok"]
    assert not audit(bom("MIT", "GPL-3.0-only"))["ok"]
    assert not audit(bom("WTFPL-ish"))["ok"]
    assert not audit({"components": [{"name": "x", "licenses": []}]})["ok"]


def _fake_web(d: Path, wasm_bytes: int = 1000) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text('<script>\nconst GODOT_CONFIG = {"args":[]};\nconst x = 1;\n</script>', encoding="utf-8")
    files = ["index.html", "index.js", "index.offline.html", "index.worker.js", "index.audio.worklet.js"]
    (d / "index.service.worker.js").write_text(
        f"const CACHED_FILES = {json.dumps(files)};\nconst CACHABLE_FILES = [\"index.wasm\",\"index.pck\"];\n"
        "const ENSURE_CROSSORIGIN_ISOLATION_HEADERS = true;\n", encoding="utf-8")
    (d / "index.manifest.json").write_text(json.dumps({"name": "G", "start_url": "./index.html", "display": "standalone",
                                                        "icons": [{"src": "a.png"}]}), encoding="utf-8")
    (d / "index.wasm").write_bytes(b"\0" * wasm_bytes)


def test_pwa_hook_budget_and_sw(tmp_path: Path) -> None:
    _fake_web(tmp_path)
    assert patch_html(tmp_path) and patch_html(tmp_path)          # idempotent
    assert (tmp_path / "index.html").read_text(encoding="utf-8").count(HOOK_MARK) == 1
    b = budget(tmp_path)
    assert b["ok"] and b["total_gzip9"] < b["total_bytes"] and b["budget_bytes"] == BUDGET_BYTES
    assert sw_report(tmp_path)["ok"]
    (tmp_path / "index.service.worker.js").write_text('const CACHED_FILES = ["index.html"];\nconst CACHABLE_FILES = [];', encoding="utf-8")
    assert not sw_report(tmp_path)["ok"]


def test_patch_sw_drops_unexported_install_files(tmp_path: Path) -> None:
    """Godot 4.3 web_nothreads lists index.worker.js in CACHED_FILES without exporting it (ADR-0019)."""
    _fake_web(tmp_path)
    for f in ("index.js", "index.offline.html", "index.audio.worklet.js"):
        (tmp_path / f).write_text("x", encoding="utf-8")
    assert patch_sw(tmp_path) == ["index.worker.js"]
    sw = (tmp_path / "index.service.worker.js").read_text(encoding="utf-8")
    assert "index.worker.js" not in sw and '"index.audio.worklet.js"' in sw
    assert patch_sw(tmp_path) == []                                   # idempotent


def test_pck_reader_roundtrip(tmp_path: Path) -> None:
    files = {"res://a.json": b'{"x":1}', "res://dir/b.png": b"\x89PNG..."}
    header = b"GDPC" + struct.pack("<IIIIIQ", 2, 4, 3, 0, 0, 0) + b"\0" * 64
    entries, blob = b"", b""
    table_len = 4 + sum(4 + len(n[6:].encode()) + 16 + 16 + 4 for n in files)
    base = len(header) + table_len
    header = b"GDPC" + struct.pack("<IIIIIQ", 2, 4, 3, 0, 0, base) + b"\0" * 64
    for n, data in files.items():
        p = n[6:].encode()
        entries += struct.pack("<I", len(p)) + p + struct.pack("<QQ", len(blob), len(data)) + b"\0" * 16 + struct.pack("<I", 0)
        blob += data
    (tmp_path / "t.pck").write_bytes(header + struct.pack("<I", len(files)) + entries + blob)
    assert read_pck(tmp_path / "t.pck") == files


def test_pe_info_detects_x86_64(tmp_path: Path) -> None:
    b = bytearray(1024)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", b, 0x84, 0x8664, 3)
    struct.pack_into("<H", b, 0x80 + 24, 0x20B)
    struct.pack_into("<H", b, 0x80 + 24 + 68, 2)
    (tmp_path / "x.exe").write_bytes(bytes(b))
    info = pe_info(tmp_path / "x.exe")
    assert info["pe"] and info["x86_64"] and info["pe32_plus"] and info["subsystem"] == "windows_gui"
