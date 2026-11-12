"""F7 acceptance: "Desktop + Android + Web launch candidates" (SPEC §13 F7, GAME_SPEC §6.2/§6.3).

Full mode (``forge accept F7``; needs Godot 4.3 + export templates (auto-fetched) + JDK 17 + Android SDK +
Chrome) — builds every target via ``forge build --target all`` and proves:

1. **Exports** — desktop-linux, desktop-windows (cross-export, PE checked), Android debug APK (aapt/apksigner,
   arm64-v8a, no INTERNET permission), Web PWA; each with ShuttleLine contract + BoltPack SBOM/license audit.
2. **Desktop launch** — the exported Linux binary, started with no scene argument inside a network-less
   namespace (``bwrap --unshare-net``), boots into the vertical slice and completes it; its final state is
   byte-identical (canonical JSON) to the editor-runtime run of the same selection.
3. **G-WEB-01** — compressed payload < 45 MB, offline SW, COOP/COEP verified in headless Chrome (PWAPipeline).
4. **G-SAVE-01** — one save travels desktop → Android → Web → desktop: the exported desktop build quits mid-slice
   at checkpoint 4; the Android build's packed content imports + rewrites it; the Web build imports + rewrites
   it into IndexedDB and reloads it **offline**; the desktop build resumes from the Web bytes and finishes with
   the same final state as an uninterrupted run. Same format, same checksum at every hop.
5. **G-NET-01** — no networking API in game scripts, Godot ``OfflineMultiplayerPeer`` on every target, the
   desktop slice runs with no network namespace, the APK requests no INTERNET permission, Web boots offline.
6. **G-A11Y-01 (input remap part)** — a profile input remap round-trips through the same save on all three
   runtimes and rebinds the actions. Palette variants exist in PatternVault; the in-game palette toggle and
   rebinding UI are not built (reported, not gated).

No device/emulator is available (no KVM): the Android **content** (APK ``assets/``) is exercised by the
exported desktop runtime and labelled as such; Windows has no runtime smoke without wine (documented).

Fast mode (``FORGE_ACCEPT_FAST=1``: pytest / CI without export templates) runs the static half: presets,
targets, ShuttleLine contract vs sources, BoltPack SBOM + license audit, network-API scan, and the
save import/rewrite/remap round-trip on the editor runtime.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from forge.accept_f6 import _godot_argv, fast_mode

NET_APIS = r"\b(HTTPRequest|HTTPClient|StreamPeerTCP|StreamPeerTLS|TCPServer|UDPServer|PacketPeerUDP|ENetMultiplayerPeer|" \
           r"ENetConnection|WebSocketPeer|WebSocketMultiplayerPeer|WebRTCPeerConnection|WebRTCMultiplayerPeer|" \
           r"MultiplayerSpawner|MultiplayerSynchronizer|JavaScriptBridge|OS\.shell_open|OS\.execute|OS\.create_process)\b"
QUIT_AT = 4
REMAP = {"attack": ["F"], "interact": ["G"]}


# --------------------------------------------------------------------------- static checks (both modes)

def presets_report(root: Path) -> dict[str, Any]:
    from forge.packaging import TARGETS, project_dir

    text = (project_dir(root) / "export_presets.cfg").read_text(encoding="utf-8")
    blocks = re.split(r"^\[preset\.\d+\]\s*$", text, flags=re.M)[1:]
    presets = {}
    for b in blocks:
        name = re.search(r'^name="([^"]+)"', b, re.M).group(1)
        presets[name] = b
    want = {t.preset for t in TARGETS.values()}
    inc_ok = all(all(x in b for x in ("assets/generated/*", "data/generated/*", "locale/*.json")) for b in presets.values())
    proj = (project_dir(root) / "project.godot").read_text(encoding="utf-8")
    a, w = presets.get("android", ""), presets.get("web", "")
    checks = {
        "all_targets": want <= set(presets),
        "ships_fabric_output": inc_ok,
        "no_secrets_in_presets": 'keystore/debug_password=""' in a and 'keystore/release_password=""' in a,
        "android_no_internet": "permissions/internet=false" in a,
        "android_arm64": "architectures/arm64-v8a=true" in a and "gradle_build/use_gradle_build=false" in a,
        "web_pwa_isolation": "progressive_web_app/enabled=true" in w and "progressive_web_app/ensure_cross_origin_isolation_headers=true" in w,
        "compatibility_renderer": 'renderer/rendering_method="gl_compatibility"' in proj and 'rendering_method.mobile="gl_compatibility"' in proj,
        "etc2_astc_import": "import_etc2_astc=true" in proj,
    }
    return {"presets": sorted(presets), "checks": checks, "ok": all(checks.values())}


def targets_report(root: Path) -> dict[str, Any]:
    from forge.manifest import load_manifest
    from forge.packaging import TARGETS

    m = load_manifest(None, root)
    have = {t.id: t.kind for t in m.targets}
    missing = [t for t, tg in TARGETS.items() if have.get(t) != tg.kind]
    return {"manifest_targets": have, "missing": missing, "ok": not missing}


def net_scan(root: Path) -> dict[str, Any]:
    from forge.packaging import project_dir

    hits = []
    for p in sorted(project_dir(root).rglob("*.gd")):
        if ".godot" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(NET_APIS, code):
                hits.append(f"{p.relative_to(root)}:{i}: {line.strip()[:100]}")
    return {"network_api_uses": hits, "ok": not hits}


def bolt_static(root: Path) -> dict[str, Any]:
    from forge.boltpack import audit, sbom
    from forge.packaging import TARGETS, game_version

    out = {}
    for t in TARGETS:
        a = audit(sbom(root, t, game_version(root)))
        out[t] = {"ok": a["ok"], "licenses": len(a["licenses"]), "copyleft": a["copyleft"], "unknown": a["unknown"]}
    return {"targets": out, "ok": all(v["ok"] for v in out.values())}


def remap_save() -> dict[str, Any]:
    from forge.save import checksum, new_save

    s = new_save("kael", {"kael": 2, "nyra": 2, "bram": 2, "sola": 2}, ["ember_fox"])
    s["profile"]["settings"]["input_remap"] = REMAP
    s["checksum"] = checksum(s)
    return s


def _b64(obj_or_bytes: Any) -> str:
    raw = obj_or_bytes if isinstance(obj_or_bytes, bytes) else json.dumps(obj_or_bytes, indent=2, sort_keys=True).encode()
    return base64.b64encode(raw).decode()


def _remap_ok(sc: dict[str, Any]) -> bool:
    inp = sc.get("input", {})
    return inp.get("attack") == ["F"] and inp.get("interact") == ["G"] and not (inp.get("remap") or {}).get("skipped")


def _savecheck_editor(root: Path, save_dir: Path, *extra: str) -> dict[str, Any]:
    from forge.milestones import parse_output

    p = subprocess.run(_godot_argv(root, "--scene=savecheck", f"--save-dir={save_dir}", *extra), capture_output=True, text=True, timeout=120)
    return parse_output(p.stdout + p.stderr).get("savecheck", {})


def static_part(root: Path, tmp: Path) -> dict[str, Any]:
    from forge.save import canonical_json, validate
    from forge.shuttleline import check_sources

    r: dict[str, Any] = {"presets": presets_report(root), "targets": targets_report(root), "net_scan": net_scan(root),
                         "shuttle_sources": check_sources(root), "bolt_static": bolt_static(root)}
    rs = remap_save()
    sc = _savecheck_editor(root, tmp / "remap-editor", f"--import-b64={_b64(rs)}", "--rewrite")
    back = json.loads(base64.b64decode(sc.get("file_b64", "")) or b"{}")
    r["editor_roundtrip"] = {"loaded_equal": canonical_json(sc.get("loaded", {})) == canonical_json(rs),
                             "rewritten_validates": validate(back) == [] if back else False,
                             "checksum_equal": back.get("checksum") == rs["checksum"], "reloaded_equal": sc.get("reloaded_equal"),
                             "remap_applied": _remap_ok(sc), "net": sc.get("net")}
    return r


# --------------------------------------------------------------------------- full mode

def _exported(root: Path, *args: str, path: Path | None = None, sandbox_net: bool = False, timeout: int = 300) -> tuple[int, dict[str, Any], str]:
    from forge.milestones import parse_output
    from forge.packaging import TARGETS, dist_dir, run_exported

    b = dist_dir(root) / "desktop-linux" / TARGETS["desktop-linux"].artifact
    code, out = run_exported(b, *args, timeout=timeout, sandbox_net=sandbox_net, extra=["--path", str(path)] if path else None)
    res = parse_output(out)
    res["_script_errors"] = len(re.findall(r"SCRIPT ERROR", out))
    return code, res, out


def full_part(root: Path, tmp: Path) -> dict[str, Any]:
    from forge.accept_f6 import _slice
    from forge.packaging import build_targets, dist_dir, unpack_android_content
    from forge.pwa import LocalHost, WebHarness
    from forge.save import canonical_json, validate

    r: dict[str, Any] = {}
    build = build_targets(root, ["desktop-linux", "desktop-windows", "android", "web"])
    r["build"] = {"ok": build["ok"], "error": build.get("error"), "toolchain": build.get("toolchain"),
                  "targets": {t: {k: v for k, v in rep.items() if k not in ("files",)} for t, rep in build.get("targets", {}).items()}}
    if not all(t.get("ok") for t in build.get("targets", {}).values()) or not build.get("targets"):
        return r
    andc = unpack_android_content(root, tmp / "android-content")
    common = ("--autoplay", "--no-live", "--watchdog=280")

    # 2. desktop launch: no --scene (default = slice), network namespace removed
    c1, d1, _ = _exported(root, *common, f"--save-dir={tmp / 'd-full'}", sandbox_net=True)
    ce, e1 = _slice(root, tmp / "e-full")
    ca, a1, _ = _exported(root, *common, "--scene=slice", f"--save-dir={tmp / 'a-full'}", path=andc)
    s_d, s_e, s_a = d1.get("slice", {}), e1.get("slice", {}), a1.get("slice", {})
    r["desktop_launch"] = {
        "exit": c1, "completed": s_d.get("completed"), "default_scene_is_slice": bool(s_d), "script_errors": d1["_script_errors"],
        "net": s_d.get("net"), "network_namespace": "bwrap --unshare-net" if shutil.which("bwrap") else "none (bwrap missing)",
        "game_minutes": s_d.get("game_minutes"), "wall_ms": s_d.get("wall_ms"),
        "final_equal_editor": bool(s_e.get("final_state")) and canonical_json(s_d.get("final_state", {})) == canonical_json(s_e.get("final_state", {})),
        "final_checksum": (s_d.get("final_state") or {}).get("checksum")}
    r["android_content"] = {"runtime": "exported desktop runtime over the APK's assets/ (no device/emulator: no KVM)",
                            "exit": ca, "completed": s_a.get("completed"), "script_errors": a1["_script_errors"],
                            "final_equal_desktop": canonical_json(s_a.get("final_state", {})) == canonical_json(s_d.get("final_state", {}))}

    # 4. G-SAVE-01 chain desktop → android → web → desktop
    chain: dict[str, Any] = {}
    cq, q, _ = _exported(root, *common, f"--save-dir={tmp / 'h1'}", f"--quit-after-checkpoint={QUIT_AT}")
    h1 = (tmp / "h1" / "slot0.json").read_bytes() if (tmp / "h1" / "slot0.json").exists() else b"{}"
    s1 = json.loads(h1)
    chain["desktop_write"] = {"exit": cq, "checkpoint": (q.get("slice_quit") or {}).get("checkpoint"), "bytes": len(h1),
                              "checksum": s1.get("checksum"), "validates": validate(s1) == []}
    ca2, a2, _ = _exported(root, "--scene=savecheck", f"--save-dir={tmp / 'h2'}", f"--import-b64={_b64(h1)}", "--rewrite", path=andc)
    sc2 = a2.get("savecheck", {})
    h2 = base64.b64decode(sc2.get("file_b64", "")) or b"{}"
    s2 = json.loads(h2)
    chain["android_import_rewrite"] = {"exit": ca2, "loaded_ok": (sc2.get("last_load") or {}).get("ok"),
                                       "loaded_equal": canonical_json(sc2.get("loaded", {})) == canonical_json(s1),
                                       "checksum": s2.get("checksum"), "validates": validate(s2) == [],
                                       "bytes_equal_previous_hop": h2 == h1, "net": sc2.get("net")}
    with LocalHost(dist_dir(root) / "web") as host, WebHarness() as wh:
        w1 = wh.run(host.url, ["--scene=savecheck", f"--import-b64={_b64(h2)}", "--rewrite"])
        wh.run(host.url, ["--net-report"])                 # SW now controls; wasm/pck get cached
        w2 = wh.run(host.url, ["--scene=savecheck"], offline=True)
    sc3, sc4 = w1["result"].get("savecheck", {}), w2["result"].get("savecheck", {})
    h3 = base64.b64decode(sc3.get("file_b64", "")) or b"{}"
    s3 = json.loads(h3)
    chain["web_import_rewrite"] = {"boot_ok": w1["boot_ok"], "platform": sc3.get("platform"), "loaded_ok": (sc3.get("last_load") or {}).get("ok"),
                                   "loaded_equal": canonical_json(sc3.get("loaded", {})) == canonical_json(s2),
                                   "checksum": s3.get("checksum"), "validates": validate(s3) == [],
                                   "bytes_equal_previous_hop": h3 == h2, "error": w1["error"], "script_errors": w1["script_errors"]}
    chain["web_offline_reload"] = {"boot_ok": w2["boot_ok"], "offline": True, "imported": sc4.get("imported"),
                                   "loaded_from_indexeddb_equal": bool(sc4.get("loaded")) and canonical_json(sc4.get("loaded", {})) == canonical_json(s3),
                                   "sw_controller": (w2.get("page") or {}).get("sw_controller"), "error": w2["error"]}
    (tmp / "h4").mkdir(parents=True, exist_ok=True)
    (tmp / "h4" / "slot0.json").write_bytes(h3)
    cr, rr, _ = _exported(root, *common, f"--save-dir={tmp / 'h4'}", "--resume")
    sr = rr.get("slice", {})
    chain["desktop_resume"] = {"exit": cr, "completed": sr.get("completed"),
                               "resumed_checksum": (sr.get("resumed_from") or {}).get("checksum"),
                               "final_equal_uninterrupted": canonical_json(sr.get("final_state", {})) == canonical_json(s_d.get("final_state", {}))}
    sums = {chain["desktop_write"]["checksum"], chain["android_import_rewrite"]["checksum"], chain["web_import_rewrite"]["checksum"],
            chain["desktop_resume"]["resumed_checksum"]}
    chain["same_checksum_all_hops"] = len(sums) == 1 and None not in sums
    chain["hops"] = ["desktop-linux (export)", "android (APK content)", "web (Chrome, IndexedDB, offline reload)", "desktop-linux (export)"]
    r["save_roundtrip"] = chain

    # 6. G-A11Y-01 remap through the same save on the three runtimes
    rs = _b64(remap_save())
    _, ad, _ = _exported(root, "--scene=savecheck", f"--save-dir={tmp / 'r1'}", f"--import-b64={rs}")
    _, aa, _ = _exported(root, "--scene=savecheck", f"--save-dir={tmp / 'r2'}", f"--import-b64={rs}", path=andc)
    with LocalHost(dist_dir(root) / "web") as host, WebHarness() as wh:
        aw = wh.run(host.url, ["--scene=savecheck", f"--import-b64={rs}"])
    r["input_remap"] = {"remap": REMAP, "desktop": _remap_ok(ad.get("savecheck", {})), "android_content": _remap_ok(aa.get("savecheck", {})),
                        "web": _remap_ok(aw["result"].get("savecheck", {}))}
    r["net_runtime"] = {"desktop": (ad.get("savecheck") or {}).get("net"), "android_content": (aa.get("savecheck") or {}).get("net"),
                        "web": (aw["result"].get("savecheck") or {}).get("net")}
    return r


def f7_run(root: Path) -> tuple[int, dict[str, Any]]:
    tmp = Path(tempfile.mkdtemp(prefix="fabric-f7-"))
    try:
        result = {"mode": "fast" if fast_mode() else "full"} | static_part(root, tmp)
        if not fast_mode():
            result |= full_part(root, tmp)
        result["a11y"] = a11y_report(root, result)
        return 0, result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def a11y_report(root: Path, r: dict[str, Any]) -> dict[str, Any]:
    from forge.patternvault import PatternVault

    variants = PatternVault(root).variants()
    remap = r.get("input_remap") or {"editor": (r.get("editor_roundtrip") or {}).get("remap_applied")}
    return {"palette_variants_in_patternvault": variants, "input_remap_roundtrip": remap,
            "runtime_palette_toggle": False, "rebinding_ui": False,
            "status": "partial — data-level remap travels with the save on every target; no in-game palette toggle / rebinding UI yet"}


# --------------------------------------------------------------------------- gate

def f7_check(r: dict[str, Any]) -> list[str]:
    from forge.milestones import _need

    errs: list[str] = []
    for k in ("presets", "targets", "net_scan", "shuttle_sources", "bolt_static"):
        _need((r.get(k) or {}).get("ok") is True, f"{k}: {r.get(k)}", errs)
    er = r.get("editor_roundtrip", {})
    _need(all(er.get(k) for k in ("loaded_equal", "rewritten_validates", "checksum_equal", "reloaded_equal", "remap_applied")),
          f"editor save/remap round-trip: {er}", errs)
    _need(bool((er.get("net") or {}).get("offline_peer")), "editor runtime networking not dormant", errs)
    if r.get("mode") != "full":
        return errs
    b = r.get("build", {})
    ts = b.get("targets", {})
    _need(set(ts) == {"desktop-linux", "desktop-windows", "android", "web"}, f"targets built: {sorted(ts)} {b.get('error')}", errs)
    for t, rep in ts.items():
        _need(rep.get("ok") is True, f"{t}: export failed {rep.get('errors') or rep.get('error')}", errs)
        _need((rep.get("shuttle") or {}).get("ok") is True, f"{t}: ShuttleLine contract {rep.get('shuttle')}", errs)
        _need((rep.get("bolt") or {}).get("ok") is True, f"{t}: BoltPack audit {rep.get('bolt')}", errs)
    _need((ts.get("desktop-linux", {}).get("verify") or {}).get("ok") is True, "desktop-linux smoke", errs)
    _need((ts.get("desktop-windows", {}).get("verify") or {}).get("ok") is True, f"desktop-windows: {ts.get('desktop-windows', {}).get('verify')}", errs)
    _need((ts.get("android", {}).get("verify") or {}).get("ok") is True, f"android: {ts.get('android', {}).get('verify')}", errs)
    pwa = ts.get("web", {}).get("pwa") or {}
    _need((pwa.get("budget") or {}).get("ok") is True, f"G-WEB-01 budget: {(pwa.get('budget') or {}).get('total_gzip9')}", errs)
    _need((pwa.get("service_worker") or {}).get("ok") is True, "G-WEB-01 service worker cache list", errs)
    _need((pwa.get("smoke") or {}).get("ok") is True, f"G-WEB-01 smoke: {(pwa.get('smoke') or {}).get('checks')}", errs)
    dl = r.get("desktop_launch", {})
    _need(dl.get("exit") == 0 and dl.get("completed") is True and dl.get("script_errors") == 0, f"desktop slice: {dl}", errs)
    _need(dl.get("final_equal_editor") is True, "exported desktop slice differs from the editor runtime", errs)
    _need(bool((dl.get("net") or {}).get("offline_peer")), "desktop networking not dormant", errs)
    ac = r.get("android_content", {})
    _need(ac.get("completed") is True and ac.get("final_equal_desktop") is True, f"android content slice: {ac}", errs)
    sr = r.get("save_roundtrip", {})
    _need(sr.get("desktop_write", {}).get("validates") is True, "G-SAVE-01 desktop save invalid", errs)
    for hop in ("android_import_rewrite", "web_import_rewrite"):
        h = sr.get(hop, {})
        _need(h.get("loaded_ok") is True and h.get("loaded_equal") is True and h.get("validates") is True, f"G-SAVE-01 {hop}: {h}", errs)
    _need(sr.get("web_offline_reload", {}).get("loaded_from_indexeddb_equal") is True, f"G-SAVE-01 web offline reload: {sr.get('web_offline_reload')}", errs)
    _need(sr.get("desktop_resume", {}).get("completed") is True and sr.get("desktop_resume", {}).get("final_equal_uninterrupted") is True,
          f"G-SAVE-01 resume: {sr.get('desktop_resume')}", errs)
    _need(sr.get("same_checksum_all_hops") is True, "G-SAVE-01 checksum changed between platforms", errs)
    _need(all((r.get("input_remap") or {}).get(k) for k in ("desktop", "android_content", "web")), f"G-A11Y-01 remap: {r.get('input_remap')}", errs)
    _need(all((v or {}).get("offline_peer") for v in (r.get("net_runtime") or {}).values()), f"G-NET-01 runtime: {r.get('net_runtime')}", errs)
    _need(not (ts.get("android", {}).get("verify") or {}).get("internet_permission"), "APK requests INTERNET", errs)
    return errs


def f7_perf(r: dict[str, Any]) -> dict[str, Any]:
    ts = (r.get("build") or {}).get("targets", {})
    pwa = (ts.get("web") or {}).get("pwa") or {}
    return {"mode": r.get("mode"),
            "artifacts": {t: {"artifact": rep.get("artifact"), "total_size": rep.get("total_size"),
                              "export_wall_s": rep.get("export_wall_s")} for t, rep in ts.items()},
            "web_gzip9_bytes": (pwa.get("budget") or {}).get("total_gzip9"),
            "web_budget_headroom_bytes": (pwa.get("budget") or {}).get("headroom_bytes"),
            "apk_bytes": ((ts.get("android") or {}).get("verify") or {}).get("apk_size"),
            "desktop_slice_game_minutes": (r.get("desktop_launch") or {}).get("game_minutes")}
