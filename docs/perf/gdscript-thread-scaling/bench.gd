extends SceneTree
const Ent = preload("res://ent.gd")
var sets := []
func typed(i: int) -> void:
	var es: Array = sets[i]
	var s := 0
	for k in 20000:
		for e: Ent in es:
			s += e.hp
func untyped(i: int) -> void:
	var es: Array = sets[i]
	var s := 0
	for k in 20000:
		for e in es:
			s += e.hp
func calls(i: int) -> void:
	var es: Array = sets[i]
	var s := 0
	for k in 20000:
		for e in es:
			s += e.get_hp()
func newdict(i: int) -> void:
	var s := 0
	for k in 100000:
		var d := {"a": k, "b": 2}
		var a := [k, 1, 2]
		s += d.size() + a.size()
func run(cb: Callable, label: String) -> void:
	var t := Time.get_ticks_usec()
	for i in 4: cb.call(i)
	var ser := Time.get_ticks_usec() - t
	t = Time.get_ticks_usec()
	var g := WorkerThreadPool.add_group_task(cb, 4, 4)
	WorkerThreadPool.wait_for_group_task_completion(g)
	var thr := Time.get_ticks_usec() - t
	print(label, " ser=", ser/1000, "ms thr=", thr/1000, "ms speedup=", float(ser)/thr)
func _init() -> void:
	for i in 4:
		var es := []
		for j in 15: es.append(Ent.new())
		sets.append(es)
	run(typed, "typed-loop")
	run(untyped, "untyped-loop")
	run(calls, "method-calls")
	run(newdict, "alloc-dict-array")
	quit()
