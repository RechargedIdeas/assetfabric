extends Node
## A11y autoload (G-A11Y-01, 0.7.10) — runtime colour-blind palette switch + settings persistence.
## The palette tables come from AssetFabric (PatternVault colour-blind variants → world.json "a11y", Codegen-World), so
## no colour is hand-wired here. Switching is live: a full-screen post-process layer remaps every palette colour on
## screen (sprites, tiles, plots, HUD) without reloading anything. Default = layer hidden (zero cost).
## Settings (`palette_variant` + `input_remap`) live in the save's profile layer: the open slot is patched in place;
## with no slot yet they go to `settings.json` next to it and are folded into the first checkpoint save.

const WORLD_PATH := "res://data/generated/world.json"
const MAX_PAIRS := 24
const SHADER := preload("res://ui/palette_remap.gdshader")

var variants: Array = ["default"]
var tables: Dictionary = {}           # variant -> [[src Color, dst Color], ...]
var palette := "default"
var ui: Dictionary = {}               # role -> Color (PatternVault `ui_roles`), so UI signal colours are palette colours too
var _layer: CanvasLayer
var _rect: ColorRect
var _mat: ShaderMaterial


func _ready() -> void:
	var w = Fabric.read_json(WORLD_PATH)
	var a: Dictionary = w.get("a11y", {}) if typeof(w) == TYPE_DICTIONARY else {}
	variants = a.get("variants", ["default"])
	for k in a.get("ui", {}):
		ui[k] = Color.html(str(a["ui"][k]))
	for v in a.get("palettes", {}):
		var pairs := []
		for p in a["palettes"][v]:
			pairs.append([Color.html(str(p[0])), Color.html(str(p[1]))])
		tables[v] = pairs
	_layer = CanvasLayer.new()
	_layer.layer = 120
	_layer.visible = false
	_rect = ColorRect.new()
	_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	_mat = ShaderMaterial.new()
	_mat.shader = SHADER
	_rect.material = _mat
	_layer.add_child(_rect)
	add_child(_layer)


## Switch the palette live. Unknown names fall back to "default". Returns the applied name.
func set_palette(v: String) -> String:
	if not tables.has(v):
		v = "default"
	palette = v
	var pairs: Array = tables.get(v, [])
	var src := PackedVector3Array()
	var dst := PackedVector3Array()
	for i in MAX_PAIRS:
		var p: Array = pairs[i] if i < pairs.size() else [Color.BLACK, Color.BLACK]
		src.append(Vector3(p[0].r, p[0].g, p[0].b))
		dst.append(Vector3(p[1].r, p[1].g, p[1].b))
	_mat.set_shader_parameter("src", src)
	_mat.set_shader_parameter("dst", dst)
	_mat.set_shader_parameter("count", mini(pairs.size(), MAX_PAIRS))
	_layer.visible = v != "default" and not pairs.is_empty()
	return v


## Next / previous variant in the list (Settings screen).
func cycle_palette(step: int) -> String:
	var i := maxi(0, variants.find(palette))
	return set_palette(str(variants[posmod(i + step, variants.size())]))


## What a remapped colour becomes under the active palette (non-palette colours unchanged) — for reports/tests.
func mapped(c: Color) -> Color:
	for p in tables.get(palette, []):
		if absf(p[0].r - c.r) < 0.012 and absf(p[0].g - c.g) < 0.012 and absf(p[0].b - c.b) < 0.012:
			return p[1]
	return c


func ui_colour(role: String, fallback: Color = Color.MAGENTA) -> Color:
	return ui.get(role, fallback)


func remap_active() -> bool:
	return _layer.visible


## Profile-layer settings dict (the save's `profile.settings`).
func settings() -> Dictionary:
	return {"palette_variant": palette, "input_remap": Fabric.current_remap()}


func apply_settings(s: Dictionary) -> void:
	if typeof(s) != TYPE_DICTIONARY:
		return
	var rm = s.get("input_remap", {})
	Fabric.apply_input_remap(rm if typeof(rm) == TYPE_DICTIONARY else {})
	set_palette(str(s.get("palette_variant", "default")))


func sidecar_path() -> String:
	return Save.dir.path_join("settings.json")


## Persist the current settings: patch the slot's profile layer (atomic writer, checksum recomputed), else the sidecar.
func save_settings() -> String:
	var st := settings()
	var s: Dictionary = Save.load_slot("slot0", false)
	if not s.is_empty():
		s["profile"]["settings"] = st
		return Save.write(s)
	var f := FileAccess.open(sidecar_path(), FileAccess.WRITE)
	if f == null:
		return ""
	f.store_string(JSON.stringify({"format": "gamezero-settings", "version": 1, "settings": st}, "  ", true))
	f.close()
	return "sidecar"


func load_sidecar() -> Dictionary:
	if not FileAccess.file_exists(sidecar_path()):
		return {}
	var d = JSON.parse_string(FileAccess.get_file_as_string(sidecar_path()))
	return d.get("settings", {}) if typeof(d) == TYPE_DICTIONARY and typeof(d.get("settings")) == TYPE_DICTIONARY else {}
