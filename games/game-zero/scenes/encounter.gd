extends Node2D
## Generic encounter scene: renders a CombatSim built from Fabric data.
## Headless acceptance: godot --headless --path games/game-zero -- --scene=<sandbox|combat> --autoplay

const EncounterBuilder = preload("res://sim/encounter_builder.gd")
const Brain = preload("res://ai/brain.gd")
const SwapAdvisor = preload("res://ai/swap_advisor.gd")
var field_warm_ms := 0.0
var swap_parity := false
const IntentGrammar = preload("res://ai/intent_grammar.gd")
const StateChart = preload("res://sim/statechart.gd")
const PROBE_TICKS := 90       # F4 health probe: forward-simulate a clone 1.5 s after a live commit
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
var chart                      # F4 parallel statechart: combat / reload / dialogue regions
var layout: Dictionary
var snapshots := {}            # name -> {"sim": Dictionary, "wal_len": int, "path": String}
var live_report := {}
var _replaying := false
var _serve := false
var _status_frames := 0
var _leader_moving := false
var resume_info := {}
var _last_autosnap := -1
const AUTOSNAP_TICKS := 300      # serve mode: on-disk session snapshot cadence (5 s of sim)


func _ready() -> void:
	autoplay = Fabric.flag("autoplay")
	_serve = Fabric.flag("serve")
	encounter = Fabric.read_json("res://data/encounters/%s.json" % Fabric.arg("encounter", default_encounter))
	_build()
	if Fabric.flag("live-resume") and Live.enabled:
		resume_info = _resume()
	_publish_status(true)
	if autoplay and DisplayServer.get_name() == "headless" and not _serve:
		_run_headless()


func _build() -> void:
	for c in get_children():
		c.queue_free()
	sprites.clear()
	layout = Fabric.json_asset(encounter["tilemap"])
	sim = EncounterBuilder.build(encounter, layout, Fabric.game_data, Fabric.abilities)
	chart = StateChart.new(Fabric.read_json("res://data/statecharts/live_session.json"))
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
		_sprite_for(e)
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
	if sim == null or (autoplay and DisplayServer.get_name() == "headless" and not _serve):
		return
	for t in Live.pending():
		apply_ticket(t)
		if t.get("control") == "quit":
			_quit_serve()
			return
	_status_frames += 1
	if _status_frames % 30 == 0:
		_publish_status(true)
	if _serve and Live.enabled and sim.tick > 0 and sim.tick % AUTOSNAP_TICKS == 0 and sim.tick != _last_autosnap:
		_autosnap()
	if command_box.visible or settings_open():
		return
	if Input.is_action_just_pressed("settings"):
		open_settings()
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
			if Input.is_action_just_pressed("swap_pick_%d" % (i + 1)) and i < swap_recs.get("recommendations", []).size():
				do_swap(swap_recs["recommendations"][i]["id"])
				toggle_freeze()
				break
		_sync_view()
		return
	if Input.is_action_just_pressed("tactic_menu"):
		submit_command("defend" if sim.tactic == "aggressive" else "charge")
	if Input.is_action_just_pressed("command"):
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
	chart.tick = sim.tick
	var l = sim.leader()
	var mv: bool = l != null and l.moving
	if mv != _leader_moving:
		_leader_moving = mv
		chart.send("move" if mv else "stop")
	_emit_events()
	CascadeHub.drain(sim.tick)


# ---------------------------------------------------------------- F4: live tune / hot reload / snapshots

## Two-phase commit of one live ticket at a tick boundary (SPEC §6.3 atomic reload).
func apply_ticket(t: Dictionary, replay: bool = false) -> Dictionary:
	chart.send("ticket")
	if t.get("control") == "quit" and t.get("patches", []).is_empty() and t.get("assets", []).is_empty():
		chart.send("invalid")
		return Live.ack(t, "committed", {"tick": sim.tick, "control": "quit"}) if not replay else {}
	var reason: String = "" if replay else Live.validate(t, Fabric.game_data)
	if reason != "":
		chart.send("invalid")
		return Live.ack(t, "rejected", {"tick": sim.tick, "reason": reason})
	chart.send("valid")
	if not replay:
		Live.begin(int(t.get("ticket", 0)))
		if Live.allow_fault and t.get("fault", "") == "crash":
			OS.crash("fault injected: crash during commit of ticket %d (guardian acceptance)" % int(t["ticket"]))
		if Live.allow_fault and t.get("fault", "") == "hang":
			while true:
				OS.delay_msec(1000)
	var t0 := Time.get_ticks_usec()
	var snap: Dictionary = sim.to_snapshot()
	var bak: Dictionary = Live.backup()
	var h0: String = sim.full_hash()
	var applied: Dictionary = Live.apply_data(t)
	for k in applied["sim"]:
		sim.set(k, applied["sim"][k])
	var restatted: int = EncounterBuilder.restat(sim, encounter, layout, Fabric.game_data, Fabric.abilities)
	_refresh_textures()
	chart.send("applied")
	if replay:
		chart.send("probe_ok")
		return {}
	var probe := _probe()
	if t.get("fault", "") == "probe" and Live.allow_fault:
		probe = "fault injected (acceptance test of the rollback path)"
	if probe != "":
		chart.send("probe_fail")
		sim.restore(snap)
		Live.restore_backup(bak)
		_refresh_textures()
		chart.send("restored")
		return Live.ack(t, "rolled_back", {"tick": sim.tick, "reason": probe, "hash_before": h0, "hash_after": sim.full_hash(),
			"restored_equal": sim.full_hash() == h0})
	chart.send("probe_ok")
	Live.log_input(sim.tick, "ticket", t)
	if _serve:
		_autosnap.call_deferred()
	return Live.ack(t, "committed", {"tick": sim.tick, "hash_before": h0, "hash_after": sim.full_hash(), "restatted": restatted,
		"assets": t.get("assets", []).map(func(a): return a["id"]), "apply_us": Time.get_ticks_usec() - t0})


## Health probe: a forward clone must survive PROBE_TICKS with sane invariants.
func _probe() -> String:
	var c = sim.clone()
	c.forward = true
	for _i in PROBE_TICKS:
		c.step({})
		if c.outcome() != "running":
			break
	for e in c.entities:
		if is_nan(e.pos.x) or is_nan(e.pos.y) or e.hp < 0 or e.hp > e.max_hp or e.max_hp <= 0:
			return "invariant violated by %s" % e.id
		if not e.casting.is_empty() and int(e.casting["left"]) > 3600:
			return "cast never resolves for %s" % e.id
	return ""


func _refresh_textures() -> void:
	for e in sim.entities:
		if sprites.has(e.id):
			sprites[e.id].texture = Fabric.texture(e.sprite_id)


func _snapshot_dict(name: String) -> Dictionary:
	return {"name": name, "sim": sim.to_snapshot(), "wal_len": Live.wal.size(), "full_hash": sim.full_hash(),
		"chart": chart.to_dict(), "data": {"game_data": Fabric.game_data, "abilities": Fabric.abilities, "registry": Fabric.registry},
		"live_applied": Live.applied, "script_i": _script_i, "event_cursor": _event_cursor}


func take_snapshot(name: String) -> Dictionary:
	var snap := _snapshot_dict(name)
	DirAccess.make_dir_recursive_absolute("user://snapshots")
	var path := "user://snapshots/%s.json" % name
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(JSON.stringify(snap, "", true, true))
	f.close()
	snap["path"] = ProjectSettings.globalize_path(path)
	snapshots[name] = snap
	return snap


## Serve mode: atomic on-disk session snapshot in the live dir (restart point for the guardian).
func _autosnap() -> void:
	_last_autosnap = sim.tick
	Live.write_file("snapshots/auto.json", _snapshot_dict("auto"))


## Restore sim + chart + data overlay from a snapshot dictionary (shared by replay and resume).
func _load_snapshot_state(snap: Dictionary) -> void:
	sim.restore(snap["sim"])
	chart.restore(snap["chart"])
	_event_cursor = sim.events.size()
	Fabric.game_data = snap["data"]["game_data"]
	for id in snap["data"]["abilities"]:
		if Fabric.abilities.has(id):
			for k in snap["data"]["abilities"][id]:
				var v = snap["data"]["abilities"][id][k]
				Fabric.abilities[id][k] = int(v) if typeof(Fabric.abilities[id][k]) == TYPE_INT else v
	if snap["data"].has("registry"):
		Fabric.registry = snap["data"]["registry"]
		Fabric.clear_caches()
	_refresh_textures()


## Guardian restart (`--live-resume`): restore the last session snapshot, quarantine the ticket
## that was in flight when the previous process died, re-apply committed tickets after the snapshot.
func _resume() -> Dictionary:
	var info := {"from_snapshot": false, "reapplied": [], "quarantined": 0, "tick": 0}
	var snap := Live.read_json_file("snapshots/auto.json")
	var after := 0
	if not snap.is_empty():
		_load_snapshot_state(snap)
		after = int(snap.get("live_applied", 0))
		_script_i = int(snap.get("script_i", 0))
		info["from_snapshot"] = true
	info["quarantined"] = Live.quarantine_inflight()
	Live.applied = after
	for n in range(after + 1, Live.head() + 1):
		var a := Live.read_ack(n)
		if a.is_empty():
			break                       # never handled: leave it pending for the normal poll
		Live.applied = n
		if str(a.get("status", "")) == "committed":
			var t := Live.read_ticket(n)
			if not t.is_empty() and (t.get("patches", []).size() > 0 or t.get("assets", []).size() > 0):
				apply_ticket(t, true)
				Live.log_input(sim.tick, "ticket", t)
				info["reapplied"].append(n)
	info["tick"] = sim.tick
	info["full_hash"] = sim.full_hash()
	return info


func _tuned() -> Dictionary:
	return {"rock_brute_max_hp": _max_hp_of("rock_brute"), "leash": sim.leash, "separation": sim.separation,
		"sprite_override": Fabric.file_path("spr_rock_brute", "spr_rock_brute.png")}


func _publish_status(ready: bool) -> void:
	Live.status({"ready": ready, "scene": encounter["id"], "tick": sim.tick, "pid": Fabric.pid(), "applied": Live.applied,
		"outcome": sim.outcome(), "tuned": _tuned(), "resume": resume_info, "full_hash": sim.full_hash(),
		"hb_unix": Time.get_unix_time_from_system()})


## Restore a snapshot from disk and replay the session WAL (inputs + live tickets) to `until_tick`.
func replay_from_disk(name: String, until_tick: int) -> Dictionary:
	var snap = JSON.parse_string(FileAccess.get_file_as_string("user://snapshots/%s.json" % name))
	var wal: Array = Live.wal.duplicate()
	_load_snapshot_state(snap)
	var restored_hash: String = sim.full_hash()
	_replaying = true
	var i := int(snap["wal_len"])
	while sim.outcome() == "running" and sim.tick < until_tick:
		while i < wal.size() and int(wal[i]["tick"]) <= sim.tick:
			var w: Dictionary = wal[i]
			i += 1
			match w["kind"]:
				"command": submit_command(w["payload"])
				"swap": do_swap(w["payload"])
				"ticket": apply_ticket(w["payload"], true)
		_step({})
	_replaying = false
	return {"restored_hash_equal": restored_hash == snap["full_hash"], "replayed": wal.size() - int(snap["wal_len"]),
		"final_hash": sim.full_hash(), "tick": sim.tick, "outcome": sim.outcome()}


func _quit_serve() -> void:
	_publish_status(false)
	print("FABRIC_RESULT " + JSON.stringify({"serve": {"acks": Live.acks, "ticks": sim.tick, "wal": Live.wal.size()}}))
	get_tree().quit(0)


# ---------------------------------------------------------------- F3: swap / intents / callouts / dialogue

func toggle_freeze() -> void:
	frozen = not frozen
	chart.send("freeze" if frozen else "resume")
	if frozen:
		swap_recs = SwapAdvisor.rank(sim)


func do_swap(id_: String, log_it: bool = true) -> void:
	if log_it and not _replaying:
		Live.log_input(sim.tick, "swap", id_)
	sim.set_leader(id_)
	chart.send("swap")
	if not _replaying:
		swaps.append({"tick": sim.tick, "to": id_, "wall_ms": swap_recs.get("wall_ms", 0.0)})


func submit_command(text: String) -> void:
	if not _replaying:
		Live.log_input(sim.tick, "command", text)
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
				do_swap(p["to"], false)
		_:
			return
	chart.send("intent")
	if not _replaying:
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
		if ev["type"] in ["battle_start", "victory", "defeat"]:
			chart.send(ev["type"])
		var sp := _speaker_for(ev)
		if sp[0] != "" and not _replaying:
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
	chart.send("dialogue_request")
	var reply: String = GIRT.lm_generate(p["persona"], int(p["seed"]), p["topic"])
	var e2e_ms := (Time.get_ticks_usec() - int(p["t_us"])) / 1000.0
	dialogue_log.append({"persona": p["persona"], "reply": reply, "e2e_ms": snappedf(e2e_ms, 0.01)})
	chart.send("dialogue_reply")
	if bubble and reply != "":
		bubble.text = "%s: %s" % [tr("roster." + p["persona"]), reply.capitalize()]


func _sprite_for(e) -> Sprite2D:
	var s := Sprite2D.new()
	s.texture = Fabric.texture(e.sprite_id)
	s.hframes = FRAME_NAMES.size()
	if e.kind == "pet":
		s.scale = Vector2(0.75, 0.75)
	elif e.tier >= 3:
		s.scale = Vector2(1.5, 1.5)        # bosses read bigger at a glance
	add_child(s)
	sprites[e.id] = s
	return s


func _sync_view() -> void:
	for e in sim.entities:
		var s: Sprite2D = sprites[e.id] if sprites.has(e.id) else _sprite_for(e)   # F5: summoned adds
		s.position = e.pos.round()
		s.visible = e.alive()
		s.flip_h = e.facing < 0
		s.frame = maxi(0, FRAME_NAMES.find(e.anim))
		s.modulate = Color(1, 0.4, 0.4) if e.hit_flash > 0 else (Color(1, 1, 0.6) if e.taunt_left > 0 else Color.WHITE)
	var lines := []
	if frozen:
		overlay.text = "\n".join(freeze_overlay())
	else:
		overlay.text = "%s: %s%s" % [tr("hud.tactic"), tr("tactic." + sim.tactic), (" · " + tr("hud.focus") + " " + sim.focus_kind) if sim.focus_kind != "" else ""]
	for e in sim.entities:
		if e.team == 0 and e.kind == "fighter":
			lines.append("%s%s %s %d/%d" % ["> " if e.is_leader else "  ", tr("roster." + e.id), tr("hud.hp"), e.hp, e.max_hp])
	lines.append("%s: %d" % [tr("hud.enemies_left"), sim.team_alive(1).size()])
	match sim.outcome():
		"victory": lines.append(tr("hud.victory"))
		"defeat": lines.append(tr("hud.defeat"))
		_: lines.append(tr("hud.objective.defeat"))
	lines.append(Fabric.hint("hud.hint.controls"))
	hud.text = "\n".join(lines)


## Time-freeze overlay (GAME_SPEC §4.1): ranked swaps with each fighter's HP, target, cooldowns and
## cell; nearby threats with a threat score; pet status. Also captured headless (F6 acceptance).
func freeze_overlay() -> Array:
	var ol := [tr("hud.freeze.title") + " (%.1f ms)" % swap_recs.get("wall_ms", 0.0)]
	var i := 1
	for r in swap_recs.get("recommendations", []):
		var e = sim.by_id.get(r["id"])
		var cds := []
		for k in r.get("cooldowns", {}):
			if int(r["cooldowns"][k]) > 0:
				cds.append("%s %.1fs" % [tr("ability." + str(k)), int(r["cooldowns"][k]) / 60.0])
		var cell: Vector2i = sim.grid.to_cell(e.pos) if e else Vector2i(-1, -1)
		var tgt: String = str(r.get("target", ""))
		ol.append("%d. %s  %s %d/%d  %s %.1f  %s %s  %s %s  @%d,%d" % [i, tr("roster." + r["id"]), tr("hud.hp"), r["hp"], r["max_hp"],
			tr("hud.freeze.score"), r["score"], tr("hud.freeze.target"), tgt if tgt != "" else "-",
			tr("hud.freeze.cooldowns"), ", ".join(cds) if not cds.is_empty() else tr("hud.freeze.ready"), cell.x, cell.y])
		i += 1
	var l = sim.leader()
	var threats := []
	for o in sim.entities:
		if o.team == 1 and o.alive():
			var d: float = o.pos.distance_to(l.pos) if l else 999.0
			threats.append([snappedf(o.atk * (2.0 if d <= o.aggro_range else 1.0) * (1.0 + o.tier) / maxf(1.0, d / 32.0), 0.1), o])
	threats.sort_custom(func(a, b): return a[0] > b[0])
	ol.append(tr("hud.freeze.threats") + ": " + ", ".join(threats.slice(0, 3).map(func(t): return "%s %d (%.1f)" % [str(t[1].get_meta("ref", t[1].id)), t[1].hp, t[0]])))
	var pets := []
	for p in sim.entities:
		if p.kind == "pet" and p.team == 0:
			pets.append("%s→%s %d/%d" % [str(p.get_meta("ref", p.id)), tr("roster." + p.owner_id), p.hp, p.max_hp])
	ol.append(tr("hud.freeze.pets") + ": " + (", ".join(pets) if not pets.is_empty() else "-"))
	ol.append(Fabric.hint("hud.freeze.hint"))
	return ol


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
			if s.has("snapshot"):
				take_snapshot(s["snapshot"])
			if s.get("live_poll", false):
				for t in Live.pending(true):
					apply_ticket(t)
			if s.has("command"):
				submit_command(s["command"])
			if s.get("freeze_swap", false):
				toggle_freeze()
				# acceptance-only: threaded ranking must equal the serial ranking exactly
				var serial: Array = SwapAdvisor.rank(sim, false)["recommendations"].map(func(r): return [r["id"], r["score"]])
				swap_parity = serial == swap_recs.get("recommendations", []).map(func(r): return [r["id"], r["score"]])
				_scripted_swap(s)
		_step({})
	if encounter.has("replay_check") and sim.outcome() != "running":
		var final_hash: String = sim.full_hash()
		var final_tick: int = sim.tick
		var final_summary_hash: String = sim.state_hash()
		var outcome0: String = sim.outcome()
		var chart_main := {"events": chart.events.duplicate(), "active": chart.active.duplicate(),
			"transitions": chart.trace.size()}
		var rp := replay_from_disk(str(encounter["replay_check"]), final_tick)
		live_report = {"acks": Live.acks, "wal": Live.wal.map(func(w): return {"tick": w["tick"], "kind": w["kind"]}),
			"snapshots": snapshots.keys(), "snapshot_bytes": FileAccess.get_file_as_bytes("user://snapshots/%s.json" % encounter["replay_check"]).size(),
			"final_hash": final_hash, "replay": rp, "replay_equal": rp["final_hash"] == final_hash and rp["outcome"] == outcome0,
			"chart_trace": chart.trace.filter(func(r): return r["region"] == "reload").map(func(r): return "%s>%s" % [r["from"], r["to"]]),
			"chart_active": chart.active, "chart_main": chart_main, "chart_active_after_replay": chart.active.duplicate(), "summary_hash": final_summary_hash,
			"tuned": _tuned(), "chart_replay_equal": chart.active == chart_main["active"],
			"restarts": 0, "live_dir": Live.dir}
	var t_lm := Time.get_ticks_usec()
	if sim.outcome() == "victory" and encounter.has("dialogue"):
		for d in encounter["dialogue"]:
			talk(d["persona"], int(d.get("seed", 1)), d.get("topic", "<s>"))
		CascadeHub.drain(sim.tick)
	var result: Dictionary = sim.summary()
	if sim.outcome() == "victory" and encounter.get("save_on_victory", false):
		result["save"] = save_progress()
	if brain:
		result["ai"] = {"brain": "bt+policy", "decisions": brain.decisions, "girt": GIRT.report(), "selftest": GIRT.selftest(), "lm_selftest": GIRT.lm_selftest(),
			"cascade": CascadeHub.counts, "callouts": callout_log.slice(0, 40), "callouts_total": callout_log.size(),
			"intents": intents_handled, "swaps": swaps, "swap_recs": swap_recs.get("recommendations", []).map(func(r): return [r["id"], r["score"]]),
			"swap_wall_ms": swap_recs.get("wall_ms", 0.0), "swap_threaded": swap_recs.get("threaded", false), "field_warm_ms": field_warm_ms, "swap_parity": swap_parity, "dialogue": dialogue_log}
	if not live_report.is_empty():
		result["live"] = live_report
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
	var mus = encounter.get("music", {})
	result["music_stem"] = str(mus.get("stem", "")) if typeof(mus) == TYPE_DICTIONARY else ""
	for e in sim.entities:
		if not e.phases.is_empty():
			result["boss"] = {"id": e.id, "ref": e.get_meta("ref", ""), "tier": e.tier, "defeated": not e.alive(),
				"phases_reached": e.phase + 1, "phase_events": sim.events.filter(func(ev): return ev["type"] == "boss_phase").size(),
				"summons": sim.summons, "max_hp": e.max_hp}
	print("FABRIC_RESULT " + JSON.stringify(result))
	var ok: bool = sim.outcome() == "victory"
	print("ENCOUNTER %s %s" % [encounter["id"], "OK" if ok else "FAIL"])
	get_tree().quit(0 if ok else 1)


## F5: fold the encounter outcome into the Player State save (profile / roster / world).
const XP_PER_TIER := 10        # [INFERENCE] F5-5: xp per defeated hostile = tier × 10
func save_progress() -> Dictionary:
	var s: Dictionary = Save.load_slot()
	var leader = sim.leader()
	if s.is_empty():
		var lv := {}
		for m in encounter["party"]:
			lv[m["ref"]] = int(m.get("level", 1))
		s = Save.new_save(str(leader.get_meta("ref", leader.id)) if leader else "", lv, [])
	var xp := 0
	var bosses := []
	for e in sim.entities:
		if e.team == 1 and not e.alive():
			xp += XP_PER_TIER * maxi(1, e.tier)
			if not e.phases.is_empty():
				bosses.append(str(e.get_meta("ref", e.id)))
	var r: Dictionary = s["roster"]
	for m in encounter["party"]:
		var f: Dictionary = r["fighters"].get(m["ref"], {"level": int(m.get("level", 1)), "xp": 0})
		f["level"] = maxi(int(f["level"]), int(m.get("level", 1)))
		f["xp"] = int(f["xp"]) + xp
		r["fighters"][m["ref"]] = f
		for p in m.get("pets", []):
			if not r["pets"]["owned"].has(p):
				r["pets"]["owned"].append(p)
		if not m.get("pets", []).is_empty():
			r["pets"]["assigned"][m["ref"]] = m["pets"].duplicate()
	if leader:
		r["leader"] = str(leader.get_meta("ref", leader.id))
	var w: Dictionary = s["world"]
	w["area"] = encounter["tilemap"]
	if not w["cleared"].has(encounter["id"]):
		w["cleared"].append(encounter["id"])
	for b in bosses:
		if not w["bosses_defeated"].has(b):
			w["bosses_defeated"].append(b)
	s["profile"]["playtime_ticks"] = int(s["profile"]["playtime_ticks"]) + sim.tick
	s["profile"]["stats"]["encounters_won"] = int(s["profile"]["stats"]["encounters_won"]) + 1
	s["profile"]["stats"]["bosses_defeated"] = w["bosses_defeated"].size()
	var sum := Save.write(s)
	var state: Dictionary = Save.canon(s)
	state["format"] = Save.FORMAT
	state["version"] = Save.CURRENT
	state["checksum"] = sum      # exactly what is on disk
	return {"path": Save.path(), "checksum": sum, "state": state}


func _max_hp_of(ref: String) -> int:
	for e in sim.entities:
		if str(e.get_meta("ref", "")) == ref:
			return e.max_hp
	return -1


# ---------------------------------------------------------------- settings (G-A11Y-01)

const SettingsMenu = preload("res://ui/settings_menu.gd")
var settings_menu: Node = null


func settings_open() -> bool:
	return settings_menu != null and is_instance_valid(settings_menu)


var _settings_closed_at := -100


func open_settings() -> Node:
	# the key press that closed the menu (Escape = ui_cancel = `settings`) must not reopen it in the same frame
	if settings_open() or Engine.get_physics_frames() - _settings_closed_at <= 1:
		return settings_menu
	settings_menu = SettingsMenu.new()
	settings_menu.closed.connect(func():
		settings_menu = null
		_settings_closed_at = Engine.get_physics_frames())
	add_child(settings_menu)
	return settings_menu
