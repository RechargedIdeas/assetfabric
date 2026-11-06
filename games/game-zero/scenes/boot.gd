extends Node
## F0 boot scene — proves the empty project loads.
## No gameplay yet. F1 adds sandbox encounter content via Fabric generators.

func _ready() -> void:
	print("Game Zero F0 boot OK — AssetFabric env gate")
	# Locale keys only — no hard-coded user-facing strings in production paths.
	# Display string deferred to F1 UI with locale tables.
