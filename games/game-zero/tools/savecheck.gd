extends Node
## Save tooling scene (F5, cross-platform in F7):
##   `--scene=savecheck --save-dir=<dir> [--fixtures=<file.json>] [--import-b64=<base64 save>] [--rewrite]`
## Loads slot0 (with backup fallback + migration) and migrates every fixture with the GDScript
## migrations, printing one `FABRIC_RESULT` line for forge (parity with forge/save.py).
## F7 (G-SAVE-01): `--import-b64` drops a save produced on another platform into this platform's save
## dir (on Web that is IndexedDB-backed user://) before loading; `--rewrite` writes the loaded save back
## through the normal atomic writer so the next platform receives *this* platform's bytes
## (`file_b64`). `net` / `platform` / `input` are reported for G-NET-01 / G-A11Y-01.
## (`--save-dir` is optional; default user://saves.)

func _ready() -> void:
	var imp := str(Fabric.arg("import-b64", ""))
	if imp != "":
		var f := FileAccess.open(Save.path(), FileAccess.WRITE)
		f.store_buffer(Marshalls.base64_to_raw(imp))
		f.close()
	var loaded := Save.load_slot()
	var out := {"loaded": loaded, "last_load": Save.last_load, "migrated": {}, "platform": Fabric.platform_id(),
		"os": OS.get_name(), "net": Fabric.net_report(), "imported": imp != ""}
	if Fabric.flag("rewrite") and not loaded.is_empty():
		out["rewrite_checksum"] = Save.write(loaded)
		out["reloaded_equal"] = Save.canonical_json(Save.load_slot()) == Save.canonical_json(loaded)
	if FileAccess.file_exists(Save.path()):
		out["file_b64"] = Marshalls.raw_to_base64(FileAccess.get_file_as_bytes(Save.path()))
	out["input"] = {"remap": Fabric.input_remap_applied, "attack": Fabric.action_keys("attack"),
		"interact": Fabric.action_keys("interact")}
	var fx := str(Fabric.arg("fixtures", ""))
	if fx != "":
		var d = JSON.parse_string(FileAccess.get_file_as_string(fx))
		for name in d:
			var m := Save.migrate(d[name])
			out["migrated"][name] = {"save": m[0], "steps": m[1], "errors": Save.validate(m[0]),
				"canonical_sha": Save.canonical_json(m[0]).sha256_text()}
	print("FABRIC_RESULT " + JSON.stringify({"savecheck": out}))
	get_tree().quit(0)
