extends Node
## Adaptive music director (F6; GAME_SPEC §7 "audio stems remixable by macro state").
## One AudioStreamPlayer per G1-Audio stem of the current biome track. All stems of a track have
## the same loop length (G1-Audio `duration` gate), so they start together and only the volumes
## move: each tick every stem eases toward the macro state's target (rules: data/generated/world.json
## `music`) over `fade_ticks`. A biome change crossfades the old set out and the new one in.
## Headless runs keep the same logic (players exist, nothing is audible) and log every transition.

const SILENT := -80.0

var rules: Dictionary = {}
var biome := ""
var state := ""
var players := {}            # stem -> AudioStreamPlayer (current biome)
var _fading := []            # players of the previous biome fading out
var trace: Array = []        # [{tick, biome, state, layers}]
var audible := true


func setup(rules_: Dictionary) -> void:
	rules = rules_
	audible = DisplayServer.get_name() != "headless"


func _track(b: String) -> String:
	return str(rules["biomes"].get(b, {}).get("track", ""))


func set_biome(b: String, tick: int) -> void:
	if b == biome:
		return
	for st in players:
		_fading.append(players[st])
	players = {}
	biome = b
	var track := _track(b)
	for stem in ["ambient", "tension", "combat", "boss"]:
		var stream: AudioStreamWAV = Fabric.audio(track, "%s_%s.wav" % [track, stem])
		if stream == null:
			continue
		stream.loop_mode = AudioStreamWAV.LOOP_FORWARD
		stream.loop_end = stream.data.size() / 2
		var p := AudioStreamPlayer.new()
		p.stream = stream
		p.volume_db = SILENT
		add_child(p)
		if audible:
			p.play()
		players[stem] = p
	var s := state
	state = ""
	set_state(s if s != "" else "explore", tick)


func set_state(s: String, tick: int) -> void:
	if not LiveOps.enabled("adaptive_music"):
		s = "explore"      # F9 kill switch — music stays on the exploration mix
	if s == state:
		return
	state = s
	trace.append({"tick": tick, "biome": biome, "state": s, "layers": layers()})


## Stems that are (or are fading toward) audible in the current state.
func layers() -> Array:
	var want: Dictionary = rules["states"].get(state, {})
	var out := []
	for stem in want:
		if players.has(stem) and float(want[stem]) > -60.0:
			out.append(stem)
	out.sort()
	return out


func target_db(stem: String) -> float:
	return float(rules["states"].get(state, {}).get(stem, SILENT))


## Advance fades by one 60 Hz tick.
func step() -> void:
	var fade := maxf(1.0, float(rules.get("fade_ticks", 45)))
	var rate := (0.0 - SILENT) / fade
	for stem in players:
		var p: AudioStreamPlayer = players[stem]
		p.volume_db = move_toward(p.volume_db, target_db(stem), rate)
	for p in _fading.duplicate():
		p.volume_db = move_toward(p.volume_db, SILENT, rate)
		if p.volume_db <= SILENT:
			_fading.erase(p)
			p.queue_free()


func volumes() -> Dictionary:
	var out := {}
	for stem in players:
		out[stem] = snappedf(players[stem].volume_db, 0.1)
	return out
