# Slim down the HaloByte assistant GLB: decimate with the screen region
# protected (the face overlay submesh must keep matching the main surface),
# plus 1024 textures.
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=r"C:\Users\阿木\Downloads\Meshy_AI_HaloByte_1025091710_texture.glb")
ob = bpy.data.objects['Mesh_0']
mesh = ob.data
uvl = mesh.uv_layers[0]
img = bpy.data.images['Image_0']
W, H = img.size
px = list(img.pixels)
mw = ob.matrix_world
nmat = mw.inverted().transposed().to_3x3()


def sample(u, v):
    x = min(W - 1, int(u * W))
    y = min(H - 1, int(v * H))
    i = (y * W + x) * 4
    return px[i], px[i + 1], px[i + 2]


print('BEFORE verts', len(mesh.vertices), 'tris', sum(len(p.vertices) - 2 for p in mesh.polygons))

# Screen faces (same criteria as export_screen_mesh.py).
screen_faces = set()
for poly in mesh.polygons:
    n_world = (nmat @ poly.normal).normalized()
    if n_world.y > -0.18:
        continue
    center = mw @ poly.center
    if center.z < -0.10 or center.z > 0.34 or center.y > -0.10 or abs(center.x) > 0.34:
        continue
    uvs = [uvl.data[li].uv for li in poly.loop_indices]
    samples = [sample(u, v) for u, v in uvs]
    lum = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in samples) / len(samples)
    is_eye = sum(1 for r, g, b in samples if b > r + 0.08 and g > r + 0.08) > len(samples) * 0.5
    if lum > 0.30 and not is_eye:
        continue
    screen_faces.add(poly.index)

group = ob.vertex_groups.new(name='NoDecimate')
protected = set()
for poly in mesh.polygons:
    if poly.index in screen_faces:
        protected.update(poly.vertices)
group.add(list(protected), 0.0, 'REPLACE')  # weight 0 = protected from decimation
others = [v.index for v in mesh.vertices if v.index not in protected]
group.add(others, 1.0, 'REPLACE')
print('SCREEN faces', len(screen_faces), 'protected verts', len(protected))

dec = ob.modifiers.new('Decimate', 'DECIMATE')
dec.ratio = 0.45
pass  # vertex_group alone activates per-vertex weights
dec.vertex_group = 'NoDecimate'
bpy.context.view_layer.objects.active = ob
bpy.ops.object.modifier_apply(modifier='Decimate')
print('AFTER verts', len(mesh.vertices), 'tris', sum(len(p.vertices) - 2 for p in mesh.polygons))

for img in bpy.data.images:
    if img.size[0] > 1024:
        img.scale(1024, 1024)
        print('resized', img.name, img.size[:])

bpy.ops.object.select_all(action='DESELECT')
ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=r"D:\MyPro\Cortexa\tools\robot\halobyte-slim-raw.glb",
                          export_format='GLB', use_selection=True, export_apply=True)
print('EXPORT_OK')
