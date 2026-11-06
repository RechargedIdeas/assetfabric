extends Node2D
## Generic encounter scene: renders a CombatSim built from Fabric data.
## Headless acceptance: godot --headless --path games/game-zero -- --scene=<sandbox|combat> --autoplay

const EncounterBuilder = preload("res://sim/encounter_builder.gd")
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
	if Input.is_action_just_pressed("restart"):
		_build()
		return
	_accum += delta
	while _accum >= 1.0 / 60.0:
		_accum -= 1.0 / 60.0
		sim.step({} if autoplay else _player_input())
	_sync_view()


func _sync_view() -> void:
	for e in sim.entities:
		var s: Sprite2D = sprites[e.id]
		s.position = e.pos.round()
		s.visible = e.alive()
		s.flip_h = e.facing < 0
		s.frame = maxi(0, FRAME_NAMES.find(e.anim))
		s.modulate = Color(1, 0.4, 0.4) if e.hit_flash > 0 else (Color(1, 1, 0.6) if e.taunt_left > 0 else Color.WHITE)
	var lines := []
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


func _run_headless() -> void:
	var limit := int(encounter.get("tick_limit", 7200))
	var t0 := Time.get_ticks_usec()
	while sim.outcome() == "running" and sim.tick < limit:
		sim.step({})
	var result: Dictionary = sim.summary()
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
