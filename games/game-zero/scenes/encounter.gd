extends Node2D
## Generic encounter scene: renders a CombatSim built from Fabric data.
## Headless acceptance: godot --headless --path games/game-zero -- --scene=<sandbox|combat> --autoplay

const EncounterBuilder = preload("res://sim/encounter_builder.gd")
const Brain = preload("res://ai/brain.gd")
const SwapAdvisor = preload("res://ai/swap_advisor.gd")
var field_warm_ms := 0.0
var swap_parity := false
const IntentGrammar = preload("res://ai/intent_grammar.gd")
const CALLOUT_GAP := 90   # ticks between callouts per speaker
const FRAME_NAMES := ["idle0", "idle1", "walk0", "walk1", "attack0", "attack1"]

@export var default_encounter := "sandbox"

var sim
var encounter: Dictionary
var tileset: Texture2D
var sprites := {}
var hud: Label
var music: AudioStreamPlayer
var autoplay := false
var _accum := 0.0
var brain
var frozen := false
var swap_recs: Dictionary = {}
var _event_cursor := 0
var _last_callout := {}
var callout_log: Array = []
var intents_handled: Array = []
var dialogue_log: Array = []
var swaps: Array = []
var bubble: Label
var overlay: Label
var command_box: LineEdit


func _ready() -> void:
	autoplay = Fabric.flag("autoplay")
	encounter = Fabric.read_json("res://data/encounters/%s.json" % Fabric.arg("encounter", default_encounter))
	_build()
	if autoplay and DisplayServer.get_name() == "headless":
		_run_headless()


func _build() -> void:
	for c in get_children():
		c.queue_free()
	sprites.clear()
	var layout = Fabric.json_asset(encounter["tilemap"])
	sim = EncounterBuilder.build(encounter, layout, Fabric.game_data, Fabric.abilities)
	var warm_t0 := Time.get_ticks_usec()
	sim.grid.warm_fields()
	field_warm_ms = snappedf((Time.get_ticks_usec() - warm_t0) / 1000.0, 0.01)
	_event_cursor = 0
	frozen = false
	_script_i = 0
	_freeze_hold = 0
	CascadeHub.reset()
	if encounter.get("ai", "rule") == "bt":
		brain = Brain.new(Fabric.read_json("res://data/ai/behaviour_trees.json")["trees"])
		sim.brain_override = brain.tick
	CascadeHub.subscribe("callout_request", _on_callout_request)
	CascadeHub.subscribe("callout", _on_callout)
	CascadeHub.subscribe("intent", _on_intent)
	CascadeHub.subscribe("dialogue_request", _on_dialogue_request)
	tileset = Fabric.texture(encounter["tilemap"], encounter["tilemap"] + "_tiles.png")
	for e in sim.entities:
		var s := Sprite2D.new()
		s.texture = Fabric.texture(e.sprite_id)
		s.hframes = FRAME_NAMES.size()
		if e.kind == "pet":
			s.scale = Vector2(0.75, 0.75)
		add_child(s)
		sprites[e.id] = s
	var cam := Camera2D.new()
	cam.zoom = Vector2(2, 2)
	cam.position = Vector2(sim.grid.width * sim.grid.tile_size, sim.grid.height * sim.grid.tile_size) / 2.0
	add_child(cam)
	var layer := CanvasLayer.new()
	hud = Label.new()
	hud.position = Vector2(8, 8)
	layer.add_child(hud)
	bubble = Label.new()
	bubble.position = Vector2(8, 640)
	layer.add_child(bubble)
	overlay = Label.new()
	overlay.position = Vector2(760, 8)
	layer.add_child(overlay)
	command_box = LineEdit.new()
	command_box.position = Vector2(8, 600)
	command_box.size = Vector2(420, 28)
	command_box.placeholder_text = tr("hud.command.placeholder")
	command_box.visible = false
	command_box.text_submitted.connect(func(txt):
		submit_command(txt)
		command_box.visible = false
		command_box.release_focus())
	layer.add_child(command_box)
	add_child(layer)
	var m = encounter.get("music")
	if m:
		music = AudioStreamPlayer.new()
		var stream: AudioStreamWAV = Fabric.audio(m["id"], "%s_%s.wav" % [m["id"], m["stem"]])
		if stream:
			stream.loop_mode = AudioStreamWAV.LOOP_FORWARD
			stream.loop_end = stream.data.size() / 2
			music.stream = stream
			music.volume_db = -8.0
		add_child(music)
		if not autoplay:
			music.play()
	queue_redraw()


func _draw() -> void:
	if sim == null or tileset == null:
		return
	var ts: int = sim.grid.tile_size
	var legend := {"#": 0, ".": 1, "S": 2, "E": 3}
	for y in sim.grid.height:
		for x in sim.grid.width:
			var idx: int = legend.get(sim.grid.rows[y][x], 0)
			draw_texture_rect_region(tileset, Rect2(x * ts, y * ts, ts, ts), Rect2(idx * ts, 0, ts, ts))


func _player_input() -> Dictionary:
	return {"move": Input.get_vector("move_left", "move_right", "move_up", "move_down"),
		"attack": Input.is_action_pressed("attack"), "skill": Input.is_action_pressed("skill")}


func _physics_process(delta: float) -> void:
	if sim == null or (autoplay and DisplayServer.get_name() == "headless"):
		return
	if command_box.visible:
		return
	if Input.is_action_just_pressed("restart"):
		_build()
		return
	if autoplay and _demo_script():
		_sync_view()
		return
	if Input.is_action_just_pressed("swap"):
		toggle_freeze()
	if frozen:
		for i in 4:
			if Input.is_key_pressed(KEY_1 + i) and i < swap_recs.get("recommendations", []).size():
				do_swap(swap_recs["recommendations"][i]["id"])
				toggle_freeze()
				break
		_sync_view()
		return
	if Input.is_action_just_pressed("tactic_menu"):
		submit_command("defend" if sim.tactic == "aggressive" else "charge")
	if Input.is_key_pressed(KEY_SLASH):
		command_box.visible = true
		command_box.text = ""
		command_box.grab_focus()
		return
	if Input.is_action_just_pressed("interact") and sim.outcome() == "victory":
		talk(sim.leader().id if sim.leader() else "kael", sim.tick)
	_accum += delta
	while _accum >= 1.0 / 60.0:
		_accum -= 1.0 / 60.0
		_step({} if autoplay else _player_input())
	_sync_view()


func _step(input: Dictionary) -> void:
	sim.step(input)
	_emit_events()
	CascadeHub.drain(sim.tick)


# ---------------------------------------------------------------- F3: swap / intents / callouts / dialogue

func toggle_freeze() -> void:
	frozen = not frozen
	if frozen:
		swap_recs = SwapAdvisor.rank(sim)


func do_swap(id_: String) -> void:
	sim.set_leader(id_)
	swaps.append({"tick": sim.tick, "to": id_, "wall_ms": swap_recs.get("wall_ms", 0.0)})


func submit_command(text: String) -> void:
	var kinds := []
	for e in sim.entities:
		if e.team == 1:
			var k: String = e.id.substr(0, e.id.rfind("_"))
			if not kinds.has(k):
				kinds.append(k)
	var party: Array = sim.entities.filter(func(e): return e.kind == "fighter").map(func(e): return e.id)
	CascadeHub.publish("intent", "player", IntentGrammar.parse(text, kinds, party))


func _on_intent(m: Dictionary) -> void:
	var p: Dictionary = m["payload"]
	match p.get("intent"):
		"focus":
			sim.focus_kind = p["target_kind"]
		"regroup", "defensive":
			sim.tactic = "defensive"
			sim.focus_kind = ""
		"aggressive":
			sim.tactic = "aggressive"
		"swap":
			if p.has("to"):
				do_swap(p["to"])
		_:
			return
	intents_handled.append({"tick": sim.tick, "intent": p.get("intent"), "text": p.get("text"), "target_kind": p.get("target_kind", "")})


func _speaker_for(ev: Dictionary) -> Array:
	var t: String = ev["type"]
	match t:
		"battle_start", "victory":
			var l = sim.leader()
			return [l.id if l else "", t]
		"defeated":
			if ev.get("target_team") == 0 and ev.get("target_kind") == "fighter":
				var alive: Array = sim.entities.filter(func(e): return e.team == 0 and e.kind == "fighter" and e.alive())
				return [alive[0].id if not alive.is_empty() else "", "ally_down"]
			var by = sim.by_id.get(ev["by"])
			if by and by.team == 0:
				return [by.owner_id if by.kind == "pet" else by.id, "kill"]
		"heal":
			return [ev["by"], "heal"]
		"taunt":
			return [ev["by"], "taunt"]
		"low_hp":
			return [ev["target"], "low_hp"]
		"swap":
			return [ev["to"], "swap_in"]
	return ["", ""]


func _emit_events() -> void:
	while _event_cursor < sim.events.size():
		var ev: Dictionary = sim.events[_event_cursor]
		_event_cursor += 1
		var sp := _speaker_for(ev)
		if sp[0] != "":
			CascadeHub.publish("callout_request", sp[0], {"event": sp[1], "tick": ev["tick"], "subject": ev.get("target", "")})


func _on_callout_request(m: Dictionary) -> void:
	var who: String = m["from"]
	var ev: String = m["payload"]["event"]
	var t: int = m["payload"]["tick"]
	var urgent := ev in ["ally_down", "victory", "low_hp"]
	if not urgent and t - int(_last_callout.get(who, -9999)) < CALLOUT_GAP:
		return
	_last_callout[who] = t
	var ally_name := tr("roster." + str(m["payload"].get("subject", ""))) if ev == "ally_down" else ""
	var line: String = GIRT.callout(who, ev, t + who.length() * 7, ally_name)
	if line != "":
		CascadeHub.publish("callout", who, {"event": ev, "line": line, "tick": t})


func _on_callout(m: Dictionary) -> void:
	callout_log.append({"tick": m["payload"]["tick"], "who": m["from"], "event": m["payload"]["event"], "line": m["payload"]["line"]})
	if bubble:
		bubble.text = "%s: %s" % [tr("roster." + m["from"]), m["payload"]["line"]]


## Dialogue is out-of-combat and async: request now, answer on a later frame.
func talk(persona: String, seed: int, topic: String = "<s>") -> void:
	CascadeHub.publish("dialogue_request", "player", {"persona": persona, "seed": seed, "topic": topic, "t_us": Time.get_ticks_usec()})


func _on_dialogue_request(m: Dictionary) -> void:
	var p: Dictionary = m["payload"]
	var reply: String = GIRT.lm_generate(p["persona"], int(p["seed"]), p["topic"])
	var e2e_ms := (Time.get_ticks_usec() - int(p["t_us"])) / 1000.0
	dialogue_log.append({"persona": p["persona"], "reply": reply, "e2e_ms": snappedf(e2e_ms, 0.01)})
	if bubble and reply != "":
		bubble.text = "%s: %s" % [tr("roster." + p["persona"]), reply.capitalize()]


func _sync_view() -> void:
	for e in sim.entities:
		var s: Sprite2D = sprites[e.id]
		s.position = e.pos.round()
		s.visible = e.alive()
		s.flip_h = e.facing < 0
		s.frame = maxi(0, FRAME_NAMES.find(e.anim))
		s.modulate = Color(1, 0.4, 0.4) if e.hit_flash > 0 else (Color(1, 1, 0.6) if e.taunt_left > 0 else Color.WHITE)
	var lines := []
	if frozen:
		var ol := [tr("hud.freeze.title") + " (%.1f ms)" % swap_recs.get("wall_ms", 0.0)]
		var i := 1
		for r in swap_recs.get("recommendations", []):
			ol.append("%d. %s  %s %d/%d  score %.1f" % [i, tr("roster." + r["id"]), tr("hud.hp"), r["hp"], r["max_hp"], r["score"]])
			i += 1
		var near: Array = sim.entities.filter(func(o): return o.team == 1 and o.alive()).map(func(o): return "%s %d" % [o.id, o.hp])
		ol.append(tr("hud.freeze.threats") + ": " + ", ".join(near.slice(0, 3)))
		ol.append(tr("hud.freeze.hint"))
		overlay.text = "\n".join(ol)
	else:
		overlay.text = "%s: %s%s" % [tr("hud.tactic"), sim.tactic, (" · focus " + sim.focus_kind) if sim.focus_kind != "" else ""]
	for e in sim.entities:
		if e.team == 0 and e.kind == "fighter":
			lines.append("%s%s %s %d/%d" % ["> " if e.is_leader else "  ", tr("roster." + e.id), tr("hud.hp"), e.hp, e.max_hp])
	lines.append("%s: %d" % [tr("hud.enemies_left"), sim.team_alive(1).size()])
	match sim.outcome():
		"victory": lines.append(tr("hud.victory"))
		"defeat": lines.append(tr("hud.defeat"))
		_: lines.append(tr("hud.objective.defeat"))
	lines.append(tr("hud.hint.controls"))
	hud.text = "\n".join(lines)


func _scripted_swap(s: Dictionary) -> void:
	var recs: Array = swap_recs.get("recommendations", [])
	var pick: String = recs[0]["id"] if not recs.is_empty() else ""
	if pick == (sim.leader().id if sim.leader() else "") and recs.size() > 1:
		pick = recs[1]["id"] if s.get("force_change", false) else pick
	do_swap(pick)
	toggle_freeze()


## Windowed autoplay ("attract"/demo mode) plays the same encounter script, holding
## the time-freeze overlay on screen for FREEZE_HOLD frames so it can be seen/captured.
const FREEZE_HOLD := 90
var _script_i := 0
var _freeze_hold := 0
var _freeze_entry: Dictionary = {}


func _demo_script() -> bool:
	if _freeze_hold > 0:
		_freeze_hold -= 1
		if _freeze_hold == 0:
			_scripted_swap(_freeze_entry)
		return true
	var script_: Array = encounter.get("script", [])
	while _script_i < script_.size() and int(script_[_script_i]["tick"]) <= sim.tick:
		var s: Dictionary = script_[_script_i]
		_script_i += 1
		if s.has("command"):
			submit_command(s["command"])
		if s.get("freeze_swap", false):
			toggle_freeze()
			_freeze_entry = s
			_freeze_hold = FREEZE_HOLD
			return true
	return false


func _run_headless() -> void:
	var limit := int(encounter.get("tick_limit", 7200))
	var t0 := Time.get_ticks_usec()
	var script_: Array = encounter.get("script", [])
	var si := 0
	while sim.outcome() == "running" and sim.tick < limit:
		while si < script_.size() and int(script_[si]["tick"]) <= sim.tick:
			var s: Dictionary = script_[si]
			si += 1
			if s.has("command"):
				submit_command(s["command"])
			if s.get("freeze_swap", false):
				toggle_freeze()
				# acceptance-only: threaded ranking must equal the serial ranking exactly
				var serial: Array = SwapAdvisor.rank(sim, false)["recommendations"].map(func(r): return [r["id"], r["score"]])
				swap_parity = serial == swap_recs.get("recommendations", []).map(func(r): return [r["id"], r["score"]])
				_scripted_swap(s)
		_step({})
	var t_lm := Time.get_ticks_usec()
	if sim.outcome() == "victory" and encounter.has("dialogue"):
		for d in encounter["dialogue"]:
			talk(d["persona"], int(d.get("seed", 1)), d.get("topic", "<s>"))
		CascadeHub.drain(sim.tick)
	var result: Dictionary = sim.summary()
	if brain:
		result["ai"] = {"brain": "bt+policy", "decisions": brain.decisions, "girt": GIRT.report(), "selftest": GIRT.selftest(), "lm_selftest": GIRT.lm_selftest(),
			"cascade": CascadeHub.counts, "callouts": callout_log.slice(0, 40), "callouts_total": callout_log.size(),
			"intents": intents_handled, "swaps": swaps, "swap_recs": swap_recs.get("recommendations", []).map(func(r): return [r["id"], r["score"]]),
			"swap_wall_ms": swap_recs.get("wall_ms", 0.0), "swap_threaded": swap_recs.get("threaded", false), "field_warm_ms": field_warm_ms, "swap_parity": swap_parity, "dialogue": dialogue_log}
	result["increment"] = encounter.get("increment", encounter["id"])
	result["encounter"] = encounter["id"]
	result["sim_ms"] = snappedf((Time.get_ticks_usec() - t0) / 1000.0, 0.01)
	var assets := [encounter["tilemap"]]
	for e in sim.entities:
		if not assets.has(e.sprite_id):
			assets.append(e.sprite_id)
	result["assets"] = assets
	result["abilities_loaded"] = Fabric.abilities.size()
	result["tres_loaded"] = Fabric.game_data.get("abilities", {}).keys().filter(func(k): return ResourceLoader.exists(Fabric.game_data["abilities"][k]["tres"])).size()
	result["music_loaded"] = music != null and music.stream != null
	print("FABRIC_RESULT " + JSON.stringify(result))
	var ok: bool = sim.outcome() == "victory"
	print("ENCOUNTER %s %s" % [encounter["id"], "OK" if ok else "FAIL"])
	get_tree().quit(0 if ok else 1)
