extends RefCounted
## Behaviour-tree brain (F3) — data-driven trees from data/ai/behaviour_trees.json.
## Target selection for the party uses the GIRT policy (P-TargetSelect) with a
## rule fallback; enemies use the rule brain's taunt-aware targeting.
## Deterministic; no LLM (ADR-0011).

const SimEntity = preload("res://sim/entity.gd")
const K := 4
const RETARGET := 6   # ticks between target re-evaluations (10 Hz decision rate) unless the target dies

# Trees are compiled to int opcodes at load ([op, leaf, children]) so the hot
# path never touches shared String Variants (refcount contention across the
# swap advisor's worker threads, and ~2x faster single-threaded too).
enum Op { SELECTOR, SEQUENCE, CONDITION, ACTION }
const LEAVES := ["is_casting", "ally_needs_heal", "should_taunt", "tactic_defensive", "not_threatened",
	"cast_heal", "cast_taunt", "select_target", "engage", "regroup", "idle"]
## A tier-3 boss counts as a whole pack for should_taunt: the warden pulls it off whoever
## leads (F5 balance finding: without this, non-tank leaders tanked the boss alone).
const BOSS_TIER := 3
const BOSS_TAUNT_WEIGHT := 2

enum Leaf { IS_CASTING, ALLY_NEEDS_HEAL, SHOULD_TAUNT, TACTIC_DEFENSIVE, NOT_THREATENED,
	CAST_HEAL, CAST_TAUNT, SELECT_TARGET, ENGAGE, REGROUP, IDLE }

var trees: Dictionary = {}
var _fighter: Array = []
var _pet: Array = []
var _enemy: Array = []
var decisions := {"policy": 0, "rule": 0, "bt_ticks": 0}


func _init(trees_: Dictionary) -> void:
	trees = trees_
	_fighter = compile(trees.get("fighter", {}))
	_pet = compile(trees.get("pet", {}))
	_enemy = compile(trees.get("enemy", {}))


## Independent copy for a worker thread (fresh compiled trees, no shared containers).
func fork():
	return get_script().new(trees.duplicate(true))


static func compile(node: Dictionary) -> Array:
	if node.is_empty():
		return []
	var ops := {"selector": Op.SELECTOR, "sequence": Op.SEQUENCE, "condition": Op.CONDITION, "action": Op.ACTION}
	var op: int = ops[node["type"]]
	if op == Op.SELECTOR or op == Op.SEQUENCE:
		var kids := []
		for c in node["children"]:
			kids.append(compile(c))
		return [op, -1, kids]
	var leaf := LEAVES.find(node["name"])
	assert(leaf >= 0, "unknown BT leaf " + str(node["name"]))
	return [op, leaf, []]


## Plugged into CombatSim.brain_override. Returns true when the BT handled the entity.
func tick(sim, e) -> bool:
	if e.is_leader and sim.leader_manual:
		return false
	var tree: Array = _enemy if e.team == 1 else (_pet if e.kind == "pet" else _fighter)
	if tree.is_empty():
		return false
	if not sim.forward:
		decisions["bt_ticks"] += 1
	# ready abilities computed once per think: cooldowns cannot change before it ends (begin_cast ends it)
	_run(tree, sim, e, e.ready_abilities())
	return true


func _run(node: Array, sim, e: SimEntity, ready: Array) -> bool:
	var op: int = node[0]
	if op == Op.SELECTOR:
		for c in node[2]:
			if _run(c, sim, e, ready):
				return true
		return false
	if op == Op.SEQUENCE:
		for c in node[2]:
			if not _run(c, sim, e, ready):
				return false
		return true
	if op == Op.CONDITION:
		return _cond(node[1], sim, e, ready)
	return _act(node[1], sim, e, ready)


func _cond(leaf: int, sim, e: SimEntity, ready: Array) -> bool:
	match leaf:
		Leaf.IS_CASTING:
			return not e.casting.is_empty()
		Leaf.ALLY_NEEDS_HEAL:
			for ab: Dictionary in ready:
				if ab["type"] == "heal" and sim.lowest_ally(e, float(ab.get("threshold", 0.6)), float(ab["range"])) != null:
					e.bt_ability = ab
					return true
			return false
		Leaf.SHOULD_TAUNT:
			for ab: Dictionary in ready:
				if ab["type"] == "taunt" and e.taunt_left <= 0:
					var n: int = sim.threat_weight(e, float(ab["range"]), BOSS_TIER, BOSS_TAUNT_WEIGHT)
					if n >= 2:
						e.bt_ability = ab
						return true
			return false
		Leaf.TACTIC_DEFENSIVE:
			return sim.tactic == "defensive"
		Leaf.NOT_THREATENED:
			return sim.nearest(e, 1 - e.team, 40.0) == null
	return false


func _act(leaf: int, sim, e: SimEntity, ready: Array) -> bool:
	match leaf:
		Leaf.CAST_HEAL:
			var ab: Dictionary = e.bt_ability
			sim.begin_cast(e, ab, sim.lowest_ally(e, float(ab.get("threshold", 0.6)), float(ab["range"])))
			return true
		Leaf.CAST_TAUNT:
			sim.begin_cast(e, e.bt_ability, e)
			return true
		Leaf.SELECT_TARGET:
			var keep: String = e.bt_target
			var t: SimEntity = sim.by_id.get(keep) if keep != "" else null
			var stale: bool = sim.tick - e.bt_target_tick >= RETARGET
			var refocus: bool = e.team == 0 and sim.focus_kind != "" and t != null and not t.id.begins_with(sim.focus_kind)
			if t == null or t.hp <= 0 or stale or refocus:
				t = _select_target(sim, e)
				e.bt_mem = true
				e.bt_target = t.id if t else ""
				e.bt_target_tick = sim.tick
			return t != null
		Leaf.ENGAGE:
			var t: SimEntity = sim.by_id.get(e.bt_target)
			var pick: Array = sim.choose_ability(e, t, ready)
			if not pick.is_empty():
				e.moving = false
				sim.begin_cast(e, pick[0], pick[1])
				return true
			var best := 0.0
			for ab: Dictionary in e.abilities:
				if ab["target"] == "enemy":
					best = maxf(best, float(ab["range"]))
			if sim.rally_hold(e, t):
				e.moving = false
			elif e.pos.distance_to(t.pos) > best * 0.8:
				sim.move_toward_entity(e, t)
			else:
				e.moving = false
			return true
		Leaf.REGROUP:
			var anchor: SimEntity = sim.by_id.get(e.owner_id) if e.kind == "pet" else (null if e.is_leader else sim.leader())
			if anchor and anchor.hp > 0 and e.pos.distance_to(anchor.pos) > sim.leash * (0.5 if e.kind == "pet" else 1.0):
				sim.move_toward_entity(e, anchor)
			else:
				e.moving = false
			return true
		Leaf.IDLE:
			e.moving = false
			return true
	return false


## Candidate features — must match forge/generators/policy.py FEATURES.
## `hurt` = positions of same-team allies under 50% HP (precomputed once per call).
func features(e: SimEntity, c: SimEntity, best_range: float, hurt: Array) -> Array:
	var cp: Vector2 = c.pos
	var d: float = e.pos.distance_to(cp)
	var threat := 0.0
	for p: Vector2 in hurt:
		if p.distance_to(cp) < 24.0:
			threat = 1.0
			break
	var hp: int = c.hp
	return [d / 128.0, float(hp) / c.max_hp, hp / 100.0, c.tier / 3.0, c.atk / 10.0, 1.0 if d <= best_range else 0.0, threat]


func _hurt_allies(sim, e: SimEntity) -> Array:
	var out := []
	var team: int = e.team
	for a: SimEntity in sim.entities:
		if a.team == team and a.hp > 0 and float(a.hp) / a.max_hp < 0.5:
			out.append(a.pos)
	return out


func _select_target(sim, e: SimEntity) -> SimEntity:
	if e.team == 1:
		if not sim.forward:
			decisions["rule"] += 1
		return sim.enemy_target(e)
	# focus intent from CascadeHub (player command) overrides the policy
	if sim.focus_kind != "":
		for o: SimEntity in sim.entities:
			if o.team == 1 and o.hp > 0 and o.id.begins_with(sim.focus_kind):
				return o
	var anchor: SimEntity = sim.by_id.get(e.owner_id) if e.kind == "pet" else sim.leader()
	if anchor == null or anchor.hp <= 0:
		anchor = e
	var radius := 96.0 if e.kind == "pet" else 128.0
	# K nearest hostiles within radius of the anchor (sorted by distance; ties by id)
	var idx: Array = sim.k_nearest_hostiles(e, anchor, radius, K)
	if idx.is_empty():
		return sim.nearest(e, 1) if e.is_leader else null
	var best_range := 0.0
	for ab: Dictionary in e.abilities:
		if ab["target"] == "enemy":
			best_range = maxf(best_range, float(ab["range"]))
	var hurt: PackedVector2Array = sim.hurt_positions(e.team)
	var feats := []
	var cands := []
	var ents: Array = sim.entities
	for ci in idx:
		feats.append(sim.policy_features(e, ci, best_range, hurt))
		cands.append(ents[ci])
	var scores: Array = GIRT.score_targets(feats, not sim.forward)
	if scores.size() != cands.size():
		if not sim.forward:
			decisions["rule"] += 1
		return cands[0]
	if not sim.forward:
		decisions["policy"] += 1
	var bi := 0
	for i in scores.size():
		if scores[i] > scores[bi]:
			bi = i
	return cands[bi]
