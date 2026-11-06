extends RefCounted
## Time-freeze swap advisor (GAME_SPEC §4.1): for each living fighter, clone the
## sim, make it leader, forward-simulate ~2 s and rank by outcome.
## Budget: <50 ms wall time. Candidates run in parallel on WorkerThreadPool
## (clones are independent; `forward=true` keeps them free of shared writes),
## with a serial fallback on single-core targets. Brains think at 20 Hz (LOD 3)
## inside the forward sim; movement still integrates every tick.

const HORIZON := 120    # ticks (2 s simulated, GAME_SPEC §4.1)
const LOD := 4          # brains think at 15 Hz in the forward sim; movement integrates at 60 Hz


static func _hp(sim, team: int) -> int:
	var s := 0
	for e in sim.entities:
		if e.team == team:
			s += e.hp
	return s


static func _run(c) -> void:
	for _i in HORIZON:
		c.step({})
		if c.outcome() != "running":
			break


static func rank(sim, threaded: bool = true) -> Dictionary:
	var t0 := Time.get_ticks_usec()
	sim.grid.warm_fields()   # build shared read-only tables before any thread starts
	var party_hp0: int = _hp(sim, 0)
	var foe_hp0: int = _hp(sim, 1)
	var cands := []
	var clones := []
	for cand in sim.entities:
		if cand.team != 0 or cand.kind != "fighter" or not cand.alive():
			continue
		var c = sim.clone()
		c.set_leader(cand.id)
		c.leader_manual = false
		c.forward = true
		c.think_interval = LOD
		if threaded and c.brain_override.is_valid():
			# private brain per worker: shared Arrays/Dicts cost atomic refcount traffic across cores
			var b = c.brain_override.get_object()
			if b and b.has_method("fork"):
				var fb = b.fork()
				c.brain_ref = fb          # Callables do not keep RefCounted targets alive
				c.brain_override = fb.tick
		if threaded:
			c.grid = sim.grid.fork()
			# private ability dicts: avoids cross-core refcount contention on shared Variants
			var own := {}
			for e in c.entities:
				var abs_ := []
				for ab in e.abilities:
					if not own.has(ab["id"]):
						own[ab["id"]] = ab.duplicate(true)
					abs_.append(own[ab["id"]])
				e.abilities = abs_
		cands.append(cand)
		clones.append(c)
	var use_threads: bool = threaded and OS.get_processor_count() > 1 and clones.size() > 1
	if use_threads:
		var gid := WorkerThreadPool.add_group_task(func(i: int): _run(clones[i]), clones.size(), clones.size(), true, "swap_advisor")
		WorkerThreadPool.wait_for_group_task_completion(gid)
	else:
		for c in clones:
			_run(c)
	var recs := []
	for i in cands.size():
		var cand = cands[i]
		var c = clones[i]
		var me = c.by_id[cand.id]
		var dealt: int = me.stats_dealt["damage"] + me.stats_dealt["healing"] - cand.stats_dealt["damage"] - cand.stats_dealt["healing"]
		# team outcome + what the swapped-in character itself contributes + its survival
		var score: float = float(foe_hp0 - _hp(c, 1)) - 1.5 * float(party_hp0 - _hp(c, 0)) + 2.0 * dealt \
			+ 20.0 * float(me.hp) / me.max_hp + (50.0 if c.outcome() == "victory" else 0.0)
		recs.append({"id": cand.id, "score": snappedf(score, 0.01), "hp": cand.hp, "max_hp": cand.max_hp,
			"target": str(cand.get_meta("bt_target", "")),
			"cooldowns": cand.cooldowns.duplicate()})
	recs.sort_custom(func(a, b): return a["score"] > b["score"] or (a["score"] == b["score"] and a["id"] < b["id"]))
	return {"recommendations": recs, "wall_ms": snappedf((Time.get_ticks_usec() - t0) / 1000.0, 0.01),
		"horizon": HORIZON, "lod": LOD, "threaded": use_threads}
