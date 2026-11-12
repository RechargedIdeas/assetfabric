extends RefCounted
## Party combat simulation (F1 sandbox → F2 first combat).
## Fixed-step 60 Hz, deterministic, rendering-free. No LLM anywhere (ADR-0011):
## decisions come from rule brains here (F2) and Behavior Trees / ONNX policies (F3).

const SimGrid = preload("res://sim/grid.gd")
const SimEntity = preload("res://sim/entity.gd")

const TICK_HZ := 60
const LEASH := 56.0          # default; live-tunable as `sim.leash` (F4)
const SEPARATION := 9.0      # default; live-tunable as `sim.separation`
const SNAPSHOT_VERSION := 2      # v2 (F5): rng_state, variance, progress tick, boss phases
const STALL_TICKS := 1200        # F5 soft-lock: 20 s with no damage/heal while both sides live

var grid
var entities: Array = []
var by_id: Dictionary = {}
var tick: int = 0
var events: Array = []
var brain_override: Callable   # F3: BT/policy brains plug in here
var leader_manual := false     # true while the player drives the leader
var tactic := "aggressive"     # aggressive | defensive (CascadeHub intents)
var focus_kind := ""           # focus intent: enemy roster id prefix
var engaged := false
var brain_ref: RefCounted = null   # strong ref for a brain_override target owned by this sim
var forward := false           # true for swap-advisor clones: no global (GIRT) writes, thread-safe
var think_interval := 1        # forward-sim LOD: brains think every N ticks (swap advisor uses 3)
var leash := LEASH             # followers stay near the leader when idle
var separation := SEPARATION
# F5 Monte Carlo: seeded variance (0 = fully deterministic legacy behaviour, as in F1–F4)
var variance := 0.0            # ± fraction applied to every damage roll
var crit_chance := 0.0         # seeded encounters: chance of a ×1.5 hit
var rng_state := 0             # 31-bit LCG state; part of the snapshot
var last_progress_tick := 0    # last tick with damage or healing (soft-lock detector)
var summons := 0
var explore := false           # F6 world areas: no "victory" while exploring; only a wipe ends the area


func _init(grid_) -> void:
	grid = grid_


func add(e) -> Variant:
	entities.append(e)
	by_id[e.id] = e
	return e


func set_leader(id_: String) -> void:
	for e in entities:
		e.is_leader = e.id == id_
	events.append({"tick": tick, "type": "swap", "to": id_})


func clone():
	var c = get_script().new(grid)
	for e in entities:
		c.add(e.copy())
	c.tick = tick
	c.brain_override = brain_override
	c.tactic = tactic
	c.focus_kind = focus_kind
	c.engaged = engaged
	c.think_interval = think_interval
	c.leash = leash
	c.separation = separation
	c.variance = variance
	c.crit_chance = crit_chance
	c.rng_state = rng_state
	c.last_progress_tick = last_progress_tick
	c.summons = summons
	c.explore = explore
	return c


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
	var party := 0
	var foes := 0
	for e in entities:
		if e.hp > 0:
			if e.team == 0 and e.kind == "fighter":
				party += 1
			elif e.team == 1:
				foes += 1
	if party == 0:
		return "defeat"
	if explore:
		return "running"
	if foes == 0:
		return "victory"
	return "running"


# ---------------------------------------------------------------- movement

func move(e, dir: Vector2) -> void:
	# separation from same-team neighbours (deterministic order). F6: a player-driven leader
	# exploring the world is not shoved by followers (they part around it instead) — otherwise a
	# follower parked on the leader's next waypoint can pin it in place [INFERENCE F6-7].
	var shove: bool = not (explore and leader_manual and e.is_leader)
	for o in entities:
		if not shove:
			break
		if o == e or not o.alive() or o.team != e.team:
			continue
		var d: Vector2 = e.pos - o.pos
		var l := d.length()
		if l > 0.001 and l < separation:
			dir += d / l * (separation - l) / separation * 0.8
	e.moving = dir.length_squared() > 0.0001
	if not e.moving:
		return
	e.last_dir = dir
	var v: Vector2 = dir.normalized() * e.speed if dir.length() > 1.0 else dir * e.speed
	if absf(v.x) > 0.05:
		e.facing = 1 if v.x > 0 else -1
	var nx: Vector2 = e.pos + Vector2(v.x, 0)
	if not grid.blocked_at(nx, e.radius):
		e.pos = nx
	var ny: Vector2 = e.pos + Vector2(0, v.y)
	if not grid.blocked_at(ny, e.radius):
		e.pos = ny


## F5 rally: the autoplay leader stops just outside an un-pulled boss's aggro ring until every
## living follower is within the leash, so the whole party engages together. Without it the
## leader (whoever was picked at character select) tanked the opening alone and G-BAL-01
## measured the *pathing order*, not the matchup ([INFERENCE] F5-6).
const RALLY_TIER := 3
func rally_hold(e, target) -> bool:
	if not e.is_leader or leader_manual or target == null or target.tier < RALLY_TIER or target.hp < target.max_hp:
		return false
	var d: float = e.pos.distance_to(target.pos)
	if d < target.aggro_range * 0.9 or d > target.aggro_range + 32.0:
		return false
	for o in entities:
		if o.team == e.team and o.kind == "fighter" and o != e and o.alive() and o.pos.distance_to(e.pos) > leash:
			return true
	return false


func move_toward_entity(e, target) -> void:
	if e.pos.distance_to(target.pos) < 20.0:
		move(e, target.pos - e.pos)
	else:
		var wp: Vector2 = grid.step_toward(grid.to_cell(target.pos), e.pos)
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


## Deterministic LCG (Numerical Recipes constants, 31-bit) — same seed, same fight.
func rand01() -> float:
	rng_state = (rng_state * 1103515245 + 12345) & 0x7fffffff
	return float(rng_state) / 2147483648.0


func _damage(src, dst, power: float) -> void:
	var raw: float = src.atk * power - dst.def
	if variance > 0.0:
		raw *= 1.0 + variance * (rand01() * 2.0 - 1.0)
	if crit_chance > 0.0 and rand01() < crit_chance:
		raw *= 1.5
	var dmg := maxi(1, int(round(raw)))
	last_progress_tick = tick
	dst.hp = maxi(0, dst.hp - dmg)
	dst.hit_flash = 8
	src.stats_dealt["damage"] += dmg
	src.stats_dealt["hits"] += 1
	events.append({"tick": tick, "type": "hit", "by": src.id, "target": dst.id, "dmg": dmg, "hp": dst.hp})
	if not dst.alive():
		src.stats_dealt["kills"] += 1
		events.append({"tick": tick, "type": "defeated", "target": dst.id, "by": src.id, "target_team": dst.team, "target_kind": dst.kind})
	elif dst.kind == "fighter" and not dst.low_hp_called and float(dst.hp) / dst.max_hp < 0.35:
		dst.low_hp_called = true
		events.append({"tick": tick, "type": "low_hp", "target": dst.id})


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
				if target.hp != before:
					last_progress_tick = tick
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
			var threats := 0
			if e.taunt_left <= 0:
				for o in entities:
					if o.team != e.team and o.hp > 0 and e.pos.distance_to(o.pos) <= r:
						threats += 1
			if threats >= 2:
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
		if rally_hold(e, target):
			e.moving = false
		elif e.pos.distance_to(target.pos) > best_range * 0.8:
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
	if anchor and anchor.alive() and e.pos.distance_to(anchor.pos) > leash * (0.5 if e.kind == "pet" else 1.0):
		move_toward_entity(e, anchor)
	else:
		e.moving = false


# ---------------------------------------------------------------- tick

## `input` drives the leader: {"move": Vector2, "attack": bool, "skill": bool}. Empty → autoplay.
func step(input: Dictionary = {}) -> void:
	if outcome() != "running":
		return
	tick += 1
	if not forward:
		GIRT.in_tick = true
	leader_manual = not input.is_empty()
	var l = leader()
	if not engaged and l:
		var foe = nearest(l, 1, 112.0)
		if foe:
			engaged = true
			events.append({"tick": tick, "type": "battle_start", "by": l.id})
	_boss_managers()
	var idx := 0
	for e in entities:
		idx += 1
		if not e.alive():
			continue
		if e == l and not input.is_empty():
			_player_control(e, input)
		elif think_interval <= 1 or (tick + idx) % think_interval == 0:
			e.last_dir = Vector2.ZERO
			think(e)
		elif e.moving and e.last_dir != Vector2.ZERO:
			move(e, e.last_dir)
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
	if outcome() == "victory" and think_interval <= 1:
		events.append({"tick": tick, "type": "victory"})
	if not forward:
		GIRT.in_tick = false


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


# ---------------------------------------------------------------- F5 boss manager / soft-lock

## Hierarchical boss: the manager picks the phase from HP thresholds; the worker (BT / rule
## brain) then plays that phase's kit. Phase entry may summon adds and enrage.
func _boss_managers() -> void:
	var n := entities.size()
	for i in n:
		var e = entities[i]
		if e.phases.is_empty() or not e.alive():
			continue
		var ratio := float(e.hp) / float(e.max_hp)
		var want: int = e.phase
		for pi in range(e.phase + 1, e.phases.size()):
			if ratio <= float(e.phases[pi]["at"]):
				want = pi
		if want == e.phase:
			continue
		for pi in range(e.phase + 1, want + 1):
			_enter_phase(e, pi)


func _enter_phase(e, pi: int) -> void:
	var ph: Dictionary = e.phases[pi]
	e.phase = pi
	e.abilities = ph["abilities"]
	for ab in e.abilities:
		if not e.cooldowns.has(ab["id"]):
			e.cooldowns[ab["id"]] = 0
	if ph.has("speed"):
		e.speed = float(ph["speed"])
	e.atk = snappedf(e.base_atk * float(ph.get("atk_mult", 1.0)), 0.01)
	events.append({"tick": tick, "type": "boss_phase", "by": e.id, "phase": pi + 1})
	if ph.has("summon"):
		var t: Dictionary = ph["summon"]
		var cnt := int(t["count"])
		for k in cnt:
			var ang := TAU * float(k) / float(cnt)
			var at: Vector2 = e.pos + Vector2(cos(ang), sin(ang)) * 18.0
			if grid.blocked_at(at, 4.0):
				at = e.pos
			summons += 1
			var minion = SimEntity.create("%s_add%d" % [t["ref"], summons], 1, "enemy", t["sprite_id"], t["stats"], t["abilities"], at)
			minion.tier = int(t.get("tier", 1))
			minion.set_meta("ref", t["ref"])
			add(minion)
			events.append({"tick": tick, "type": "summon", "by": e.id, "target": minion.id})


## Soft-lock (runtime): both sides alive but nothing has been hit or healed for STALL_TICKS.
func stalled(limit: int = STALL_TICKS) -> bool:
	return outcome() == "running" and engaged and tick - last_progress_tick > limit


# ---------------------------------------------------------------- F4 snapshots (Tier 2: application state)

## Complete, JSON-safe sim state. Restoring it and stepping is bit-identical to stepping
## the original (proved by `full_hash` + the F4 acceptance replay).
func to_snapshot() -> Dictionary:
	var ents := []
	for e in entities:
		ents.append(e.to_dict())
	return {"v": SNAPSHOT_VERSION, "tick": tick, "tactic": tactic, "focus_kind": focus_kind, "engaged": engaged,
		"leader_manual": leader_manual, "think_interval": think_interval, "leash": leash, "separation": separation,
		"variance": variance, "crit_chance": crit_chance, "rng_state": rng_state, "last_progress_tick": last_progress_tick, "summons": summons,
		"explore": explore, "entities": ents, "events": events.duplicate(true)}


## Restore in place (keeps grid, brain hook and forward flag).
func restore(snap: Dictionary) -> void:
	var v := int(snap.get("v", 0))
	assert(v >= 1 and v <= SNAPSHOT_VERSION, "unsupported snapshot version %d" % v)   # v1 → defaults below
	entities.clear()
	by_id.clear()
	for d in snap["entities"]:
		add(SimEntity.from_dict(d))
	tick = int(snap["tick"])
	tactic = str(snap["tactic"])
	focus_kind = str(snap["focus_kind"])
	engaged = bool(snap["engaged"])
	leader_manual = bool(snap["leader_manual"])
	think_interval = int(snap["think_interval"])
	leash = float(snap["leash"])
	separation = float(snap["separation"])
	variance = float(snap.get("variance", 0.0))
	crit_chance = float(snap.get("crit_chance", 0.0))
	rng_state = int(snap.get("rng_state", 0))
	last_progress_tick = int(snap.get("last_progress_tick", tick))
	summons = int(snap.get("summons", 0))
	explore = bool(snap.get("explore", false))
	events = []
	for ev in snap["events"]:
		events.append(_int_fields(ev))


static func _int_fields(ev: Dictionary) -> Dictionary:
	var out := ev.duplicate()
	for k in ["tick", "dmg", "hp", "amount", "target_team", "phase"]:
		if out.has(k):
			out[k] = int(out[k])
	return out


## Strict hash over the whole snapshot (full float precision), vs. the display-level state_hash.
func full_hash() -> String:
	var s := to_snapshot()
	s.erase("events")
	return JSON.stringify(s, "", true, true).sha256_text().substr(0, 16)


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
