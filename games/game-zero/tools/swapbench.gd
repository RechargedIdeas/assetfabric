extends Node
## Swap-advisor benchmark + fidelity gate (Q3, GAME_SPEC §4.1 "<50 ms wall time").
##   godot --headless --path games/game-zero -- --scene=swapbench [--reps=5]
## `forge accept F3` runs it pinned to 2 CPU cores (the weakest-node budget, `taskset`).
## Freeze states are sampled from real fights (party_ai pack fight + boss_warden), every
## SAMPLE_EVERY ticks while both sides live. For each state:
##   * wall time of SwapAdvisor.rank (threaded, shipped LOD) over `reps` runs,
##   * serial == threaded ranking (parity),
##   * fidelity: shipped-LOD ranking vs the full-fidelity LOD-1 ranking (brains every tick).
## Prints one `SWAPBENCH {json}` line. Deterministic states; only the timings vary.

const EncounterBuilder = preload("res://sim/encounter_builder.gd")
const Brain = preload("res://ai/brain.gd")
const SwapAdvisor = preload("res://ai/swap_advisor.gd")

const ENCOUNTERS := ["party_ai", "boss_warden"]
const SAMPLE_EVERY := 60
const MAX_STATES_PER_ENCOUNTER := 12


func _ready() -> void:
	var reps := int(Fabric.arg("reps", "5"))
	var trees: Dictionary = Fabric.read_json("res://data/ai/behaviour_trees.json")["trees"]
	var walls: Array = []
	var states := []
	var parity := true
	var top1 := 0
	var top1_in_top2 := 0
	var exact := 0
	for enc_id in ENCOUNTERS:
		var enc: Dictionary = Fabric.read_json("res://data/encounters/%s.json" % enc_id)
		var sim = EncounterBuilder.build(enc, Fabric.json_asset(enc["tilemap"]), Fabric.game_data, Fabric.abilities)
		var brain = Brain.new(trees)
		sim.brain_override = brain.tick
		sim.grid.warm_fields()
		var taken := 0
		var limit := int(enc.get("tick_limit", 18000))
		while sim.outcome() == "running" and sim.tick < limit and taken < MAX_STATES_PER_ENCOUNTER:
			sim.step({})
			if not sim.engaged or sim.tick % SAMPLE_EVERY != 0:
				continue
			var fighters := 0
			for e in sim.entities:
				if e.team == 0 and e.kind == "fighter" and e.alive():
					fighters += 1
			if fighters < 2:
				continue
			taken += 1
			var ws := []
			var res: Dictionary = {}
			for r in reps:
				res = SwapAdvisor.rank(sim, true)
				ws.append(float(res["wall_ms"]))
			var ids := _ids(res)
			var serial := _ids(SwapAdvisor.rank(sim, false))
			var ref := _ids(SwapAdvisor.rank(sim, false, 1))
			parity = parity and serial == ids
			top1 += 1 if ids[0] == ref[0] else 0
			top1_in_top2 += 1 if ref.slice(0, 2).has(ids[0]) else 0
			exact += 1 if ids == ref else 0
			walls.append_array(ws)
			ws.sort()
			states.append({"encounter": enc_id, "tick": sim.tick, "candidates": ids.size(), "wall_ms_median": ws[ws.size() / 2],
				"threaded": res["threaded"], "ranking": ids, "reference_lod1": ref})
	walls.sort()
	var n := walls.size()
	var out := {"states": states.size(), "samples": n, "reps": reps, "lod": SwapAdvisor.LOD, "horizon": SwapAdvisor.HORIZON,
		"processor_count": OS.get_processor_count(), "parity": parity,
		"wall_ms_p50": walls[n / 2] if n else -1.0, "wall_ms_p95": walls[mini(n - 1, int(ceil(0.95 * n)) - 1)] if n else -1.0,
		"wall_ms_max": walls[n - 1] if n else -1.0,
		"fidelity": {"top1_agree": top1, "top1_in_ref_top2": top1_in_top2, "exact_order": exact, "of": states.size()},
		"per_state": states}
	print("SWAPBENCH " + JSON.stringify(out))
	get_tree().quit(0)


static func _ids(res: Dictionary) -> Array:
	return res["recommendations"].map(func(r): return r["id"])
