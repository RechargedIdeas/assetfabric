extends RefCounted
## Parallel statechart runtime (F4; SPEC §6.3 "parallel statecharts").
## Subset of SCXML semantics, mirrored exactly by `forge/statechart.py` (which also
## does static soft-lock analysis of the same JSON at build time):
##   chart  = {"id", "regions": {name: machine}}         regions run concurrently
##   machine = {"initial": s, "states": {s: {"on": {event: target | {"target", "guard"}}, "final": bool}}}
## `send(event)` offers the event to every region in sorted-name order; each region takes
## its first matching transition whose guard passes. Guards are named; the host supplies
## `guard_fn(name, region, state) -> bool`. Deterministic; no allocation per tick beyond the trace.

var id: String
var regions: Dictionary = {}     # name -> machine
var active: Dictionary = {}      # name -> state
var trace: Array = []            # [{tick, region, from, to, event}]
var events: Array = []           # every event offered, in order (parity replay in forge/statechart.py)
var guard_fn: Callable
var tick := 0
var _order: Array = []


func _init(chart: Dictionary, guard: Callable = Callable()) -> void:
	id = str(chart.get("id", "chart"))
	regions = chart["regions"]
	guard_fn = guard
	_order = regions.keys()
	_order.sort()
	for r in _order:
		active[r] = str(regions[r]["initial"])


func send(event: String) -> Array:
	events.append(event)
	var taken := []
	for r in _order:
		var cur: String = active[r]
		var st: Dictionary = regions[r]["states"].get(cur, {})
		var on: Dictionary = st.get("on", {})
		if not on.has(event):
			continue
		var tr = on[event]
		var target: String
		var guard := ""
		if typeof(tr) == TYPE_DICTIONARY:
			target = str(tr["target"])
			guard = str(tr.get("guard", ""))
		else:
			target = str(tr)
		if guard != "" and not (guard_fn.is_valid() and guard_fn.call(guard, r, cur)):
			continue
		active[r] = target
		var rec := {"tick": tick, "region": r, "from": cur, "to": target, "event": event}
		trace.append(rec)
		taken.append(rec)
	return taken


func state(region: String) -> String:
	return active.get(region, "")


func in_state(region: String, s: String) -> bool:
	return active.get(region, "") == s


func is_final(region: String) -> bool:
	return bool(regions[region]["states"].get(active[region], {}).get("final", false))


func done() -> bool:
	for r in _order:
		if not is_final(r):
			return false
	return true


func to_dict() -> Dictionary:
	return {"id": id, "active": active.duplicate(), "tick": tick}


func restore(d: Dictionary) -> void:
	for r in d["active"]:
		active[r] = str(d["active"][r])
	tick = int(d.get("tick", 0))
