extends Node
## CascadeHub — typed multi-agent message bus (F3).
## Agents (fighters, pets, enemies, player, director) publish typed messages;
## subscribers are invoked when the hub is drained *after* a sim tick, so nothing
## here sits on the combat tick's critical path (GAME_SPEC §4.3, SPEC Layer C).

const TYPES := ["intent", "callout_request", "callout", "dialogue_request", "dialogue", "telemetry"]

var _queue: Array = []
var _subs: Dictionary = {}
var log_: Array = []
var counts := {}


func publish(type: String, from: String, payload: Dictionary = {}, to: String = "*") -> bool:
	if not TYPES.has(type):
		push_error("CascadeHub: unknown message type %s" % type)
		return false
	_queue.append({"type": type, "from": from, "to": to, "payload": payload})
	return true


func subscribe(type: String, fn: Callable) -> void:
	if not _subs.has(type):
		_subs[type] = []
	_subs[type].append(fn)


func drain(tick: int) -> int:
	var n := 0
	while not _queue.is_empty():
		var batch := _queue
		_queue = []
		for m in batch:
			m["tick"] = tick
			counts[m["type"]] = int(counts.get(m["type"], 0)) + 1
			if log_.size() < 2000:
				log_.append(m)
			for fn in _subs.get(m["type"], []):
				if fn.is_valid():
					fn.call(m)
			n += 1
	return n


func reset() -> void:
	_queue.clear()
	_subs.clear()
	log_.clear()
	counts.clear()
