# Cortexa mascot robot v2 — voxel/low-poly CRT monitor robot rework.
# Geometry only: no material/UV/texture editing. The v1 material slots
# (Shell/Accent/Screen/Base) are merely re-assigned by name so the frontend
# theme-paint pipeline keeps working.
# Run: blender --background --factory-startup --python rework_voxel.py
#
# Proportion sheet (front = -Y, ground = z0):
#   head  1.30 x 1.00 x 0.95 @ z 1.34..2.29   (CRT shell, front screen inset)
#   torso chest 0.82 wide / waist 0.60 / hips 0.74  -> head:chest = 1.59
#   neck  0.30 x 0.30 x 0.18, separate object bridging head and chest
#   arm   shoulder disc + upper 0.17 + elbow + forearm 0.19 + fist 0.24 cube
#   leg   thigh 0.22 + foot 0.28 x 0.40 x 0.16 (beveled block, no disc base)
#   antenna square rod + 0.10 cube, offset +Y (slightly back of head center)
import bpy
import bmesh
import math
import os
from mathutils import Vector

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
BLEND_PATH = os.path.join(OUT_DIR, 'cortexa-robot.blend')
GLB_PATH = os.path.join(OUT_DIR, 'cortexa-robot.glb')
AUTOSMOOTH = math.radians(24)  # keeps 12-gon facets (30 deg) crisp, bevels (<=22.5) smooth

bpy.ops.wm.read_factory_settings(use_empty=True)


def principled(name, base, rough=0.35, metal=0.05):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*base, 1.0)
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    return material


MAT_SHELL = principled('Shell', (0.949, 0.929, 0.878), rough=0.38, metal=0.02)
MAT_ACCENT = principled('Accent', (0.918, 0.412, 0.243), rough=0.30, metal=0.05)
MAT_SCREEN = principled('Screen', (0.125, 0.140, 0.160), rough=0.28, metal=0.10)
MAT_BASE = principled('Base', (0.220, 0.236, 0.256), rough=0.50, metal=0.15)

robot = []


def finish(ob, radius, segments=3):
    if radius > 0:
        bevel = ob.modifiers.new('Bevel', 'BEVEL')
        bevel.width = min(radius, min(ob.dimensions) * 0.49)
        bevel.segments = segments
    try:
        bpy.ops.object.shade_auto_smooth(angle=AUTOSMOOTH)
    except AttributeError:
        bpy.ops.object.shade_smooth()


def box(name, dims, radius, location, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material:
        ob.data.materials.append(material)
    finish(ob, radius)
    robot.append(ob)
    return ob


def cylinder(name, radius, depth, location, material, axis='X', segments=12):
    rotation = {'X': (0, math.pi / 2, 0), 'Y': (math.pi / 2, 0, 0), 'Z': (0, 0, 0)}[axis]
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location,
                                        rotation=rotation, vertices=segments)
    ob = bpy.context.active_object
    ob.name = name
    if material:
        ob.data.materials.append(material)
    finish(ob, 0)
    robot.append(ob)
    return ob


def join(name, objects):
    global robot
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objects:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    merged = bpy.context.active_object
    merged.name = name
    # Join deletes the non-active inputs: drop their stale RNA references.
    robot = [ob for ob in robot if ob not in objects] + [merged]
    return merged


# ---- Head: thick CRT shell with an inset screen plateau (local inset, no booleans). ----
head = box('RobotHead', (1.30, 1.00, 0.95), 0.06, (0, 0, 1.815), MAT_SHELL)
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(head.data)
bm.faces.ensure_lookup_table()
front = next(f for f in bm.faces if f.normal.y < -0.9 and abs(f.normal.x) < 0.1 and abs(f.normal.z) < 0.1)
bmesh.ops.inset_individual(bm, faces=[front], thickness=0.10, depth=-0.05)
bmesh.update_edit_mesh(head.data)
bpy.ops.object.mode_set(mode='OBJECT')
# Back vents: shallow ribs joined into the head shell.
vents = [box('RobotVent', (0.46, 0.03, 0.05), 0.006, (0, 0.505, z), MAT_SHELL) for z in (1.78, 1.90, 2.02)]
head = join('RobotHead', [head] + vents)

# Screen: blank slab sitting inside the recess (front stays 0.03 behind the shell face).
box('RobotScreen', (1.02, 0.06, 0.62), 0.02, (0, -0.44, 1.815), MAT_SCREEN)
# Ear covers: faceted low-poly discs.
cylinder('RobotEarL', 0.17, 0.07, (-0.67, 0, 1.815), MAT_ACCENT, axis='X')
cylinder('RobotEarR', 0.17, 0.07, (0.67, 0, 1.815), MAT_ACCENT, axis='X')
# Antenna: square rod + cube, slightly back of head center. The stem is tall
# enough that the cube reads clear of the head silhouette from behind.
antenna = join('RobotAntenna', [
    box('RobotAntennaRod', (0.05, 0.05, 0.18), 0.012, (0, 0.15, 2.38), MAT_SHELL),
    box('RobotAntennaCube', (0.10, 0.10, 0.10), 0.015, (0, 0.15, 2.52), MAT_ACCENT),
])

# ---- Torso: stepped chest / waist / hips + raised square chest plate. ----
torso = join('RobotTorso', [
    box('RobotChest', (0.82, 0.64, 0.52), 0.07, (0, 0, 0.96), MAT_SHELL),
    box('RobotWaist', (0.60, 0.44, 0.16), 0.05, (0, 0, 0.63), MAT_SHELL),
    box('RobotHips', (0.74, 0.56, 0.28), 0.06, (0, 0, 0.42), MAT_SHELL),
    box('RobotChestPlate', (0.30, 0.05, 0.30), 0.015, (0, -0.325, 0.98), MAT_ACCENT),
])
box('RobotNeck', (0.30, 0.30, 0.18), 0.04, (0, 0, 1.27), MAT_SHELL)

# ---- Arms: shoulder disc, upper arm, elbow ring, forearm, cube fist. ----
# The stack sits slightly off the torso with width steps + a proud elbow ring so
# each segment reads; the shoulder disc bridges chest and arm (no floating gap).
for side, sx in (('L', -1), ('R', 1)):
    x = sx * 0.535
    join(f'RobotArm{side}', [
        cylinder(f'RobotShoulder{side}', 0.12, 0.16, (sx * 0.47, 0, 1.05), MAT_SHELL, axis='X'),
        box(f'RobotUpperArm{side}', (0.17, 0.17, 0.28), 0.04, (x, 0, 0.89), MAT_SHELL),
        cylinder(f'RobotElbow{side}', 0.10, 0.24, (x, 0, 0.72), MAT_SHELL, axis='X'),
        box(f'RobotForearm{side}', (0.21, 0.21, 0.28), 0.04, (x, 0, 0.57), MAT_SHELL),
        box(f'RobotFist{side}', (0.26, 0.26, 0.20), 0.05, (x, 0, 0.33), MAT_SHELL),
    ])

# ---- Legs: short thigh + wide beveled-block foot, clear gap between feet. ----
# Feet are deep and shifted forward so the toes extend past the hips silhouette.
for side, sx in (('L', -1), ('R', 1)):
    join(f'RobotLeg{side}', [
        box(f'RobotThigh{side}', (0.22, 0.20, 0.20), 0.04, (sx * 0.22, 0, 0.22), MAT_SHELL),
        box(f'RobotFoot{side}', (0.28, 0.46, 0.16), 0.045, (sx * 0.22, -0.10, 0.08), MAT_BASE),
    ])

for ob in robot:
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ---- Symmetry + sanity report. ----
pairs = [('RobotEarL', 'RobotEarR'), ('RobotArmL', 'RobotArmR'), ('RobotLegL', 'RobotLegR')]
for left, right in pairs:
    l, r = bpy.data.objects[left], bpy.data.objects[right]
    assert all(abs(a - b) < 1e-4 for a, b in zip(l.dimensions, r.dimensions)), f'asymmetric: {left}/{right}'
triangles = sum(len(ob.data.polygons) for ob in robot)
print('PARTS', [ob.name for ob in robot])
print('TRIANGLES', triangles)
print('HEAD_W', 1.30, 'CHEST_W', 0.82, 'RATIO', round(1.30 / 0.82, 3))

# ---- Verification renders: front / back / left / right / 45 deg. ----
scene = bpy.context.scene
world = bpy.data.worlds.new('World')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (0.92, 0.94, 1.0, 1.0)
world.node_tree.nodes['Background'].inputs[1].default_value = 0.9
scene.world = world

bpy.ops.mesh.primitive_plane_add(size=24, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = 'Ground'
ground_mat = bpy.data.materials.new('GroundMat')
ground_mat.use_nodes = True
ground_mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.905, 0.910, 0.925, 1.0)
ground_mat.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.9
ground.data.materials.append(ground_mat)


def look_at(ob, target):
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat('-Z', 'Y').to_euler()


def area_light(name, power, location, target, size=2):
    light_data = bpy.data.lights.new(name, 'AREA')
    light_data.energy = power
    light_data.size = size
    light = bpy.data.objects.new(name, light_data)
    scene.collection.objects.link(light)
    light.location = location
    look_at(light, target)


area_light('Key', 90, (2.8, -2.4, 3.6), (0, 0, 1.2))
area_light('Fill', 28, (-3.4, -1.6, 2.4), (0, 0, 1.2), size=3)
area_light('Rim', 45, (-1.6, 3.0, 3.0), (0, 0, 1.3), size=2.5)

camera_data = bpy.data.cameras.new('Camera')
camera_data.lens = 52
camera = bpy.data.objects.new('Camera', camera_data)
scene.collection.objects.link(camera)
scene.camera = camera

D = 4.9
views = {
    'front': ((0.0, -D, 1.30), (0, 0, 1.18)),
    'back': ((0.0, D, 1.30), (0, 0, 1.18)),
    'left': ((-D, 0.0, 1.30), (0, 0, 1.18)),
    'right': ((D, 0.0, 1.30), (0, 0, 1.18)),
    'persp45': ((D * 0.62, -D * 0.78, 1.72), (0, 0, 1.05)),
}
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x = 720
scene.render.resolution_y = 920
for view, (position, target) in views.items():
    camera.location = position
    look_at(camera, target)
    scene.render.filepath = os.path.join(OUT_DIR, f'v2-{view}.png')
    bpy.ops.render.render(write_still=True)
    print('VIEW_OK', view)

# ---- Save working blend + export GLB (robot selection only). ----
bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
print('BLEND_OK', BLEND_PATH)

bpy.ops.object.select_all(action='DESELECT')
for ob in robot:
    ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=GLB_PATH, export_format='GLB', use_selection=True,
                          export_apply=True, export_yup=True)
print('GLB_OK', GLB_PATH, os.path.getsize(GLB_PATH), 'bytes')
