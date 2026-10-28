# Erase the baked eyes from the HaloByte atlas: paint the whole screen region
# (same selection criteria as the overlay export) with the dark screen color.
# After this the dynamic face plate no longer needs to cover anything.
import bpy
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
from mathutils import Vector

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=r"D:\MyPro\Cortexa\tools\robot\halobyte-slim-raw.glb")
ob = bpy.data.objects['Mesh_0']
mesh = ob.data
uvl = mesh.uv_layers[0]
mat = bpy.data.materials[0]
# Identify the base-color image by material wiring (names change across exports).
base_img = None
for node in mat.node_tree.nodes:
    if node.type == 'BSDF_PRINCIPLED' and node.inputs['Base Color'].is_linked:
        for link in node.inputs['Base Color'].links:
            if link.from_node.type == 'TEX_IMAGE' and link.from_node.image:
                base_img = link.from_node.image
if base_img is None:
    raise RuntimeError('base color image not found')
print('BASE image:', base_img.name)
img = base_img
W, H = img.size
px = list(img.pixels)
mw = ob.matrix_world
nmat = mw.inverted().transposed().to_3x3()


def sample(u, v):
    x = min(W - 1, int(u * W))
    y = min(H - 1, int(v * H))
    i = (y * W + x) * 4
    return px[i], px[i + 1], px[i + 2]


sel = []
for poly in mesh.polygons:
    # Position box only: the screen's lower lip tilts its normals past any
    # fixed threshold, which used to leave glossy eye-relief arcs behind.
    center = mw @ poly.center
    if center.z < -0.20 or center.z > 0.37 or center.y > -0.02 or abs(center.x) > 0.36:
        continue
    sel.append(poly.index)
print('SCREEN faces', len(sel))

# Paint the whole baked expression PURE BLACK (user request): uniform screen,
# no gradient or erase-patch shading. The third map is the EMISSION map (the
# glowing eyes were baked there, not in base color!) — paint it black too.
ERASE = (0.0, 0.0, 0.0)
NORMAL_FLAT = (0.5, 0.5, 1.0)   # tangent-space neutral
EMISSION_FLAT = (0.0, 0.0, 0.0)  # no emission
# Identify maps by material wiring, not by filename guesswork.
mat = bpy.data.materials[0]
normal_img = None
emissive_img = None
for node in mat.node_tree.nodes:
    if node.type == 'NORMAL_MAP':
        for link in node.inputs['Color'].links:
            if link.from_node.type == 'TEX_IMAGE' and link.from_node.image:
                normal_img = link.from_node.image
for node in mat.node_tree.nodes:
    if node.type == 'BSDF_PRINCIPLED':
        for link in node.inputs['Emission Color'].links:
            if link.from_node.type == 'TEX_IMAGE' and link.from_node.image:
                emissive_img = link.from_node.image
print('MAPS normal=', normal_img.name if normal_img else None, 'emissive=', emissive_img.name if emissive_img else None)
img_normal = normal_img
img_emissive = emissive_img
px_n = list(img_normal.pixels) if img_normal else None
px_e = list(img_emissive.pixels) if img_emissive else None
painted = 0
for poly in mesh.polygons:
    if poly.index not in set(sel):
        continue
    uvs = [uvl.data[li].uv for li in poly.loop_indices]
    # Blender pixel buffer is BOTTOM-LEFT origin: row = v*H (no flip).
    pts = [(u * W, v * H) for u, v in uvs]
    if len(pts) < 3:
        continue
    x0 = max(0, int(min(p[0] for p in pts)) - 1)
    x1 = min(W - 1, int(max(p[0] for p in pts)) + 1)
    y0 = max(0, int(min(p[1] for p in pts)) - 1)
    y1 = min(H - 1, int(max(p[1] for p in pts)) + 1)
    a, b, c = pts[0], pts[1], pts[2]
    det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
    if abs(det) < 1e-9:
        continue
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            w1 = ((xx - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (yy - a[1])) / det
            w2 = ((b[0] - a[0]) * (yy - a[1]) - (xx - a[0]) * (b[1] - a[1])) / det
            w0 = 1 - w1 - w2
            if w0 >= -0.03 and w1 >= -0.03 and w2 >= -0.03:
                i = (yy * W + xx) * 4
                px[i] = ERASE[0]; px[i + 1] = ERASE[1]; px[i + 2] = ERASE[2]; px[i + 3] = 1.0
                if px_n:
                    px_n[i] = NORMAL_FLAT[0]; px_n[i + 1] = NORMAL_FLAT[1]; px_n[i + 2] = NORMAL_FLAT[2]
                if px_e:
                    px_e[i] = EMISSION_FLAT[0]; px_e[i + 1] = EMISSION_FLAT[1]; px_e[i + 2] = EMISSION_FLAT[2]
                painted += 1
print('PAINTED px', painted)

# 2D safety net: inside the two eye-blob rects of the atlas (given in PNG
# top-left coords), paint every dark or cyan texel navy. Blender's buffer is
# bottom-up, so the row index must be flipped. Light neighboring islands
# (lum > 0.42, non-cyan) are left untouched.
RECTS = [(590, 640, 200, 230), (540, 830, 170, 194)]
rect_px = 0
for rx, ry, rw, rh in RECTS:
    for yy in range(ry, min(H, ry + rh)):
        b_yy = H - 1 - yy  # PNG top-left row -> Blender bottom-up row
        for xx in range(rx, min(W, rx + rw)):
            i = (b_yy * W + xx) * 4
            px[i] = ERASE[0]; px[i + 1] = ERASE[1]; px[i + 2] = ERASE[2]; px[i + 3] = 1.0
            if px_n:
                px_n[i] = NORMAL_FLAT[0]; px_n[i + 1] = NORMAL_FLAT[1]; px_n[i + 2] = NORMAL_FLAT[2]
            if px_e:
                px_e[i] = EMISSION_FLAT[0]; px_e[i + 1] = EMISSION_FLAT[1]; px_e[i + 2] = EMISSION_FLAT[2]
            rect_px += 1
print('RECT px', rect_px)
xs_all = [p[0] for p in pts]  # last face only; global bbox below
print('PAINT done')

img.pixels = px
if img_normal:
    img_normal.pixels = px_n
if img_emissive:
    img_emissive.pixels = px_e

# Critical: the glTF exporter reads each image's backing file, not live pixel
# memory. Save the edited images to disk and swap freshly loaded copies into
# the material nodes before exporting, or the erase never ships.

swap = []
for image, px_data in ((img, px), (img_normal, px_n), (img_emissive, px_e)):
    if not image or px_data is None:
        continue
    tmp = os.path.join(OUT_DIR, 'erased_' + image.name + '.png')
    image.filepath_raw = tmp
    image.file_format = 'PNG'
    image.save()
    fresh = bpy.data.images.load(tmp)
    fresh.colorspace_settings.name = image.colorspace_settings.name
    swap.append((image, fresh))

mat = bpy.data.materials[0]
for node in mat.node_tree.nodes:
    if node.type == 'TEX_IMAGE' and node.image:
        for old, fresh in swap:
            if node.image == old:
                node.image = fresh
                print('SWAPPED node image ->', fresh.name)
bpy.ops.object.select_all(action='DESELECT')
ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=r"D:\MyPro\Cortexa\tools\robot\halobyte-slim-raw.glb",
                          export_format='GLB', use_selection=True, export_apply=True)
print('EXPORT_OK')
