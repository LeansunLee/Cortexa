# Delete the protruding 3D glass-eye geometry from the HaloByte mesh.
# The baked "eyes" turned out to be actual face clusters bulging out of the
# screen (z > 0.36, front y < -0.15) — texture erases could never hide them.
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=r"D:\MyPro\Cortexa\tools\robot\halobyte-slim-raw.glb")
ob = bpy.data.objects['Mesh_0']
mesh = ob.data
mw = ob.matrix_world

targets = []
nmat = mw.inverted().transposed().to_3x3()
for poly in mesh.polygons:
    c = mw @ poly.center
    n = (nmat @ poly.normal).normalized()
    # The glass eyes bulge FORWARD (normal.y < -0.6) past the screen bulge
    # (z > 0.36). The helmet dome at the same heights points UP (normal.y ~ 0).
    if c.z > 0.36 and n.y < -0.6:
        targets.append(poly.index)
print('EYE faces', len(targets))

import bmesh
bm = bmesh.new()
bm.from_mesh(mesh)
bm.faces.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.faces[i] for i in targets], context='FACES')
bm.to_mesh(mesh)
bm.free()
mesh.update()
print('AFTER tris', sum(len(p.vertices) - 2 for p in mesh.polygons))

bpy.ops.object.select_all(action='DESELECT')
ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=r"D:\MyPro\Cortexa\tools\robot\halobyte-slim-raw.glb",
                          export_format='GLB', use_selection=True, export_apply=True)
print('EXPORT_OK')
