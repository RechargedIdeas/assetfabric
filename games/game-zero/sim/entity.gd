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
	for prop in ["id", "team", "kind", "sprite_id", "pos", "radius", "max_hp", "hp", "atk", "def", "speed", "aggro_range",
			"owner_id", "is_leader", "tier", "taunt_left", "facing", "anim", "moving", "hit_flash", "last_ability"]:
		c.set(prop, get(prop))
	c.abilities = abilities
	c.cooldowns = cooldowns.duplicate()
	c.casting = casting.duplicate()
	c.stats_dealt = stats_dealt.duplicate()
	c.low_hp_called = low_hp_called
	c.last_dir = last_dir
	for m in ["bt_target", "bt_target_tick"]:   # brain memory (ids/ints only, never object refs)
		if has_meta(m):
			c.set_meta(m, get_meta(m))
	return c


func snapshot() -> Dictionary:
	return {"id": id, "hp": hp, "pos": [snappedf(pos.x, 0.01), snappedf(pos.y, 0.01)], "anim": anim}
