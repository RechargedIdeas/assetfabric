extends Node
## LiveChannel — game side of the F4 atomic hot-reload / live-tune protocol.
## Forge writes tickets (forge/live.py); this autoload polls HEAD, validates, and hands
## tickets to the active scene, which commits them at a tick boundary, probes, and acks.
## Everything is file based (no sockets): works headless, on desktop dev builds and in CI.
## Disabled in exported builds unless `--live-dir=` is passed explicitly.

const POLL_FRAMES := 6          # physics frames between HEAD polls (~10 Hz)

var dir := ""
var enabled := false
var allow_fault := false
var applied := 0                # last ticket handled (committed, rejected or rolled back)
var wal: Array = []             # session input log: [{tick, kind, payload}] (tickets, commands, swaps)
var acks: Array = []
var _frames := 0


func _ready() -> void:
	var explicit: String = str(Fabric.arg("live-dir", ""))
	# F7: exported builds (even debug APK/web) never open the channel implicitly — only the editor/dev runtime does.
	enabled = explicit != "" or (OS.has_feature("editor") and not Fabric.flag("no-live"))
	dir = explicit if explicit != "" else ProjectSettings.globalize_path("res://").path_join("../../.fabric/live/game-zero").simplify_path()
	allow_fault = Fabric.flag("allow-fault-injection")
	if enabled:
		DirAccess.make_dir_recursive_absolute(dir.path_join("acks"))
		# start after whatever is already on the channel unless asked to consume the backlog
		if not Fabric.flag("live-backlog"):
			applied = head()


func head() -> int:
	var p := dir.path_join("HEAD")
	if not FileAccess.file_exists(p):
		return 0
	var d = JSON.parse_string(FileAccess.get_file_as_string(p))
	return int(d["ticket"]) if typeof(d) == TYPE_DICTIONARY else 0


## Tickets newer than the last handled one, in order. Cheap when nothing changed.
func pending(force: bool = false) -> Array:
	if not enabled:
		return []
	if not force:
		_frames += 1
		if _frames % POLL_FRAMES != 0:
			return []
	var out := []
	var h := head()
	for n in range(applied + 1, h + 1):
		var p := dir.path_join("tickets/%d.json" % n)
		var t = JSON.parse_string(FileAccess.get_file_as_string(p)) if FileAccess.file_exists(p) else null
		if typeof(t) != TYPE_DICTIONARY:
			t = {"ticket": n, "_missing": true}
		out.append(t)
	return out


# --------------------------------------------------------------------------- validation (mirrors forge/live.py)

static func _path_matches(pattern: String, path: String) -> bool:
	var a := pattern.split(".")
	var b := path.split(".")
	if a.size() != b.size():
		return false
	for i in a.size():
		if a[i] != "*" and a[i] != b[i]:
			return false
	return true


static func rule_for(limits: Dictionary, path: String) -> Array:
	var best: Array = []
	var best_w := 999
	for pat in limits:
		if _path_matches(pat, path):
			var w: int = pat.count("*")
			if w < best_w:
				best_w = w
				best = limits[pat]
	return best


static func data_at(data, path: String):
	var node = data
	for seg in path.split("."):
		if typeof(node) == TYPE_ARRAY:
			if not seg.is_valid_int() or int(seg) >= node.size():
				return null
			node = node[int(seg)]
		elif typeof(node) == TYPE_DICTIONARY:
			if not node.has(seg):
				return null
			node = node[seg]
		else:
			return null
	return node


static func _is_num(v) -> bool:
	return typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT


func validate(t: Dictionary, game_data: Dictionary) -> String:
	if t.get("_missing", false):
		return "ticket file missing/corrupt"
	var limits: Dictionary = game_data.get("tune_limits", {})
	for p in t.get("patches", []):
		var path := str(p.get("path", ""))
		var v = p.get("value")
		if path == "":
			return "patch.path missing"
		if not _is_num(v) or is_nan(float(v)) or is_inf(float(v)):
			return "%s: value must be a finite number" % path
		var rng := rule_for(limits, path)
		if rng.is_empty():
			return "%s: not live-tunable" % path
		if float(v) < float(rng[0]) or float(v) > float(rng[1]):
			return "%s: %s outside [%s, %s]" % [path, str(v), str(rng[0]), str(rng[1])]
		if not path.begins_with("sim.") and not _is_num(data_at(game_data, path)):
			return "%s: no such numeric field" % path
	for a in t.get("assets", []):
		var ap := str(a.get("path", ""))
		if ap == "" or not FileAccess.file_exists(ap):
			return "asset %s: staged file missing" % a.get("id", "?")
		if FileAccess.get_sha256(ap) != str(a.get("sha256", "")):
			return "asset %s: sha256 mismatch (torn or tampered stage)" % a.get("id", "?")
		if Fabric.asset(str(a.get("id", ""))).is_empty():
			return "asset %s: unknown id (structural → forge build)" % a.get("id", "?")
	return ""


# --------------------------------------------------------------------------- data overlay (in memory only)

## Apply numeric patches to Fabric.game_data / Fabric.abilities. Returns {"sim": {...}} params.
func apply_data(t: Dictionary) -> Dictionary:
	var sim_params := {}
	for p in t.get("patches", []):
		var path := str(p["path"])
		var segs := path.split(".")
		if segs[0] == "sim":
			sim_params[segs[1]] = float(p["value"])
			continue
		var node = Fabric.game_data
		for i in segs.size() - 1:
			node = node[int(segs[i])] if typeof(node) == TYPE_ARRAY else node[segs[i]]
		var leaf: String = segs[segs.size() - 1]
		var cur = node[int(leaf)] if typeof(node) == TYPE_ARRAY else node[leaf]
		var v = int(p["value"]) if typeof(cur) == TYPE_INT else float(p["value"])
		if typeof(node) == TYPE_ARRAY:
			node[int(leaf)] = v
		else:
			node[leaf] = v
		if segs[0] == "abilities" and Fabric.abilities.has(segs[1]):
			var ab: Dictionary = Fabric.abilities[segs[1]]
			ab[leaf] = int(p["value"]) if typeof(ab.get(leaf)) == TYPE_INT else float(p["value"])
	for a in t.get("assets", []):
		Fabric.override_file(str(a["id"]), str(a["file"]), str(a["path"]))
	return {"sim": sim_params}


func backup() -> Dictionary:
	return {"game_data": Fabric.game_data.duplicate(true), "abilities": Fabric.abilities.duplicate(true),
		"registry": Fabric.registry.duplicate(true)}


func restore_backup(b: Dictionary) -> void:
	Fabric.game_data = b["game_data"]
	# keep the same ability Dictionary objects alive (entities hold references): copy values back
	for id in b["abilities"]:
		if Fabric.abilities.has(id):
			var cur: Dictionary = Fabric.abilities[id]
			for k in b["abilities"][id]:
				cur[k] = b["abilities"][id][k]
	Fabric.registry = b["registry"]
	Fabric.clear_caches()


# --------------------------------------------------------------------------- acks / status / WAL

func _atomic_write(path: String, data: Dictionary) -> void:
	var tmp := path + ".tmp"
	var f := FileAccess.open(tmp, FileAccess.WRITE)
	if f == null:
		push_error("LiveChannel: cannot write %s" % tmp)
		return
	f.store_string(JSON.stringify(data, "", true, true))
	f.close()
	DirAccess.rename_absolute(tmp, path)


func ack(t: Dictionary, status: String, extra: Dictionary = {}) -> Dictionary:
	var n := int(t.get("ticket", 0))
	applied = maxi(applied, n)
	var a := {"ticket": n, "status": status, "source": t.get("source", "")}
	a.merge(extra)
	acks.append(a)
	if enabled:
		_atomic_write(dir.path_join("acks/%d.json" % n), a)
		end_flight()
	return a


func status(d: Dictionary) -> void:
	if enabled:
		_atomic_write(dir.path_join("status.json"), d)


## Crash safety (F4 guardian): mark a ticket in flight before commit; a restart that finds an
## in-flight ticket with no ack quarantines it instead of re-applying a poison ticket.
func begin(n: int) -> void:
	if enabled:
		_atomic_write(dir.path_join("inflight.json"), {"ticket": n, "pid": Fabric.pid()})


func end_flight() -> void:
	if enabled and FileAccess.file_exists(dir.path_join("inflight.json")):
		DirAccess.remove_absolute(dir.path_join("inflight.json"))


func read_json_file(rel: String) -> Dictionary:
	var p := dir.path_join(rel)
	if not FileAccess.file_exists(p):
		return {}
	var d = JSON.parse_string(FileAccess.get_file_as_string(p))
	return d if typeof(d) == TYPE_DICTIONARY else {}


func read_ack(n: int) -> Dictionary:
	return read_json_file("acks/%d.json" % n)


func read_ticket(n: int) -> Dictionary:
	return read_json_file("tickets/%d.json" % n)


## Returns the quarantined ticket number (0 if nothing was in flight).
func quarantine_inflight() -> int:
	var f := read_json_file("inflight.json")
	if f.is_empty():
		return 0
	var n := int(f["ticket"])
	if read_ack(n).is_empty():
		ack(read_ticket(n) if not read_ticket(n).is_empty() else {"ticket": n}, "quarantined",
			{"reason": "process died while this ticket was in flight (pid %s)" % str(f.get("pid", "?"))})
	end_flight()
	return n


func write_file(rel: String, d: Dictionary) -> String:
	var p := dir.path_join(rel)
	DirAccess.make_dir_recursive_absolute(p.get_base_dir())
	_atomic_write(p, d)
	return p


func log_input(tick: int, kind: String, payload) -> void:
	wal.append({"tick": tick, "kind": kind, "payload": payload})
