extends Node
## Retro autoload (F8, 0.8.0+f8) — console-style presentation profiles (ASSETFABRIC_SPEC §6.1 path 2 "console-style Godot
## authenticity profiles/shaders"; GAME_SPEC §4.6 global pixelation/quantisation post-process).
##
## Profiles come from AssetFabric (content/retro/profiles.yaml → `forge build` → assets/generated/retro/retro.json + one
## palette LUT per profile); nothing here is hand-tuned. A profile is presentation only — the simulation never reads it,
## so combat, balance and saves are identical with or without it (gated in `forge accept F8`).
##
## When a profile is active:
##   * R1 post-process: a full-screen layer between the world (canvas layer 0) and the HUD (layer 2) pixelates to the
##     profile's logical resolution and quantises through its LUT (ui/retro_post.gdshader); the colour-blind variant is
##     applied inside the same pass, before quantisation (so the A11y layer stands down while a profile is on);
##   * Q1 camera policy: game cameras (group "fabric_camera") zoom so one texel = one logical pixel, follow the leader on
##     whole world pixels, and sprite scales snap to whole numbers (forge/retro/validate.py q1_scale) — no shimmer;
##   * the window stretches by whole multiples only (pixel-perfect integer scaling).
## The player's choice (profile + scanlines) lives in the save's profile settings next to the palette and bindings.

signal changed(profile: String)

const TABLE_PATH := "res://assets/generated/retro/retro.json"
const SHADER := preload("res://ui/retro_post.gdshader")
const SCANLINE_STRENGTH := 0.35
const LAYER := 1

var order: Array = ["off"]
var profiles: Dictionary = {}
var q1_scales: Dictionary = {}       # "0.75" -> 1 … (Q1 geometry quantisation for sprite scales)
var profile := "off"
var scanlines := false
var preview_only := false            # acceptance: camera policy without the post-process (V1 source frames)
var _layer: CanvasLayer
var _rect: ColorRect
var _mat: ShaderMaterial


func _ready() -> void:
	var t = Fabric.read_json(TABLE_PATH)
	if typeof(t) == TYPE_DICTIONARY:
		order = t.get("order", ["off"])
		profiles = t.get("profiles", {})
		q1_scales = t.get("q1_scales", {})
	_layer = CanvasLayer.new()
	_layer.layer = LAYER
	_layer.visible = false
	_rect = ColorRect.new()
	_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	_mat = ShaderMaterial.new()
	_mat.shader = SHADER
	_rect.material = _mat
	_layer.add_child(_rect)
	add_child(_layer)
	var cli := str(Fabric.arg("retro", ""))
	if cli != "":
		set_profile(cli)


func active() -> bool:
	return profile != "off"


func post_active() -> bool:
	return _layer.visible


func scale() -> int:
	return int(profiles.get(profile, {}).get("scale", 1)) if active() else 1


## Switch live. Unknown names fall back to "off". Returns the applied profile.
func set_profile(p: String) -> String:
	if not profiles.has(p):
		p = "off"
	profile = p
	refresh()
	changed.emit(p)
	return p


func cycle(step: int) -> String:
	var i := maxi(0, order.find(profile))
	return set_profile(str(order[posmod(i + step, order.size())]))


func set_scanlines(on: bool) -> void:
	scanlines = on
	refresh()


## Re-apply shader parameters (also called by A11y when the colour-blind variant changes).
func refresh() -> void:
	var win := get_tree().root
	if not active():
		_layer.visible = false
		win.content_scale_stretch = Window.CONTENT_SCALE_STRETCH_FRACTIONAL
		A11y.refresh_layer()
		apply_cameras()
		return
	var d: Dictionary = profiles[profile]
	_mat.set_shader_parameter("lut", Fabric.texture("retro_profiles", str(d["lut"])))
	_mat.set_shader_parameter("logical", Vector2(float(d["logical"][0]), float(d["logical"][1])))
	_mat.set_shader_parameter("scanline", SCANLINE_STRENGTH if scanlines else 0.0)
	var pairs: Array = A11y.tables.get(A11y.palette, [])
	var src := PackedVector3Array()
	var dst := PackedVector3Array()
	for i in A11y.MAX_PAIRS:
		var pr: Array = pairs[i] if i < pairs.size() else [Color.BLACK, Color.BLACK]
		src.append(Vector3(pr[0].r, pr[0].g, pr[0].b))
		dst.append(Vector3(pr[1].r, pr[1].g, pr[1].b))
	_mat.set_shader_parameter("src", src)
	_mat.set_shader_parameter("dst", dst)
	_mat.set_shader_parameter("count", mini(pairs.size(), A11y.MAX_PAIRS))
	_layer.visible = not preview_only
	win.content_scale_stretch = Window.CONTENT_SCALE_STRETCH_INTEGER
	A11y.refresh_layer()
	apply_cameras()


## Q1 camera policy for every game camera.
func apply_cameras() -> void:
	for c in get_tree().get_nodes_in_group("fabric_camera"):
		if not c.has_meta("base_zoom"):
			c.set_meta("base_zoom", c.zoom)
		c.zoom = Vector2(scale(), scale()) if active() else c.get_meta("base_zoom")


## Camera position under the policy: whole world pixels; while a profile is on, centred on `target` and clamped so the
## view stays inside the map (when the map is larger than the view).
func camera_position(target: Vector2, map_px: Vector2, fallback: Vector2) -> Vector2:
	if not active():
		return fallback
	var d: Dictionary = profiles[profile]
	var half := Vector2(float(d["logical"][0]), float(d["logical"][1])) / 2.0
	var p := target.round()
	if map_px.x > half.x * 2.0:
		p.x = clampf(p.x, half.x, map_px.x - half.x)
	if map_px.y > half.y * 2.0:
		p.y = clampf(p.y, half.y, map_px.y - half.y)
	return p.round()


## Q1 geometry quantisation: sprite scale under the active profile (whole numbers only).
func sprite_scale(s: float) -> float:
	if not active() or is_equal_approx(s, roundf(s)):
		return s
	return float(q1_scales.get("%.2f" % s, maxf(1.0, roundf(s))))


func settings() -> Dictionary:
	return {"retro_profile": profile, "retro_scanlines": scanlines}


func apply_settings(s: Dictionary) -> void:
	scanlines = bool(s.get("retro_scanlines", false))
	set_profile(str(s.get("retro_profile", "off")))
