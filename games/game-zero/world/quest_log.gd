extends RefCounted
## Quest state machines (F6). The quests compiled by Codegen-World are one parallel statechart
## (one region per quest) run by the F4 StateChart runtime; guards read world counters.
## Guard language (twin of forge/world.py `eval_guard`):
##   have:<item>>=n · total:<counter>>=n · flag:<name>, joined with "&".

const StateChart = preload("res://sim/statechart.gd")
const DONE := "done"

var world: Dictionary
var chart
var counters := {"have": {}, "total": {}, "flag": {}}
var trace: Array = []      # [{tick, event, taken, counters}] — replayed by forge for parity


func _init(world_: Dictionary, active: Dictionary = {}) -> void:
	world = world_
	chart = StateChart.new(world["quest_chart"], _guard)
	for r in active:
		if chart.active.has(r):
			chart.active[r] = str(active[r])


func _guard(expr: String, _region: String, _state: String) -> bool:
	return eval_guard(expr, counters)


static func eval_guard(expr: String, c: Dictionary) -> bool:
	if expr == "":
		return true
	for part in expr.split("&"):
		var p := part.strip_edges()
		var kind := p.get_slice(":", 0)
		var rest := p.substr(kind.length() + 1)
		if kind == "flag":
			if not bool(c.get("flag", {}).get(rest, false)):
				return false
			continue
		var name := rest.get_slice(">=", 0)
		var n := float(rest.get_slice(">=", 1)) if rest.contains(">=") else 1.0
		if float(c.get(kind, {}).get(name, 0)) < n:
			return false
	return true


## Offer a world event; returns the transitions taken (each completes one stage).
func send(event: String, tick: int) -> Array:
	chart.tick = tick
	var taken: Array = chart.send(event)
	if not taken.is_empty():
		trace.append({"tick": tick, "event": event, "taken": taken.map(func(t): return [t["region"], t["from"], t["to"]]),
			"counters": counters.duplicate(true)})
	return taken


func stage(quest: String) -> String:
	return str(chart.active.get(quest, ""))


func stage_index(quest: String, st: String = "") -> int:
	var s := st if st != "" else stage(quest)
	for q in world["quests"]:
		if q["id"] == quest:
			var ids: Array = q["stages"].map(func(x): return str(x["id"]))
			ids.append(DONE)
			return ids.find(s)
	return -1


## Stage definition by id (reward lookup).
func stage_def(quest: String, st: String) -> Dictionary:
	for q in world["quests"]:
		if q["id"] == quest:
			for x in q["stages"]:
				if x["id"] == st:
					return x
	return {}


func done(quest: String) -> bool:
	return stage(quest) == DONE


func active() -> Dictionary:
	return chart.active.duplicate()
