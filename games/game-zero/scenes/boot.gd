extends Node
## Boot scene — env gate (F0) then routes to the requested scene.
## User args (after `--`): --scene=<name> (default sandbox), --boot-only.

func _ready() -> void:
	print("Game Zero F0 boot OK — AssetFabric env gate")
	if Fabric.flag("boot-only"):
		get_tree().quit(0)
		return
	var scene: String = Fabric.arg("scene", "sandbox")
	get_tree().change_scene_to_file.call_deferred("res://scenes/%s.tscn" % scene)
