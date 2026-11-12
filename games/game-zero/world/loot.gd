extends RefCounted
## Tier loot tables (F6, GAME_SPEC §4.4) — exact twin of `forge/world.py` `roll_loot`:
## same 31-bit LCG as CombatSim, same roll order (guaranteed → tier rolls → per-enemy extra).
## The rng state lives in the save (world.rng), so a reloaded game keeps rolling the same drops.

var state := 0


func _init(s: int = 0) -> void:
	state = s & 0x7fffffff


func rand01() -> float:
	state = (state * 1103515245 + 12345) & 0x7fffffff
	return float(state) / 2147483648.0


func _qty(q: Array) -> int:
	var lo := int(q[0])
	var hi := int(q[1])
	return mini(hi, lo + int(rand01() * float(hi - lo + 1)))


func _pick(table: Array):
	var total := 0.0
	for e in table:
		total += float(e["weight"])
	if total <= 0.0:
		return null
	var r := rand01() * total
	var acc := 0.0
	for e in table:
		acc += float(e["weight"])
		if r < acc:
			return e
	return table[table.size() - 1]


## Drops for one defeated hostile: [[item, qty], ...]; "none" slots omitted.
func roll(world: Dictionary, tier: int, ref: String) -> Array:
	var out := []
	var t = world["loot"]["tiers"].get(str(tier))
	if t != null:
		for g in t.get("guaranteed", []):
			out.append([str(g["item"]), _qty(g["qty"])])
		for _i in int(t.get("rolls", 1)):
			var e = _pick(t["table"])
			if e != null and str(e["item"]) != "none":
				out.append([str(e["item"]), _qty(e["qty"])])
	var extra = world["loot"]["enemies"].get(ref)
	if extra != null:
		var e2 = _pick(extra["table"])
		if e2 != null and str(e2["item"]) != "none":
			out.append([str(e2["item"]), _qty(e2["qty"])])
	return out
