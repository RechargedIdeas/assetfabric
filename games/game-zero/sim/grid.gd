extends RefCounted
## Tile grid from a G1-Tile layout. '#' = wall; '.', 'S', 'E' passable.

var rows: PackedStringArray
var width: int
var height: int
var tile_size: int
var start: Vector2i
var exit: Vector2i
var spawns: Array = []


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
	return cell(c) == "#"


func to_cell(p: Vector2) -> Vector2i:
	return Vector2i(floori(p.x / tile_size), floori(p.y / tile_size))


func center(c: Vector2i) -> Vector2:
	return Vector2((c.x + 0.5) * tile_size, (c.y + 0.5) * tile_size)


func blocked_at(p: Vector2, radius: float) -> bool:
	for off in [Vector2(-radius, -radius), Vector2(radius, -radius), Vector2(-radius, radius), Vector2(radius, radius)]:
		if is_wall(to_cell(p + off)):
			return true
	return false


## BFS distance field from `goal` (deterministic neighbour order).
func flow_field(goal: Vector2i) -> Dictionary:
	var dist := {goal: 0}
	var q: Array[Vector2i] = [goal]
	var head := 0
	while head < q.size():
		var c: Vector2i = q[head]
		head += 1
		for d in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			var n: Vector2i = c + d
			if not dist.has(n) and not is_wall(n):
				dist[n] = dist[c] + 1
				q.append(n)
	return dist


## Next waypoint (world position) from `from_pos` toward the field's goal.
func next_step(field: Dictionary, from_pos: Vector2) -> Vector2:
	var c := to_cell(from_pos)
	if not field.has(c):
		return from_pos
	var best := c
	var best_d: int = field[c]
	for d in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
		var n: Vector2i = c + d
		if field.has(n) and field[n] < best_d:
			best = n
			best_d = field[n]
	return center(best)
