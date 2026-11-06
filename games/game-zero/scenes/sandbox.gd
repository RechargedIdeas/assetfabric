extends Node2D
## F1 sandbox encounter — renders SandboxSim with Fabric-generated assets.
## Run headless acceptance: godot --headless --path games/game-zero -- --scene=sandbox --autoplay

const SimGrid = preload("res://sim/grid.gd")
const SimEntity = preload("res://sim/entity.gd")
const SandboxSim = preload("res://sim/sandbox_sim.gd")

const FRAME_NAMES := ["idle0", "idle1", "walk0", "walk1", "attack0", "attack1"]

var sim: SandboxSim
var encounter: Dictionary
var tileset: Texture2D
var sprites := {}      # entity id -> Sprite2D
var hud: Label
var autoplay := false
var _accum := 0.0
var _reported := false


func _ready() -> void:
	autoplay = Fabric.flag("autoplay")
	encounter = Fabric.read_json("res://data/encounters/%s.json" % Fabric.arg("encounter", "sandbox"))
	_build()
	if autoplay and DisplayServer.get_name() == "headless":
		_run_headless()


func _build() -> void:
	for c in get_children():
		c.queue_free()
	sprites.clear()
	var layout = Fabric.json_asset(encounter["tilemap"])
	var grid = SimGrid.from_layout(layout)
	sim = SandboxSim.new(grid)
	tileset = Fabric.texture(encounter["tilemap"], encounter["tilemap"] + "_tiles.png")
	for i in encounter["party"].size():
		var m: Dictionary = encounter["party"][i]
		sim.add(SimEntity.from_stats(m["id"], 0, m["sprite"], m["stats"], grid.center(grid.start)))
	for i in encounter["hostiles"].size():
		var h: Dictionary = encounter["hostiles"][i]
		var at: Vector2i = grid.spawns[i % grid.spawns.size()] if not grid.spawns.is_empty() else grid.exit
		sim.add(SimEntity.from_stats(h["id"], 1, h["sprite"], h["stats"], grid.center(at)))
	for e in sim.entities:
		var s := Sprite2D.new()
		s.texture = Fabric.texture(e.sprite_id)
		s.hframes = FRAME_NAMES.size()
		s.centered = true
		add_child(s)
		sprites[e.id] = s
	var cam := Camera2D.new()
	cam.zoom = Vector2(2, 2)
	cam.position = Vector2(grid.width * grid.tile_size, grid.height * grid.tile_size) / 2.0
	add_child(cam)
	var layer := CanvasLayer.new()
	hud = Label.new()
	hud.position = Vector2(8, 8)
	layer.add_child(hud)
	add_child(layer)
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


func _input_from_player() -> Dictionary:
	var v := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	return {"move": v, "attack": Input.is_action_pressed("attack")}


func _physics_process(delta: float) -> void:
	if autoplay and DisplayServer.get_name() == "headless":
		return
	if Input.is_action_just_pressed("restart"):
		_build()
		return
	_accum += delta
	while _accum >= 1.0 / SandboxSim.TICK_HZ:
		_accum -= 1.0 / SandboxSim.TICK_HZ
		sim.step(sim.autoplay_input() if autoplay else _input_from_player())
	_sync_view()


func _sync_view() -> void:
	for e in sim.entities:
		var s: Sprite2D = sprites[e.id]
		s.position = e.pos.round()
		s.visible = e.alive()
		s.flip_h = e.facing < 0
		s.frame = maxi(0, FRAME_NAMES.find(e.anim))
		s.modulate = Color(1, 0.4, 0.4) if e.hit_flash > 0 else Color.WHITE
	var p = sim.player()
	var lines := ["%s %d/%d" % [tr("hud.hp"), p.hp, p.max_hp]]
	for h in sim.hostiles_alive():
		lines.append("%s %d/%d" % [tr("hud.enemy"), h.hp, h.max_hp])
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
		sim.step(sim.autoplay_input())
	var ms := (Time.get_ticks_usec() - t0) / 1000.0
	var result := {
		"increment": "sandbox-encounter",
		"outcome": sim.outcome(),
		"ticks": sim.tick,
		"sim_ms": snappedf(ms, 0.01),
		"player_hp": sim.player().hp,
		"hits": sim.events.filter(func(ev): return ev["type"] == "hit").size(),
		"state_hash": sim.state_hash(),
		"assets": [encounter["tilemap"]] + sim.entities.map(func(e): return e.sprite_id),
	}
	print("FABRIC_RESULT " + JSON.stringify(result))
	var ok: bool = sim.outcome() == "victory"
	print("F1 SANDBOX OK" if ok else "F1 SANDBOX FAIL")
	get_tree().quit(0 if ok else 1)
