extends RefCounted
## Deterministic combat entity. Stats + abilities come from AssetFabric codegen.

var id: String
var team: int              # 0 = player party, 1 = hostile
var kind: String = "fighter"   # fighter | pet | enemy
var sprite_id: String
var pos: Vector2
var radius: float = 5.0
var max_hp: int = 10
var hp: int = 10
var atk: float = 1.0
var def: float = 0.0
var speed: float = 1.0     # px per tick @ 60 Hz
var aggro_range: float = 112.0
var abilities: Array = []  # Array[Dictionary] from game_data.json / .tres
var cooldowns: Dictionary = {}   # ability id -> ticks left
var casting: Dictionary = {}     # {ability, target_id, left}
var owner_id: String = ""  # pets: owning fighter
var is_leader: bool = false
var tier: int = 0
var taunt_left: int = 0
var facing: int = 1
var anim: String = "idle0"
var moving: bool = false
var hit_flash: int = 0
var stats_dealt := {"damage": 0, "healing": 0, "hits": 0, "kills": 0, "casts": 0}
var last_ability: String = ""
var low_hp_called := false
var last_dir := Vector2.ZERO
# F5 boss: hierarchical manager state (phase thresholds → worker kit). Empty for non-bosses.
var phases: Array = []     # [{at, abilities: [Dictionary], speed, atk_mult, summon: {template}}]
var phase: int = 0
var base_atk: float = 1.0
var idx: int = -1              # index in CombatSim.entities (Q3 struct-of-arrays mirror)
# BT brain memory (Q3: plain members instead of Object metadata — set_meta/get_meta go through the
# global StringName table, which dominated the swap advisor's forward sims and serialised its threads)
var bt_mem := false            # true once the brain has picked a target (snapshot "memory" present)
var bt_target: String = ""
var bt_target_tick: int = -999
var bt_ability: Dictionary = {}


static func create(id_: String, team_: int, kind_: String, sprite: String, stats: Dictionary, abilities_: Array, at: Vector2):
	var e = new()
	e.id = id_
	e.team = team_
	e.kind = kind_
	e.sprite_id = sprite
	e.pos = at
	e.max_hp = int(round(float(stats.get("hp", 10))))
	e.hp = e.max_hp
	e.atk = float(stats.get("atk", 1))
	e.def = float(stats.get("def", 0))
	e.speed = float(stats.get("speed", 1.0))
	e.aggro_range = float(stats.get("aggro", 112.0))
	e.abilities = abilities_
	e.base_atk = e.atk
	for a in abilities_:
		e.cooldowns[a["id"]] = 0
	return e


func alive() -> bool:
	return hp > 0


func ready_abilities() -> Array:
	var out := []
	if not casting.is_empty():
		return out
	for a in abilities:
		if int(cooldowns.get(a["id"], 0)) <= 0:
			out.append(a)
	return out


func copy():
	var c = new()
	c.id = id
	c.team = team
	c.kind = kind
	c.sprite_id = sprite_id
	c.pos = pos
	c.radius = radius
	c.max_hp = max_hp
	c.hp = hp
	c.atk = atk
	c.def = def
	c.speed = speed
	c.aggro_range = aggro_range
	c.owner_id = owner_id
	c.is_leader = is_leader
	c.tier = tier
	c.taunt_left = taunt_left
	c.facing = facing
	c.anim = anim
	c.moving = moving
	c.hit_flash = hit_flash
	c.last_ability = last_ability
	c.abilities = abilities
	c.cooldowns = cooldowns.duplicate()
	c.casting = casting.duplicate()
	c.stats_dealt = stats_dealt.duplicate()
	c.low_hp_called = low_hp_called
	c.phases = phases          # read-only templates, shared
	c.phase = phase
	c.base_atk = base_atk
	c.last_dir = last_dir
	c.bt_mem = bt_mem          # brain memory (ids/ints only)
	c.bt_target = bt_target
	c.bt_target_tick = bt_target_tick
	if has_meta("ref"):        # roster ref (not hot)
		c.set_meta("ref", get_meta("ref"))
	return c


## Q3: give a forward clone private String buffers and containers. Godot Strings/Arrays/Dicts are
## copy-on-write with atomic refcounts; clones on different worker threads that merely *read* a
## shared buffer still bounce its cache line between cores (the swap advisor scaled 1.0x on 2 cores).
## `abilities` maps ability id -> this clone's private ability dict.
static func own(s: String) -> String:
	return s.to_utf8_buffer().get_string_from_utf8()


static func own_value(v):
	match typeof(v):
		TYPE_STRING:
			return own(v)
		TYPE_DICTIONARY:
			var d := {}
			for k in v:
				d[own_value(k)] = own_value(v[k])
			return d
		TYPE_ARRAY:
			var a := []
			for x in v:
				a.append(own_value(x))
			return a
	return v


func isolate(abilities_by_id: Dictionary) -> void:
	id = own(id)
	kind = own(kind)
	sprite_id = own(sprite_id)
	owner_id = own(owner_id)
	anim = own(anim)
	last_ability = own(last_ability)
	bt_target = own(bt_target)
	var abs_ := []
	for ab in abilities:
		if not abilities_by_id.has(ab["id"]):
			abilities_by_id[own(ab["id"])] = own_value(ab)
		abs_.append(abilities_by_id[ab["id"]])
	abilities = abs_
	var cds := {}
	for k in cooldowns:
		cds[own(k)] = cooldowns[k]
	cooldowns = cds
	if not casting.is_empty():
		var ab: Dictionary = casting["ability"]
		if not abilities_by_id.has(ab["id"]):
			abilities_by_id[own(ab["id"])] = own_value(ab)
		casting = {"ability": abilities_by_id[ab["id"]], "target": own(casting["target"]), "left": casting["left"]}
	else:
		casting = {}
	stats_dealt = own_value(stats_dealt)
	phases = own_value(phases)
	bt_ability = {}


const _SCALARS := ["id", "team", "kind", "sprite_id", "radius", "max_hp", "hp", "atk", "def", "speed", "aggro_range",
	"owner_id", "is_leader", "tier", "taunt_left", "facing", "anim", "moving", "hit_flash", "last_ability", "low_hp_called"]
const _INTS := ["team", "max_hp", "hp", "tier", "taunt_left", "facing", "hit_flash"]


## Full JSON-safe state (F4 snapshots). Abilities are stored inline so a snapshot
## taken before a live tune restores the *pre-tune* numbers exactly.
func to_dict() -> Dictionary:
	var d := {}
	for p in _SCALARS:
		d[p] = get(p)
	d["ref"] = get_meta("ref", "")
	d["pos"] = [pos.x, pos.y]
	d["last_dir"] = [last_dir.x, last_dir.y]
	d["abilities"] = abilities.duplicate(true)
	d["cooldowns"] = cooldowns.duplicate()
	var cast := casting.duplicate(true)
	d["casting"] = cast
	d["stats_dealt"] = stats_dealt.duplicate()
	var mem := {}
	if bt_mem:
		mem["bt_target"] = bt_target
		mem["bt_target_tick"] = bt_target_tick
	d["memory"] = mem
	d["phases"] = phases.duplicate(true)
	d["phase"] = phase
	d["base_atk"] = base_atk
	return d


static func from_dict(d: Dictionary):
	var e = new()
	for p in _SCALARS:
		e.set(p, int(d[p]) if p in _INTS else d[p])
	if str(d.get("ref", "")) != "":
		e.set_meta("ref", d["ref"])
	e.pos = Vector2(float(d["pos"][0]), float(d["pos"][1]))
	e.last_dir = Vector2(float(d["last_dir"][0]), float(d["last_dir"][1]))
	e.abilities = []
	for ab in d["abilities"]:
		e.abilities.append(_norm_ability(ab))
	e.cooldowns = {}
	for k in d["cooldowns"]:
		e.cooldowns[k] = int(d["cooldowns"][k])
	e.casting = {}
	if not d["casting"].is_empty():
		e.casting = {"ability": _norm_ability(d["casting"]["ability"]), "target": str(d["casting"]["target"]),
			"left": int(d["casting"]["left"])}
	e.stats_dealt = {}
	for k in d["stats_dealt"]:
		e.stats_dealt[k] = int(d["stats_dealt"][k])
	e.phase = int(d.get("phase", 0))
	e.base_atk = float(d.get("base_atk", e.atk))
	e.phases = []
	for ph in d.get("phases", []):
		var q: Dictionary = ph.duplicate(true)
		q["abilities"] = q.get("abilities", []).map(func(a): return _norm_ability(a))
		if q.has("summon"):
			q["summon"]["count"] = int(q["summon"]["count"])
			q["summon"]["tier"] = int(q["summon"].get("tier", 1))
			q["summon"]["abilities"] = q["summon"]["abilities"].map(func(a): return _norm_ability(a))
		e.phases.append(q)
	var mem: Dictionary = d.get("memory", {})
	if mem.has("bt_target"):
		e.bt_mem = true
		e.bt_target = str(mem["bt_target"])
		e.bt_target_tick = int(mem.get("bt_target_tick", -999))
	return e


## JSON numbers come back as floats; integer-valued ability fields must stay ints so
## cooldown/windup arithmetic and hashes match the live object.
static func _norm_ability(ab: Dictionary) -> Dictionary:
	var out := ab.duplicate(true)
	for k in out:
		if typeof(out[k]) == TYPE_FLOAT and k in ["cooldown", "windup", "duration"]:
			out[k] = int(out[k])
	return out


func snapshot() -> Dictionary:
	return {"id": id, "hp": hp, "pos": [snappedf(pos.x, 0.01), snappedf(pos.y, 0.01)], "anim": anim}
