extends RefCounted
## Party combat simulation (F1 sandbox → F2 first combat).
## Fixed-step 60 Hz, deterministic, rendering-free. No LLM anywhere (ADR-0011):
## decisions come from rule brains here (F2) and Behavior Trees / ONNX policies (F3).

const SimGrid = preload("res://sim/grid.gd")
const SimEntity = preload("res://sim/entity.gd")

const TICK_HZ := 60
const LEASH := 56.0          # followers stay near the leader when idle
const SEPARATION := 9.0

var grid
var entities: Array = []
var by_id: Dictionary = {}
var tick: int = 0
var events: Array = []
var brain_override: Callable   # F3: BT/policy brains plug in here
var _fields: Dictionary = {}
var _field_tick: Dictionary = {}


func _init(grid_) -> void:
	grid = grid_


func add(e) -> Variant:
	entities.append(e)
	by_id[e.id] = e
	return e


func leader():
	for e in entities:
		if e.is_leader and e.alive():
			return e
	for e in entities:
		if e.team == 0 and e.kind == "fighter" and e.alive():
			return e
	return null


func team_alive(team: int) -> Array:
	return entities.filter(func(e): return e.team == team and e.alive())


func outcome() -> String:
	var party := entities.filter(func(e): return e.team == 0 and e.kind == "fighter" and e.alive())
	if party.is_empty():
		return "defeat"
	if team_alive(1).is_empty():
		return "victory"
	return "running"


# ---------------------------------------------------------------- movement

func _field_to(e) -> Dictionary:
	if not _fields.has(e.id) or tick - int(_field_tick.get(e.id, -999)) >= 10:
		_fields[e.id] = grid.flow_field(grid.to_cell(e.pos))
		_field_tick[e.id] = tick
	return _fields[e.id]


func move(e, dir: Vector2) -> void:
	# separation from same-team neighbours (deterministic order)
	for o in entities:
		if o == e or not o.alive() or o.team != e.team:
			continue
		var d: Vector2 = e.pos - o.pos
		var l := d.length()
		if l > 0.001 and l < SEPARATION:
			dir += d / l * (SEPARATION - l) / SEPARATION * 0.8
	e.moving = dir.length_squared() > 0.0001
	if not e.moving:
		return
	var v: Vector2 = dir.normalized() * e.speed if dir.length() > 1.0 else dir * e.speed
	if absf(v.x) > 0.05:
		e.facing = 1 if v.x > 0 else -1
	var nx: Vector2 = e.pos + Vector2(v.x, 0)
	if not grid.blocked_at(nx, e.radius):
		e.pos = nx
	var ny: Vector2 = e.pos + Vector2(0, v.y)
	if not grid.blocked_at(ny, e.radius):
		e.pos = ny


func move_toward_entity(e, target) -> void:
	if e.pos.distance_to(target.pos) < 20.0:
		move(e, target.pos - e.pos)
	else:
		var wp: Vector2 = grid.next_step(_field_to(target), e.pos)
		move(e, wp - e.pos)


# ---------------------------------------------------------------- targeting

func nearest(e, team: int, max_d: float = INF):
	var best = null
	var bd := max_d
	for o in entities:
		if o.team == team and o.alive():
			var d: float = e.pos.distance_to(o.pos)
			if d < bd:
				bd = d
				best = o
	return best


func enemy_target(e):
	# hostiles prefer an active taunter in range
	if e.team == 1:
		for o in entities:
			if o.team == 0 and o.alive() and o.taunt_left > 0 and e.pos.distance_to(o.pos) <= e.aggro_range * 1.5:
				return o
		return nearest(e, 0, e.aggro_range)
	if e.kind == "pet":
		var owner = by_id.get(e.owner_id)
		var anchor = owner if owner and owner.alive() else e
		return nearest(anchor, 1, 96.0)
	var l = leader()
	var anchor2 = l if l else e
	return nearest(anchor2, 1, 128.0)


func lowest_ally(e, threshold: float, max_d: float):
	var best = null
	var br := threshold
	for o in entities:
		if o.team == e.team and o.alive() and e.pos.distance_to(o.pos) <= max_d:
			var r: float = float(o.hp) / o.max_hp
			if r < br:
				br = r
				best = o
	return best


# ---------------------------------------------------------------- abilities

func begin_cast(e, ab: Dictionary, target) -> void:
	e.casting = {"ability": ab, "target": target.id if target else "", "left": int(ab["windup"])}
	e.cooldowns[ab["id"]] = int(ab["cooldown"])
	e.last_ability = ab["id"]
	e.stats_dealt["casts"] += 1
	if target and target != e:
		e.facing = 1 if target.pos.x >= e.pos.x else -1
	events.append({"tick": tick, "type": "cast", "by": e.id, "ability": ab["id"], "target": e.casting["target"]})


func _damage(src, dst, power: float) -> void:
	var dmg := maxi(1, int(round(src.atk * power - dst.def)))
	dst.hp = maxi(0, dst.hp - dmg)
	dst.hit_flash = 8
	src.stats_dealt["damage"] += dmg
	src.stats_dealt["hits"] += 1
	events.append({"tick": tick, "type": "hit", "by": src.id, "target": dst.id, "dmg": dmg, "hp": dst.hp})
	if not dst.alive():
		src.stats_dealt["kills"] += 1
		events.append({"tick": tick, "type": "defeated", "target": dst.id, "by": src.id})


func resolve_cast(e) -> void:
	var ab: Dictionary = e.casting["ability"]
	var target = by_id.get(e.casting["target"])
	e.casting = {}
	var kind: String = ab["type"]
	var reach: float = float(ab["range"]) + 6.0
	match kind:
		"melee", "ranged":
			if target and target.alive() and e.pos.distance_to(target.pos) <= reach + target.radius:
				_damage(e, target, float(ab["power"]))
		"aoe":
			var center: Vector2 = target.pos if target and target.alive() else e.pos
			if e.pos.distance_to(center) > reach + 4.0:
				return
			for o in entities:
				if o.team != e.team and o.alive() and center.distance_to(o.pos) <= float(ab.get("radius", 20)):
					_damage(e, o, float(ab["power"]))
		"heal":
			if target and target.alive():
				var amt := int(round(e.atk * float(ab["power"])))
				var before: int = target.hp
				target.hp = mini(target.max_hp, target.hp + amt)
				e.stats_dealt["healing"] += target.hp - before
				events.append({"tick": tick, "type": "heal", "by": e.id, "target": target.id, "amount": target.hp - before})
		"taunt":
			e.taunt_left = int(ab.get("duration", 120))
			events.append({"tick": tick, "type": "taunt", "by": e.id})


## Pick the first ready ability (priority = list order) with a valid target in range.
func choose_ability(e, target) -> Array:
	for ab in e.ready_abilities():
		var kind: String = ab["type"]
		var r: float = float(ab["range"])
		if kind == "heal":
			var ally = lowest_ally(e, float(ab.get("threshold", 0.6)), r)
			if ally:
				return [ab, ally]
		elif kind == "taunt":
			var threats := entities.filter(func(o): return o.team != e.team and o.alive() and e.pos.distance_to(o.pos) <= r)
			if threats.size() >= 2 and e.taunt_left <= 0:
				return [ab, e]
		elif target and e.pos.distance_to(target.pos) <= r + target.radius:
			return [ab, target]
	return []


# ---------------------------------------------------------------- brains

## Default rule brain for followers, pets and hostiles. Returns nothing; acts on sim.
func think(e) -> void:
	if brain_override.is_valid():
		if brain_override.call(self, e):
			return
	rule_brain(e)


func rule_brain(e) -> void:
	if not e.casting.is_empty():
		return
	var target = enemy_target(e)
	if target == null and e.is_leader:
		target = nearest(e, 1)   # autoplay leader pushes the objective: hunt remaining hostiles
	var pick := choose_ability(e, target)
	if not pick.is_empty():
		e.moving = false
		begin_cast(e, pick[0], pick[1])
		return
	if target:
		# ranged units hold at ~80% of their best range
		var best_range := 0.0
		for ab in e.abilities:
			if ab["target"] == "enemy":
				best_range = maxf(best_range, float(ab["range"]))
		if e.pos.distance_to(target.pos) > best_range * 0.8:
			move_toward_entity(e, target)
		else:
			e.moving = false
		return
	# idle: followers/pets regroup on leader/owner
	var anchor = null
	if e.kind == "pet":
		anchor = by_id.get(e.owner_id)
	elif e.team == 0 and not e.is_leader:
		anchor = leader()
	if anchor and anchor.alive() and e.pos.distance_to(anchor.pos) > LEASH * (0.5 if e.kind == "pet" else 1.0):
		move_toward_entity(e, anchor)
	else:
		e.moving = false


# ---------------------------------------------------------------- tick

## `input` drives the leader: {"move": Vector2, "attack": bool, "skill": bool}. Empty → autoplay.
func step(input: Dictionary = {}) -> void:
	if outcome() != "running":
		return
	tick += 1
	var l = leader()
	for e in entities:
		if not e.alive():
			continue
		if e == l and not input.is_empty():
			_player_control(e, input)
		else:
			think(e)
	for e in entities:
		if not e.alive():
			e.anim = "dead"
			continue
		if not e.casting.is_empty():
			e.casting["left"] -= 1
			if e.casting["left"] <= 0:
				resolve_cast(e)
		for k in e.cooldowns:
			if e.cooldowns[k] > 0:
				e.cooldowns[k] -= 1
		if e.taunt_left > 0:
			e.taunt_left -= 1
		if e.hit_flash > 0:
			e.hit_flash -= 1
		_animate(e)


func _player_control(e, input: Dictionary) -> void:
	if e.casting.is_empty():
		move(e, input.get("move", Vector2.ZERO))
	if input.get("attack", false) or input.get("skill", false):
		var target = nearest(e, 1, 140.0)
		var abs_: Array = e.ready_abilities()
		# attack = last ability (basic); skill = first (signature)
		if not abs_.is_empty():
			var ab: Dictionary = e.abilities[0] if input.get("skill", false) else e.abilities[e.abilities.size() - 1]
			if abs_.has(ab):
				var tgt = target
				if ab["type"] == "heal":
					tgt = lowest_ally(e, 1.01, float(ab["range"]))
				elif ab["type"] == "taunt":
					tgt = e
				begin_cast(e, ab, tgt if tgt else e)


func _animate(e) -> void:
	if not e.casting.is_empty():
		e.anim = "attack0"
	elif e.last_ability != "" and int(e.cooldowns.get(e.last_ability, 0)) > 0 and \
			_cd_of(e, e.last_ability) - int(e.cooldowns[e.last_ability]) < 8:
		e.anim = "attack1"
	elif e.moving:
		e.anim = "walk0" if (tick / 8) % 2 == 0 else "walk1"
	else:
		e.anim = "idle0" if (tick / 30) % 2 == 0 else "idle1"


func _cd_of(e, ab_id: String) -> int:
	for a in e.abilities:
		if a["id"] == ab_id:
			return int(a["cooldown"])
	return 0


func state_hash() -> String:
	var parts := [str(tick)]
	for e in entities:
		parts.append(JSON.stringify(e.snapshot()))
	return ",".join(parts).sha256_text().substr(0, 16)


func summary() -> Dictionary:
	var per := {}
	for e in entities:
		per[e.id] = {"kind": e.kind, "team": e.team, "hp": e.hp, "max_hp": e.max_hp, "alive": e.alive()}
		per[e.id].merge(e.stats_dealt)
	var used := {}
	for ev in events:
		if ev["type"] == "cast":
			used[ev["ability"]] = true
	var ab_list := used.keys()
	ab_list.sort()
	return {"outcome": outcome(), "ticks": tick, "state_hash": state_hash(), "entities": per, "abilities_used": ab_list,
		"hits": events.filter(func(ev): return ev["type"] == "hit").size()}
