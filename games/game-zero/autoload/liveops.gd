extends Node
## LiveOps (F9 — readiness only; ASSETFABRIC_SPEC §12 "remote config / feature flags", GAME_SPEC §8 "remote config
## hooks for balance knobs"). Game side of forge/liveops.py — same payload rules, same signature bytes.
##
## Offline-first by construction (G-NET-01): this node only reads and writes LOCAL files. Nothing here (or anywhere in
## the game) fetches a bundle; a bundle arrives inside a platform update or is dropped by `forge liveops install`.
##
## Device state machine, every boot (dir = user://liveops, or `--liveops-dir=` for tools/tests):
##  1. crash guard — `boot.json` is written when an active bundle is applied and removed on a clean exit; finding it
##     again means the previous boot died. After MAX_BOOT_FAILS such boots the bundle is quarantined and
##     `previous.json` (the last good one) is restored.
##  2. inbox — `inbox.json` is verified (pinned RSA key, payload rules, serial > max seen); good → `active.json`
##     (old active kept as `previous.json`), bad → `rejected/`. Without a pinned key the inbox is left untouched and
##     every bundle is ignored.
##  3. active — `active.json` is re-verified (on-disk tamper → safe defaults) and applied: kill-switch flags, then
##     balance patches through the F4 LiveChannel validator/overlay (in memory only — never written into a save).
## No bundle / any failure = the manifest defaults = exactly the shipped 0.8.0 behaviour.

const MANIFEST_PATH := "res://assets/generated/liveops/liveops.json"
const PUBKEY_PATH := "res://data/liveops/pubkey.pem"    # pinned by the Producer key ceremony; absent until then

var manifest: Dictionary = {}
var dir := ""
var flags: Dictionary = {}          # effective flag values
var consent: Dictionary = {}        # player decisions (consent flags), never from a bundle
var report: Dictionary = {}         # what happened this boot (printed by tools/liveopscheck, written to status.json)
var active_payload: Dictionary = {}
var _key: CryptoKey = null
var _key_id := ""
var _patches: Array = []            # applied balance patches (re-applied when Fabric reloads its game data)
var _sentinel := false


func _ready() -> void:
	var m = Fabric.read_json(MANIFEST_PATH) if FileAccess.file_exists(MANIFEST_PATH) else null
	manifest = m if typeof(m) == TYPE_DICTIONARY else {"flags": {}, "knobs": {}}
	var d := str(Fabric.arg("liveops-dir", ""))
	dir = d if d != "" else ProjectSettings.globalize_path("user://liveops")
	boot()


func defaults() -> Dictionary:
	var out := {}
	for n in manifest.get("flags", {}):
		out[n] = bool(manifest["flags"][n]["default"])
	return out


## Kill switch / consent value. Unknown flags read as off.
func enabled(name: String) -> bool:
	return bool(flags.get(name, false))


func _p(rel: String) -> String:
	return dir.path_join(rel)


func _read(rel: String) -> Variant:
	if not FileAccess.file_exists(_p(rel)):
		return null
	return JSON.parse_string(FileAccess.get_file_as_string(_p(rel)))


func _write(rel: String, data) -> void:
	DirAccess.make_dir_recursive_absolute(_p(rel).get_base_dir())
	var tmp := _p(rel) + ".tmp"
	var f := FileAccess.open(tmp, FileAccess.WRITE)
	if f == null:
		push_error("LiveOps: cannot write %s" % tmp)
		return
	f.store_string(data if typeof(data) == TYPE_STRING else JSON.stringify(data, "", true))
	f.close()
	DirAccess.rename_absolute(tmp, _p(rel))


func _move(rel: String, to_rel: String) -> void:
	DirAccess.make_dir_recursive_absolute(_p(to_rel).get_base_dir())
	if FileAccess.file_exists(_p(to_rel)):
		DirAccess.remove_absolute(_p(to_rel))
	DirAccess.rename_absolute(_p(rel), _p(to_rel))


# --------------------------------------------------------------------------- key

func _load_key() -> String:
	var path := PUBKEY_PATH
	# debug builds (editor, CI, debug exports) may pin a test key; release builds only trust the shipped key
	if OS.is_debug_build() and str(Fabric.arg("liveops-pubkey", "")) != "":
		path = str(Fabric.arg("liveops-pubkey", ""))
	if not FileAccess.file_exists(path):
		return "none"
	var pem := FileAccess.get_file_as_string(path)
	var k := CryptoKey.new()
	if k.load_from_string(pem, true) != OK:
		return "unreadable"
	_key = k
	_key_id = key_id(pem)
	return "pinned"


static func _sha256_hex(b: PackedByteArray) -> String:
	var h := HashingContext.new()
	h.start(HashingContext.HASH_SHA256)
	h.update(b)
	return h.finish().hex_encode()


static func key_id(pem: String) -> String:
	var body := ""
	for line in pem.strip_edges().split("\n"):
		var l := line.strip_edges()
		if l != "" and not l.begins_with("-----"):
			body += l
	return _sha256_hex(Marshalls.base64_to_raw(body)).substr(0, 16)


# --------------------------------------------------------------------------- verification (mirrors forge/liveops.py)

static func version_tuple(v: String) -> Array:
	var core := v.split("+")[0].split("-")[0]
	var out := []
	for p in core.split("."):
		out.append(int(p) if p.is_valid_int() else 0)
	while out.size() < 3:
		out.append(0)
	return out.slice(0, 3)


static func _ver_lt(a: Array, b: Array) -> bool:
	for i in 3:
		if a[i] != b[i]:
			return a[i] < b[i]
	return false


func build_version() -> String:
	return str(ProjectSettings.get_setting("application/config/version", "0.0.0"))


## Returns [payload, errors]. `min_serial`: the payload's serial must be strictly greater (anti-replay/downgrade).
func verify_bundle(text: String, min_serial: int) -> Array:
	var b = JSON.parse_string(text)
	if typeof(b) != TYPE_DICTIONARY or str(b.get("format", "")) != str(manifest.get("signed_format", "")) \
			or str(b.get("alg", "")) != str(manifest.get("alg", "")):
		return [{}, ["not a gamezero-liveops-signed bundle"]]
	if _key == null:
		return [{}, ["no pinned key"]]
	if str(b.get("key_id", "")) != _key_id:
		return [{}, ["key_id %s does not match the pinned key %s" % [str(b.get("key_id", "")), _key_id]]]
	var body: PackedByteArray = str(b.get("payload", "")).to_utf8_buffer()
	if body.size() > int(manifest.get("max_payload_bytes", 65536)):
		return [{}, ["payload too large"]]
	var sig := Marshalls.base64_to_raw(str(b.get("sig", "")))
	var h := HashingContext.new()
	h.start(HashingContext.HASH_SHA256)
	h.update(body)
	if sig.is_empty() or not Crypto.new().verify(HashingContext.HASH_SHA256, h.finish(), sig, _key):
		return [{}, ["signature invalid"]]
	var payload = JSON.parse_string(str(b["payload"]))
	var errs := validate_payload(payload, min_serial)
	return [payload if errs.is_empty() else {}, errs]


const PAYLOAD_KEYS := ["format", "schema", "serial", "channel", "build_min", "build_max", "issued", "flags", "patches", "notes"]
const REQUIRED_KEYS := ["format", "schema", "serial", "build_min", "flags", "patches"]


func validate_payload(p, min_serial: int) -> Array:
	if typeof(p) != TYPE_DICTIONARY:
		return ["payload is not an object"]
	var errs := []
	for k in p:
		if not PAYLOAD_KEYS.has(k):
			errs.append("unknown key %s (bundles carry flags + balance patches only)" % k)
	for k in REQUIRED_KEYS:
		if not p.has(k):
			errs.append("missing key %s" % k)
	if not errs.is_empty():
		return errs
	if str(p["format"]) != str(manifest.get("bundle_format", "")) or int(p["schema"]) != int(manifest.get("bundle_schema", -1)):
		errs.append("format/schema not supported")
	var serial = p["serial"]
	if typeof(serial) not in [TYPE_INT, TYPE_FLOAT] or float(serial) != floorf(float(serial)) or int(serial) < 1:
		errs.append("serial must be an int >= 1")
	elif int(serial) <= min_serial:
		errs.append("serial %d is not newer than %d (replay/downgrade)" % [int(serial), min_serial])
	if p.has("channel") and not manifest.get("channels", []).has(str(p["channel"])):
		errs.append("channel %s unknown" % str(p["channel"]))
	var v := version_tuple(build_version())
	if _ver_lt(v, version_tuple(str(p["build_min"]))):
		errs.append("build_min %s > build %s" % [str(p["build_min"]), build_version()])
	if p.has("build_max") and _ver_lt(version_tuple(str(p["build_max"])), v):
		errs.append("build_max %s < build %s" % [str(p["build_max"]), build_version()])
	if typeof(p["flags"]) != TYPE_DICTIONARY:
		errs.append("flags must be an object")
	else:
		for n in p["flags"]:
			var spec = manifest["flags"].get(n)
			if spec == null:
				errs.append("flag %s: unknown" % n)
			elif str(spec["kind"]) == "consent":
				errs.append("flag %s: consent is the player's decision, a bundle cannot set it" % n)
			elif typeof(p["flags"][n]) != TYPE_BOOL:
				errs.append("flag %s: value must be a bool" % n)
	if typeof(p["patches"]) != TYPE_ARRAY:
		errs.append("patches must be a list")
	else:
		if p["patches"].size() > int(manifest.get("max_patches", 256)):
			errs.append("too many patches")
		for patch in p["patches"]:
			if typeof(patch) != TYPE_DICTIONARY or str(patch.get("path", "")) == "":
				errs.append("patch.path missing")
			elif str(patch["path"]).begins_with("sim."):
				errs.append("%s: sim.* knobs are dev-only live tune, not remote config" % patch["path"])
		if errs.is_empty():
			# same validator as the F4 LiveChannel (ranges + numeric field exists), against the remote-config knob table
			var gd: Dictionary = Fabric.game_data.duplicate(false)
			gd["tune_limits"] = manifest.get("knobs", {})
			var e: String = Live.validate({"patches": p["patches"]}, gd)
			if e != "":
				errs.append(e)
	return errs


# --------------------------------------------------------------------------- boot state machine

func boot() -> void:
	flags = defaults()
	consent = _load_consent()
	for n in consent:
		flags[n] = consent[n]
	active_payload = {}
	_patches = []
	var key_state := _load_key()
	report = {"key": key_state, "source": "defaults", "serial": 0, "inbox": "none", "rejected": [], "quarantined": 0,
		"active_invalid": [], "previous_boot_crashed": false, "patches_applied": 0, "errors": []}
	var st = _read("state.json")
	var state: Dictionary = st if typeof(st) == TYPE_DICTIONARY else {"max_serial": 0}
	# 1. crash guard
	var sen = _read("boot.json")
	if typeof(sen) == TYPE_DICTIONARY:
		report["previous_boot_crashed"] = true
		var act_serial := _serial_of("active.json")
		if act_serial > 0 and int(sen.get("serial", 0)) == act_serial and int(sen.get("count", 0)) >= int(manifest.get("max_boot_fails", 2)):
			_move("active.json", "quarantine/%d.json" % act_serial)
			report["quarantined"] = act_serial
			if FileAccess.file_exists(_p("previous.json")):
				_move("previous.json", "active.json")
			state["active_serial"] = _serial_of("active.json")
			_write("state.json", state)
			DirAccess.remove_absolute(_p("boot.json"))
			sen = null
	# 2. inbox
	if FileAccess.file_exists(_p("inbox.json")):
		if _key == null:
			report["inbox"] = "ignored_no_key"
		else:
			var r := verify_bundle(FileAccess.get_file_as_string(_p("inbox.json")), int(state.get("max_serial", 0)))
			if r[1].is_empty():
				if FileAccess.file_exists(_p("active.json")):
					_move("active.json", "previous.json")
				_move("inbox.json", "active.json")
				state["max_serial"] = int(r[0]["serial"])
				state["active_serial"] = int(r[0]["serial"])
				_write("state.json", state)
				report["inbox"] = "promoted"
				sen = null
				if FileAccess.file_exists(_p("boot.json")):
					DirAccess.remove_absolute(_p("boot.json"))
			else:
				var n := _serial_unverified(FileAccess.get_file_as_string(_p("inbox.json")))
				_move("inbox.json", "rejected/%d-%d.json" % [n, Time.get_ticks_usec()])
				report["inbox"] = "rejected"
				report["rejected"] = r[1]
	# 3. active
	if FileAccess.file_exists(_p("active.json")) and _key != null:
		# the active bundle passed the serial check when it was promoted; here signature + rules again, and it must be the
		# bundle the state machine put there (an older, validly signed file swapped in on disk is a downgrade)
		var r2 := verify_bundle(FileAccess.get_file_as_string(_p("active.json")), 0)
		if r2[1].is_empty() and state.has("active_serial") and int(r2[0]["serial"]) != int(state["active_serial"]):
			r2 = [{}, ["active serial %d is not the promoted serial %d (swapped on disk)" % [int(r2[0]["serial"]), int(state["active_serial"])]]]
		if r2[1].is_empty():
			_apply(r2[0])
			report["source"] = "bundle"
			report["serial"] = int(r2[0]["serial"])
			var count := (int(sen.get("count", 0)) if typeof(sen) == TYPE_DICTIONARY and int(sen.get("serial", 0)) == report["serial"] else 0) + 1
			_write("boot.json", {"serial": report["serial"], "count": count})
			_sentinel = true
			if int(state.get("max_serial", 0)) < report["serial"] or not state.has("active_serial"):
				state["max_serial"] = maxi(int(state.get("max_serial", 0)), report["serial"])
				state["active_serial"] = report["serial"]
				_write("state.json", state)
		else:
			report["active_invalid"] = r2[1]          # tamper on disk / build no longer compatible → safe defaults
	report["flags"] = flags.duplicate()
	report["max_serial"] = int(state.get("max_serial", 0))
	if DirAccess.dir_exists_absolute(dir):
		_write("status.json", report)
	if enabled("diagnostics"):
		write_diagnostics()


func _serial_of(rel: String) -> int:
	if not FileAccess.file_exists(_p(rel)):
		return 0
	return _serial_unverified(FileAccess.get_file_as_string(_p(rel)))


static func _serial_unverified(text: String) -> int:
	var b = JSON.parse_string(text)
	if typeof(b) != TYPE_DICTIONARY:
		return 0
	var p = JSON.parse_string(str(b.get("payload", "")))
	return int(p.get("serial", 0)) if typeof(p) == TYPE_DICTIONARY and typeof(p.get("serial")) in [TYPE_INT, TYPE_FLOAT] else 0


func _apply(p: Dictionary) -> void:
	active_payload = p
	for n in p["flags"]:
		flags[n] = bool(p["flags"][n])
	if enabled("remote_balance") and not p["patches"].is_empty():
		_patches = p["patches"].duplicate(true)
		Live.apply_data({"patches": _patches})
		report["patches_applied"] = _patches.size()


## Fabric reloads its game data (F4 live tune / forge build hot reload): put the remote-config overlay back on top.
func reapply() -> void:
	if not _patches.is_empty():
		Live.apply_data({"patches": _patches})


func _exit_tree() -> void:
	if _sentinel and not (OS.is_debug_build() and Fabric.flag("liveops-simulate-crash")):
		DirAccess.remove_absolute(_p("boot.json"))


## QA hook (debug builds only): die after boot as a crashing bundle would (the sentinel stays behind).
func simulate_crash_if_asked() -> void:
	if OS.is_debug_build() and Fabric.flag("liveops-simulate-crash"):
		OS.crash("LiveOps QA: simulated crash after applying bundle %d" % int(report.get("serial", 0)))


# --------------------------------------------------------------------------- consent + diagnostics (local only)

## Player consent lives in `consent.json` next to the bundles (written by the game's settings, never by a bundle);
## debug builds may also pass `--diagnostics=on`. Default: off.
func _load_consent() -> Dictionary:
	var out := {}
	var c = _read("consent.json")
	for n in manifest.get("flags", {}):
		if str(manifest["flags"][n]["kind"]) != "consent":
			continue
		out[n] = typeof(c) == TYPE_DICTIONARY and c.get(n) == true
		if OS.is_debug_build() and str(Fabric.arg(n, "")) == "on":
			out[n] = true
	return out


func set_consent(name: String, on: bool) -> void:
	var c = _read("consent.json")
	var d: Dictionary = c if typeof(c) == TYPE_DICTIONARY else {}
	d[name] = on
	_write("consent.json", d)
	consent[name] = on
	flags[name] = on


## Local session record (opt-in). No paths, no user/host names, no ids — `forge liveops diag-export` scrubs anyway.
func write_diagnostics() -> String:
	if not enabled("diagnostics"):
		return ""
	var rec := {"format": "gamezero-diag-session", "schema": 1, "build": build_version(), "platform": Fabric.platform_id(),
		"engine": Engine.get_version_info()["string"], "liveops": {"source": report.get("source"), "serial": report.get("serial"),
		"inbox": report.get("inbox"), "quarantined": report.get("quarantined")},
		"previous_boot_crashed": report.get("previous_boot_crashed", false), "flags": flags.duplicate()}
	_write("diag/session.json", rec)
	return _p("diag/session.json")
