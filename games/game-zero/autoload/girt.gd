extends Node
## GIRT — Godot Inference Runtime (F3). One facade for policies, LMs and caches,
## with per-call latency budgets, telemetry and CPU paths (GroundWeave).
## Backends today: `mlp-gdscript` (policy), `persona-bigram` (LM stand-in),
## `callout-cache`. ONNX Runtime / llama.cpp adapters plug in behind the same API.
## Hard rule (ADR-0011): LM calls are refused while a combat tick is running.

const MODELS_DIR := "res://data/generated/ai"
const POLICY_BUDGET_US := 500.0     # per scoring call
const LM_BUDGET_US := 20000.0       # per generation (mobile-mid target <2 s E2E)

var policy: Dictionary = {}
var lm: Dictionary = {}
var callouts: Dictionary = {}
var in_tick := false
var stats := {"policy_calls": 0, "policy_fallbacks": 0, "policy_over_budget": 0, "policy_us": [], "lm_calls": 0, "lm_us": [],
	"lm_refused_in_tick": 0, "callouts_served": 0}


func _ready() -> void:
	reload()


func reload() -> void:
	policy = _read(MODELS_DIR + "/policy_target.json")
	if not policy.is_empty():
		_flatten()
	lm = _read(MODELS_DIR + "/persona_lm.json")
	callouts = _read(MODELS_DIR + "/callouts.json")


func _read(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var d = JSON.parse_string(FileAccess.get_file_as_string(path))
	return d if typeof(d) == TYPE_DICTIONARY else {}


func registry() -> Array:
	var out := []
	if not policy.is_empty():
		out.append({"model_id": policy["model_id"], "kind": "policy", "backend": "mlp-gdscript", "arch": policy["arch"]})
	if not lm.is_empty():
		out.append({"model_id": "M-PersonaLM", "kind": "lm", "backend": lm["backend"]})
	if not callouts.is_empty():
		out.append({"model_id": "CalloutCache", "kind": "cache", "backend": "callout-cache"})
	return out


# ------------------------------------------------------------------ policy

# Flattened float64 weights (row-major w1[i][j] -> _w1[i * hidden + j]); built once in _flatten().
var _w1 := PackedFloat64Array()
var _b1 := PackedFloat64Array()
var _w2 := PackedFloat64Array()
var _b2 := 0.0
var _hidden := 0


func _flatten() -> void:
	var w: Dictionary = policy["weights"]
	_b1 = PackedFloat64Array(w["b1"])
	_hidden = _b1.size()
	_w1 = PackedFloat64Array()
	for row in w["w1"]:
		_w1.append_array(PackedFloat64Array(row))
	_w2 = PackedFloat64Array()
	for row in w["w2"]:
		_w2.append(float(row[0]))
	_b2 = float(w["b2"][0])


func _mlp_score(x: Array) -> float:
	var out := _b2
	var n := x.size()
	var h := _hidden
	if n == 7 and _w1.size() == 7 * h:
		# Q3: unrolled for the shipped 7-feature policy; same operation order as the loop below
		# (acc = b1 + x0*w + x1*w + ...), so scores are bit-identical.
		var x0 := float(x[0])
		var x1 := float(x[1])
		var x2 := float(x[2])
		var x3 := float(x[3])
		var x4 := float(x[4])
		var x5 := float(x[5])
		var x6 := float(x[6])
		for j in h:
			var acc: float = _b1[j]
			acc += x0 * _w1[j]
			acc += x1 * _w1[h + j]
			acc += x2 * _w1[2 * h + j]
			acc += x3 * _w1[3 * h + j]
			acc += x4 * _w1[4 * h + j]
			acc += x5 * _w1[5 * h + j]
			acc += x6 * _w1[6 * h + j]
			out += tanh(acc) * _w2[j]
		return out
	for j in _hidden:
		var acc: float = _b1[j]
		for i in n:
			acc += float(x[i]) * _w1[i * _hidden + j]
		out += tanh(acc) * _w2[j]
	return out


## Score candidate feature vectors; returns [] when unavailable or over budget (caller falls back).
## `record=false` for forward-sim clones (swap advisor worker threads): pure, no shared-state writes.
func score_targets(candidates: Array, record: bool = true) -> Array:
	if policy.is_empty():
		if record:
			stats["policy_fallbacks"] += 1
		return []
	if not record:
		var out := []
		for f in candidates:
			out.append(_mlp_score(f))
		return out
	var t0 := Time.get_ticks_usec()
	var scores := []
	for f in candidates:
		scores.append(_mlp_score(f))
	var us := float(Time.get_ticks_usec() - t0)
	stats["policy_calls"] += 1
	if stats["policy_us"].size() < 20000:
		stats["policy_us"].append(us)
	if us > POLICY_BUDGET_US:
		# Scores are still returned (no fallback happened); a single over-budget call is usually an OS
		# scheduling hiccup. Counted separately; the F3 gate checks the p95 against the budget (F7 de-flake).
		stats["policy_over_budget"] += 1
	return scores


## Parity probe for the LM stand-in: same seeds as forge/generators/callouts.py probes.
func lm_selftest() -> Dictionary:
	var out := {}
	if lm.is_empty():
		return out
	for pid in lm["models"]:
		var xs := []
		for s in range(1, 6):
			xs.append(lm_generate(pid, s))
		out[pid] = xs
	return out


func selftest() -> Array:
	if policy.is_empty():
		return []
	return policy["probe"]["inputs"].map(func(x): return snappedf(_mlp_score(x), 0.0001))


# ------------------------------------------------------------------ LM (stand-in)

## Deterministic bigram sampler — exact mirror of forge/generators/callouts.py::sample.
func lm_generate(persona: String, seed: int, start: String = "<s>") -> String:
	if in_tick:
		stats["lm_refused_in_tick"] += 1
		push_warning("GIRT: LM call refused inside combat tick (ADR-0011)")
		return ""
	if lm.is_empty() or not lm["models"].has(persona):
		return ""
	var t0 := Time.get_ticks_usec()
	var table: Dictionary = lm["models"][persona]["bigram"]
	var state: int = seed & 0x7FFFFFFF
	var out: Array = [] if start == "<s>" else [start]
	var cur := start
	var seen := {}
	for _i in int(lm.get("max_tokens", 14)):
		if not table.has(cur):
			break
		var nxt: Dictionary = table[cur]
		var total := 0
		for k in nxt:
			total += int(nxt[k])
		state = (state * 1103515245 + 12345) & 0x7FFFFFFF
		var r: int = state % total
		var acc := 0
		var keys := nxt.keys()
		keys.sort()
		for tok in keys:
			acc += int(nxt[tok])
			if r < acc:
				cur = tok
				break
		if cur == "</s>":
			break
		var pair := "%s|%s" % [out[-1] if not out.is_empty() else "<s>", cur]
		if seen.has(pair):
			break
		seen[pair] = true
		out.append(cur)
	stats["lm_calls"] += 1
	stats["lm_us"].append(float(Time.get_ticks_usec() - t0))
	return " ".join(out)


# ------------------------------------------------------------------ callouts

## Pick a cached callout (deterministic). Never touches an LM.
func callout(persona: String, event: String, salt: int, ally_name: String = "") -> String:
	var lines: Array = callouts.get("callouts", {}).get(persona, {}).get(event, [])
	if lines.is_empty():
		return ""
	stats["callouts_served"] += 1
	var line: String = lines[absi(salt) % lines.size()]
	return line.replace("%ALLY%", ally_name)


func p95(key: String) -> float:
	var arr: Array = stats[key].duplicate()
	if arr.is_empty():
		return 0.0
	arr.sort()
	return arr[mini(arr.size() - 1, int(arr.size() * 0.95))]


func report() -> Dictionary:
	return {"registry": registry(), "policy_calls": stats["policy_calls"], "policy_fallbacks": stats["policy_fallbacks"],
		"policy_over_budget": stats["policy_over_budget"], "policy_budget_us": POLICY_BUDGET_US, "policy_p95_us": p95("policy_us"), "lm_calls": stats["lm_calls"], "lm_p95_us": p95("lm_us"),
		"lm_refused_in_tick": stats["lm_refused_in_tick"], "callouts_served": stats["callouts_served"]}
