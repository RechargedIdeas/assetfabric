extends Node
## Monte Carlo balance worker (F5). Headless only; driven by `forge balance` (forge/balance.py).
##   godot --headless --path games/game-zero -- --scene=balance --jobs=<file.json>
## Job file: {"encounter": id, "variance": f, "jobs": [{"id", "seed", "party": [...], "overrides": [patch]}]}
## Each job rebuilds the encounter with its party, seed and data overrides (same patch format
## and limits as the F4 live channel), runs the BT + policy AI to an outcome, and prints one
## `BALANCE_RESULT {json}` line. Soft-locks are detected at runtime (no damage/heal for
## CombatSim.STALL_TICKS while both sides live). No rendering, no LLM, deterministic per seed.

const EncounterBuilder = preload("res://sim/encounter_builder.gd")
const Brain = preload("res://ai/brain.gd")


func _ready() -> void:
	var path := str(Fabric.arg("jobs", ""))
	if path == "":
		push_error("balance: --jobs=<file> required")
		get_tree().quit(2)
		return
	var spec = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(spec) != TYPE_DICTIONARY:
		push_error("balance: cannot read %s" % path)
		get_tree().quit(2)
		return
	var base: Dictionary = Fabric.read_json("res://data/encounters/%s.json" % spec["encounter"])
	var layout = Fabric.json_asset(base["tilemap"])
	var trees: Dictionary = Fabric.read_json("res://data/ai/behaviour_trees.json")["trees"]
	var t0 := Time.get_ticks_usec()
	var cache := {}     # overrides signature -> [data, abilities]
	var n := 0
	for job in spec["jobs"]:
		var sig := JSON.stringify(job.get("overrides", []))
		if not cache.has(sig):
			cache[sig] = _patched(job.get("overrides", []))
		var data: Dictionary = cache[sig][0]
		var abilities: Dictionary = cache[sig][1]
		var enc := base.duplicate(true)
		enc["seed"] = int(job["seed"])
		enc["variance"] = float(spec.get("variance", 0.1))
		enc["crit"] = float(spec.get("crit", 0.1))
		if job.has("party"):
			enc["party"] = job["party"]
		var sim = EncounterBuilder.build(enc, layout, data, abilities)
		for p in job.get("overrides", []):
			var segs := str(p["path"]).split(".")
			if segs[0] == "sim":
				sim.set(segs[1], float(p["value"]))
		var brain = Brain.new(trees)
		sim.brain_override = brain.tick
		var limit := int(base.get("tick_limit", 18000))
		var outcome := "running"
		while true:
			sim.step({})
			outcome = sim.outcome()
			if outcome != "running":
				break
			if sim.stalled():
				outcome = "softlock"
				break
			if sim.tick >= limit:
				outcome = "timeout"
				break
		var boss_phase := 0
		var party_hp := 0
		var party_max := 0
		for e in sim.entities:
			if not e.phases.is_empty():
				boss_phase = maxi(boss_phase, e.phase + 1)
			if e.team == 0 and e.kind == "fighter":
				party_hp += e.hp
				party_max += e.max_hp
		print("BALANCE_RESULT " + JSON.stringify({"id": job["id"], "seed": job["seed"], "outcome": outcome, "ticks": sim.tick,
			"boss_phase": boss_phase, "leader_alive": sim.leader() != null and sim.leader().is_leader, "summons": sim.summons, "party_hp_ratio": snappedf(float(party_hp) / maxf(1.0, party_max), 0.001)}))
		n += 1
	print("BALANCE_DONE %d %.1f" % [n, (Time.get_ticks_usec() - t0) / 1000.0])
	get_tree().quit(0)


## Deep-copied game data + ability dicts with numeric overrides applied (F4 patch format).
func _patched(patches: Array) -> Array:
	var data: Dictionary = Fabric.game_data.duplicate(true)
	var abilities: Dictionary = Fabric.abilities.duplicate(true)
	for p in patches:
		var path := str(p["path"])
		var segs := path.split(".")
		if segs[0] == "sim":
			continue
		var node = data
		for i in segs.size() - 1:
			node = node[int(segs[i])] if typeof(node) == TYPE_ARRAY else node[segs[i]]
		var leaf: String = segs[segs.size() - 1]
		var cur = node[int(leaf)] if typeof(node) == TYPE_ARRAY else node[leaf]
		var v = int(p["value"]) if typeof(cur) == TYPE_INT else float(p["value"])
		if typeof(node) == TYPE_ARRAY:
			node[int(leaf)] = v
		else:
			node[leaf] = v
		if segs[0] == "abilities" and abilities.has(segs[1]):
			abilities[segs[1]][leaf] = v
	return [data, abilities]
