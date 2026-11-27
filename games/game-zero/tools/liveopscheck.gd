extends Node
## LiveOps QA scene (F9): `--scene=liveopscheck --liveops-dir=<dir> [--liveops-pubkey=<pem>] [--probe=<path>,...]
## [--save-dir=<dir>] [--save-guard] [--liveops-simulate-crash] [--diagnostics=on] [--consent-ui=toggle|verify]`
## Reports what the LiveOps boot state machine did, the effective flags, probed balance values, the kill switches in
## effect (Retro profile request, MusicDirector state), the save forward-compat guard and G-NET-01 — one FABRIC_RESULT.

func _ready() -> void:
	var out := {"report": LiveOps.report, "flags": LiveOps.flags, "net": Fabric.net_report(), "build": LiveOps.build_version(),
		"probe": {}, "manifest_flags": LiveOps.manifest.get("flags", {}).keys(), "knobs": LiveOps.manifest.get("knobs", {}).size()}
	for path in str(Fabric.arg("probe", "")).split(",", false):
		out["probe"][path] = Live.data_at(Fabric.game_data, path)
	out["retro_request_nes"] = Retro.set_profile("nes-style")
	Retro.set_profile("off")
	var md = load("res://audio/music_director.gd").new()
	md.rules = Fabric.read_json("res://data/generated/world.json").get("music", {})
	md.set_state("combat", 0)
	out["music_state_for_combat"] = md.state
	md.free()
	if Fabric.flag("save-guard"):
		out["save_guard"] = _save_guard()
	out["diag_written"] = FileAccess.file_exists(LiveOps.dir.path_join("diag/session.json"))
	var cu := str(Fabric.arg("consent-ui", ""))
	if cu == "toggle":
		out["consent_ui"] = await _consent_ui_toggle()
	elif cu == "verify":
		out["consent_ui"] = _consent_state()
	await Save.persist_wait()
	print("FABRIC_RESULT " + JSON.stringify({"liveops": out}))
	LiveOps.simulate_crash_if_asked()
	get_tree().quit(0)


## A save from a newer build (v CURRENT+1) must survive this build untouched: load refuses (no .bak fallback), write
## refuses, bytes unchanged. Then an ordinary save still round-trips in a fresh slot.
func _save_guard() -> Dictionary:
	var newer := {"format": Save.FORMAT, "version": Save.CURRENT + 1, "profile": {"future": true}, "roster": {}, "world": {}}
	var f := FileAccess.open(Save.path("future"), FileAccess.WRITE)
	f.store_string(JSON.stringify(newer))
	f.close()
	var before := FileAccess.get_sha256(Save.path("future"))
	var older := Save.new_save("kael", {"kael": 1}, ["ember_fox"])
	var fb := FileAccess.open(Save.path("future") + ".bak", FileAccess.WRITE)
	fb.store_string(JSON.stringify(older))
	fb.close()
	var loaded := Save.load_slot("future", false)
	var r := {"load_empty": loaded.is_empty(), "newer_than_build": Save.last_load.get("newer_than_build", false),
		"write_refused": Save.write(older, "future") == "", "bytes_unchanged": FileAccess.get_sha256(Save.path("future")) == before,
		"read_only": Save.read_only}
	var cs := Save.write(older, "f9_roundtrip")
	r["roundtrip_ok"] = cs != "" and Save.canonical_json(Save.load_slot("f9_roundtrip", false)) == Save.canonical_json(Save.canon(older).merged({"checksum": cs}, true))
	return r


# --------------------------------------------------------------------------- post-F9: Settings consent toggle (F9-12)

const SettingsMenu := preload("res://ui/settings_menu.gd")
const MARKER := "[PLACEHOLDER — LEGAL REVIEW REQUIRED]"


func _frames(n: int) -> void:
	for i in n:
		await get_tree().physics_frame
		await get_tree().process_frame


func _key(code: Key) -> void:
	for pressed in [true, false]:
		var ev := InputEventKey.new()
		ev.physical_keycode = code
		ev.keycode = code
		ev.pressed = pressed
		Input.parse_input_event(ev)
		await _frames(3)


func _pad(button: JoyButton) -> void:
	for pressed in [true, false]:
		var ev := InputEventJoypadButton.new()
		ev.button_index = button
		ev.pressed = pressed
		Input.parse_input_event(ev)
		await _frames(3)


## What the device + the save profile say right now.
func _consent_state() -> Dictionary:
	var c = null
	var cp := LiveOps.dir.path_join("consent.json")
	if FileAccess.file_exists(cp):
		c = JSON.parse_string(FileAccess.get_file_as_string(cp))
	var s: Dictionary = Save.load_slot("slot0", false)
	var st = s.get("profile", {}).get("settings", {}) if not s.is_empty() else {}
	return {"consent": LiveOps.diagnostics_consent(), "flag": LiveOps.enabled("diagnostics"),
		"consent_file": c.get("diagnostics") if typeof(c) == TYPE_DICTIONARY else null,
		"profile": st.get("diagnostics_consent") if typeof(st) == TYPE_DICTIONARY else null,
		"diag_file": FileAccess.file_exists(LiveOps.dir.path_join("diag/session.json"))}


## Drive the real Settings screen: keyboard ↑×3 from the palette row reaches the toggle, Enter turns it on; pad A turns
## it off; pad A again leaves it on for the `verify` boot. A checkpoint save exists first so the profile layer is patched.
func _consent_ui_toggle() -> Dictionary:
	var r := {"steps": [], "errors": []}
	var step := func(name: String, ok: bool, extra: Dictionary = {}) -> void:
		var row := {"step": name, "ok": ok}
		row.merge(extra)
		r["steps"].append(row)
		if not ok:
			r["errors"].append(name)
	Save.write(Save.new_save("kael", {"kael": 1}, ["ember_fox"]))
	step.call("default_off", not LiveOps.diagnostics_consent() and not LiveOps.enabled("diagnostics")
		and not FileAccess.file_exists(LiveOps.dir.path_join("diag/session.json")), _consent_state())
	var menu = SettingsMenu.new()
	add_child(menu)
	await _frames(3)
	var notice: String = menu._diag_notice.text
	step.call("notice_is_locale_text", notice != "settings.diagnostics.notice" and notice == tr("settings.diagnostics.notice"))
	step.call("notice_legal_placeholder", notice.begins_with(MARKER))
	step.call("label_shows_off", menu._diag_btn.text.contains(tr("settings.off")), {"label": menu._diag_btn.text})
	for i in 3:
		await _key(KEY_UP)
	step.call("keyboard_reaches_toggle", menu.get_viewport().gui_get_focus_owner() == menu._diag_btn)
	await _key(KEY_ENTER)
	var on := _consent_state()
	step.call("keyboard_on", on["consent"] == true and on["flag"] == true and on["consent_file"] == true
		and on["profile"] == true and on["diag_file"] == true, on)
	step.call("label_shows_on", menu._diag_btn.text.contains(tr("settings.on")))
	await _pad(JOY_BUTTON_A)
	var off := _consent_state()
	step.call("gamepad_off_deletes_record", off["consent"] == false and off["flag"] == false and off["consent_file"] == false
		and off["profile"] == false and off["diag_file"] == false, off)
	await _pad(JOY_BUTTON_A)
	var on2 := _consent_state()
	step.call("gamepad_on_again", on2["consent"] == true and on2["profile"] == true and on2["diag_file"] == true, on2)
	r["events"] = menu.events_log.duplicate(true)
	menu.close()
	await _frames(2)
	return r
