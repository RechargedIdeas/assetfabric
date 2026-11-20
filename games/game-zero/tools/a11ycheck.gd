extends Node
## G-A11Y-01 acceptance driver (0.7.10). Plays the real Settings screen with injected keyboard + gamepad events — the same
## events a player's devices produce — and reports what happened as one `FABRIC_RESULT {"a11y": …}` line.
##
##   --scene=a11ycheck --phase=configure --save-dir=<dir> [--capture=<png prefix>]
##       slice select screen → `settings` key opens the menu → palette ▶ (deuteranopia) → ↓×7 + Enter + F rebinds
##       Interact to F → pad ↓ + pad A + pad Y rebinds Use salve to pad Y (conflict: Skill gets pad B) → Escape closes →
##       the rebound Interact (F) starts the game → checkpoint save. With a display, also renders the real enemy / hero
##       sprites + crop colours under each palette and writes PNGs (`--capture`) for forge to check pixel-exactly.
##   --scene=a11ycheck --phase=verify --save-dir=<dir>
##       fresh process: the save's profile settings are re-applied at boot (palette + bindings live in the InputMap).

const SliceScene := preload("res://scenes/slice.tscn")

var out := {"phase": "", "platform": "", "steps": [], "errors": []}


func _ready() -> void:
	Fabric._start_watchdog(float(Fabric.arg("watchdog", "60")))
	out["phase"] = str(Fabric.arg("phase", "configure"))
	out["platform"] = Fabric.platform_id()
	out["display"] = DisplayServer.get_name()
	if out["phase"] == "verify":
		_report_state()
		await _finish()
		return
	await _configure()
	await _finish()


func _finish() -> void:
	await Save.persist_wait()
	print("FABRIC_RESULT " + JSON.stringify({"a11y": out}))
	get_tree().quit(0)


func _frames(n: int) -> void:
	for i in n:
		await get_tree().physics_frame
		await get_tree().process_frame


func _key(code: Key) -> void:
	for pressed in [true, false]:
		var ev := InputEventKey.new()
		ev.physical_keycode = code
		ev.keycode = code
		ev.pressed = pressed
		Input.parse_input_event(ev)
		await _frames(3)


func _pad(button: JoyButton) -> void:
	for pressed in [true, false]:
		var ev := InputEventJoypadButton.new()
		ev.button_index = button
		ev.pressed = pressed
		Input.parse_input_event(ev)
		await _frames(3)


func _step(name: String, ok: bool, extra: Dictionary = {}) -> void:
	var row := {"step": name, "ok": ok}
	row.merge(extra)
	out["steps"].append(row)
	if not ok:
		out["errors"].append(name)


func _configure() -> void:
	var slice = SliceScene.instantiate()
	add_child(slice)
	await _frames(4)
	_step("select_screen", slice.phase == "select")
	await _key(KEY_ESCAPE)                                   # default `settings` binding
	_step("settings_opens_from_select", slice.settings_open())
	if not slice.settings_open():
		return
	var menu = slice.settings_menu
	_step("menu_focus_on_palette", menu.get_viewport().gui_get_focus_owner() == menu._palette_btn)
	await _key(KEY_RIGHT)                                    # ui_right on the palette row → next variant
	_step("palette_switched_live", A11y.palette == "deuteranopia" and A11y.remap_active(), {"palette": A11y.palette})
	for i in 7:                                              # palette → move_up … interact (7th row)
		await _key(KEY_DOWN)
	_step("keyboard_navigation", menu.get_viewport().gui_get_focus_owner() == menu._rows["interact"],
		{"focus": str(menu.get_viewport().gui_get_focus_owner().text) if menu.get_viewport().gui_get_focus_owner() else ""})
	await _key(KEY_ENTER)
	_step("capture_mode", menu.is_capturing())
	await _key(KEY_F)
	var ib: Array = Fabric.bindings("interact")
	_step("rebind_keyboard", ib.size() > 0 and ib[0] == "F" and not ib.has("E") and Fabric.action_keys("interact") == ["F"], {"interact": ib})
	await _pad(JOY_BUTTON_DPAD_DOWN)                         # gamepad navigation: interact → use_salve
	_step("gamepad_navigation", menu.get_viewport().gui_get_focus_owner() == menu._rows["use_salve"])
	await _pad(JOY_BUTTON_A)                                 # ui_accept on the pad
	_step("capture_mode_pad", menu.is_capturing())
	await _pad(JOY_BUTTON_Y)                                 # already Skill's pad button → swap
	var sb: Array = Fabric.bindings("use_salve")
	var kb: Array = Fabric.bindings("skill")
	_step("rebind_gamepad_with_conflict_swap", sb.has("pad:3") and not kb.has("pad:3") and kb.has("pad:1"),
		{"use_salve": sb, "skill": kb, "log": menu.events_log.duplicate(true)})
	out["sidecar_written"] = FileAccess.file_exists(A11y.sidecar_path())
	await _key(KEY_ESCAPE)
	_step("settings_closes", not slice.settings_open())
	_step("old_key_unbound", not _would_trigger("interact", KEY_E))
	_step("new_key_bound", _would_trigger("interact", KEY_F))
	await _key(KEY_F)                                        # the rebound Interact starts the game (select → play)
	_step("rebound_key_drives_game", slice.phase == "play")
	var s: Dictionary = Save.load_slot("slot0", false)
	var st: Dictionary = s.get("profile", {}).get("settings", {})
	_step("settings_in_save", str(st.get("palette_variant", "")) == "deuteranopia" and st.get("input_remap", {}).has("interact")
		and st.get("input_remap", {}).has("use_salve"), {"settings": st})
	out["save_checksum"] = s.get("checksum", "")
	out["hint_follows_binding"] = Fabric.hint("slice.hint").contains("F interact")
	_step("hint_follows_binding", out["hint_follows_binding"])
	if DisplayServer.get_name() != "headless":
		await _render_checks(slice)


func _would_trigger(action: String, code: Key) -> bool:
	var ev := InputEventKey.new()
	ev.physical_keycode = code
	ev.keycode = code
	ev.pressed = true
	return InputMap.event_is_action(ev, action, true)


## Draw the real generated sprites + crop colours on a strip above the game (below the remap layer), capture per palette.
func _render_checks(slice) -> void:
	slice.process_mode = Node.PROCESS_MODE_DISABLED
	var layer := CanvasLayer.new()
	layer.layer = 50
	var bg := ColorRect.new()
	bg.color = Color(0.04, 0.04, 0.06)
	bg.size = Vector2(1280, 720)
	layer.add_child(bg)
	var x := 40.0
	for id in ["spr_emberling", "spr_cave_mite", "spr_rock_brute", "spr_kael", "spr_nyra"]:
		var sp := Sprite2D.new()
		sp.texture = Fabric.texture(id)
		sp.hframes = 6 if sp.texture and sp.texture.get_width() >= 6 * sp.texture.get_height() else 1
		sp.centered = false
		sp.scale = Vector2(6, 6)
		sp.position = Vector2(x, 60)
		sp.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		layer.add_child(sp)
		x += 220.0
	for i in 2:
		var r := ColorRect.new()
		r.color = A11y.ui_colour("plot_growing" if i == 0 else "plot_ready")
		r.position = Vector2(40 + i * 220, 400)
		r.size = Vector2(160, 160)
		layer.add_child(r)
	add_child(layer)
	var caps := {}
	var prefix := str(Fabric.arg("capture", ""))
	for v in A11y.variants:
		A11y.set_palette(v)
		await _frames(4)
		await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		var path := ""
		if prefix != "":
			path = "%s_%s.png" % [prefix, v]
			img.save_png(path)
		caps[v] = {"path": path, "size": [img.get_width(), img.get_height()]}
	A11y.set_palette("deuteranopia")
	out["captures"] = caps


func _report_state() -> void:
	var st := A11y.settings()
	out["settings"] = st
	out["palette"] = A11y.palette
	out["remap_active"] = A11y.remap_active()
	out["tokens"] = {"interact": Fabric.action_tokens("interact"), "use_salve": Fabric.action_tokens("use_salve"),
		"skill": Fabric.action_tokens("skill")}
	out["last_load"] = Save.last_load
	_step("palette_restored", A11y.palette == "deuteranopia" and A11y.remap_active())
	_step("bindings_restored", out["tokens"]["interact"].has("F") and not out["tokens"]["interact"].has("E")
		and out["tokens"]["use_salve"].has("pad:3") and out["tokens"]["skill"].has("pad:1"))
