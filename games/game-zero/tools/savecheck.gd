extends Node
## Save tooling scene (F5): `--scene=savecheck --save-dir=<dir> [--fixtures=<file.json>]`.
## Loads slot0 (with backup fallback + migration) and migrates every fixture with the
## GDScript migrations, printing one `FABRIC_RESULT` line for forge (parity with forge/save.py).

func _ready() -> void:
	var out := {"loaded": Save.load_slot(), "last_load": Save.last_load, "migrated": {}}
	var fx := str(Fabric.arg("fixtures", ""))
	if fx != "":
		var d = JSON.parse_string(FileAccess.get_file_as_string(fx))
		for name in d:
			var m := Save.migrate(d[name])
			out["migrated"][name] = {"save": m[0], "steps": m[1], "errors": Save.validate(m[0]),
				"canonical_sha": Save.canonical_json(m[0]).sha256_text()}
	print("FABRIC_RESULT " + JSON.stringify({"savecheck": out}))
	get_tree().quit(0)
