extends Node
## Dev profiler (not shipped in acceptance): godot --headless --path games/game-zero res://tools/profile.tscn
const EncounterBuilder = preload("res://sim/encounter_builder.gd")
const Brain = preload("res://ai/brain.gd")
const SwapAdvisor = preload("res://ai/swap_advisor.gd")

func _t(label: String, n: int, f: Callable) -> void:
	var t0 := Time.get_ticks_usec()
	for i in n:
		f.call()
	print("PROFILE %-22s %8.2f us" % [label, float(Time.get_ticks_usec() - t0) / n])

func _ready() -> void:
	var enc = Fabric.read_json("res://data/encounters/party_ai.json")
	var sim = EncounterBuilder.build(enc, Fabric.json_asset(enc["tilemap"]), Fabric.game_data, Fabric.abilities)
	sim.grid.warm_fields()
	var brain = Brain.new(Fabric.read_json("res://data/ai/behaviour_trees.json")["trees"])
	sim.brain_override = brain.tick
	for i in 300:
		sim.step({})
	var c = sim.clone()
	c.forward = true
	var fighter = null
	var foe = null
	for e in c.entities:
		if e.team == 0 and e.kind == "fighter" and fighter == null:
			fighter = e
		if e.team == 1 and e.alive() and foe == null:
			foe = e
	print("PROFILE entities %d alive_foes %d" % [c.entities.size(), c.team_alive(1).size()])
	_t("step(forward)", 200, func(): c.clone().step({}))
	_t("clone", 200, func(): c.clone())
	_t("brain.tick fighter", 2000, func(): brain.tick(c, fighter))
	_t("brain.tick foe", 2000, func(): brain.tick(c, foe))
	_t("brain._select_target", 2000, func(): brain._select_target(c, fighter))
	_t("choose_ability", 2000, func(): c.choose_ability(fighter, foe))
	_t("move_toward_entity", 2000, func(): c.move_toward_entity(fighter, foe))
	_t("enemy_target", 2000, func(): c.enemy_target(foe))
	_t("outcome", 2000, func(): c.outcome())
	_t("ready_abilities", 2000, func(): fighter.ready_abilities())
	_t("_animate", 2000, func(): c._animate(fighter))
	var acc := {}
	var c3 = sim.clone()
	c3.forward = true
	c3.think_interval = 4
	c3.brain_override = func(s, e):
		var t0 := Time.get_ticks_usec()
		var r: bool = brain.tick(s, e)
		var k: String = "%s/%s" % [e.kind, "cast" if not e.casting.is_empty() else "free"]
		acc[k] = acc.get(k, 0) + Time.get_ticks_usec() - t0
		acc[k + "#"] = acc.get(k + "#", 0) + 1
		return r
	var ts := Time.get_ticks_usec()
	for i in 120:
		c3.step({})
	print("PROFILE 120 forward steps %d us; brain breakdown %s" % [Time.get_ticks_usec() - ts, acc])
	var rs = SwapAdvisor.rank(sim, false)["recommendations"].map(func(r): return [r["id"], r["score"]])
	var rs2 = SwapAdvisor.rank(sim, false)["recommendations"].map(func(r): return [r["id"], r["score"]])
	print("PROFILE serial-again %s" % [rs2])
	var rt = SwapAdvisor.rank(sim, true)["recommendations"].map(func(r): return [r["id"], r["score"]])
	var rt2 = SwapAdvisor.rank(sim, true)["recommendations"].map(func(r): return [r["id"], r["score"]])
	print("PROFILE parity serial=%s threaded=%s again=%s" % [rs, rt, rt2])
	_t("advisor serial", 5, func(): SwapAdvisor.rank(sim, false))
	_t("advisor threaded", 5, func(): SwapAdvisor.rank(sim, true))
	for n in [1, 2, 4]:
		var cl := []
		for i in n:
			var x = sim.clone()
			x.forward = true
			x.think_interval = 4
			cl.append(x)
		var tt := Time.get_ticks_usec()
		var gid := WorkerThreadPool.add_group_task(func(i: int): SwapAdvisor._run(cl[i]), n, n, true)
		WorkerThreadPool.wait_for_group_task_completion(gid)
		print("PROFILE threads=%d same-candidate wall %d us" % [n, Time.get_ticks_usec() - tt])
	get_tree().quit()
