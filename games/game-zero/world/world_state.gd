extends RefCounted
## Vertical-slice world state (F6): party, inventory, farm, quests, loot rng, progress.
## Pure data + rules (no nodes, no rendering); serialises to Player State v4 (autoload/save.gd)
## so a checkpoint save → quit → reload restores *everything* the slice needs (no data loss).
## Rules come from data/generated/world.json (Codegen-World); [INFERENCE F6-3..F6-7].

const Loot = preload("res://world/loot.gd")
const QuestLog = preload("res://world/quest_log.gd")

var world: Dictionary
var data: Dictionary
var seed := 1
var tick := 0                  # world clock (60 Hz): farm growth + playtime
var area := ""
var arrive := "S"
var leader := ""
var pet := ""
var fighters := {}             # ref -> {"level", "xp"}
var party_hp := {}             # entity id -> hp carried between areas ({} = full)
var unlocked := []
var gear := {"shared": [], "unique": {}}
var inventory := {}
var counters := {}             # planted, harvested, gathered, crafted, kills, wipes, salves_used, ...
var flags := {}
var plots := []                # [{"cell": [x, y], "crop": "", "planted": tick}]
var visits := {}
var depleted := {}             # area -> ["x,y", ...] gathered nodes
var packs_cleared := {}        # area -> [pack index, ...]
var buffs := []                # [{"item", "bonus"}] area-scoped consumable buffs
var cleared := []
var bosses := []
var encounters_won := 0
var loot
var quests
var log_: Array = []           # [{tick, kind, ...}] world events (drops, crafts, rewards, ...)


func _init(world_: Dictionary, data_: Dictionary) -> void:
	world = world_
	data = data_


func base_fighters() -> Array:
	var out := []
	for k in data["fighters"]:
		if data["fighters"][k].get("base", false):
			out.append(k)
	out.sort()
	return out


func new_game(leader_: String, pet_: String, seed_: int, field_layout: Dictionary) -> void:
	seed = seed_
	leader = leader_
	pet = pet_
	var lv := int(world["xp"]["start_level"])
	for f in base_fighters():
		fighters[f] = {"level": lv, "xp": int(world["xp"]["level_at"][lv - 1])}
	for k in world["start_kit"]:
		inventory[k] = int(world["start_kit"][k])
	for c in field_layout.get("plots", []).slice(0, int(world["farm"]["plots"])):
		plots.append({"cell": [int(c[0]), int(c[1])], "crop": "", "planted": 0})
	area = str(world["start_area"])
	arrive = "S"
	loot = Loot.new((seed * 7919 + 13) & 0x7fffffff)
	quests = QuestLog.new(world)


# ----------------------------------------------------------------------------- inventory

func count(item: String) -> int:
	return int(inventory.get(item, 0))


func add_item(item: String, n: int) -> void:
	inventory[item] = count(item) + n


func take(item: String, n: int) -> bool:
	if count(item) < n:
		return false
	inventory[item] = count(item) - n
	if int(inventory[item]) == 0:
		inventory.erase(item)
	return true


func bump(counter: String, n: int = 1) -> void:
	counters[counter] = int(counters.get(counter, 0)) + n


func note(kind: String, info: Dictionary) -> void:
	var d := info.duplicate()
	d["tick"] = tick
	d["kind"] = kind
	log_.append(d)


# ----------------------------------------------------------------------------- quests

func quest_counters() -> Dictionary:
	var c := counters.duplicate()
	return {"have": inventory.duplicate(), "total": c, "flag": flags.duplicate()}


## Offer a world event to every quest; grant the reward of each stage it completes.
## Persistent facts (areas cleared, bosses defeated) are re-offered after every transition, so a
## stage that becomes current *after* its fact happened still completes (no order soft-lock).
func emit(event: String) -> Array:
	var all := []
	var queue := [event]
	var guard := 0
	while not queue.is_empty() and guard < 64:
		guard += 1
		var ev: String = queue.pop_front()
		quests.counters = quest_counters()
		var taken: Array = quests.send(ev, tick)
		for t in taken:
			var st: Dictionary = quests.stage_def(t["region"], t["from"])
			note("stage", {"quest": t["region"], "stage": t["from"], "next": t["to"], "event": ev})
			grant(st.get("reward", {}))
		if not taken.is_empty():
			all += taken
			queue += facts()
	return all


func facts() -> Array:
	var out := []
	for a in cleared:
		out.append("cleared:" + str(a))
	for b in bosses:
		out.append("defeated:" + str(b))
	return out


func grant(r: Dictionary) -> void:
	if r.is_empty():
		return
	if r.has("coin"):
		add_item("coin", int(r["coin"]))
	for k in r.get("item", {}):
		add_item(k, int(r["item"][k]))
	if int(r.get("xp", 0)) > 0:
		add_xp(int(r["xp"]))
	if r.has("unlock") and not unlocked.has(r["unlock"]):
		unlocked.append(str(r["unlock"]))
		fighters[str(r["unlock"])] = {"level": 1, "xp": 0}
	if r.has("flag"):
		flags[str(r["flag"])] = true
	note("reward", {"reward": r})


func stage_at_least(quest: String, st: String) -> bool:
	return quests.stage_index(quest) >= quests.stage_index(quest, st)


func requires_ok(expr: String) -> bool:
	if expr == "":
		return true
	if expr.begins_with("stage:"):
		var q := expr.substr(6).get_slice(">=", 0)
		return stage_at_least(q, expr.get_slice(">=", 1))
	return QuestLog.eval_guard(expr, quest_counters())


# ----------------------------------------------------------------------------- xp / party

func level_for(xp: int) -> int:
	var lv := 1
	var table: Array = world["xp"]["level_at"]
	for i in table.size():
		if xp >= int(table[i]):
			lv = i + 1
	return lv


func add_xp(n: int) -> void:
	for f in base_fighters():
		var d: Dictionary = fighters[f]
		d["xp"] = int(d["xp"]) + n
		var lv := level_for(int(d["xp"]))
		if lv > int(d["level"]):
			note("level_up", {"fighter": f, "level": lv})
			d["level"] = lv


func party_def() -> Array:
	var out := []
	for f in base_fighters():
		var m := {"ref": f, "level": int(fighters[f]["level"])}
		if f == leader:
			m["leader"] = true
			m["pets"] = [pet]
		out.append(m)
	return out


## Item bonuses for the next area build: shared gear + area buffs → party, unique gear → holder.
func bonus_for_build() -> Dictionary:
	var party := {}
	for g in gear["shared"]:
		for k in world["items"][g].get("bonus", {}):
			party[k] = float(party.get(k, 0.0)) + float(world["items"][g]["bonus"][k])
	for b in buffs:
		for k in b["bonus"]:
			party[k] = float(party.get(k, 0.0)) + float(b["bonus"][k])
	var own := {}
	for holder in gear["unique"]:
		var d := {}
		for g in gear["unique"][holder]:
			for k in world["items"][g].get("bonus", {}):
				d[k] = float(d.get(k, 0.0)) + float(world["items"][g]["bonus"][k])
		own[holder] = d
	return {"party": party, "own": own}


func on_kill(ref: String, tier: int) -> Array:
	add_xp(int(world["xp"]["per_tier"]) * maxi(1, tier))
	bump("kills")
	var drops: Array = loot.roll(world, tier, ref)
	for d in drops:
		add_item(d[0], int(d[1]))
	note("drop", {"ref": ref, "tier": tier, "drops": drops})
	return drops


# ----------------------------------------------------------------------------- farming / gather / craft

func plot_at(cell: Vector2i) -> int:
	for i in plots.size():
		if int(plots[i]["cell"][0]) == cell.x and int(plots[i]["cell"][1]) == cell.y:
			return i
	return -1


func crop_ready(i: int) -> bool:
	var p: Dictionary = plots[i]
	if str(p["crop"]) == "":
		return false
	return tick - int(p["planted"]) >= int(world["crops"][p["crop"]]["grow_ticks"])


func seed_in_bag() -> String:
	var ids: Array = world["items"].keys()
	ids.sort()
	for k in ids:
		if world["items"][k]["kind"] == "seed" and count(k) > 0:
			return k
	return ""


func plant(i: int, seed_item: String) -> bool:
	if i < 0 or str(plots[i]["crop"]) != "" or not take(seed_item, 1):
		return false
	plots[i]["crop"] = str(world["items"][seed_item]["crop"])
	plots[i]["planted"] = tick
	bump("planted")
	note("plant", {"plot": i, "crop": plots[i]["crop"]})
	emit("plant")
	return true


func harvest(i: int) -> bool:
	if i < 0 or not crop_ready(i):
		return false
	var crop: Dictionary = world["crops"][plots[i]["crop"]]
	add_item(str(crop["id"]), int(crop["yield"]))
	bump("harvested", int(crop["yield"]))
	note("harvest", {"plot": i, "crop": crop["id"], "qty": crop["yield"]})
	plots[i]["crop"] = ""
	plots[i]["planted"] = 0
	emit("harvest")
	return true


func is_depleted(area_id: String, cell: Vector2i) -> bool:
	return depleted.get(area_id, []).has("%d,%d" % [cell.x, cell.y])


func gather(area_id: String, cell: Vector2i, item: String) -> bool:
	if is_depleted(area_id, cell):
		return false
	if not depleted.has(area_id):
		depleted[area_id] = []
	depleted[area_id].append("%d,%d" % [cell.x, cell.y])
	add_item(item, 1)
	bump("gathered")
	note("gather", {"area": area_id, "item": item})
	emit("gather")
	return true


func can_craft(recipe: String) -> bool:
	var r: Dictionary = world["recipes"][recipe]
	for k in r["in"]:
		if count(k) < int(r["in"][k]):
			return false
	return true


func craft(recipe: String) -> bool:
	if not can_craft(recipe):
		return false
	var r: Dictionary = world["recipes"][recipe]
	for k in r["in"]:
		take(k, int(r["in"][k]))
	for k in r["out"]:
		var it: Dictionary = world["items"][k]
		if it["kind"] == "gear":      # gear equips immediately (shared → party, unique → leader)
			if it.get("slot", "shared") == "unique":
				if not gear["unique"].has(leader):
					gear["unique"][leader] = []
				gear["unique"][leader].append(k)
			else:
				gear["shared"].append(k)
			flags["gear_" + k] = true     # gear is not in the bag: quests read it as flag:gear_<id> (Q4)
		else:
			add_item(k, int(r["out"][k]))
	bump("crafted")
	note("craft", {"recipe": recipe})
	emit("craft")
	return true


func owns_gear(item: String) -> bool:
	if gear["shared"].has(item):
		return true
	for h in gear["unique"]:
		if gear["unique"][h].has(item):
			return true
	return false


func buy(item: String) -> bool:
	var price := int(world["shop"].get(item, -1))
	if price < 0 or not take("coin", price):
		return false
	add_item(item, 1)
	note("buy", {"item": item, "price": price})
	return true


## Consumables: returns the use effect (the caller applies heals to the live sim).
func use(item: String) -> Dictionary:
	var it: Dictionary = world["items"].get(item, {})
	if it.get("kind", "") != "consumable" or not take(item, 1):
		return {}
	var u: Dictionary = it["use"]
	if u.has("buff"):
		buffs.append({"item": item, "bonus": u["buff"]})
	bump("used_" + item)
	note("use", {"item": item})
	return u


# ----------------------------------------------------------------------------- Player State v4

func to_save() -> Dictionary:
	var s: Dictionary = Save.new_save(leader, {}, [pet])
	var r: Dictionary = s["roster"]
	r["fighters"] = fighters.duplicate(true)
	r["pets"] = {"owned": [pet], "assigned": {leader: [pet]}}
	r["unlocked"] = unlocked.duplicate()
	r["party_hp"] = party_hp.duplicate()
	r["gear"] = gear.duplicate(true)
	var w: Dictionary = s["world"]
	w["area"] = area
	w["cleared"] = cleared.duplicate()
	w["bosses_defeated"] = bosses.duplicate()
	w["inventory"] = inventory.duplicate()
	w["quests"] = quests.active()
	w["flags"] = flags.duplicate()
	w["farm"] = {"plots": plots.duplicate(true)}
	w["checkpoint"] = {"area": area, "arrive": arrive}
	w["counters"] = counters.duplicate()
	w["seed"] = seed
	w["rng"] = loot.state
	w["tick"] = tick
	w["visits"] = visits.duplicate()
	w["depleted"] = depleted.duplicate(true)
	w["packs_cleared"] = packs_cleared.duplicate(true)
	w["buffs"] = buffs.duplicate(true)
	s["profile"]["playtime_ticks"] = tick
	s["profile"]["settings"] = A11y.settings()      # G-A11Y-01: the player's palette + bindings travel with every save
	s["profile"]["stats"] = {"encounters_won": encounters_won, "bosses_defeated": bosses.size()}
	return s


func from_save(s: Dictionary) -> void:
	var r: Dictionary = s["roster"]
	var w: Dictionary = s["world"]
	leader = str(r["leader"])
	pet = str(r["pets"]["assigned"].get(leader, [""])[0]) if not r["pets"]["assigned"].get(leader, []).is_empty() else ""
	fighters = {}
	for k in r["fighters"]:
		fighters[k] = {"level": int(r["fighters"][k]["level"]), "xp": int(r["fighters"][k]["xp"])}
	unlocked = r.get("unlocked", []).duplicate()
	party_hp = {}
	for k in r.get("party_hp", {}):
		party_hp[k] = int(r["party_hp"][k])
	gear = r.get("gear", {"shared": [], "unique": {}}).duplicate(true)
	area = str(w["checkpoint"].get("area", w["area"]))
	arrive = str(w["checkpoint"].get("arrive", "S"))
	cleared = w["cleared"].duplicate()
	bosses = w["bosses_defeated"].duplicate()
	inventory = {}
	for k in w["inventory"]:
		inventory[k] = int(w["inventory"][k])
	flags = w["flags"].duplicate()
	plots = []
	for p in w["farm"]["plots"]:
		plots.append({"cell": [int(p["cell"][0]), int(p["cell"][1])], "crop": str(p["crop"]), "planted": int(p["planted"])})
	counters = {}
	for k in w["counters"]:
		counters[k] = int(w["counters"][k])
	seed = int(w["seed"])
	loot = Loot.new(int(w["rng"]))
	tick = int(w["tick"])
	visits = {}
	for k in w["visits"]:
		visits[k] = int(w["visits"][k])
	depleted = w["depleted"].duplicate(true)
	packs_cleared = {}
	for k in w["packs_cleared"]:
		packs_cleared[k] = w["packs_cleared"][k].map(func(x): return int(x))
	buffs = w["buffs"].duplicate(true)
	encounters_won = int(s["profile"]["stats"].get("encounters_won", 0))
	quests = QuestLog.new(world, w["quests"])
