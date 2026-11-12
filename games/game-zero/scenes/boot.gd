extends Node
## Boot scene — env gate (F0) then routes to the requested scene.
## User args (after `--`): --scene=<name> (default slice since F7 — a shipped build opens the game),
## --boot-only, --net-report (G-NET-01: print the dormant-network report and quit).

func _ready() -> void:
	print("Game Zero F0 boot OK — AssetFabric env gate")
	if Fabric.flag("net-report"):
		print("FABRIC_RESULT " + JSON.stringify({"net": Fabric.net_report(), "version": ProjectSettings.get_setting("application/config/version")}))
	if Fabric.flag("boot-only") or Fabric.flag("net-report"):
		get_tree().quit(0)
		return
	var scene: String = Fabric.arg("scene", "slice")
	get_tree().change_scene_to_file.call_deferred("res://scenes/%s.tscn" % scene)
