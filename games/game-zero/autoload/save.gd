extends Node
## SaveSystem (F5) — Player State layers profile / roster / world, versioned + migratable.
## Mirrors forge/save.py exactly (same migrations, same canonical JSON, same sha256), so
## saves written by either side validate on the other. Atomic: write tmp → rename, the
## previous good save is kept as `.bak` and used if the primary is torn or tampered.
## Directory: user://saves (override with `--save-dir=<abs path>` for tests/tools).

const FORMAT := "gamezero-save"
const CURRENT := 3
const TICK_HZ := 60

var dir := ""
var last_load := {}     # diagnostics of the last load(): {ok, migrated_from, recovered_from_backup, errors}


func _ready() -> void:
	var d := str(Fabric.arg("save-dir", ""))
	dir = d if d != "" else ProjectSettings.globalize_path("user://saves")
	DirAccess.make_dir_recursive_absolute(dir)


# --------------------------------------------------------------------------- canonical form

static func canon(v):
	match typeof(v):
		TYPE_FLOAT:
			return int(v) if v == floorf(v) and absf(v) < 9.0e15 else v
		TYPE_DICTIONARY:
			var out := {}
			for k in v:
				out[str(k)] = canon(v[k])
			return out
		TYPE_ARRAY:
			var a := []
			for x in v:
				a.append(canon(x))
			return a
	return v


static func canonical_json(v) -> String:
	return JSON.stringify(canon(v), "", true)


static func checksum(save: Dictionary) -> String:
	return canonical_json({"profile": save["profile"], "roster": save["roster"], "world": save["world"]}).sha256_text()


# --------------------------------------------------------------------------- migrations

static func _v1_to_v2(s: Dictionary) -> Dictionary:
	var pets: Array = s.get("pets", []).duplicate()
	var leader := str(s.get("leader", ""))
	var fighters := {}
	for k in s.get("levels", {}):
		fighters[k] = int(s["levels"][k])
	var assigned := {}
	if leader != "" and not pets.is_empty():
		assigned[leader] = pets.slice(0, 1)
	return {"format": FORMAT, "version": 2,
		"profile": {"playtime_ticks": int(round(float(s.get("playtime", 0)) * TICK_HZ))},
		"roster": {"leader": leader, "fighters": fighters, "pets": {"owned": pets, "assigned": assigned}},
		"world": {"area": "", "cleared": s.get("cleared", []).duplicate()}}


static func _v2_to_v3(s: Dictionary) -> Dictionary:
	var out: Dictionary = s.duplicate(true)
	out["version"] = 3
	var fighters := {}
	for k in s["roster"]["fighters"]:
		fighters[k] = {"level": int(s["roster"]["fighters"][k]), "xp": 0}
	out["roster"]["fighters"] = fighters
	if not out["profile"].has("settings"):
		out["profile"]["settings"] = {"palette_variant": "default", "input_remap": {}}
	if not out["profile"].has("stats"):
		out["profile"]["stats"] = {"encounters_won": s["world"].get("cleared", []).size(), "bosses_defeated": 0}
	for k in ["bosses_defeated"]:
		if not out["world"].has(k):
			out["world"][k] = []
	for k in ["inventory", "quests", "flags"]:
		if not out["world"].has(k):
			out["world"][k] = {}
	return out


## Returns [migrated save, steps taken]. Pushes an error and returns {} for future versions.
static func migrate(save: Dictionary) -> Array:
	var s: Dictionary = save.duplicate(true)
	var v := int(s.get("version", 1))
	if v > CURRENT:
		push_error("save version %d is newer than this build (%d)" % [v, CURRENT])
		return [{}, []]
	var steps := []
	while v < CURRENT:
		match v:
			1: s = _v1_to_v2(s)
			2: s = _v2_to_v3(s)
		steps.append(v)
		v = int(s["version"])
	s["checksum"] = checksum(s)
	return [canon(s), steps]


static func validate(save: Dictionary) -> Array:
	var errs := []
	if save.get("format", "") != FORMAT:
		errs.append("format")
	if int(save.get("version", 0)) != CURRENT:
		errs.append("version %s != %d" % [str(save.get("version")), CURRENT])
	for layer in ["profile", "roster", "world"]:
		if typeof(save.get(layer)) != TYPE_DICTIONARY:
			errs.append("missing layer " + layer)
	if errs.is_empty() and str(save.get("checksum", "")) != checksum(save):
		errs.append("checksum mismatch")
	return errs


static func new_save(leader: String, fighters: Dictionary, pets: Array) -> Dictionary:
	var f := {}
	for k in fighters:
		f[k] = {"level": int(fighters[k]), "xp": 0}
	var s := {"format": FORMAT, "version": CURRENT,
		"profile": {"playtime_ticks": 0, "settings": {"palette_variant": "default", "input_remap": {}},
			"stats": {"encounters_won": 0, "bosses_defeated": 0}},
		"roster": {"leader": leader, "fighters": f, "pets": {"owned": pets.duplicate(), "assigned": {leader: pets.slice(0, 1)}}},
		"world": {"area": "", "cleared": [], "bosses_defeated": [], "inventory": {}, "quests": {}, "flags": {}}}
	s["checksum"] = checksum(s)
	return s


# --------------------------------------------------------------------------- disk

func path(slot: String = "slot0") -> String:
	return dir.path_join(slot + ".json")


func write(save: Dictionary, slot: String = "slot0") -> String:
	var s: Dictionary = canon(save)
	s["format"] = FORMAT
	s["version"] = CURRENT
	s["checksum"] = checksum(s)
	var p := path(slot)
	var tmp := p + ".tmp"
	var f := FileAccess.open(tmp, FileAccess.WRITE)
	if f == null:
		push_error("SaveSystem: cannot write %s" % tmp)
		return ""
	f.store_string(JSON.stringify(s, "  ", true))
	f.flush()
	f.close()
	if FileAccess.file_exists(p):
		DirAccess.copy_absolute(p, p + ".bak")
	DirAccess.rename_absolute(tmp, p)
	return s["checksum"]


func _read(p: String) -> Dictionary:
	if not FileAccess.file_exists(p):
		return {}
	var d = JSON.parse_string(FileAccess.get_file_as_string(p))
	return d if typeof(d) == TYPE_DICTIONARY else {}


## Load (+ migrate) a slot; falls back to the backup on a torn/tampered primary.
func load_slot(slot: String = "slot0") -> Dictionary:
	last_load = {"ok": false, "migrated_from": [], "recovered_from_backup": false, "errors": []}
	for candidate in [path(slot), path(slot) + ".bak"]:
		var raw := _read(candidate)
		if raw.is_empty():
			last_load["errors"].append("%s: unreadable" % candidate.get_file())
			continue
		if int(raw.get("version", 1)) == CURRENT and str(raw.get("checksum", "")) != checksum(raw):
			last_load["errors"].append("%s: checksum mismatch" % candidate.get_file())
			continue
		var m := migrate(raw)
		var s: Dictionary = m[0]
		if s.is_empty():
			last_load["errors"].append("%s: unsupported version" % candidate.get_file())
			continue
		var errs := validate(s)
		if not errs.is_empty():
			last_load["errors"].append("%s: %s" % [candidate.get_file(), ", ".join(errs)])
			continue
		last_load["ok"] = true
		last_load["migrated_from"] = m[1]
		last_load["recovered_from_backup"] = candidate.ends_with(".bak")
		return s
	return {}
