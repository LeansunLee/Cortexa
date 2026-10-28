import bpy, json, math
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=r"C:\Users\阿木\Downloads\Meshy_AI_HaloByte_1025091710_texture.glb")
ob = bpy.data.objects['Mesh_0']; mesh = ob.data
uvl = mesh.uv_layers[0]; img = bpy.data.images['Image_0']
W, H = img.size; px = list(img.pixels)

def sample(u, v):
    x = min(W-1, int(u*W)); y = min(H-1, int(v*H)); i = (y*W+x)*4
    return px[i], px[i+1], px[i+2]

mw = ob.matrix_world
nmat = mw.inverted().transposed().to_3x3()
GRID = 512
occ = [[False]*GRID for _ in range(GRID)]
sel = []
for poly in mesh.polygons:
    n_world = (nmat @ poly.normal).normalized()
    if n_world.y > -0.18: continue
    center = mw @ poly.center
    if center.z < -0.10 or center.z > 0.34 or center.y > -0.10 or abs(center.x) > 0.34: continue
    uvs = [uvl.data[li].uv for li in poly.loop_indices]
    samples = [sample(u, v) for u, v in uvs]
    lum = sum(0.2126*r + 0.7152*g + 0.0722*b for r, g, b in samples)/len(samples)
    # Accept dark screen texels AND the baked cyan eye texels sitting inside the screen.
    is_eye = sum(1 for r, g, b in samples if b > r + 0.08 and g > r + 0.08) > len(samples) * 0.5
    if lum > 0.30 and not is_eye: continue
    sel.append(poly.index)
    for u, v in uvs:
        cx = min(GRID-1, max(0, int(u*GRID))); cy = min(GRID-1, max(0, int(v*GRID)))
        occ[cy][cx] = True

def dilate(m, r):
    out = [row[:] for row in m]
    for y in range(GRID):
        for x in range(GRID):
            if m[y][x]:
                for dy in range(-r, r+1):
                    for dx in range(-r, r+1):
                        ny, nx = y+dy, x+dx
                        if 0 <= ny < GRID and 0 <= nx < GRID: out[ny][nx] = True
    return out

def erode(m, r):
    out = [row[:] for row in m]
    for y in range(GRID):
        for x in range(GRID):
            if m[y][x]:
                for dy in range(-r, r+1):
                    hole = False
                    for dx in range(-r, r+1):
                        ny, nx = y+dy, x+dx
                        if not (0 <= ny < GRID and 0 <= nx < GRID and m[ny][nx]):
                            hole = True; break
                    if hole: out[y][x] = False
    return out

occ = erode(dilate(occ, 8), 8)

# UV-space clustering: the screen may be packed as 2+ atlas islands; keep the
# largest cluster and any ≥25% of its size, drop stray texels from other parts.
from collections import deque
seen = [[False]*GRID for _ in range(GRID)]
clusters = []
for y in range(GRID):
    for x in range(GRID):
        if occ[y][x] and not seen[y][x]:
            q = deque([(x, y)]); seen[y][x] = True; comp = []
            while q:
                cx, cy = q.popleft(); comp.append((cx, cy))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = cx+dx, cy+dy
                        if 0 <= nx < GRID and 0 <= ny < GRID and occ[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True; q.append((nx, ny))
            clusters.append(comp)
clusters.sort(key=len, reverse=True)
kept = set()
if clusters:
    biggest = len(clusters[0])
    def bbox(comp):
        xs = [c[0] for c in comp]; ys = [c[1] for c in comp]
        return min(xs), max(xs), min(ys), max(ys)
    bx0, bx1, by0, by1 = bbox(clusters[0])
    for comp in clusters:
        if len(comp) < 30: continue
        cx0, cx1, cy0, cy1 = bbox(comp)
        near = cx0 <= bx1 + 60 and bx0 <= cx1 + 60 and cy0 <= by1 + 60 and by0 <= cy1 + 60
        if near and len(comp) >= biggest * 0.02: kept.update(comp)
print("CLUSTERS", [len(c) for c in clusters[:6]], "KEPT", len(kept))
cells = sorted(kept)
xs = [c[0] for c in cells]; ys = [c[1] for c in cells]
gx0, gx1, gy0, gy1 = min(xs), max(xs), min(ys), max(ys)
cell_px = W / GRID
rect_x = int(gx0 * cell_px); rect_y = int((GRID - 1 - gy1) * cell_px)
rect_w = int((gx1 - gx0 + 1) * cell_px); rect_h = int((gy1 - gy0 + 1) * cell_px)
rows = []
for gy in range(gy0, gy1+1):
    runs = []; start = None
    for gx in range(gx0, gx1+2):
        on = gx <= gx1 and (gx, gy) in kept
        if on and start is None: start = gx
        elif not on and start is not None: runs.append([start - gx0, gx - gx0]); start = None
    rows.append(runs)
runs_total = sum(len(r) for r in rows)
print("RECT", rect_x, rect_y, rect_w, rect_h, "SEL_FACES", len(sel), "RUNS", runs_total)

# Per-cell bake: normalized screen-plane coords (u: left->right = x asc, v: top->bottom = z desc)
# plus the original texel luminance, so the runtime can erase the baked eyes and paint
# the dynamic pixel face with correct placement on the curved screen.
mx0 = mx1 = mz0 = mz1 = None
cent = {}
for poly in mesh.polygons:
    if poly.index not in set(sel): continue
    c3 = mw @ poly.center
    cent[poly.index] = (c3.x, c3.z)
xs3 = [c[0] for c in cent.values()]; zs3 = [c[1] for c in cent.values()]
xmin, xmax, zmin, zmax = min(xs3), max(xs3), min(zs3), max(zs3)
print("SCREEN3D x", round(xmin,3), round(xmax,3), "z", round(zmin,3), round(zmax,3))
# per-poly cell coverage: rasterize poly uv bbox (polys are tiny)
poly_cells = {}
for poly in mesh.polygons:
    if poly.index not in cent: continue
    uvs = [uvl.data[li].uv for li in poly.loop_indices]
    us = [u for u, v in uvs]; vs = [v for u, v in uvs]
    for cu in range(max(0,int(min(us)*GRID)), min(GRID-1, int(max(us)*GRID))+1):
        for cv in range(max(0,int(min(vs)*GRID)), min(GRID-1, int(max(vs)*GRID))+1):
            if occ[cv][cu]:
                poly_cells.setdefault((cu, cv), []).append(poly.index)
cell_uv = {}
for (cu, cv), idxs in poly_cells.items():
    us = [cent[i][0] for i in idxs]; zs = [cent[i][1] for i in idxs]
    u = (sum(us)/len(us) - xmin) / (xmax - xmin)
    v = (zmax - sum(zs)/len(zs)) / (zmax - zmin)
    cell_uv[(cu, cv)] = (u, v)

# per-cell luminance from atlas
def cell_lum(cu, cv):
    total = 0; n = 0
    for dy in range(4):
        for dx in range(4):
            x = cu*4 + dx; y_at = cv*4 + dy
            if x >= W or y_at >= H: continue
            i = (y_at*W + x)*4
            total += 0.2126*px[i] + 0.7152*px[i+1] + 0.0722*px[i+2]; n += 1
    return total / max(1, n)

erase_rgb = [0, 0, 0]; erase_n = 0
entries = bytearray()
for gy in range(gy0, gy1+1):
    for run in rows[gy - gy0]:
        for gx in range(run[0] + gx0, run[1] + gx0):
            u, v = cell_uv.get((gx, gy), (0.5, 0.5))
            lum = cell_lum(gx, gy)
            entries.extend([int(u*255), int(v*255), int(min(255, lum*255))])
            if lum <= 0.25:
                x = gx*4; y_at = cv = gy*4
                i = (min(H-1,y_at)*W + min(W-1,x))*4
                erase_rgb[0] += px[i]; erase_rgb[1] += px[i+1]; erase_rgb[2] += px[i+2]; erase_n += 1
import base64
uv_b64 = base64.b64encode(bytes(entries)).decode()
erase = [round(c / max(1, erase_n), 4) for c in erase_rgb]
print("ERASE_COLOR", erase, "ENTRIES", len(entries)//3)
with open(r"D:\MyPro\Cortexa\tools\robot\screen_mask.json", "w") as f:
    json.dump({"rect": [rect_x, rect_y, rect_w, rect_h], "grid": GRID, "origin": [gx0, gy0],
               "rows": rows, "uv": uv_b64, "erase": erase}, f)
print("JSON_SAVED")

img2 = img.copy()
arr = list(img2.pixels)
for gy in range(gy0, gy1+1):
    for run in rows[gy - gy0]:
        for gx in range(run[0] + gx0, run[1] + gx0):
            for dy in range(4):
                y_at = gy*4 + dy
                for dx in range(4):
                    x = gx*4 + dx
                    i = (y_at*W + x)*4
                    arr[i] = 1.0; arr[i+1] = 0.05; arr[i+2] = 0.05; arr[i+3] = 1.0
img2.pixels = arr
mat = bpy.data.materials['Material_0']
for node in mat.node_tree.nodes:
    if node.type == 'TEX_IMAGE' and node.image == img:
        node.image = img2
scene = bpy.context.scene

def look_at(ob, t):
    ob.rotation_euler = (Vector(t) - ob.location).to_track_quat('-Z','Y').to_euler()

cd = bpy.data.cameras.new('C'); cam = bpy.data.objects.new('C', cd); scene.collection.objects.link(cam); scene.camera = cam
cd.lens = 50
world = bpy.data.worlds.new('W'); world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (0.92,0.94,1.0,1.0); scene.world = world
scene.render.engine = 'CYCLES'; scene.cycles.device='CPU'; scene.cycles.samples=48; scene.cycles.use_denoising=True
scene.render.resolution_x = 640; scene.render.resolution_y = 640
cam.location = (0,-1.6,0.12); look_at(cam,(0,0,0.05))
scene.render.filepath = r"D:\MyPro\Cortexa\tools\robot\meshy_mask_debug.png"
bpy.ops.render.render(write_still=True)
print("DEBUG_RENDER_OK")
