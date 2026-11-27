extends "res://scenes/encounter.gd"
## Vertical slice (F6, GAME_SPEC §6.1): character select (4 fighters × 3 starter pets) → farm +
## forage in the open-world field → cave exploration with packs → back to the farm to harvest and
## craft → Cave Warden (F5 boss) → out to the open world → rest/save. Checkpoint saves on every
## area entry (Player State v4); `--resume` reloads the last checkpoint in a new process.
##
## Windowed: godot --path games/game-zero -- --scene=slice            (keyboard; --autoplay = demo)
## Headless: ... --headless ... -- --scene=slice --autoplay --leader=kael --pet=ember_fox --seed=1
##           [--save-dir=<dir>] [--quit-after-checkpoint=N] [--resume] [--watchdog=600]
## Everything except the QA autopilot's choices is the same code a player drives.

const WorldState = preload("res://world/world_state.gd")
const MusicDirector = preload("res://audio/music_director.gd")
const Autopilot = preload("res://world/autopilot.gd")

const COMBAT_END_TICKS := 90      # calm ticks before a fight counts as over
const REVIVE_FRAC := 0.25         # downed allies get up with 25 % HP after a fight [INFERENCE F6-5]
const MAX_WIPES := 8
const TICK_LIMIT := 216000        # 60 game-minutes hard stop for automation
const STUCK_TICKS := 3600         # QA agent: same goal for 60 s → soft-lock
const SWAP_AT := 150              # scripted time-freeze swap this many ticks into a scripted fight

var ws
var world: Dictionary
var area_def: Dictionary
var director
var phase := "select"             # select | play | done
var in_combat := false
var _calm := 0
var _wcursor := 0
var _cells := {}
var _buffs_applied := false
var _checkpoints := 0
var _quit_after := -1
var _sel := [0, 0]
var _goal_key := ""
var _goal_ticks := 0
var _fight := {}
var _swapped_here := false
var _boss_engaged := false
var _msg := ""
var _boss_built := false
var _transitions := 0             # bumped on every area change: a transition ends the tick (resume parity)
var rep := {"wait_ticks": 0, "wait_segments": [], "areas": [], "fights": [], "swaps": [], "overlay": [], "swap_parity": [], "salves": [], "softlocks": [],
	"party_stats": {}, "boss": {}, "buff_at_boss": {}, "music_stems_loaded": {}, "checkpoints": []}


func _ready() -> void:
	autoplay = Fabric.flag("autoplay")
	world = Fabric.read_json("res://data/generated/world.json")
	director = MusicDirector.new()
	director.setup(world["music"])
	add_child(director)
	_quit_after = int(Fabric.arg("quit-after-checkpoint", "-1"))
	ws = WorldState.new(world, Fabric.game_data)
	if Fabric.flag("resume"):
		var s: Dictionary = Save.load_slot()
		if s.is_empty():
			push_error("slice: --resume but no loadable save in %s (%s)" % [Save.dir, Save.last_load])
			get_tree().quit(4)
			return
		ws.from_save(s)
		rep["resumed_from"] = {"tick": ws.tick, "area": ws.area, "checksum": s["checksum"], "last_load": Save.last_load,
			"state": _canon_state(s)}
		phase = "play"
		_enter_area()
	elif autoplay:
		start_game(str(Fabric.arg("leader", "kael")), str(Fabric.arg("pet", "ember_fox")))
	else:
		_show_select()
	if autoplay and DisplayServer.get_name() == "headless":
		_run_headless_slice()


func _canon_state(s: Dictionary) -> Dictionary:
	var st: Dictionary = Save.canon(s)
	st["format"] = Save.FORMAT
	st["version"] = Save.CURRENT
	st["checksum"] = Save.checksum(st)
	return st


# ---------------------------------------------------------------- character select

func base_ids() -> Array:
	return ws.base_fighters()


func starter_pets() -> Array:
	var out := []
	for k in Fabric.game_data["pets"]:
		if Fabric.game_data["pets"][k].get("starter", false):
			out.append(k)
	out.sort()
	return out


func _show_select() -> void:
	phase = "select"
	var layer := CanvasLayer.new()
	hud = Label.new()
	hud.position = Vector2(48, 48)
	layer.add_child(hud)
	add_child(layer)
	_render_select()


func _render_select() -> void:
	var lines := [tr("slice.select.title"), ""]
	var f := base_ids()
	for i in f.size():
		var d: Dictionary = Fabric.game_data["fighters"][f[i]]
		var st: Dictionary = d["levels"][int(world["xp"]["start_level"]) - 1]
		lines.append("%s %s — %s  %s %d  ATK %.1f  DEF %.1f" % ["▶" if i == _sel[0] else " ", tr("roster." + f[i]), tr("role." + str(d["role"])),
			tr("hud.hp"), int(st["hp"]), float(st["atk"]), float(st["def"])])
	lines.append("")
	var p := starter_pets()
	for i in p.size():
		lines.append("%s %s — %s" % ["▶" if i == _sel[1] else " ", tr("pet." + p[i]), tr("pet.style." + str(Fabric.game_data["pets"][p[i]]["style"]))])
	lines.append("")
	lines.append(Fabric.hint("slice.select.hint"))
	hud.text = "\n".join(lines)


func start_game(leader: String, pet: String) -> void:
	var field_layout: Dictionary = Fabric.json_asset(world["areas"][world["start_area"]]["tilemap"])
	ws.new_game(leader, pet, int(Fabric.arg("seed", "1")), field_layout)
	ws.emit("select")
	phase = "play"
	transition_to(str(world["start_area"]), "S")


# ---------------------------------------------------------------- areas

func cells(glyph: String) -> Array:
	return _cells.get(glyph, [])


func hostiles_left() -> int:
	var n := 0
	for e in sim.entities:
		if e.team == 1 and e.alive():
			n += 1
	return n


func _boss_down() -> bool:
	return ws.flags.get("warden_down", false)


## Leave the current area (carry HP, expire area buffs), update world state, checkpoint-save, build.
func transition_to(area: String, arrive: String) -> void:
	if sim != null:
		_record_party()
		if _buffs_applied:
			ws.buffs.clear()
	_transitions += 1
	ws.area = area
	ws.arrive = arrive
	ws.visits[area] = int(ws.visits.get(area, 0)) + 1
	if str(world["areas"][area].get("biome", "")) == "field":
		ws.party_hp = {}           # home: rest at the farm, party fully healed [INFERENCE F6-5]
	ws.emit("enter:" + area)
	checkpoint_save()
	_enter_area()


func checkpoint_save() -> void:
	var s: Dictionary = ws.to_save()
	var sum: String = Save.write(s)
	_checkpoints += 1
	rep["checkpoints"].append({"n": _checkpoints, "tick": ws.tick, "area": ws.area, "checksum": sum})
	if _quit_after == _checkpoints:
		var loaded: Dictionary = Save.load_slot()
		print("FABRIC_RESULT " + JSON.stringify({"slice_quit": {"checkpoint": _checkpoints, "tick": ws.tick, "area": ws.area,
			"checksum": sum, "state": _canon_state(s), "reloaded_same_process": loaded.get("checksum", "") == sum}}))
		Save.quit_after_persist(0)
		phase = "quit"


func _record_party() -> void:
	ws.party_hp = {}
	for e in sim.entities:
		if e.team == 0:
			ws.party_hp[e.id] = maxi(0, e.hp)
			if e.kind == "fighter":
				var st: Dictionary = rep["party_stats"].get(e.id, {"damage": 0, "healing": 0, "kills": 0})
				st["damage"] += int(e.stats_dealt["damage"])
				st["healing"] += int(e.stats_dealt["healing"])
				st["kills"] += int(e.stats_dealt["kills"])
				rep["party_stats"][e.id] = st
			elif e.kind == "pet":
				var ps: Dictionary = rep["party_stats"].get(e.id, {"damage": 0, "healing": 0, "kills": 0, "pet": true})
				ps["damage"] += int(e.stats_dealt["damage"])
				rep["party_stats"][e.id] = ps


func _area_encounter() -> Dictionary:
	area_def = world["areas"][ws.area]
	layout = Fabric.json_asset(area_def["tilemap"])
	var enc: Dictionary
	var boss_area: bool = area_def.has("encounter")
	if boss_area and not _boss_down():
		enc = Fabric.read_json("res://data/encounters/%s.json" % area_def["encounter"]).duplicate(true)
		enc.erase("script")
		enc.erase("save_on_victory")
	else:
		enc = {"hostiles": []}
		var done: Array = ws.packs_cleared.get(ws.area, [])
		var packs: Array = area_def.get("packs", [])
		for i in packs.size():
			if done.has(i) or not ws.requires_ok(str(packs[i].get("requires", ""))):
				continue
			for u in packs[i]["units"]:
				enc["hostiles"].append({"ref": u["ref"], "count": int(u.get("count", 1)), "spawn": int(packs[i]["spawn"]), "pack": i})
	enc.erase("music")                  # the MusicDirector owns music in the slice
	enc["id"] = ws.area
	enc["increment"] = "vertical-slice"
	enc["tilemap"] = area_def["tilemap"]
	enc["ai"] = "bt"
	enc["party"] = ws.party_def()
	enc["seed"] = (ws.seed * 1000003 + ws.area.hash() % 100003 * 131 + int(ws.visits.get(ws.area, 0)) * 7 + int(ws.counters.get("wipes", 0)) * 977) & 0x7fffffff
	enc["variance"] = 0.2
	enc["crit"] = 0.1
	enc["bonus"] = ws.bonus_for_build()
	var c: Array = layout["exit"] if ws.arrive == "E" else layout["start"]
	enc["start_cell"] = [int(c[0]), int(c[1])]
	return enc


func _build() -> void:
	remove_child(director)
	super._build()
	add_child(director)


func _enter_area() -> void:
	encounter = _area_encounter()
	_buffs_applied = not ws.buffs.is_empty()
	_build()
	_boss_built = area_def.has("encounter") and not _boss_down()
	sim.explore = not _boss_built
	for e in sim.entities:
		if e.team == 0 and ws.party_hp.has(e.id):
			var hp := int(ws.party_hp[e.id])
			e.hp = clampi(hp, 1, e.max_hp) if hp > 0 else maxi(1, int(e.max_hp * REVIVE_FRAC))
	_cells = {}
	var rows: Array = layout["rows"]
	for y in rows.size():
		var row: String = rows[y]
		for x in row.length():
			if row[x] != "#" and row[x] != ".":
				if not _cells.has(row[x]):
					_cells[row[x]] = []
				_cells[row[x]].append(Vector2i(x, y))
	_wcursor = 0
	in_combat = false
	_calm = 0
	_swapped_here = false
	_boss_engaged = false
	_goal_key = ""
	_goal_ticks = 0
	director.set_biome(str(area_def["biome"]), ws.tick)
	var tr_ := str(world["music"]["biomes"][area_def["biome"]]["track"])
	rep["music_stems_loaded"][tr_] = director.players.keys()
	rep["areas"].append({"tick": ws.tick, "area": ws.area, "arrive": ws.arrive, "hostiles": hostiles_left(), "buffs": ws.buffs.size(),
		"boss": _boss_built})
	if _boss_built:
		for e in sim.entities:
			if e.team == 0 and e.kind == "fighter" and e.is_leader:
				rep["buff_at_boss"] = {"leader": e.id, "atk": e.atk, "bonus": e.get_meta("bonus", {}), "buffs": ws.buffs.duplicate(true),
					"gear": ws.gear.duplicate(true)}
	queue_redraw()


# ---------------------------------------------------------------- world tick

func world_step(input: Dictionary) -> void:
	_step(input)
	ws.tick += 1
	director.step()
	_process_kills()
	_update_combat()
	if _boss_built and not sim.explore and sim.outcome() == "victory":
		_on_boss_victory()
	if sim.outcome() == "defeat":
		_on_wipe()
	elif sim.stalled():
		rep["softlocks"].append({"tick": ws.tick, "area": ws.area, "kind": "combat_stall"})


func _process_kills() -> void:
	while _wcursor < sim.events.size():
		var ev: Dictionary = sim.events[_wcursor]
		_wcursor += 1
		if ev["type"] != "defeated" or int(ev.get("target_team", 0)) != 1:
			continue
		var e = sim.by_id.get(ev["target"])
		if e == null:
			continue
		var ref := str(e.get_meta("ref", e.id))
		ws.on_kill(ref, e.tier)
		if _fight:
			_fight["kills"] += 1
		if not e.phases.is_empty():
			if not ws.bosses.has(ref):
				ws.bosses.append(ref)
		var pk := int(e.get_meta("pack", -1))
		if pk >= 0:
			var left := 0
			for o in sim.entities:
				if o.team == 1 and o.alive() and int(o.get_meta("pack", -1)) == pk:
					left += 1
			if left == 0:
				if not ws.packs_cleared.has(ws.area):
					ws.packs_cleared[ws.area] = []
				ws.packs_cleared[ws.area].append(pk)
				ws.note("pack_cleared", {"area": ws.area, "pack": pk})
				var wave := str(area_def.get("packs", [])[pk].get("wave", "")) if pk < area_def.get("packs", []).size() else ""
				if wave != "" and _wave_cleared(wave) and not ws.cleared.has(ws.area + "." + wave):
					ws.cleared.append(ws.area + "." + wave)     # persistent fact cleared:<area>.<wave> (Q4)
					ws.encounters_won += 1
					ws.emit("cleared:" + ws.area + "." + wave)
				if _active_packs_cleared() and not ws.cleared.has(ws.area):
					ws.cleared.append(ws.area)
					ws.encounters_won += 1
		ws.emit("defeated:" + ref)
		if ws.cleared.has(ws.area):
			ws.emit("cleared:" + ws.area)


## Every pack of `wave` in this area is cleared (Q4 named waves, e.g. the tunnels patrol).
func _wave_cleared(wave: String) -> bool:
	var done: Array = ws.packs_cleared.get(ws.area, [])
	var packs: Array = area_def.get("packs", [])
	for i in packs.size():
		if str(packs[i].get("wave", "")) == wave and not done.has(i):
			return false
	return true


## Every pack that is live in this area right now (Q4: packs may carry a `requires` gate — the route
## repopulates for the boss trip) is cleared.
func _active_packs_cleared() -> bool:
	var done: Array = ws.packs_cleared.get(ws.area, [])
	var packs: Array = area_def.get("packs", [])
	for i in packs.size():
		if not done.has(i) and ws.requires_ok(str(packs[i].get("requires", ""))):
			return false
	return true


## P7 (0.7.15): the state a world fight starts from — party levels + pet, item/buff bonuses, every party member's HP
## (carried between fights) and the tilemap — so `forge worldfights` can replay the same fight over many seeds.
## Diagnostics only: nothing here feeds back into the run.
func _fight_context() -> Dictionary:
	var hp := {}
	for e in sim.entities:
		if e.team == 0:
			hp[e.id] = maxi(0, e.hp)
	var ctx := {"tilemap": str(area_def["tilemap"]), "party": ws.party_def(), "bonus": encounter.get("bonus", {}),
		"hp": hp, "packs": []}
	if _boss_built:
		ctx["encounter"] = str(area_def["encounter"])
	return ctx


func _update_combat() -> void:
	var engaged_packs := []
	var near := false
	var tension := false
	var boss := false
	var tr_range := float(world["music"].get("tension_range", 176))
	for h in sim.entities:
		if h.team != 1 or not h.alive():
			continue
		var d := INF
		for p in sim.entities:
			if p.team == 0 and p.alive():
				d = minf(d, h.pos.distance_to(p.pos))
		if d <= h.aggro_range:
			near = true
			if h.tier >= 3:
				boss = true
			engaged_packs.append(int(h.get_meta("pack", -1)))
		elif d <= tr_range:
			tension = true
	if near:
		_calm = 0
		if not in_combat:
			in_combat = true
			_fight = {"area": ws.area, "start": ws.tick, "kills": 0, "boss": false, "swap": false, "ctx": _fight_context()}
		for pk in engaged_packs:        # P7: which packs this fight pulled (world-fight Monte Carlo context)
			if not _fight["ctx"]["packs"].has(pk):
				_fight["ctx"]["packs"].append(pk)
		if boss:
			_fight["boss"] = true
			if not _boss_engaged:
				_boss_engaged = true
				submit_command("everyone focus the warden")
	elif in_combat:
		_calm += 1
		if _calm >= COMBAT_END_TICKS:
			in_combat = false
			_on_combat_end()
	director.set_state("boss" if boss else ("combat" if in_combat else ("tension" if tension else "explore")), ws.tick)


func _on_combat_end() -> void:
	for e in sim.entities:
		if e.team == 0 and e.hp <= 0:
			e.hp = maxi(1, int(e.max_hp * REVIVE_FRAC))
			e.casting = {}
			e.anim = "idle0"
	sim.engaged = false                 # re-arm battle_start callouts for the next fight
	var l = sim.leader()
	if l != null and l.id != ws.leader and sim.by_id.has(ws.leader):
		do_swap(ws.leader, false)       # temporary swap ends with the fight (GAME_SPEC §4.1)
	_fight["end"] = ws.tick - COMBAT_END_TICKS
	rep["fights"].append(_fight)
	_fight = {}


func _on_boss_victory() -> void:
	sim.explore = true
	in_combat = false
	var b = null
	for e in sim.entities:
		if not e.phases.is_empty():
			b = e
	if b:
		rep["boss"] = {"id": b.id, "ref": b.get_meta("ref", ""), "tier": b.tier, "defeated": not b.alive(), "phases_reached": b.phase + 1,
			"summons": sim.summons, "ticks": sim.tick, "attempt": int(ws.counters.get("wipes_lair", 0)) + 1}
	if _fight:
		_fight["end"] = ws.tick
		rep["fights"].append(_fight)
		_fight = {}
	for e in sim.entities:
		if e.team == 0 and e.hp <= 0:
			e.hp = maxi(1, int(e.max_hp * REVIVE_FRAC))
			e.casting = {}
	if not ws.cleared.has(ws.area):
		ws.cleared.append(ws.area)
		ws.encounters_won += 1
	ws.emit("cleared:" + ws.area)
	var l = sim.leader()
	if l != null and l.id != ws.leader and sim.by_id.has(ws.leader):
		do_swap(ws.leader, false)


func _on_wipe() -> void:
	ws.bump("wipes")
	if _boss_built:
		ws.bump("wipes_lair")
	rep["fights"].append(_fight.merged({"end": ws.tick, "wipe": true}))
	_fight = {}
	ws.note("wipe", {"area": ws.area})
	ws.party_hp = {}                    # respawn at the area checkpoint, rested
	_enter_area()


# ---------------------------------------------------------------- actions

func perform(act: String, arg) -> bool:
	var l = sim.leader()
	var here: Vector2i = sim.grid.to_cell(l.pos) if l else Vector2i(-1, -1)
	match act:
		"harvest": return ws.harvest(int(arg))
		"plant": return ws.plant(ws.plot_at(here), str(arg))
		"gather": return ws.gather(ws.area, here, str(arg))
		"craft": return ws.craft(str(arg))
		"buy": return ws.buy(str(arg))
		"use": return _use(str(arg))
		"save":
			ws.emit("save")
			checkpoint_save()
			return true
		"link": return _try_link(str(arg))
		"wait": return true
	return false


func _use(item: String) -> bool:
	var u: Dictionary = ws.use(item)
	if u.is_empty():
		return false
	if u.has("heal_pct"):
		var healed := 0
		for e in sim.entities:
			if e.team == 0:
				var before: int = e.hp
				e.hp = mini(e.max_hp, maxi(e.hp, 0) + int(round(e.max_hp * float(u["heal_pct"]))))
				healed += e.hp - maxi(before, 0)
		rep["salves"].append({"tick": ws.tick, "area": ws.area, "healed": healed})
	return true


func _try_link(glyph: String) -> bool:
	var link = area_def.get("links", {}).get(glyph)
	if link == null:
		return false
	if not ws.requires_ok(str(link.get("requires", ""))):
		_msg = tr("slice.msg.sealed")
		return false
	transition_to(str(link["to"]), str(link.get("arrive", "S")))
	return true


func _awaited_plant_tick() -> int:
	var best := -1
	var ready_at := 1 << 40
	for p in ws.plots:
		if str(p["crop"]) != "":
			var r := int(p["planted"]) + int(world["crops"][p["crop"]]["grow_ticks"])
			if r < ready_at:
				ready_at = r
				best = int(p["planted"])
	return best


func _autopilot_input() -> Dictionary:
	var a: Dictionary = Autopilot.decide(self)
	match a["kind"]:
		"fight":
			_goal_key = ""
			return {}
		"wait":
			return {"move": Vector2.ZERO}
		"done":
			return {"move": Vector2.ZERO}
		"do":
			perform(a["act"], a["arg"])
			return {"move": Vector2.ZERO}
	var key := "%s|%s|%s" % [a["cell"], a["act"], str(a["arg"])]
	if key != _goal_key:
		_goal_key = key
		_goal_ticks = 0
	_goal_ticks += 1
	if _goal_ticks > STUCK_TICKS:
		rep["softlocks"].append({"tick": ws.tick, "area": ws.area, "kind": "stuck", "goal": key})
		_goal_ticks = 0
	if a["arrived"]:
		if a["act"] == "wait":
			_goal_ticks = 0     # waiting by a growing crop is a timer, not a soft-lock (Q4 crop cycle)
			rep["wait_ticks"] += 1
			# wait segments for the human-pace model (forge/pace.py): when it started, how long, and when the
			# crop being waited on (the soonest-ready growing plot) was planted
			var segs: Array = rep["wait_segments"]
			if segs.is_empty() or int(segs[-1]["start"]) + int(segs[-1]["ticks"]) != ws.tick:
				segs.append({"start": ws.tick, "ticks": 0, "planted": _awaited_plant_tick()})
			segs[-1]["ticks"] = int(segs[-1]["ticks"]) + 1
		perform(a["act"], a["arg"])
		return {"move": Vector2.ZERO}
	var l = sim.leader()
	var goal: Vector2i = a["cell"]
	var wp: Vector2 = sim.grid.step_toward(goal, l.pos)
	if wp.distance_to(l.pos) < 0.5:
		wp = sim.grid.center(goal)
	return {"move": (wp - l.pos).limit_length(1.0) if wp.distance_to(l.pos) > 1.0 else (wp - l.pos)}


## Scripted time-freeze swap (QA script, once per area visit in a big fight): freeze, rank,
## capture the overlay, prove threaded == serial ranking, swap to the top recommendation.
func _maybe_scripted_swap() -> bool:
	if _swapped_here or not in_combat or _fight.is_empty():
		return false
	if not (_fight.get("boss", false) or (ws.area == "cave_deep" and hostiles_left() >= 3)):
		return false
	if ws.tick - int(_fight["start"]) < SWAP_AT:
		return false
	_swapped_here = true
	toggle_freeze()
	var serial: Array = SwapAdvisor.rank(sim, false)["recommendations"].map(func(r): return [r["id"], r["score"]])
	rep["swap_parity"].append(serial == swap_recs.get("recommendations", []).map(func(r): return [r["id"], r["score"]]))
	if rep["overlay"].is_empty() or _fight.get("boss", false):
		rep["overlay"] = freeze_overlay()
	rep["swaps"].append({"tick": ws.tick, "area": ws.area, "boss": _fight.get("boss", false), "wall_ms": swap_recs.get("wall_ms", 0.0),
		"recs": swap_recs.get("recommendations", []).map(func(r): return [r["id"], r["score"]])})
	_fight["swap"] = true
	return true


# ---------------------------------------------------------------- headless scripted playthrough

func _run_headless_slice() -> void:
	var t0 := Time.get_ticks_usec()
	while phase == "play" and ws.tick < TICK_LIMIT:
		if _maybe_scripted_swap():
			_scripted_swap({"force_change": true})
		var tr0 := _transitions
		var input := _autopilot_input()
		if phase != "play":
			break
		if ws.quests.done("q_warden"):
			phase = "done"
			break
		if _transitions != tr0:
			continue                    # new area: decide again from the checkpointed state, like a reload
		world_step(input)
		if int(ws.counters.get("wipes", 0)) > MAX_WIPES or rep["softlocks"].size() > 0:
			break
	if phase == "quit":
		return
	_record_party()
	var final: Dictionary = ws.to_save()
	var result := {"slice": _slice_report(final, (Time.get_ticks_usec() - t0) / 1000.0)}
	result["slice"]["net"] = Fabric.net_report()    # F7 G-NET-01: solo run with the network stack dormant
	print("FABRIC_RESULT " + JSON.stringify(result))
	var ok: bool = result["slice"]["completed"]
	print("SLICE %s %s" % [ws.leader + "+" + ws.pet, "OK" if ok else "FAIL"])
	get_tree().quit(0 if ok else 1)


func _slice_report(final: Dictionary, wall_ms: float) -> Dictionary:
	var stage_ticks := {}
	var drops := []
	var crafts := []
	var plants := []
	var harvests := []
	var gathers := []
	var level_ups := []
	for n in ws.log_:
		match n["kind"]:
			"stage": stage_ticks["%s.%s" % [n["quest"], n["stage"]]] = n["tick"]
			"drop": drops.append([n["ref"], n["tier"], n["drops"], n["tick"]])
			"craft": crafts.append(n["recipe"])
			"plant": plants.append(n["crop"])
			"harvest": harvests.append([n["crop"], n["qty"]])
			"gather": gathers.append(n["item"])
			"level_up": level_ups.append([n["fighter"], n["level"], n["tick"]])
	var probe = Loot.new(12345)
	var probe_rolls := []
	for k in [["cave_mite", 1], ["emberling", 1], ["rock_brute", 2], ["cave_warden", 3], ["cave_mite", 1]]:
		probe_rolls.append(probe.roll(world, k[1], k[0]))
	return {
		"selection": {"leader": ws.leader, "pet": ws.pet}, "seed": ws.seed,
		"completed": ws.quests.done("q_warden") and rep["softlocks"].is_empty(),
		"ticks": ws.tick, "game_minutes": snappedf(ws.tick / 3600.0, 0.01), "wall_ms": snappedf(wall_ms, 0.1),
		"areas": rep["areas"], "quests": ws.quests.active(), "quest_trace": ws.quests.trace, "stage_ticks": stage_ticks,
		"farming": {"planted": plants, "harvested": harvests, "gathered": gathers, "crafted": crafts, "salves": rep["salves"],
			"gear": ws.gear, "inventory": ws.inventory, "counters": ws.counters},
		"loot": {"drops": drops, "rng_final": ws.loot.state, "probe_seed": 12345, "probe_rolls": probe_rolls},
		"level_ups": level_ups, "fighters": ws.fighters, "unlocked": ws.unlocked,
		"fights": rep["fights"], "wipes": int(ws.counters.get("wipes", 0)), "party_stats": rep["party_stats"],
		"swaps": rep["swaps"], "swap_parity": rep["swap_parity"], "overlay": rep["overlay"],
		"boss": rep["boss"], "buff_at_boss": rep["buff_at_boss"],
		"music": {"trace": director.trace, "stems_loaded": rep["music_stems_loaded"]},
		"wait_ticks": int(rep["wait_ticks"]), "wait_segments": rep["wait_segments"], "buys": ws.log_.filter(func(n): return n["kind"] == "buy").size(),
		"bought": ws.log_.filter(func(n): return n["kind"] == "buy").map(func(n): return n["item"]),
		"callouts_total": callout_log.size(), "intents": intents_handled.size(),
		"softlocks": rep["softlocks"], "checkpoints": rep["checkpoints"],
		"resumed_from": rep.get("resumed_from", {}),
		"final_state": _canon_state(final),
	}


const Loot = preload("res://world/loot.gd")


# ---------------------------------------------------------------- windowed play

func _physics_process(delta: float) -> void:
	if settings_open():
		return
	if Input.is_action_just_pressed("settings") and phase in ["select", "play"] and not command_box_visible():
		open_settings()
		return
	if phase == "select":
		_select_input()
		return
	if sim == null or phase != "play" or (autoplay and DisplayServer.get_name() == "headless"):
		return
	if command_box.visible:
		return
	if _freeze_hold > 0:                # demo autoplay holds the overlay on screen
		_freeze_hold -= 1
		if _freeze_hold == 0:
			_scripted_swap({"force_change": true})
		_sync_view()
		return
	if Input.is_action_just_pressed("swap"):
		toggle_freeze()
	if frozen:
		for i in 4:
			if Input.is_action_just_pressed("swap_pick_%d" % (i + 1)) and i < swap_recs.get("recommendations", []).size():
				do_swap(swap_recs["recommendations"][i]["id"])
				toggle_freeze()
				break
		_sync_view()
		return
	if Input.is_action_just_pressed("tactic_menu"):
		submit_command("defend" if sim.tactic == "aggressive" else "charge")
	if Input.is_action_just_pressed("command"):
		command_box.visible = true
		command_box.text = ""
		command_box.grab_focus()
		return
	if not autoplay:
		if Input.is_action_just_pressed("interact"):
			_interact()
		if Input.is_action_just_pressed("use_salve") and not in_combat:   # edge-triggered: one salve per press
			_use("moss_salve")
	_accum += delta
	while _accum >= 1.0 / 60.0 and phase == "play":
		_accum -= 1.0 / 60.0
		if autoplay:
			if _maybe_scripted_swap():
				_freeze_hold = FREEZE_HOLD
				break
			var tr0 := _transitions
			var inp := _autopilot_input()
			if ws.quests.done("q_warden"):
				phase = "done"
				break
			if _transitions == tr0:
				world_step(inp)
		else:
			world_step(_player_input())
	_sync_view()


func _select_input() -> void:
	var f := base_ids()
	var p := starter_pets()
	if Input.is_action_just_pressed("move_right"):
		_sel[0] = (_sel[0] + 1) % f.size()
	elif Input.is_action_just_pressed("move_left"):
		_sel[0] = (_sel[0] + f.size() - 1) % f.size()
	elif Input.is_action_just_pressed("move_down"):
		_sel[1] = (_sel[1] + 1) % p.size()
	elif Input.is_action_just_pressed("move_up"):
		_sel[1] = (_sel[1] + p.size() - 1) % p.size()
	elif Input.is_action_just_pressed("interact") or Input.is_action_just_pressed("ui_accept"):
		for c in get_children():
			if c != director:
				c.queue_free()
		start_game(f[_sel[0]], p[_sel[1]])
		return
	_render_select()


## Context action on the tile under the leader (E): harvest/plant, gather, craft/rest, travel.
func _interact() -> void:
	var l = sim.leader()
	if l == null:
		return
	var here: Vector2i = sim.grid.to_cell(l.pos)
	var g: String = sim.grid.cell(here)
	_msg = ""
	match g:
		"P":
			var i: int = ws.plot_at(here)
			if not ws.harvest(i):
				var sd: String = ws.seed_in_bag()
				if sd == "" or not ws.plant(i, sd):
					_msg = tr("slice.msg.plot_busy")
		"G":
			if not perform("gather", area_def.get("nodes", {}).get("G", "")):
				_msg = tr("slice.msg.depleted")
		"W":
			for r in ["moss_salve", "ember_tonic", "flint_edge", "warden_charm"]:
				if ws.can_craft(r) and not ws.owns_gear(r):
					ws.craft(r)
					_msg = tr("slice.msg.crafted") + " " + tr("item." + r)
					return
			if ws.quests.stage("q_warden") == "rest":
				perform("save", null)
				_msg = tr("slice.msg.saved")
			elif ws.buy(ws.seed_in_bag() if ws.seed_in_bag() != "" else "sunroot_seed"):
				_msg = tr("slice.msg.bought")
		"S", "E":
			_try_link(g)


# ---------------------------------------------------------------- rendering

func _draw() -> void:
	if sim == null or tileset == null or phase == "select":
		return
	var ts: int = sim.grid.tile_size
	var legend: Dictionary = layout.get("legend", {"#": 0, ".": 1, "S": 2, "E": 3})
	for y in sim.grid.height:
		for x in sim.grid.width:
			var g: String = sim.grid.rows[y][x]
			if g == "G" and ws.is_depleted(ws.area, Vector2i(x, y)):
				g = "."
			var idx: int = int(legend.get(g, 0))
			draw_texture_rect_region(tileset, Rect2(x * ts, y * ts, ts, ts), Rect2(idx * ts, 0, ts, ts))
	if ws.area == world["start_area"]:
		for i in ws.plots.size():
			var c: Array = ws.plots[i]["cell"]
			if str(ws.plots[i]["crop"]) != "":
				# palette colours (PatternVault ui_roles → live colour-blind remap) + a shape cue: ready crops get a frame
				var ready: bool = ws.crop_ready(i)
				var col: Color = A11y.ui_colour("plot_ready" if ready else "plot_growing")
				draw_rect(Rect2(int(c[0]) * ts + 5, int(c[1]) * ts + 5, ts - 10, ts - 10), col)
				if ready:
					draw_rect(Rect2(int(c[0]) * ts + 2, int(c[1]) * ts + 2, ts - 4, ts - 4), col, false, 1.0)


func _sync_view() -> void:
	super._sync_view()
	for c in get_children():
		if c is Camera2D:
			var l = sim.leader()
			if l:
				c.position = l.pos.round()
	if not frozen and hud:
		var st: String = ws.quests.stage("q_warden")
		var inv := []
		var keys: Array = ws.inventory.keys()
		keys.sort()
		for k in keys:
			inv.append("%s %d" % [tr("item." + k), int(ws.inventory[k])])
		var lines := [tr("area." + ws.area) + "   " + tr("slice.music") + ": " + director.state,
			tr("slice.objective") + ": " + tr("quest.q_warden." + st),
			tr("slice.forager") + ": " + tr("quest.q_forager." + ws.quests.stage("q_forager")), ""]
		for e in sim.entities:
			if e.team == 0 and e.kind == "fighter":
				lines.append("%s%s Lv%d %s %d/%d" % ["> " if e.is_leader else "  ", tr("roster." + e.id), int(ws.fighters[e.id]["level"]),
					tr("hud.hp"), e.hp, e.max_hp])
		lines.append("")
		lines.append(", ".join(inv))
		if _msg != "":
			lines.append(_msg)
		if phase == "done":
			lines.append(tr("slice.done"))
		lines.append(Fabric.hint("slice.hint"))
		hud.text = "\n".join(lines)
	queue_redraw()


func command_box_visible() -> bool:
	return command_box != null and command_box.visible
