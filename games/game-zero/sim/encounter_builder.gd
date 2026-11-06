extends RefCounted
## Builds a CombatSim from an encounter definition + codegen game data.
## Encounter units reference roster ids (`ref`) — stats/abilities are never hand-wired.

const SimGrid = preload("res://sim/grid.gd")
const SimEntity = preload("res://sim/entity.gd")
const CombatSim = preload("res://sim/combat_sim.gd")


## Diminishing-returns stacking with hard cap (mirrors forge/generators/codegen.py).
static func diminishing(total: float, cap: float) -> float:
	if cap <= 0.0:
		return 0.0
	return snappedf(cap * (1.0 - exp(-total / cap)), 0.0001)


static func _free_cells_near(grid, origin: Vector2i, count: int, taken: Dictionary) -> Array:
	var out := []
	var field: Dictionary = grid.field_dict(origin)
	var cells := field.keys()
	cells.sort_custom(func(a, b): return field[a] < field[b] or (field[a] == field[b] and (a.y < b.y or (a.y == b.y and a.x < b.x))))
	for c in cells:
		if out.size() >= count:
			break
		if taken.has(c) or grid.cell(c) != ".":
			continue
		out.append(c)
		taken[c] = true
	return out


static func build(encounter: Dictionary, layout: Dictionary, data: Dictionary, abilities: Dictionary):
	var grid = SimGrid.from_layout(layout)
	var sim = CombatSim.new(grid)
	var taken := {}
	var party_cells := _free_cells_near(grid, grid.start, 16, taken)
	var pi := 0
	var rules: Dictionary = data.get("pet_rules", {})
	var caps: Dictionary = rules.get("bonus_caps", {})
	var share := float(rules.get("ally_share", 0.0))
	var party_bonus := {"atk_pct": 0.0, "def_flat": 0.0, "hp_pct": 0.0}
	var fighters := []
	for m in encounter.get("party", []):
		var f: Dictionary = data["fighters"][m["ref"]]
		var lv := clampi(int(m.get("level", 1)), 1, f["levels"].size())
		var stats: Dictionary = f["levels"][lv - 1].duplicate()
		var ab_ids: Array = m.get("abilities", f["abilities"])
		var abs_ := ab_ids.map(func(a): return abilities[a])
		var e = SimEntity.create(m["ref"], 0, "fighter", m.get("sprite", f["sprite_id"]), stats, abs_, grid.center(party_cells[pi]))
		pi += 1
		e.is_leader = bool(m.get("leader", false))
		sim.add(e)
		fighters.append([e, m])
	# pets: bonuses to owner with diminishing returns; a share to the whole party
	for pair in fighters:
		var owner = pair[0]
		var m: Dictionary = pair[1]
		var own := {"atk_pct": 0.0, "def_flat": 0.0, "hp_pct": 0.0}
		var pets: Array = m.get("pets", [])
		pets = pets.slice(0, int(rules.get("max_pets_per_character", 2)))
		for pid in pets:
			var p: Dictionary = data["pets"][pid]
			var pe = SimEntity.create("%s_%s" % [owner.id, pid], 0, "pet", p["sprite_id"], p["stats"],
				p["abilities"].map(func(a): return abilities[a]), grid.center(party_cells[pi]))
			pi += 1
			pe.owner_id = owner.id
			pe.radius = 4.0
			sim.add(pe)
			for k in p["bonus"]:
				own[k] += float(p["bonus"][k])
				party_bonus[k] += float(p["bonus"][k]) * share
		owner.set_meta("own_bonus", own)
	for pair in fighters:
		var e = pair[0]
		var own: Dictionary = e.get_meta("own_bonus")
		var atk_b := diminishing(own["atk_pct"] + party_bonus["atk_pct"], float(caps.get("atk_pct", 0.3)))
		var def_b := diminishing(own["def_flat"] + party_bonus["def_flat"], float(caps.get("def_flat", 4)))
		var hp_b := diminishing(own["hp_pct"] + party_bonus["hp_pct"], float(caps.get("hp_pct", 0.3)))
		e.atk = snappedf(e.atk * (1.0 + atk_b), 0.01)
		e.def = snappedf(e.def + def_b, 0.01)
		e.max_hp = int(round(e.max_hp * (1.0 + hp_b)))
		e.hp = e.max_hp
		e.set_meta("bonus", {"atk_pct": atk_b, "def_flat": def_b, "hp_pct": hp_b})
	# hostiles around spawn points
	var spawns: Array = grid.spawns if not grid.spawns.is_empty() else [grid.exit]
	var si := 0
	var n := 0
	for h in encounter.get("hostiles", []):
		var en: Dictionary = data["enemies"][h["ref"]]
		for i in int(h.get("count", 1)):
			var cell: Vector2i = _free_cells_near(grid, spawns[si % spawns.size()], 1, taken)[0]
			si += 1
			n += 1
			var e = SimEntity.create("%s_%d" % [h["ref"], n], 1, "enemy", h.get("sprite", en["sprite_id"]), en["stats"],
				en["abilities"].map(func(a): return abilities[a]), grid.center(cell))
			e.tier = int(en["tier"])
			sim.add(e)
	return sim
