extends Node
## Fabric autoload — runtime binding to AssetFabric output (F1).
## Reads assets/generated/fabric_assets.json (written by `forge build`), loads
## PNG/JSON at runtime (no editor import step → headless-provable, hot-reloadable),
## registers the abstract input schema and locale tables.

const REGISTRY_PATH := "res://assets/generated/fabric_assets.json"
const LOCALE_DIR := "res://locale"
const GAME_DATA_PATH := "res://data/generated/game_data.json"

## Abstract input schema (GAME_SPEC §3): one map for keyboard + controller. G-A11Y-01 (0.7.10): every action the
## game reads is here (no hard-coded keys in scenes), each with keyboard keys, gamepad buttons and gamepad axes, and every
## one is rebindable in the in-game Settings screen. Binding tokens (also the save format, `profile.settings.input_remap`):
## a key name ("F", "Shift", as OS.find_keycode_from_string), "pad:<JoyButton index>", "axis:<JoyAxis index>:+|-".
const INPUT_SCHEMA := {
	"move_left": {"keys": [KEY_A, KEY_LEFT], "pad": [JOY_BUTTON_DPAD_LEFT], "axes": [[JOY_AXIS_LEFT_X, -1]]},
	"move_right": {"keys": [KEY_D, KEY_RIGHT], "pad": [JOY_BUTTON_DPAD_RIGHT], "axes": [[JOY_AXIS_LEFT_X, 1]]},
	"move_up": {"keys": [KEY_W, KEY_UP], "pad": [JOY_BUTTON_DPAD_UP], "axes": [[JOY_AXIS_LEFT_Y, -1]]},
	"move_down": {"keys": [KEY_S, KEY_DOWN], "pad": [JOY_BUTTON_DPAD_DOWN], "axes": [[JOY_AXIS_LEFT_Y, 1]]},
	"attack": {"keys": [KEY_J, KEY_SPACE], "pad": [JOY_BUTTON_X]},
	"skill": {"keys": [KEY_K], "pad": [JOY_BUTTON_Y]},
	"swap": {"keys": [KEY_TAB], "pad": [JOY_BUTTON_RIGHT_SHOULDER]},
	"interact": {"keys": [KEY_E], "pad": [JOY_BUTTON_A]},
	"use_salve": {"keys": [KEY_H], "pad": [JOY_BUTTON_B]},
	"tactic_menu": {"keys": [KEY_Q], "pad": [JOY_BUTTON_LEFT_SHOULDER]},
	"command": {"keys": [KEY_SLASH], "pad": []},
	"restart": {"keys": [KEY_R], "pad": [JOY_BUTTON_BACK]},
	"settings": {"keys": [KEY_ESCAPE, KEY_F10], "pad": [JOY_BUTTON_START]},
	"swap_pick_1": {"keys": [KEY_1], "pad": [JOY_BUTTON_DPAD_UP]},
	"swap_pick_2": {"keys": [KEY_2], "pad": [JOY_BUTTON_DPAD_RIGHT]},
	"swap_pick_3": {"keys": [KEY_3], "pad": [JOY_BUTTON_DPAD_DOWN]},
	"swap_pick_4": {"keys": [KEY_4], "pad": [JOY_BUTTON_DPAD_LEFT]},
}
## Order of the rows on the Settings screen.
const ACTION_ORDER := ["move_up", "move_down", "move_left", "move_right", "attack", "skill", "interact", "use_salve",
	"swap", "swap_pick_1", "swap_pick_2", "swap_pick_3", "swap_pick_4", "tactic_menu", "command", "restart", "settings"]
## Actions that are read at the same time must not share a binding; rebinding a token that another action of the same
## context already uses *swaps* the two (the other action gets this action's previous binding of that kind).
## Freeze-time picks reuse the d-pad on purpose: movement is not read while time is frozen.
const CONTEXTS := {
	"play": ["move_up", "move_down", "move_left", "move_right", "attack", "skill", "interact", "use_salve", "swap",
		"tactic_menu", "command", "restart", "settings"],
	"freeze": ["swap", "swap_pick_1", "swap_pick_2", "swap_pick_3", "swap_pick_4", "settings"],
}
const AXIS_DEADZONE := 0.5
const UI_PAD := {"ui_accept": ["pad:0"], "ui_cancel": ["pad:1"], "ui_up": ["pad:11", "axis:1:-"], "ui_down": ["pad:12", "axis:1:+"],
	"ui_left": ["pad:13", "axis:0:-"], "ui_right": ["pad:14", "axis:0:+"]}

var registry: Dictionary = {}
var args: Dictionary = {}
var _tex_cache: Dictionary = {}
var game_data: Dictionary = {}
var abilities: Dictionary = {}   # id -> Dictionary, loaded from codegen .tres resources
var _audio_cache: Dictionary = {}


func _ready() -> void:
	args = _parse_args()
	_register_inputs()
	_load_locales()
	reload_registry()
	if flag("autoplay") and DisplayServer.get_name() == "headless":
		_start_watchdog(float(arg("watchdog", "30")))


## Headless runs must never hang CI: quit(3) if no result after N seconds.
func _start_watchdog(seconds: float) -> void:
	var t := Timer.new()
	t.one_shot = true
	t.wait_time = seconds
	t.timeout.connect(func():
		print("FABRIC_WATCHDOG timeout after %.0fs" % seconds)
		get_tree().quit(3))
	add_child(t)
	t.start()


func _parse_args() -> Dictionary:
	var out := {}
	for a in OS.get_cmdline_user_args():
		var s: String = a.trim_prefix("--")
		if "=" in s:
			var kv := s.split("=", true, 1)
			out[kv[0]] = kv[1]
		else:
			out[s] = true
	return out


## Process id for diagnostics; the Web platform has none (returns -1 instead of erroring).
func pid() -> int:
	return -1 if OS.has_feature("web") else OS.get_process_id()


## Platform label used in cross-platform reports (F7): desktop / android / web.
func platform_id() -> String:
	if OS.has_feature("web"):
		return "web"
	if OS.has_feature("android"):
		return "android"
	return "desktop"


## G-NET-01: Game Zero v1 is solo/offline. Nothing in the game opens a socket; the multiplayer API stays
## on Godot's OfflineMultiplayerPeer. This report is printed by the F7 acceptance on every target.
func net_report() -> Dictionary:
	var peer := get_tree().get_multiplayer().multiplayer_peer
	return {"peer": peer.get_class() if peer else "null", "offline_peer": peer is OfflineMultiplayerPeer,
		"has_multiplayer_peer": get_tree().get_multiplayer().has_multiplayer_peer(), "platform": platform_id()}


## G-A11Y-01: `profile.settings.input_remap` = {action: [token, ...]} (tokens: see INPUT_SCHEMA). Keyboard tokens replace
## that action's keyboard events; pad/axis tokens replace its gamepad events; a kind that is not mentioned keeps its
## defaults (so F7-era keyboard-only remaps load unchanged). Unknown actions / tokens are skipped and reported.
## Empty remap restores INPUT_SCHEMA.
var input_remap_applied: Dictionary = {}
var _remap: Dictionary = {}      # action -> tokens (only actions that differ from the schema)
var last_device := "keys"        # "keys" | "pad" — which binding the on-screen hints show

func default_tokens(action: String) -> Array:
	var d: Dictionary = INPUT_SCHEMA[action]
	var out := []
	for k in d.get("keys", []):
		out.append(OS.get_keycode_string(k))
	for b in d.get("pad", []):
		out.append("pad:%d" % b)
	for a in d.get("axes", []):
		out.append("axis:%d:%s" % [a[0], "+" if a[1] > 0 else "-"])
	return out


static func is_pad_token(t: String) -> bool:
	return t.begins_with("pad:") or t.begins_with("axis:")


## Token -> InputEvent (null if the token is not valid).
static func token_event(t: String) -> InputEvent:
	if t.begins_with("pad:"):
		var i := int(t.substr(4))
		if not t.substr(4).is_valid_int() or i < 0 or i >= JOY_BUTTON_MAX:
			return null
		var b := InputEventJoypadButton.new()
		b.button_index = i
		return b
	if t.begins_with("axis:"):
		var p := t.split(":")
		if p.size() != 3 or not p[1].is_valid_int() or not (p[2] == "+" or p[2] == "-") or int(p[1]) < 0 or int(p[1]) >= JOY_AXIS_MAX:
			return null
		var m := InputEventJoypadMotion.new()
		m.axis = int(p[1])
		m.axis_value = 1.0 if p[2] == "+" else -1.0
		return m
	var code := OS.find_keycode_from_string(t)
	if code == KEY_NONE:
		return null
	var ev := InputEventKey.new()
	ev.physical_keycode = code
	return ev


## InputEvent -> token ("" if it cannot be a binding). Used by the rebinding screen.
static func event_token(ev: InputEvent) -> String:
	if ev is InputEventKey:
		var code: int = ev.physical_keycode if ev.physical_keycode != KEY_NONE else ev.keycode
		return OS.get_keycode_string(code) if code != KEY_NONE else ""
	if ev is InputEventJoypadButton:
		return "pad:%d" % ev.button_index
	if ev is InputEventJoypadMotion and absf(ev.axis_value) >= AXIS_DEADZONE:
		return "axis:%d:%s" % [ev.axis, "+" if ev.axis_value > 0 else "-"]
	return ""


## Current tokens of an action (defaults merged with the remap).
func bindings(action: String) -> Array:
	if not INPUT_SCHEMA.has(action):
		return []
	var d := default_tokens(action)
	if not _remap.has(action):
		return d
	var r: Array = _remap[action]
	var has_keys := r.any(func(t): return not is_pad_token(t))
	var has_pad := r.any(func(t): return is_pad_token(t))
	var out := []
	for t in (r if has_keys else d):
		if not is_pad_token(t):
			out.append(t)
	for t in (r if has_pad else d):
		if is_pad_token(t):
			out.append(t)
	return out


func _install(action: String, tokens: Array) -> void:
	InputMap.action_erase_events(action)
	for t in tokens:
		var ev := token_event(str(t))
		if ev:
			InputMap.action_add_event(action, ev)


func apply_input_remap(remap: Dictionary) -> Dictionary:
	var rep := {"applied": {}, "skipped": []}
	_remap = {}
	for action in remap:
		if not INPUT_SCHEMA.has(action):
			rep["skipped"].append(str(action))
			continue
		if typeof(remap[action]) != TYPE_ARRAY:
			rep["skipped"].append(str(action))
			continue
		var ok := []
		for t in remap[action]:
			if token_event(str(t)) == null:
				rep["skipped"].append("%s:%s" % [action, t])
			else:
				ok.append(str(t))
		if not ok.is_empty():
			_remap[action] = ok
			rep["applied"][action] = ok
	for action in INPUT_SCHEMA:
		_install(action, bindings(action))
	input_remap_applied = rep
	return rep


## The remap to persist: only actions whose bindings differ from the schema, as full token lists.
func current_remap() -> Dictionary:
	var out := {}
	for action in INPUT_SCHEMA:
		var b := bindings(action)
		if b != default_tokens(action):
			out[action] = b
	return out


## Rebind (Settings screen): `token` becomes the action's binding of its kind (keyboard or gamepad). If another action of a
## shared context already uses the token, the two swap. Returns {"action", "token", "swapped_with", "previous"}.
func rebind(action: String, token: String) -> Dictionary:
	var pad := is_pad_token(token)
	var cur := bindings(action)
	var prev := ""
	for t in cur:
		if is_pad_token(t) == pad:
			prev = t
			break
	var swapped := ""
	for ctx in CONTEXTS.values():
		if not ctx.has(action):
			continue
		for other in ctx:
			if other == action or swapped != "":
				continue
			var ob := bindings(other)
			if ob.has(token):
				ob.erase(token)
				if prev != "" and not ob.has(prev):
					ob.append(prev)
				_remap[other] = ob
				swapped = other
	var mine := []
	for t in cur:
		if is_pad_token(t) != pad:
			mine.append(t)
	if pad:
		mine.append(token)
	else:
		mine.push_front(token)
	_remap[action] = mine
	for a in INPUT_SCHEMA:
		_install(a, bindings(a))
	_remap = current_remap()
	input_remap_applied = {"applied": _remap.duplicate(true), "skipped": []}
	return {"action": action, "token": token, "swapped_with": swapped, "previous": prev}


func reset_bindings() -> void:
	apply_input_remap({})


## Keys currently bound to an action (for reports / the remap round-trip check).
func action_keys(action: String) -> Array:
	var out := []
	for ev in InputMap.action_get_events(action):
		if ev is InputEventKey:
			out.append(OS.get_keycode_string(ev.physical_keycode))
	return out


## Every token currently installed in the InputMap for an action (keys + pad), for reports.
func action_tokens(action: String) -> Array:
	var out := []
	for ev in InputMap.action_get_events(action):
		var t := event_token(ev)
		if t != "":
			out.append(t)
	return out


## Short label for a token, localised ("F", "Pad A", "L-stick ←").
func token_label(t: String) -> String:
	if t.begins_with("pad:"):
		var k := "input.pad.%s" % t.substr(4)
		var s := tr(k)
		return s if s != k else tr("input.pad.generic") % t.substr(4)
	if t.begins_with("axis:"):
		var k2 := "input.axis.%s" % t.substr(5).replace(":", "")
		var s2 := tr(k2)
		return s2 if s2 != k2 else t
	return t


## Label of an action's current binding for on-screen hints (keyboard, or gamepad after a pad press).
func binding_label(action: String) -> String:
	var b := bindings(action)
	for t in b:
		if is_pad_token(t) == (last_device == "pad"):
			return token_label(t)
	return token_label(b[0]) if not b.is_empty() else "—"


## Locale string with `{action}` placeholders replaced by the current binding labels (hints follow rebinding).
func hint(key: String) -> String:
	var labels := {}
	for action in INPUT_SCHEMA:
		labels[action] = binding_label(action)
	return tr(key).format(labels)


func _input(event: InputEvent) -> void:
	if event is InputEventJoypadButton or (event is InputEventJoypadMotion and absf(event.axis_value) >= AXIS_DEADZONE):
		last_device = "pad"
	elif event is InputEventKey:
		last_device = "keys"


func flag(name: String) -> bool:
	return args.has(name)


func arg(name: String, default_value: Variant = null) -> Variant:
	return args.get(name, default_value)


func _register_inputs() -> void:
	for action in INPUT_SCHEMA:
		if not InputMap.has_action(action):
			InputMap.add_action(action, AXIS_DEADZONE)
		_install(action, default_tokens(action))
	# Menus (Settings, select): make sure Godot's ui_* actions answer the gamepad too — d-pad + left stick navigate,
	# A accepts, B cancels — whatever the engine defaults are on this platform.
	for ui in UI_PAD:
		for t in UI_PAD[ui]:
			var ev := token_event(t)
			if ev and not InputMap.action_has_event(ui, ev):
				InputMap.action_add_event(ui, ev)


func _load_locales() -> void:
	var dir := DirAccess.open(LOCALE_DIR)
	if dir == null:
		return
	for f in dir.get_files():
		if not f.ends_with(".json"):
			continue
		var data = read_json(LOCALE_DIR + "/" + f)
		if typeof(data) != TYPE_DICTIONARY:
			continue
		var t := Translation.new()
		t.locale = f.get_basename()
		for k in data:
			t.add_message(k, str(data[k]))
		TranslationServer.add_translation(t)


func read_json(path: String) -> Variant:
	var fa := FileAccess.open(path, FileAccess.READ)
	if fa == null:
		push_error("Fabric: cannot open %s" % path)
		return null
	return JSON.parse_string(fa.get_as_text())


func reload_registry() -> void:
	var data = read_json(REGISTRY_PATH)
	registry = data if typeof(data) == TYPE_DICTIONARY else {"assets": {}}
	_tex_cache.clear()
	_audio_cache.clear()
	_load_game_data()


func _load_game_data() -> void:
	game_data = {}
	abilities = {}
	if not FileAccess.file_exists(GAME_DATA_PATH):
		return
	game_data = read_json(GAME_DATA_PATH)
	for id in game_data.get("abilities", {}):
		var res = load(game_data["abilities"][id]["tres"])
		if res == null:
			push_error("Fabric: missing ability resource %s" % id)
			abilities[id] = game_data["abilities"][id]
		else:
			abilities[id] = res.to_dict()
	# F9: a remote-config overlay (LiveOps) survives a game-data reload (F4 hot reload / forge build)
	var lo := get_node_or_null("/root/LiveOps")
	if lo != null:
		lo.reapply()


## Runtime WAV loader (Godot 4.3 has no AudioStreamWAV.load_from_file).
func audio(id: String, file_name: String) -> AudioStreamWAV:
	var path := file_path(id, file_name)
	if path == "":
		return null
	if _audio_cache.has(path):
		return _audio_cache[path]
	var bytes := FileAccess.get_file_as_bytes(path)
	if bytes.size() < 44 or bytes.slice(0, 4).get_string_from_ascii() != "RIFF":
		return null
	var pos := 12
	var rate := 22050
	var channels := 1
	var bits := 16
	var pcm := PackedByteArray()
	while pos + 8 <= bytes.size():
		var tag := bytes.slice(pos, pos + 4).get_string_from_ascii()
		var size := bytes.decode_u32(pos + 4)
		if tag == "fmt ":
			channels = bytes.decode_u16(pos + 10)
			rate = bytes.decode_u32(pos + 12)
			bits = bytes.decode_u16(pos + 22)
		elif tag == "data":
			pcm = bytes.slice(pos + 8, pos + 8 + size)
		pos += 8 + size + (size % 2)
	var s := AudioStreamWAV.new()
	s.format = AudioStreamWAV.FORMAT_16_BITS if bits == 16 else AudioStreamWAV.FORMAT_8_BITS
	s.mix_rate = rate
	s.stereo = channels == 2
	s.data = pcm
	_audio_cache[path] = s
	return s


func asset(id: String) -> Dictionary:
	return registry.get("assets", {}).get(id, {})


func assets_tagged(tag: String) -> Array:
	var out := []
	for id in registry.get("assets", {}):
		if tag in registry["assets"][id].get("tags", []):
			out.append(id)
	out.sort()
	return out


func file_path(id: String, file_name: String) -> String:
	return asset(id).get("files", {}).get(file_name, {}).get("res", "")


func texture(id: String, file_name: String = "") -> Texture2D:
	if file_name == "":
		file_name = id + ".png"
	var path := file_path(id, file_name)
	if path == "":
		push_error("Fabric: asset %s/%s not in registry" % [id, file_name])
		return null
	if _tex_cache.has(path):
		return _tex_cache[path]
	var img := Image.load_from_file(path)
	if img == null:
		return null
	var tex := ImageTexture.create_from_image(img)
	_tex_cache[path] = tex
	return tex


func json_asset(id: String, file_name: String = "") -> Variant:
	if file_name == "":
		file_name = id + ".json"
	return read_json(file_path(id, file_name))


## F4 hot reload: point one registry file at a staged path (absolute or res://).
## In-memory only; `forge build` remains the source of truth for committed content.
func override_file(id: String, file_name: String, path: String) -> void:
	var a: Dictionary = registry.get("assets", {}).get(id, {})
	if a.is_empty():
		return
	if not a.has("files"):
		a["files"] = {}
	if not a["files"].has(file_name):
		a["files"][file_name] = {}
	a["files"][file_name]["res"] = path
	clear_caches()


func clear_caches() -> void:
	_tex_cache.clear()
	_audio_cache.clear()


func _exit_tree() -> void:
	_tex_cache.clear()
	_audio_cache.clear()
