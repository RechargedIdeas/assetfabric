extends RefCounted
## Deterministic combat entity. Stats come from data (F2 codegen), not code.

var id: String
var team: int            # 0 = player party, 1 = hostile
var sprite_id: String
var pos: Vector2
var radius: float = 5.0
var max_hp: int = 10
var hp: int = 10
var atk: int = 1
var def: int = 0
var speed: float = 1.0   # px per tick @ 60 Hz
var attack_range: float = 18.0
var attack_cooldown: int = 30
var attack_windup: int = 6
var aggro_range: float = 96.0
var cooldown_left: int = 0
var windup_left: int = 0
var facing: int = 1      # +1 right, -1 left
var anim: String = "idle"
var moving: bool = false
var hit_flash: int = 0
var kills: int = 0


static func from_stats(id_: String, team_: int, sprite: String, stats: Dictionary, at: Vector2):
	var e = new()
	e.id = id_
	e.team = team_
	e.sprite_id = sprite
	e.pos = at
	e.max_hp = int(stats.get("hp", 10))
	e.hp = e.max_hp
	e.atk = int(stats.get("atk", 1))
	e.def = int(stats.get("def", 0))
	e.speed = float(stats.get("speed", 1.0))
	e.attack_range = float(stats.get("range", 18.0))
	e.attack_cooldown = int(stats.get("cooldown", 30))
	e.attack_windup = int(stats.get("windup", 6))
	e.aggro_range = float(stats.get("aggro", 96.0))
	return e


func alive() -> bool:
	return hp > 0


func snapshot() -> Dictionary:
	return {"id": id, "hp": hp, "pos": [snappedf(pos.x, 0.01), snappedf(pos.y, 0.01)], "anim": anim}
