extends Node
## F8 acceptance driver (0.8.0+f8) — retro / console-style presentation, driven like a console player: gamepad only.
## One `FABRIC_RESULT {"retro": …}` line.
##
##   --scene=retrocheck --phase=configure --save-dir=<dir>
##       select screen → pad Start opens Settings → pad ↑ (display style) → pad → ×2 (nes-style, live) → pad ↑ (scanlines)
##       → pad A on/off → pad ↓×2 (palette) → pad → (deuteranopia, applied inside the retro pass) → pad B closes →
##       pad A starts the game → camera follows the Q1 policy → pad ← walks the leader → settings in the save.
##   --scene=retrocheck --phase=verify --save-dir=<dir>
##       fresh process: profile + palette restored from the save's profile settings.
##   --scene=retrocheck --phase=render --save-dir=<dir> --capture=<png prefix>     (needs a display, e.g. Xvfb)
##       the real slice in play; per profile × palette: a source frame (camera policy, post-process off), the retro frame,
##       a sub-pixel-moved retro frame (Q1 snapping) and, for nes-style, a scanline frame. forge checks them (V1).

const SliceScene := preload("res://scenes/slice.tscn")

var out := {"phase": "", "platform": "", "steps": [], "errors": []}


func _ready() -> void:
	Fabric._start_watchdog(float(Fabric.arg("watchdog", "90")))
	out["phase"] = str(Fabric.arg("phase", "configure"))
	out["platform"] = Fabric.platform_id()
	out["display"] = DisplayServer.get_name()
	match out["phase"]:
		"verify":
			_report_state()
		"render":
			await _render()
		_:
			await _configure()
	await Save.persist_wait()
	print("FABRIC_RESULT " + JSON.stringify({"retro": out}))
	get_tree().quit(0)


func _frames(n: int) -> void:
	for i in n:
		await get_tree().physics_frame
		await get_tree().process_frame


func _pad(button: JoyButton, hold: int = 3) -> void:
	for pressed in [true, false]:
		var ev := InputEventJoypadButton.new()
		ev.button_index = button
		ev.pressed = pressed
		Input.parse_input_event(ev)
		await _frames(hold if pressed else 3)


func _step(name: String, ok: bool, extra: Dictionary = {}) -> void:
	var row := {"step": name, "ok": ok}
	row.merge(extra)
	out["steps"].append(row)
	if not ok:
		out["errors"].append(name)


func _focus(menu) -> Control:
	return menu.get_viewport().gui_get_focus_owner()


func _cam(slice) -> Camera2D:
	for c in slice.get_children():
		if c is Camera2D:
			return c
	return null


func _configure() -> void:
	var slice = SliceScene.instantiate()
	add_child(slice)
	await _frames(4)
	_step("select_screen", slice.phase == "select" and Retro.profile == "off")
	await _pad(JOY_BUTTON_START)
	_step("settings_opens_from_pad_start", slice.settings_open())
	if not slice.settings_open():
		return
	var menu = slice.settings_menu
	_step("focus_on_palette", _focus(menu) == menu._palette_btn)
	await _pad(JOY_BUTTON_DPAD_UP)
	_step("pad_up_reaches_display_style", _focus(menu) == menu._retro_btn)
	await _pad(JOY_BUTTON_DPAD_RIGHT)
	_step("profile_cycles_live", Retro.profile == "gz-native" and Retro.post_active(), {"profile": Retro.profile})
	await _pad(JOY_BUTTON_DPAD_RIGHT)
	_step("profile_nes_style", Retro.profile == "nes-style" and Retro.post_active() and Retro.scale() == 5,
		{"profile": Retro.profile, "scale": Retro.scale()})
	_step("integer_stretch", get_tree().root.content_scale_stretch == Window.CONTENT_SCALE_STRETCH_INTEGER)
	_step("label_is_locale_key", menu._retro_btn.text.contains(tr("retro.profile.nes-style")) and tr("retro.profile.nes-style") != "retro.profile.nes-style")
	await _pad(JOY_BUTTON_DPAD_UP)
	_step("pad_up_reaches_scanlines", _focus(menu) == menu._scan_btn)
	await _pad(JOY_BUTTON_A)
	_step("scanlines_on", Retro.scanlines)
	await _pad(JOY_BUTTON_A)
	_step("scanlines_off", not Retro.scanlines)
	await _pad(JOY_BUTTON_DPAD_DOWN)
	await _pad(JOY_BUTTON_DPAD_DOWN)
	_step("pad_down_back_to_palette", _focus(menu) == menu._palette_btn)
	await _pad(JOY_BUTTON_DPAD_RIGHT)
	_step("palette_inside_retro_pass", A11y.palette == "deuteranopia" and A11y.remap_active() and not A11y._layer.visible,
		{"palette": A11y.palette})
	await _pad(JOY_BUTTON_B)
	_step("settings_closes_pad_b", not slice.settings_open())
	await _pad(JOY_BUTTON_A)
	_step("pad_a_starts_game", slice.phase == "play")
	await _frames(3)
	var cam := _cam(slice)
	_step("camera_policy_zoom", cam != null and cam.zoom == Vector2(5, 5), {"zoom": str(cam.zoom) if cam else ""})
	var l = slice.sim.leader()
	var p0: Vector2 = l.pos
	await _pad(JOY_BUTTON_DPAD_LEFT, 30)          # the spawn is against the east wall
	var p1: Vector2 = slice.sim.leader().pos
	_step("pad_moves_leader", p1.x < p0.x - 4.0, {"from": [p0.x, p0.y], "to": [p1.x, p1.y]})
	_step("camera_whole_pixels", cam != null and cam.position == cam.position.round(), {"camera": [cam.position.x, cam.position.y] if cam else []})
	var s: Dictionary = Save.load_slot("slot0", false)
	var st: Dictionary = s.get("profile", {}).get("settings", {})
	_step("settings_in_save", str(st.get("retro_profile", "")) == "nes-style" and str(st.get("palette_variant", "")) == "deuteranopia"
		and st.get("retro_scanlines", true) == false, {"settings": st})


func _report_state() -> void:
	out["settings"] = A11y.settings()
	_step("profile_restored", Retro.profile == "nes-style" and Retro.post_active() and Retro.scale() == 5, {"profile": Retro.profile})
	_step("palette_restored", A11y.palette == "deuteranopia" and A11y.remap_active())
	_step("scanlines_restored_off", not Retro.scanlines)


func _grab(path: String) -> void:
	await _frames(3)
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(path)


func _render() -> void:
	var prefix := str(Fabric.arg("capture", ""))
	var slice = SliceScene.instantiate()
	add_child(slice)
	await _frames(3)
	await _pad(JOY_BUTTON_A)                     # default selection → play
	await _frames(5)
	_step("in_play", slice.phase == "play")
	if slice.phase != "play":
		return
	slice.process_mode = Node.PROCESS_MODE_DISABLED
	if slice.hud:
		slice.hud.visible = false
	for n in ["bubble", "overlay"]:
		if slice.get(n):
			slice.get(n).visible = false
	var caps := {}
	var l = slice.sim.leader()
	var base_pos: Vector2 = l.pos
	# a line-up of real enemy sprites in world space next to the party, so hostile palette colours (the ones the
	# colour-blind variants remap) are on screen under every profile; they go through the same retro pass
	var x := -56.0
	for id in ["spr_emberling", "spr_cave_mite", "spr_rock_brute"]:
		var sp := Sprite2D.new()
		sp.texture = Fabric.texture(id)
		sp.hframes = 6
		sp.position = (base_pos + Vector2(x, -36.0)).round()
		slice.add_child(sp)
		x += 22.0
	for v in ["default", "deuteranopia"]:
		A11y.set_palette(v)
		for p in Retro.order:
			if p == "off" and v != "default":
				continue
			var key := "%s__%s" % [p, v]
			l.pos = base_pos
			Retro.scanlines = false
			Retro.preview_only = true
			Retro.set_profile(p)
			slice._sync_view()
			await _grab("%s_%s_source.png" % [prefix, key])
			Retro.preview_only = false
			Retro.refresh()
			slice._sync_view()
			await _grab("%s_%s_retro.png" % [prefix, key])
			var row := {"profile": p, "palette": v, "scale": Retro.scale(), "camera": [_cam(slice).position.x, _cam(slice).position.y],
				"zoom": _cam(slice).zoom.x}
			if p != "off":
				l.pos = base_pos + Vector2(0.4, 0.3)        # sub-pixel motion: Q1 snapping must keep the frame identical
				slice._sync_view()
				await _grab("%s_%s_subpixel.png" % [prefix, key])
				l.pos = base_pos
				slice._sync_view()
			if p == "nes-style" and v == "default":
				Retro.set_scanlines(true)
				await _grab("%s_%s_scan.png" % [prefix, key])
				Retro.set_scanlines(false)
				row["scanline_strength"] = Retro.SCANLINE_STRENGTH
			caps[key] = row
	Retro.set_profile("off")
	A11y.set_palette("default")
	out["captures"] = caps
	out["a11y_tables"] = {}
	for v in A11y.tables:
		var pairs := []
		for pr in A11y.tables[v]:
			pairs.append(["#" + pr[0].to_html(false), "#" + pr[1].to_html(false)])
		out["a11y_tables"][v] = pairs
