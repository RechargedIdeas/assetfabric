"""F9 acceptance: "LiveOps foundation — readiness only" (ASSETFABRIC_SPEC §13 F9; §12 "LiveOps readiness: remote
config / feature flags (launch content deferred)"; GAME_SPEC §5 "Live seasonal content (remote config readiness OK)",
§8 "Remote config hooks for balance knobs"; G-NET-01 stays strict). docs/acceptance-tests/F9.md has the mapping.

Everything runs locally against throw-away directories and an ephemeral RSA key — no network, no service, no launch.

 1. manifest — content/liveops/flags.yaml valid (safe offline defaults, locale keys), generated liveops.json in sync,
    every remote-config knob hits a numeric leaf of the game data.
 2. bundle rules (forge side) — sign/verify round-trip; tampered payload, wrong key, replayed serial, out-of-range
    knob, sim.* knob, unknown knob, unknown key (content), consent flag, unknown flag, future build_min all refused.
 3. device state machine (headless Godot, `--scene=liveopscheck`) — the game makes the same decision as forge for each
    bundle: promote, reject (kept in rejected/, active untouched), replay refused, roll-forward rollback, crash-loop
    quarantine after MAX_BOOT_FAILS crashed boots (real OS.crash) restores the previous bundle, on-disk tamper and
    on-disk downgrade swap fall back to safe defaults, no pinned key → inbox ignored + untouched.
 4. kill switches — retro_styles off forces the modern display, adaptive_music off keeps the exploration mix,
    remote_balance off ignores a bundle's patches.
 5. balance hook is real and deterministic — F2 first-combat state hash: defaults == no-LiveOps baseline, a signed
    bundle changes it, the same bundle twice gives the same hash, the rollback bundle restores the baseline hash.
 6. saves — a save from a newer build is never migrated down, never replaced by its .bak, never overwritten.
 7. privacy — diagnostics consent defaults off (nothing written); opt-in writes a local session record with no paths;
    diag-export refuses without consent, scrubs PII, validates against forge/schemas/diag_bundle.schema.json.
 8. G-NET-01 — every LiveOps run reports Godot's OfflineMultiplayerPeer, no network API in any game script, and one
    full bundle boot runs inside `bwrap --unshare-net` (when bwrap exists).
 9. readiness checklist — `forge liveops readiness`: no failures; user-gated items listed (production key, service).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from forge.accept_f4 import _godot_argv

PROBE = "enemies.emberling.stats.hp"
PROBE2 = "abilities.claw.power"


def _run(root: Path, args: list[str], net_off: bool = False, timeout: int = 120) -> tuple[int, dict[str, Any], str]:
    from forge.milestones import parse_output

    argv = _godot_argv(root, *args)
    if net_off and shutil.which("bwrap"):
        argv = ["bwrap", "--dev-bind", "/", "/", "--unshare-net", "--die-with-parent", *argv]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    out = p.stdout + p.stderr
    return p.returncode, parse_output(out), out


class Device:
    """One simulated install: a LiveOps dir + the pinned test key."""

    def __init__(self, root: Path, lo: Path, pub: Path | None) -> None:
        self.root, self.lo, self.pub = root, lo, pub

    def args(self, *extra: str) -> list[str]:
        a = [f"--liveops-dir={self.lo}", f"--probe={PROBE},{PROBE2}"]
        if self.pub:
            a.append(f"--liveops-pubkey={self.pub}")
        return [*a, *extra]

    def check(self, *extra: str, net_off: bool = False) -> dict[str, Any]:
        code, r, out = _run(self.root, ["--scene=liveopscheck", *self.args(*extra)], net_off=net_off)
        res = dict(r.get("liveops", {}))
        res["_exit"] = code
        res["_script_errors"] = out.count("SCRIPT ERROR")
        return res

    def combat_hash(self) -> str | None:
        from forge.milestones import INCREMENTS

        code, r, _ = _run(self.root, [*INCREMENTS["F2"].godot_args, *self.args()], timeout=180)
        return r.get("state_hash") if code == 0 else None


def _summ(r: dict[str, Any]) -> dict[str, Any]:
    rep = r.get("report", {})
    return {"exit": r.get("_exit"), "script_errors": r.get("_script_errors"), "source": rep.get("source"),
            "serial": rep.get("serial"), "inbox": rep.get("inbox"), "rejected": rep.get("rejected"),
            "quarantined": rep.get("quarantined"), "active_invalid": rep.get("active_invalid"),
            "patches_applied": rep.get("patches_applied"), "boot_ms": rep.get("boot_ms"),
            "probe": r.get("probe"), "flags": r.get("flags"), "retro_request_nes": r.get("retro_request_nes"),
            "music_state_for_combat": r.get("music_state_for_combat"),
            "offline_peer": (r.get("net") or {}).get("offline_peer"), "save_guard": r.get("save_guard"),
            "diag_written": r.get("diag_written")}


def forge_rules(root: Path, keys: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    from forge import liveops as L

    pub, priv, opriv = Path(keys["public"]), Path(keys["private"]), Path(other["private"])
    good = L.sign(L.make_payload(1, patches=[{"path": PROBE, "value": 30}], issued="2026-11-27T00:00:00Z"), priv)
    tampered = dict(good, payload=good["payload"].replace('"value":30', '"value":31'))
    cases = {
        "valid": (good, 0),
        "tampered_payload": (tampered, 0),
        "wrong_key": (L.sign(json.loads(good["payload"]), opriv), 0),
        "replayed_serial": (good, 1),
        "out_of_range": (L.sign(L.make_payload(2, patches=[{"path": PROBE, "value": 99999}]), priv), 1),
        "sim_knob": (L.sign(L.make_payload(2, patches=[{"path": "sim.leash", "value": 64}]), priv), 1),
        "unknown_knob": (L.sign(L.make_payload(2, patches=[{"path": "enemies.season_boss.stats.hp", "value": 50}]), priv), 1),
        "content_key": (L.sign({**L.make_payload(2), "content": {"areas": {"winter_fest": {}}}}, priv), 1),
        "consent_flag": (L.sign(L.make_payload(2, flags={"diagnostics": True}), priv), 1),
        "unknown_flag": (L.sign(L.make_payload(2, flags={"double_xp": True}), priv), 1),
        "future_build": (L.sign(L.make_payload(2, build_min="9.0.0"), priv), 1),
    }
    out = {}
    for name, (b, ms) in cases.items():
        r = L.verify(b, pub, root, min_serial=ms)
        out[name] = {"ok": r["ok"], "errors": r["errors"]}
    return out


def device_part(root: Path, tmp: Path, keys: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    from forge import liveops as L

    pub, priv, opriv = Path(keys["public"]), Path(keys["private"]), Path(other["private"])
    dev = Device(root, tmp / "device", pub)
    steps: dict[str, Any] = {}
    t0 = time.perf_counter()

    steps["fresh"] = _summ(dev.check())
    b1 = L.sign(L.make_payload(1, flags={"retro_styles": False, "adaptive_music": False},
                               patches=[{"path": PROBE, "value": 30}, {"path": PROBE2, "value": 3}]), priv)
    L.install(b1, dev.lo)
    steps["promote_1"] = _summ(dev.check())
    steps["boot_again_1"] = _summ(dev.check())
    b2 = L.sign(L.make_payload(2, flags={"remote_balance": False}, patches=[{"path": PROBE, "value": 40}]), priv)
    L.install(b2, dev.lo)
    steps["promote_2_balance_off"] = _summ(dev.check())
    bad = L.sign(L.make_payload(3, patches=[{"path": PROBE, "value": 31}]), priv)
    L.install(dict(bad, payload=bad["payload"].replace('"value":31', '"value":99')), dev.lo)
    steps["reject_tampered"] = _summ(dev.check())
    L.install(L.sign(L.make_payload(3), opriv), dev.lo)
    steps["reject_wrong_key"] = _summ(dev.check())
    L.install(L.sign(L.make_payload(3, patches=[{"path": PROBE, "value": 99999}]), priv), dev.lo)
    steps["reject_out_of_range"] = _summ(dev.check())
    L.install(L.sign({**L.make_payload(3), "content": {"season": "winter"}}, priv), dev.lo)
    steps["reject_content"] = _summ(dev.check())
    L.install(L.sign(L.make_payload(3, flags={"diagnostics": True}), priv), dev.lo)
    steps["reject_consent"] = _summ(dev.check())
    L.install(b1, dev.lo)
    steps["reject_replay_1"] = _summ(dev.check())
    rb = L.rollback_bundle(None, 4, priv)
    L.install(rb, dev.lo)
    steps["rollback_4_defaults"] = _summ(dev.check())
    b5 = L.sign(L.make_payload(5, patches=[{"path": PROBE, "value": 30}]), priv)
    L.install(b5, dev.lo)
    steps["crash_boot_1"] = _summ(dev.check("--liveops-simulate-crash"))
    steps["crash_boot_2"] = _summ(dev.check("--liveops-simulate-crash"))
    steps["after_crash_loop"] = _summ(dev.check())
    # on-disk tamper of the active bundle → safe defaults (file left for forensics)
    act = dev.lo / "active.json"
    good_active = act.read_text(encoding="utf-8")
    j = json.loads(good_active)
    act.write_text(json.dumps(dict(j, payload=j["payload"].replace('"patches":[]', f'"patches":[{{"path":"{PROBE}","value":99}}]'))),
                   encoding="utf-8")
    steps["active_tampered"] = _summ(dev.check())
    # on-disk downgrade swap: a validly signed OLDER bundle copied over active.json
    L.write_bundle(b1, act)
    steps["active_downgrade_swap"] = _summ(dev.check())
    act.write_text(good_active, encoding="utf-8")
    steps["restored"] = _summ(dev.check())
    # inside a network-less namespace
    steps["net_off_boot"] = _summ(dev.check(net_off=True))
    steps["net_off_boot"]["network_namespace"] = "bwrap --unshare-net" if shutil.which("bwrap") else "none (bwrap missing)"
    # no pinned key: the inbox is ignored and left in place
    nokey = Device(root, tmp / "nokey", None)
    L.install(b1, nokey.lo)
    steps["no_key"] = _summ(nokey.check())
    steps["no_key"]["inbox_left"] = (nokey.lo / "inbox.json").exists()
    # saves
    steps["save_guard"] = _summ(Device(root, tmp / "sg", pub).check("--save-guard", f"--save-dir={tmp / 'saves'}"))
    # diagnostics consent
    steps["diag_off"] = _summ(Device(root, tmp / "d0", pub).check())
    d1 = Device(root, tmp / "d1", pub)
    steps["diag_on"] = _summ(d1.check("--diagnostics=on"))
    sess = d1.lo / "diag" / "session.json"
    steps["diag_on"]["session_has_paths"] = sess.exists() and (str(tmp) in sess.read_text(encoding="utf-8")
                                                               or "/home/" in sess.read_text(encoding="utf-8"))
    return {"steps": steps, "wall_s": round(time.perf_counter() - t0, 1), "device_status": L.device_status(dev.lo),
            "_session": str(sess) if sess.exists() else ""}


def combat_part(root: Path, tmp: Path, keys: dict[str, Any]) -> dict[str, Any]:
    from forge import liveops as L
    from forge.milestones import INCREMENTS

    pub, priv = Path(keys["public"]), Path(keys["private"])
    code, r, _ = _run(root, list(INCREMENTS["F2"].godot_args), timeout=180)
    baseline = r.get("state_hash") if code == 0 else None
    dev = Device(root, tmp / "combat", pub)
    h_defaults = dev.combat_hash()
    L.install(L.sign(L.make_payload(1, patches=[{"path": PROBE, "value": 30}, {"path": PROBE2, "value": 3}]), priv), dev.lo)
    h_b1 = dev.combat_hash()
    h_b1_again = dev.combat_hash()
    L.install(L.rollback_bundle(None, 2, priv), dev.lo)
    h_rb = dev.combat_hash()
    return {"baseline_no_liveops": baseline, "defaults": h_defaults, "bundle_1": h_b1, "bundle_1_again": h_b1_again,
            "rollback_2": h_rb}


def diag_part(root: Path, tmp: Path, session: str) -> dict[str, Any]:
    from forge import liveops as L

    log = tmp / "godot.log"
    log.write_text("boot ok user=alice host=alice-laptop path=/home/alice/.local/share/godot/app_userdata/Game Zero\n"
                   "contact alice@example.com from 192.168.1.23 fe80:0:0:0:1:2:3:4 mac 01:23:45:67:89:ab\n"
                   "token 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08\n"
                   "C:\\Users\\alice\\AppData\\Roaming\\Godot\n", encoding="utf-8")
    files = [log] + ([Path(session)] if session else [])
    refused = False
    try:
        L.diag_export(files, tmp / "diag.json", consent=False)
    except PermissionError:
        refused = True
    b = L.diag_export(files, tmp / "diag.json", consent=True, extra_words=["alice", "alice-laptop"])
    text = json.dumps(b)
    leaks = [w for w in ("alice", "192.168.1.23", "example.com", "9f86d081884c7d65", "01:23:45:67:89:ab", "fe80:0:0:0")
             if w in text]
    return {"refused_without_consent": refused, "schema_errors": L.validate_diag(b, root), "leaks": leaks,
            "redactions": b["scrub"]["redactions"], "files": [f["name"] for f in b["files"]], "uploaded": b["uploaded"]}


def f9_run(root: Path) -> tuple[int, dict[str, Any]]:
    from forge import liveops as L
    from forge.accept_f7 import net_scan

    t0 = time.perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix="f9-"))
    try:
        keys = L.keygen(tmp / "keys", "test")
        other = L.keygen(tmp / "keys", "other")
        raw = L.load_flags(root)
        gm = root / L.MANIFEST_REL
        r: dict[str, Any] = {
            "manifest": {"errors": L.validate_flags(raw, L.locale_en(root)), "flags": sorted(raw["flags"]),
                         "defaults": L.defaults(root),
                         "in_sync": gm.exists() and json.loads(gm.read_text(encoding="utf-8")) == L.game_manifest(root),
                         "knobs": len(L.game_manifest(root)["knobs"])},
            "forge_rules": forge_rules(root, keys, other),
        }
        dp = device_part(root, tmp, keys, other)
        session = dp.pop("_session")
        r["device"] = dp
        r["combat"] = combat_part(root, tmp, keys)
        r["diagnostics"] = diag_part(root, tmp, session)
        r["net_scan"] = net_scan(root)
        r["readiness"] = L.readiness(root)
        r["wall_s"] = round(time.perf_counter() - t0, 1)
        return 0, r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _need(c: bool, msg: str, errs: list[str]) -> None:
    if not c:
        errs.append(msg)


def f9_check(r: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    m = r.get("manifest", {})
    _need(not m.get("errors") and m.get("in_sync"), f"manifest: {m.get('errors')} in_sync={m.get('in_sync')}", errs)
    fr = r.get("forge_rules", {})
    _need(fr.get("valid", {}).get("ok") is True, f"valid bundle refused by forge: {fr.get('valid')}", errs)
    for k, v in fr.items():
        if k != "valid":
            _need(v.get("ok") is False and v.get("errors"), f"forge accepted bad bundle {k}", errs)
    st = (r.get("device") or {}).get("steps", {})
    for name, s in st.items():
        crash = name.startswith("crash_boot")
        _need(s.get("script_errors") == 0, f"{name}: script errors", errs)
        _need((s.get("exit") != 0) if crash else (s.get("exit") == 0), f"{name}: exit {s.get('exit')}", errs)
        if not crash:
            _need(s.get("offline_peer") is True, f"{name}: networking not dormant (G-NET-01)", errs)
    g = lambda n: st.get(n, {})  # noqa: E731
    _need(g("fresh").get("source") == "defaults" and g("fresh").get("probe", {}).get(PROBE) == 24, f"fresh: {g('fresh')}", errs)
    p1 = g("promote_1")
    _need(p1.get("inbox") == "promoted" and p1.get("serial") == 1 and p1.get("probe", {}).get(PROBE) == 30
          and p1.get("probe", {}).get(PROBE2) == 3, f"promote_1: {p1}", errs)
    _need(p1.get("retro_request_nes") == "off" and p1.get("music_state_for_combat") == "explore", "kill switches not applied", errs)
    _need(g("boot_again_1").get("serial") == 1 and g("boot_again_1").get("inbox") == "none", "active bundle not persistent", errs)
    p2 = g("promote_2_balance_off")
    _need(p2.get("serial") == 2 and p2.get("patches_applied") == 0 and p2.get("probe", {}).get(PROBE) == 24
          and p2.get("retro_request_nes") == "nes-style", f"remote_balance kill switch: {p2}", errs)
    for n in ("reject_tampered", "reject_wrong_key", "reject_out_of_range", "reject_content", "reject_consent", "reject_replay_1"):
        s = g(n)
        _need(s.get("inbox") == "rejected" and s.get("serial") == 2 and s.get("rejected"), f"{n}: {s}", errs)
    rb = g("rollback_4_defaults")
    _need(rb.get("serial") == 4 and rb.get("probe", {}).get(PROBE) == 24 and rb.get("retro_request_nes") == "nes-style",
          f"rollback: {rb}", errs)
    _need(g("crash_boot_1").get("serial") == 5 and g("crash_boot_2").get("serial") == 5, "crash boots did not run bundle 5", errs)
    ac = g("after_crash_loop")
    _need(ac.get("quarantined") == 5 and ac.get("serial") == 4 and ac.get("probe", {}).get(PROBE) == 24,
          f"crash-loop quarantine: {ac}", errs)
    for n in ("active_tampered", "active_downgrade_swap"):
        s = g(n)
        _need(s.get("source") == "defaults" and s.get("active_invalid") and s.get("probe", {}).get(PROBE) == 24, f"{n}: {s}", errs)
    _need(g("restored").get("serial") == 4, f"restored: {g('restored')}", errs)
    _need(g("net_off_boot").get("serial") == 4, "network-less boot failed", errs)
    nk = g("no_key")
    _need(nk.get("inbox") == "ignored_no_key" and nk.get("source") == "defaults" and nk.get("inbox_left"), f"no_key: {nk}", errs)
    sg = g("save_guard").get("save_guard") or {}
    _need(all(sg.get(k) for k in ("load_empty", "newer_than_build", "write_refused", "bytes_unchanged", "roundtrip_ok")),
          f"save forward-compat: {sg}", errs)
    _need(g("diag_off").get("diag_written") is False and g("diag_on").get("diag_written") is True
          and not g("diag_on").get("session_has_paths"), "diagnostics consent", errs)
    c = r.get("combat", {})
    _need(c.get("baseline_no_liveops") is not None and c.get("defaults") == c.get("baseline_no_liveops"),
          f"defaults changed gameplay: {c}", errs)
    _need(c.get("bundle_1") not in (None, c.get("baseline_no_liveops")), "balance bundle had no effect on combat", errs)
    _need(c.get("bundle_1") == c.get("bundle_1_again"), "bundle run not deterministic", errs)
    _need(c.get("rollback_2") == c.get("baseline_no_liveops"), "rollback did not restore the baseline", errs)
    d = r.get("diagnostics", {})
    _need(d.get("refused_without_consent") and not d.get("schema_errors") and not d.get("leaks") and d.get("uploaded") is False,
          f"diagnostics export: {d}", errs)
    _need((r.get("net_scan") or {}).get("ok"), f"network API in game scripts: {(r.get('net_scan') or {}).get('network_api_uses')}", errs)
    _need((r.get("readiness") or {}).get("ok"), f"readiness failed: {(r.get('readiness') or {}).get('failed')}", errs)
    return errs


def f9_perf(r: dict[str, Any]) -> dict[str, Any]:
    st = (r.get("device") or {}).get("steps", {})
    boot = [s.get("boot_ms") for s in st.values() if isinstance(s.get("boot_ms"), (int, float))]
    fr = r.get("forge_rules", {})
    return {"device_boots": len(st), "liveops_boot_ms_max": max(boot) if boot else None,
            "liveops_boot_ms_mean": round(sum(boot) / len(boot), 2) if boot else None,
            "forge_bad_bundles_refused": sum(1 for k, v in fr.items() if k != "valid" and not v.get("ok")),
            "forge_bad_bundles": len(fr) - 1, "knobs": (r.get("manifest") or {}).get("knobs"),
            "flags": len((r.get("manifest") or {}).get("flags", [])), "device_wall_s": (r.get("device") or {}).get("wall_s"),
            "wall_s": r.get("wall_s"), "user_gated": (r.get("readiness") or {}).get("user_gated")}
