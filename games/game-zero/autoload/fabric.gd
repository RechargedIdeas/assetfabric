extends Node
## Fabric autoload — runtime binding to AssetFabric output (F1).
## Reads assets/generated/fabric_assets.json (written by `forge build`), loads
## PNG/JSON at runtime (no editor import step → headless-provable, hot-reloadable),
## registers the abstract input schema and locale tables.

const REGISTRY_PATH := "res://assets/generated/fabric_assets.json"
const LOCALE_DIR := "res://locale"
const GAME_DATA_PATH := "res://data/generated/game_data.json"

## Abstract input schema (GAME_SPEC §3): one map for keyboard + controller.
const INPUT_SCHEMA := {
	"move_left": [KEY_A, KEY_LEFT],
	"move_right": [KEY_D, KEY_RIGHT],
	"move_up": [KEY_W, KEY_UP],
	"move_down": [KEY_S, KEY_DOWN],
	"attack": [KEY_J, KEY_SPACE],
	"skill": [KEY_K],
	"swap": [KEY_TAB],
	"interact": [KEY_E],
	"tactic_menu": [KEY_Q],
	"restart": [KEY_R],
}

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


func flag(name: String) -> bool:
	return args.has(name)


func arg(name: String, default_value: Variant = null) -> Variant:
	return args.get(name, default_value)


func _register_inputs() -> void:
	for action in INPUT_SCHEMA:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
		for key in INPUT_SCHEMA[action]:
			var ev := InputEventKey.new()
			ev.physical_keycode = key
			InputMap.action_add_event(action, ev)


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


func _exit_tree() -> void:
	_tex_cache.clear()
	_audio_cache.clear()
