# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary.
# Headless glTF load check for forge.universal.native.godot_load_glb (prints one AF_GODOT JSON line).
extends SceneTree
func _initialize():
	var args = OS.get_cmdline_user_args()
	var doc = GLTFDocument.new()
	var st = GLTFState.new()
	var err = doc.append_from_file(args[0], st)
	var out = {"err": err}
	if err == OK:
		var root = doc.generate_scene(st)
		var meshes = 0
		var verts = 0
		var skins = 0
		var stack = [root]
		while stack.size() > 0:
			var n = stack.pop_back()
			for c in n.get_children():
				stack.append(c)
			if n is MeshInstance3D and n.mesh:
				meshes += 1
				for s in range(n.mesh.get_surface_count()):
					verts += n.mesh.surface_get_arrays(s)[Mesh.ARRAY_VERTEX].size()
				if n.skin:
					skins += 1
		out["meshes"] = meshes
		out["vertices"] = verts
		out["skins"] = skins
		out["materials"] = st.get_materials().size()
		out["images"] = st.get_images().size()
		root.free()
	print("AF_GODOT " + JSON.stringify(out))
	quit()
