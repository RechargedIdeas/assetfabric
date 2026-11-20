extends RefCounted
## Tile grid from a G1-Tile layout. '#' = wall; '.', 'S', 'E' passable.

var rows: PackedStringArray
var width: int
var height: int
var tile_size: int
var start: Vector2i
var exit: Vector2i
var spawns: Array = []
var _walls := PackedByteArray()
var _apsp := PackedInt32Array()   # all-pairs BFS table: [goal * n + cell] -> steps (-1 unreachable)


## Precompute every walkable goal's distance field into one flat table
## (load-time, ~0.1 ms per walkable cell; ~3 MB for a 40x22 map). Pathing is then
## O(1) and allocation-free, and worker threads can read a private fork().
## Q3: tables are cached per layout (walls never change at runtime), so the F5/F6 Monte Carlo
## workers that rebuild the same encounter per seed pay the BFS once per process, not per fight.
## Packed arrays are copy-on-write: grids share the table read-only. Main thread only (the swap
## advisor warms before its worker threads start).
static var _apsp_cache := {}


func warm_fields() -> int:
	if not _apsp.is_empty():
		return _apsp.size() / (width * height)
	var key := "%d|%d|%s" % [width, height, "\n".join(rows)]
	if _apsp_cache.has(key):
		_apsp = _apsp_cache[key]
		return _apsp.size() / (width * height)
	var walls := wall_mask()
	var n := width * height
	_apsp.resize(n * n)
	_apsp.fill(-1)
	var goals := 0
	for g in n:
		if walls[g] == 0:
			var f := flow_field(Vector2i(g % width, g / width))
			for i in n:
				_apsp[g * n + i] = f[i]
			goals += 1
	_apsp_cache[key] = _apsp
	return goals


func is_warm() -> bool:
	return not _apsp.is_empty()


## Independent copy for a worker thread (no shared containers on the hot path).
func fork():
	var g = get_script().new()
	g.rows = rows
	g.width = width
	g.height = height
	g.tile_size = tile_size
	g.start = start
	g.exit = exit
	g.spawns = spawns.duplicate(true)
	g._walls = wall_mask().duplicate()
	g._apsp = _apsp.duplicate()
	return g


## Next waypoint from `from_pos` toward cell `goal` (downhill on the BFS table).
func step_toward(goal: Vector2i, from_pos: Vector2) -> Vector2:
	if _apsp.is_empty():
		warm_fields()
	var n := width * height
	var c := to_cell(from_pos)
	if c.x < 0 or c.y < 0 or c.x >= width or c.y >= height or goal.x < 0 or goal.y < 0 or goal.x >= width or goal.y >= height:
		return from_pos
	var base := (goal.y * width + goal.x) * n
	var ci := c.y * width + c.x
	var best_d: int = _apsp[base + ci]
	if best_d < 0:
		return from_pos
	var best := ci
	var v: int
	if c.x + 1 < width:
		v = _apsp[base + ci + 1]
		if v >= 0 and v < best_d:
			best = ci + 1
			best_d = v
	if c.x > 0:
		v = _apsp[base + ci - 1]
		if v >= 0 and v < best_d:
			best = ci - 1
			best_d = v
	if c.y + 1 < height:
		v = _apsp[base + ci + width]
		if v >= 0 and v < best_d:
			best = ci + width
			best_d = v
	if c.y > 0:
		v = _apsp[base + ci - width]
		if v >= 0 and v < best_d:
			best = ci - width
			best_d = v
	return center(Vector2i(best % width, best / width))


func wall_mask() -> PackedByteArray:
	if _walls.is_empty():
		_walls.resize(width * height)
		for y in height:
			var row: String = rows[y]
			for x in width:
				_walls[y * width + x] = 1 if row[x] == "#" else 0
	return _walls


static func from_layout(layout: Dictionary):
	var g = new()
	g.rows = PackedStringArray(layout["rows"])
	g.width = int(layout["width"])
	g.height = int(layout["height"])
	g.tile_size = int(layout["tile_size"])
	g.start = Vector2i(int(layout["start"][0]), int(layout["start"][1]))
	g.exit = Vector2i(int(layout["exit"][0]), int(layout["exit"][1]))
	for s in layout.get("spawns", []):
		g.spawns.append(Vector2i(int(s[0]), int(s[1])))
	return g


func cell(c: Vector2i) -> String:
	if c.x < 0 or c.y < 0 or c.x >= width or c.y >= height:
		return "#"
	return rows[c.y][c.x]


func is_wall(c: Vector2i) -> bool:
	if c.x < 0 or c.y < 0 or c.x >= width or c.y >= height:
		return true
	if _walls.is_empty():
		wall_mask()
	return _walls[c.y * width + c.x] == 1


func to_cell(p: Vector2) -> Vector2i:
	return Vector2i(floori(p.x / tile_size), floori(p.y / tile_size))


func center(c: Vector2i) -> Vector2:
	return Vector2((c.x + 0.5) * tile_size, (c.y + 0.5) * tile_size)


## Hot path (every move): wall-mask lookups only — no String or Array allocation.
func blocked_at(p: Vector2, radius: float) -> bool:
	var x0 := floori((p.x - radius) / tile_size)
	var x1 := floori((p.x + radius) / tile_size)
	var y0 := floori((p.y - radius) / tile_size)
	var y1 := floori((p.y + radius) / tile_size)
	if x0 < 0 or y0 < 0 or x1 >= width or y1 >= height:
		return true
	if _walls.is_empty():
		wall_mask()
	return _walls[y0 * width + x0] == 1 or _walls[y0 * width + x1] == 1 \
		or _walls[y1 * width + x0] == 1 or _walls[y1 * width + x1] == 1


## BFS distance field from `goal` as a flat PackedInt32Array (-1 = unreachable).
## Flat arrays instead of Dictionaries: ~10x faster, which the swap advisor's
## forward simulation depends on (<50 ms budget).
func flow_field(goal: Vector2i) -> PackedInt32Array:
	var n := width * height
	var dist := PackedInt32Array()
	dist.resize(n)
	dist.fill(-1)
	if is_wall(goal):
		return dist
	var q := PackedInt32Array()
	q.resize(n)
	var head := 0
	var tail := 0
	var gi := goal.y * width + goal.x
	dist[gi] = 0
	q[tail] = gi
	tail += 1
	var walls := _walls if not _walls.is_empty() else wall_mask()
	while head < tail:
		var ci: int = q[head]
		head += 1
		var cx := ci % width
		var nd: int = dist[ci] + 1
		var ni := ci + 1
		if cx + 1 < width and dist[ni] == -1 and walls[ni] == 0:
			dist[ni] = nd
			q[tail] = ni
			tail += 1
		ni = ci - 1
		if cx > 0 and dist[ni] == -1 and walls[ni] == 0:
			dist[ni] = nd
			q[tail] = ni
			tail += 1
		ni = ci + width
		if ni < n and dist[ni] == -1 and walls[ni] == 0:
			dist[ni] = nd
			q[tail] = ni
			tail += 1
		ni = ci - width
		if ni >= 0 and dist[ni] == -1 and walls[ni] == 0:
			dist[ni] = nd
			q[tail] = ni
			tail += 1
	return dist


## Next waypoint (world position) from `from_pos` toward the field's goal.
func next_step(field: PackedInt32Array, from_pos: Vector2) -> Vector2:
	var c := to_cell(from_pos)
	if c.x < 0 or c.y < 0 or c.x >= width or c.y >= height:
		return from_pos
	var ci := c.y * width + c.x
	if field[ci] < 0:
		return from_pos
	var best := ci
	var best_d: int = field[ci]
	if c.x + 1 < width and field[ci + 1] >= 0 and field[ci + 1] < best_d:
		best = ci + 1
		best_d = field[best]
	if c.x > 0 and field[ci - 1] >= 0 and field[ci - 1] < best_d:
		best = ci - 1
		best_d = field[best]
	if c.y + 1 < height and field[ci + width] >= 0 and field[ci + width] < best_d:
		best = ci + width
		best_d = field[best]
	if c.y > 0 and field[ci - width] >= 0 and field[ci - width] < best_d:
		best = ci - width
		best_d = field[best]
	return center(Vector2i(best % width, best / width))


## Dictionary view of a flow field (cell -> distance) for non-hot callers.
func field_dict(goal: Vector2i) -> Dictionary:
	var f := flow_field(goal)
	var out := {}
	for i in f.size():
		if f[i] >= 0:
			out[Vector2i(i % width, i / width)] = f[i]
	return out
