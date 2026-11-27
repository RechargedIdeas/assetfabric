extends Node
## LiveOps QA scene (F9): `--scene=liveopscheck --liveops-dir=<dir> [--liveops-pubkey=<pem>] [--probe=<path>,...]
## [--save-dir=<dir>] [--save-guard] [--liveops-simulate-crash] [--diagnostics=on]`
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
