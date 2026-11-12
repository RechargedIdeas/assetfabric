extends RefCounted
## Scripted-playthrough QA agent (F6; GAME_SPEC §8 "soft-lock detection on scripted playthroughs",
## "hybrid QA: automated agents + human playtesters"). Plays the vertical slice like a player would:
## it reads only the quest stage + world state + what is on screen, never the sim internals, and
## returns one action per tick. Combat itself is left to the BT + policy party (no LLM, ADR-0011).
## Stateless by design: decisions are a pure function of the saved world state, so a game reloaded
## from a checkpoint continues exactly as an uninterrupted run would.
##
## Actions: {"kind": "fight"} · {"kind": "wait"} · {"kind": "do", "act", "arg"} ·
##          {"kind": "goto", "cell": Vector2i, "act", "arg"} · {"kind": "done"}

const SALVE_AT := 0.55          # use a salve out of combat below this party HP ratio
const CRAFT_PLAN := [["moss_salve", 2], ["ember_tonic", 1], ["flint_edge", 1]]


static func _cells(layout: Dictionary, glyph: String) -> Array:
	var out := []
	var rows: Array = layout["rows"]
	for y in rows.size():
		var row: String = rows[y]
		for x in row.length():
			if row[x] == glyph:
				out.append(Vector2i(x, y))
	return out


static func _nearest(cells: Array, from: Vector2i) -> Vector2i:
	var best: Vector2i = cells[0]
	var bd := INF
	for c in cells:
		var d := float((c - from).length_squared())
		if d < bd or (d == bd and (c.y < best.y or (c.y == best.y and c.x < best.x))):
			bd = d
			best = c
	return best


static func party_ratio(sim) -> float:
	var hp := 0
	var mx := 0
	for e in sim.entities:
		if e.team == 0 and e.kind == "fighter":
			hp += maxi(0, e.hp)
			mx += e.max_hp
	return float(hp) / maxf(1.0, float(mx))


static func decide(s) -> Dictionary:
	var ws = s.ws
	var sim = s.sim
	if ws.quests.done("q_warden"):
		return {"kind": "done"}
	if s.in_combat or not sim.explore:
		return {"kind": "fight"}
	var l = sim.leader()
	if l == null:
		return {"kind": "wait"}
	var here: Vector2i = sim.grid.to_cell(l.pos)
	var layout: Dictionary = s.layout
	var area: String = ws.area
	var a: Dictionary = s.area_def
	# consumables first (salves are kept for the craft guard until that stage is done)
	var crafted: bool = ws.stage_at_least("q_warden", "warden")
	if party_ratio(sim) < SALVE_AT and ws.count("moss_salve") > (0 if crafted else 1):
		return {"kind": "do", "act": "use", "arg": "moss_salve"}
	var nodes := []
	for c in s.cells("G"):
		if not ws.is_depleted(area, c):
			nodes.append(c)
	if area == "field":
		for i in ws.plots.size():
			if ws.crop_ready(i):
				return _go(here, _plot_cell(ws, i), "harvest", i)
		var seed_item: String = ws.seed_in_bag()
		if seed_item != "":
			for i in ws.plots.size():
				if str(ws.plots[i]["crop"]) == "":
					return _go(here, _plot_cell(ws, i), "plant", seed_item)
		var bench: Array = s.cells("W")
		if ws.stage_at_least("q_warden", "craft") and not bench.is_empty():
			for p in CRAFT_PLAN:
				if not crafted or p[0] == "flint_edge":
					var have: int = ws.count(p[0]) + (1 if ws.owns_gear(p[0]) else 0)
					if have < int(p[1]) and ws.can_craft(p[0]):
						return _go(here, bench[0], "craft", p[0])
			if ws.flags.get("warden_down", false) and not ws.owns_gear("warden_charm") and ws.can_craft("warden_charm"):
				return _go(here, bench[0], "craft", "warden_charm")
		if not nodes.is_empty() and not ws.stage_at_least("q_warden", "moss"):
			return _go(here, _nearest(nodes, here), "gather", a["nodes"]["G"])
		if ws.quests.stage("q_warden") == "harvest":
			for i in ws.plots.size():
				if str(ws.plots[i]["crop"]) != "":
					return _go(here, _plot_cell(ws, i), "wait", null)    # crops still growing: wait by the plot
		if ws.quests.stage("q_warden") == "rest" and not bench.is_empty():
			return _go(here, bench[0], "save", null)
		return _link(s, here, "E")
	if area == "tunnels":
		if not nodes.is_empty() and not ws.stage_at_least("q_warden", "return_farm"):
			return _go(here, _nearest(nodes, here), "gather", a["nodes"]["G"])
		if s.hostiles_left() > 0:
			return {"kind": "fight"}
		return _link(s, here, "S" if ws.quests.stage("q_warden") == "return_farm" else "E")
	if area == "cave_deep":
		if not nodes.is_empty() and not ws.stage_at_least("q_warden", "return_farm"):
			return _go(here, _nearest(nodes, here), "gather", a["nodes"]["G"])
		if s.hostiles_left() > 0:
			return {"kind": "fight"}       # BT leader hunts the nearest remaining pack
		if ws.stage_at_least("q_warden", "warden"):
			if ws.count("ember_tonic") > 0 and ws.buffs.is_empty():
				return {"kind": "do", "act": "use", "arg": "ember_tonic"}
			return _link(s, here, "E")
		return _link(s, here, "S")
	# boss lair, warden down: walk out to the open world
	return _link(s, here, "E")


static func _plot_cell(ws, i: int) -> Vector2i:
	return Vector2i(int(ws.plots[i]["cell"][0]), int(ws.plots[i]["cell"][1]))


static func _go(here: Vector2i, cell: Vector2i, act: String, arg) -> Dictionary:
	return {"kind": "goto", "cell": cell, "act": act, "arg": arg, "arrived": here == cell}


static func _link(s, here: Vector2i, glyph: String) -> Dictionary:
	var c: Vector2i = Vector2i(int(s.layout["start"][0]), int(s.layout["start"][1])) if glyph == "S" \
		else Vector2i(int(s.layout["exit"][0]), int(s.layout["exit"][1]))
	return _go(here, c, "link", glyph)
