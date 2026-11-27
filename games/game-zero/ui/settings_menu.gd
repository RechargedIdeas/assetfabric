extends CanvasLayer
## In-game Settings screen (G-A11Y-01, 0.7.10): rebind every action (keyboard *and* gamepad) and switch the colour-blind
## palette live. Navigable with keyboard or gamepad only (Godot ui_up/ui_down/ui_left/ui_right/ui_accept/ui_cancel →
## arrows / d-pad, Enter / Space / pad A, Escape / pad B); mouse/touch also work. All text is locale keys.
## Every change is persisted at once (A11y.save_settings → the save's profile layer).
##
## Rebinding: focus an action row, press accept, then press the new key / pad button / stick direction (Escape cancels).
## If another action that is read at the same time already uses it, the two swap (Fabric.rebind).

signal closed

var _panel: PanelContainer
var _list: VBoxContainer
var _status: Label
var _rows := {}               # action -> Button
var _palette_btn: Button
var _retro_btn: Button        # F8: retro / console-style profile (◀ ▶), above the palette row
var _scan_btn: Button         # F8: scanlines on/off (accept toggles)
var _capturing := ""          # action waiting for its new binding
var _capture_armed := false   # ignore the press that opened capture
var events_log := []               # what happened, for headless reports: [{"rebind"...}, {"palette"...}]


func _ready() -> void:
	layer = 100
	process_mode = Node.PROCESS_MODE_ALWAYS
	_panel = PanelContainer.new()
	_panel.position = Vector2(40, 24)
	_panel.custom_minimum_size = Vector2(760, 0)
	add_child(_panel)
	var v := VBoxContainer.new()
	_panel.add_child(v)
	var title := Label.new()
	title.text = tr("settings.title")
	v.add_child(title)
	# F8 display rows sit *above* the palette row: focus still opens on the palette (G-A11Y-01 flow unchanged); pad/arrow
	# up reaches the retro profile, then scanlines.
	_scan_btn = Button.new()
	_scan_btn.alignment = HORIZONTAL_ALIGNMENT_LEFT
	_scan_btn.pressed.connect(_toggle_scanlines)
	v.add_child(_scan_btn)
	_retro_btn = Button.new()
	_retro_btn.alignment = HORIZONTAL_ALIGNMENT_LEFT
	_retro_btn.pressed.connect(func(): _set_retro(1))
	_retro_btn.gui_input.connect(_retro_gui_input)
	v.add_child(_retro_btn)
	_palette_btn = Button.new()
	_palette_btn.alignment = HORIZONTAL_ALIGNMENT_LEFT
	_palette_btn.pressed.connect(func(): _set_palette(1))
	_palette_btn.gui_input.connect(_palette_gui_input)
	v.add_child(_palette_btn)
	var sc := ScrollContainer.new()
	sc.custom_minimum_size = Vector2(740, 470)
	sc.follow_focus = true
	v.add_child(sc)
	_list = VBoxContainer.new()
	_list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	sc.add_child(_list)
	for action in Fabric.ACTION_ORDER:
		var b := Button.new()
		b.alignment = HORIZONTAL_ALIGNMENT_LEFT
		b.pressed.connect(func(): _begin_capture(action))
		_list.add_child(b)
		_rows[action] = b
	var reset := Button.new()
	reset.text = tr("settings.reset")
	reset.pressed.connect(_reset)
	v.add_child(reset)
	var back := Button.new()
	back.text = tr("settings.back")
	back.pressed.connect(close)
	v.add_child(back)
	_status = Label.new()
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD
	_status.custom_minimum_size = Vector2(740, 0)
	v.add_child(_status)
	_status.text = tr("settings.hint")
	_refresh()
	_palette_btn.grab_focus()


func _refresh() -> void:
	_retro_btn.text = "%s: %s  ◀ ▶" % [tr("settings.retro"), tr("retro.profile." + Retro.profile)]
	_scan_btn.text = "%s: %s" % [tr("settings.scanlines"), tr("settings.on" if Retro.scanlines else "settings.off")]
	_palette_btn.text = "%s: %s  ◀ ▶" % [tr("settings.palette"), tr("settings.palette." + A11y.palette)]
	for action in _rows:
		var labels := []
		for t in Fabric.bindings(action):
			labels.append(Fabric.token_label(t))
		_rows[action].text = "%s:  %s" % [tr("input." + action), "  ·  ".join(labels)]


func _palette_gui_input(ev: InputEvent) -> void:
	if ev.is_action_pressed("ui_right"):
		_set_palette(1)
		_palette_btn.accept_event()
	elif ev.is_action_pressed("ui_left"):
		_set_palette(-1)
		_palette_btn.accept_event()


func _retro_gui_input(ev: InputEvent) -> void:
	if ev.is_action_pressed("ui_right"):
		_set_retro(1)
		_retro_btn.accept_event()
	elif ev.is_action_pressed("ui_left"):
		_set_retro(-1)
		_retro_btn.accept_event()


func _set_retro(step: int) -> void:
	var p := Retro.cycle(step)
	A11y.save_settings()
	events_log.append({"retro": p})
	_status.text = tr("settings.retro.changed") % tr("retro.profile." + p)
	_refresh()


func _toggle_scanlines() -> void:
	Retro.set_scanlines(not Retro.scanlines)
	A11y.save_settings()
	events_log.append({"scanlines": Retro.scanlines})
	_status.text = "%s: %s" % [tr("settings.scanlines"), tr("settings.on" if Retro.scanlines else "settings.off")]
	_refresh()


func _set_palette(step: int) -> void:
	var v := A11y.cycle_palette(step)
	A11y.save_settings()
	events_log.append({"palette": v})
	_status.text = tr("settings.palette.changed") % tr("settings.palette." + v)
	_refresh()


func _begin_capture(action: String) -> void:
	_capturing = action
	_capture_armed = false
	_status.text = tr("settings.capture") % tr("input." + action)
	# arm on the next frame: the accept press that opened capture must not become the binding
	get_tree().process_frame.connect(func(): _capture_armed = true, CONNECT_ONE_SHOT)


func _input(ev: InputEvent) -> void:
	if _capturing == "":
		if ev.is_action_pressed("ui_cancel") or ev.is_action_pressed("settings"):
			get_viewport().set_input_as_handled()
			close()
		return
	get_viewport().set_input_as_handled()
	if not _capture_armed or ev.is_echo():
		return
	var pressed: bool = (ev is InputEventKey and ev.pressed) or (ev is InputEventJoypadButton and ev.pressed) \
		or (ev is InputEventJoypadMotion and absf(ev.axis_value) >= Fabric.AXIS_DEADZONE)
	if not pressed:
		return
	if ev is InputEventKey and ev.physical_keycode == KEY_ESCAPE:
		_status.text = tr("settings.capture.cancelled")
		_capturing = ""
		return
	var tok := Fabric.event_token(ev)
	if tok == "":
		return
	var action := _capturing
	_capturing = ""
	var r := Fabric.rebind(action, tok)
	A11y.save_settings()
	events_log.append({"rebind": r})
	_status.text = tr("settings.rebound") % [tr("input." + action), Fabric.token_label(tok)]
	if r["swapped_with"] != "":
		_status.text += "  " + tr("settings.swapped") % tr("input." + str(r["swapped_with"]))
	_refresh()
	_rows[action].grab_focus()


func _reset() -> void:
	Fabric.reset_bindings()
	Retro.scanlines = false
	Retro.set_profile("off")
	A11y.set_palette("default")
	A11y.save_settings()
	events_log.append({"reset": true})
	_status.text = tr("settings.reset.done")
	_refresh()


func is_capturing() -> bool:
	return _capturing != ""


func close() -> void:
	closed.emit()
	queue_free()
