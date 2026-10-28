# Export the HaloByte screen surface as a separate GLB with clean UVs.
# The runtime overlays this submesh on the baked model and paints the dynamic
# pixel face onto it (u,v normalized over the screen plane, v=0 at top).
import bpy
import bmesh
import json
from mathutils import Vector

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=r"D:\MyPro\Cortexa\tools\robot\halobyte-slim-raw.glb")
ob = bpy.data.objects['Mesh_0']
mesh = ob.data
uvl = mesh.uv_layers[0]
img = bpy.data.images['Image_0']
W, H = img.size
px = list(img.pixels)


def sample(u, v):
    x = min(W - 1, int(u * W))
    y = min(H - 1, int(v * H))
    i = (y * W + x) * 4
    return px[i], px[i + 1], px[i + 2]


mw = ob.matrix_world
nmat = mw.inverted().transposed().to_3x3()

sel = []
cent3 = {}
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
    sel.append(poly.index)
    cent3[poly.index] = (center.x, center.z)

xs = [c[0] for c in cent3.values()]
zs = [c[1] for c in cent3.values()]
xmin, xmax, zmin, zmax = min(xs), max(xs), min(zs), max(zs)
print('SCREEN x', round(xmin, 3), round(xmax, 3), 'z', round(zmin, 3), round(zmax, 3), 'faces', len(sel))

poly_uv = {i: ((cent3[i][0] - xmin) / (xmax - xmin), (zmax - cent3[i][1]) / (zmax - zmin)) for i in sel}

# Build the submesh: copy selected faces, per-vertex uv = mean of adjacent poly uvs.
bm = bmesh.new()
bm.from_mesh(mesh)
bm.normal_update()  # bmesh normals are zeroed until recalculated — the LIFT needs them
new_bm = bmesh.new()
verts_map = {}
uv_layer = new_bm.loops.layers.uv.new('UVMap')
sel_set = set(sel)
LIFT = 0.0  # screen region is protected from decimation — overlay aligns exactly
for face in bm.faces:
    if face.index not in sel_set:
        continue
    vs = []
    for loop in face.loops:
        v = loop.vert
        if v.index not in verts_map:
            adj = []
            for f in v.link_faces:
                if f.index in poly_uv:
                    adj.append(poly_uv[f.index])
            if adj:
                u = sum(a[0] for a in adj) / len(adj)
                w = sum(a[1] for a in adj) / len(adj)
            else:
                u, w = poly_uv[face.index]
            nv = new_bm.verts.new(v.co.copy() + v.normal * LIFT)
            verts_map[v.index] = (nv, u, w)
        vs.append(verts_map[v.index])
    try:
        nf = new_bm.faces.new([t[0] for t in vs])
        for loop, t in zip(nf.loops, vs):
            loop[uv_layer].uv = (t[1], t[2])
    except ValueError:
        pass

new_mesh = bpy.data.meshes.new('RobotScreenSurface')
new_bm.to_mesh(new_mesh)
new_bm.free()
sob = bpy.data.objects.new('RobotScreenSurface', new_mesh)
bpy.context.scene.collection.objects.link(sob)
print('SUBMESH verts', len(new_mesh.vertices), 'polys', len(new_mesh.polygons))

# Sanity render: checker UV via a quick material won't matter — just export.
bpy.ops.object.select_all(action='DESELECT')
sob.select_set(True)
bpy.ops.export_scene.gltf(filepath=r"D:\MyPro\Cortexa\tools\robot\halobyte-screen.glb",
                          export_format='GLB', use_selection=True, export_apply=True)
print('EXPORT_OK')
