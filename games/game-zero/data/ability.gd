class_name FabricAbility
extends Resource
## Ability resource emitted by AssetFabric codegen (data/generated/abilities/*.tres).

@export var id: String
@export var kind: String          # melee | ranged | aoe | heal | taunt
@export var target: String        # enemy | ally | self
@export var power: float
@export var range: float
@export var radius: float
@export var cooldown: int
@export var windup: int
@export var duration: int
@export var threshold: float
@export var name_key: String


func to_dict() -> Dictionary:
	return {"id": id, "type": kind, "target": target, "power": power, "range": range, "radius": radius,
		"cooldown": cooldown, "windup": windup, "duration": duration, "threshold": threshold}
