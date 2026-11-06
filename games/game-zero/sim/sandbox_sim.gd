extends RefCounted

const SimGrid = preload("res://sim/grid.gd")
const SimEntity = preload("res://sim/entity.gd")
## F1 sandbox encounter simulation: 1 character, 1 tilemap, 1 enemy, 1 attack.
## Pure, fixed-step (60 Hz), deterministic. No LLM anywhere (ADR-0011).
## Rendering lives in scenes/sandbox.gd; this file is engine-logic only.

const TICK_HZ := 60

var grid: SimGrid
var entities: Array[SimEntity] = []
var tick: int = 0
var events: Array = []   # {tick, type, ...} — mirrored to telemetry
var _field_cache: Dictionary = {}
var _field_tick: Dictionary = {}


func _init(grid_: SimGrid) -> void:
	grid = grid_


func add(e: SimEntity) -> SimEntity:
	entities.append(e)
	return e


func player() -> SimEntity:
	for e in entities:
		if e.team == 0:
			return e
	return null


func hostiles_alive() -> Array[SimEntity]:
	var out: Array[SimEntity] = []
	for e in entities:
		if e.team != 0 and e.alive():
			out.append(e)
	return out


func outcome() -> String:
	var p := player()
	if p == null or not p.alive():
		return "defeat"
	if hostiles_alive().is_empty():
		return "victory"
	return "running"


func _field_to(e: SimEntity) -> Dictionary:
	# Recompute target flow field at most every 10 ticks per target.
	var c := grid.to_cell(e.pos)
	if not _field_cache.has(e.id) or tick - int(_field_tick.get(e.id, -999)) >= 10:
		_field_cache[e.id] = grid.flow_field(c)
		_field_tick[e.id] = tick
	return _field_cache[e.id]


func move(e: SimEntity, dir: Vector2) -> void:
	e.moving = dir.length_squared() > 0.0001
	if not e.moving:
		return
	var v := dir.normalized() * e.speed
	if absf(v.x) > 0.01:
		e.facing = 1 if v.x > 0 else -1
	var nx := e.pos + Vector2(v.x, 0)
	if not grid.blocked_at(nx, e.radius):
		e.pos = nx
	var ny := e.pos + Vector2(0, v.y)
	if not grid.blocked_at(ny, e.radius):
		e.pos = ny


func try_attack(e: SimEntity) -> void:
	if e.cooldown_left > 0 or e.windup_left > 0:
		return
	e.windup_left = e.attack_windup
	e.cooldown_left = e.attack_cooldown
	events.append({"tick": tick, "type": "attack_start", "by": e.id})


func _resolve_attack(e: SimEntity) -> void:
	for t in entities:
		if t.team == e.team or not t.alive():
			continue
		if e.pos.distance_to(t.pos) <= e.attack_range + t.radius:
			var dmg := maxi(1, e.atk - t.def)
			t.hp = maxi(0, t.hp - dmg)
			t.hit_flash = 8
			events.append({"tick": tick, "type": "hit", "by": e.id, "target": t.id, "dmg": dmg, "hp": t.hp})
			if not t.alive():
				e.kills += 1
				events.append({"tick": tick, "type": "defeated", "target": t.id, "by": e.id})


## Enemy brain (F1: rule-based chase/attack; BT + ONNX policy arrive in F3).
func _enemy_think(e: SimEntity) -> void:
	var p := player()
	if p == null or not p.alive():
		e.moving = false
		return
	var d := e.pos.distance_to(p.pos)
	if d <= e.attack_range:
		e.facing = 1 if p.pos.x >= e.pos.x else -1
		e.moving = false
		try_attack(e)
	elif d <= e.aggro_range:
		var wp := grid.next_step(_field_to(p), e.pos)
		move(e, wp - e.pos)
	else:
		e.moving = false


## Advance one fixed tick. `input` = {"move": Vector2, "attack": bool} for the player.
func step(input: Dictionary) -> void:
	if outcome() != "running":
		return
	tick += 1
	var p := player()
	move(p, input.get("move", Vector2.ZERO))
	if input.get("attack", false):
		try_attack(p)
	for e in entities:
		if e.team != 0 and e.alive():
			_enemy_think(e)
	for e in entities:
		if not e.alive():
			e.anim = "dead"
			continue
		if e.windup_left > 0:
			e.windup_left -= 1
			if e.windup_left == 0:
				_resolve_attack(e)
		if e.cooldown_left > 0:
			e.cooldown_left -= 1
		if e.hit_flash > 0:
			e.hit_flash -= 1
		if e.windup_left > 0:
			e.anim = "attack0"
		elif e.attack_cooldown - e.cooldown_left < 8 and e.cooldown_left > 0:
			e.anim = "attack1"
		elif e.moving:
			e.anim = "walk0" if (tick / 8) % 2 == 0 else "walk1"
		else:
			e.anim = "idle0" if (tick / 30) % 2 == 0 else "idle1"


## Autoplay agent for headless acceptance: path to nearest hostile, attack in range.
func autoplay_input() -> Dictionary:
	var p := player()
	var targets := hostiles_alive()
	if targets.is_empty():
		return {}
	var t: SimEntity = targets[0]
	var d := p.pos.distance_to(t.pos)
	if d <= p.attack_range * 0.8:
		p.facing = 1 if t.pos.x >= p.pos.x else -1
		return {"move": Vector2.ZERO, "attack": true}
	var wp := grid.next_step(_field_to(t), p.pos)
	return {"move": wp - p.pos, "attack": d <= p.attack_range}


func state_hash() -> String:
	var parts := [str(tick)]
	for e in entities:
		parts.append(JSON.stringify(e.snapshot()))
	return ",".join(parts).sha256_text().substr(0, 16)
