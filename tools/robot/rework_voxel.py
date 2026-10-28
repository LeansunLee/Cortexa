# Cortexa mascot robot v3 — chibi voxel CRT monitor robot, proportion rework.
# Geometry only: no material/UV/texture/light editing. The v1 material slots
# (Shell/Accent/Screen/Base) are merely re-assigned by name so the frontend
# theme-paint pipeline keeps working.
# Run: blender --background --factory-startup --python rework_voxel.py
#
# Proportion sheet v3 (front = -Y, ground = z0, A-pose arms 12 deg out):
#   head  1.36 x 1.10 x 1.00 @ z 1.16..2.16   -> head:torso width = 1.66
#   total height 2.42 -> head height = 41% of total (target 40-45%)
#   torso ONE stout rounded block 0.82 x 0.66 x 0.74 (waist step removed)
#   arms  chunky A-pose: shoulder disc + 0.22 upper + elbow ring + 0.24 fore
#          + 0.26 fist; fist bottom sits at the torso bottom line
#   legs  stubby thighs + 0.32 x 0.48 x 0.18 feet, toes proud of the torso
import bpy
import bmesh
import math
import os
from mathutils import Vector

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
BLEND_PATH = os.path.join(OUT_DIR, 'cortexa-robot.blend')
GLB_PATH = os.path.join(OUT_DIR, 'cortexa-robot.glb')
AUTOSMOOTH = math.radians(24)  # keeps 12-gon facets (30 deg) crisp, bevels (<=22.5) smooth
ARM_TILT = math.radians(12)    # A-pose

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


def box(name, dims, radius, location, material, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=rotation)
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


# ---- Head: thick CRT shell (deeper back), stepped bevel, inset screen plateau. ----
head = box('RobotHead', (1.36, 1.10, 1.00), 0.07, (0, 0, 1.66), MAT_SHELL)
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(head.data)
bm.faces.ensure_lookup_table()
front = next(f for f in bm.faces if f.normal.y < -0.9 and abs(f.normal.x) < 0.1 and abs(f.normal.z) < 0.1)
bmesh.ops.inset_individual(bm, faces=[front], thickness=0.10, depth=-0.05)
bmesh.update_edit_mesh(head.data)
bpy.ops.object.mode_set(mode='OBJECT')
vents = [box('RobotVent', (0.46, 0.03, 0.05), 0.006, (0, 0.555, z), MAT_SHELL) for z in (1.45, 1.60, 1.75)]
head = join('RobotHead', [head] + vents)

# Blank screen slab inside the recess (front stays 0.03 behind the shell face).
box('RobotScreen', (1.06, 0.06, 0.64), 0.02, (0, -0.49, 1.66), MAT_SCREEN)
# Faceted low-poly ear covers.
cylinder('RobotEarL', 0.18, 0.07, (-0.70, 0, 1.66), MAT_ACCENT, axis='X')
cylinder('RobotEarR', 0.18, 0.07, (0.70, 0, 1.66), MAT_ACCENT, axis='X')
# Square rod + cube antenna, slightly back of head center.
antenna = join('RobotAntenna', [
    box('RobotAntennaRod', (0.05, 0.05, 0.16), 0.012, (0, 0.18, 2.24), MAT_SHELL),
    box('RobotAntennaCube', (0.10, 0.10, 0.10), 0.015, (0, 0.18, 2.37), MAT_ACCENT),
])

# ---- Torso: one stout rounded block (waist step removed) + chest module. ----
torso = join('RobotTorso', [
    box('RobotChest', (0.82, 0.66, 0.74), 0.10, (0, 0, 0.67), MAT_SHELL),
    box('RobotChestPlate', (0.30, 0.05, 0.30), 0.015, (0, -0.345, 0.80), MAT_ACCENT),
])
box('RobotNeck', (0.30, 0.30, 0.16), 0.04, (0, 0, 1.10), MAT_SHELL)

# ---- Arms: chunky A-pose stack, parametrically tilted 12 deg from vertical. ----
# Segments are placed along the tilted axis so the whole limb reads as one
# chunky mass with a proud elbow ring; origin lands on the shoulder disc.
tilt = (math.sin(ARM_TILT), 0.0, -math.cos(ARM_TILT))
for side, sx in (('L', -1), ('R', 1)):
    pivot = Vector((sx * 0.50, 0.0, 1.00))
    along = Vector(tilt) * sx if sx < 0 else Vector(tilt)

    def at(distance):
        return pivot + along * distance

    rotation = (0, -ARM_TILT if sx < 0 else ARM_TILT, 0)
    join(f'RobotArm{side}', [
        cylinder(f'RobotShoulder{side}', 0.13, 0.14, (sx * 0.475, 0, 1.00), MAT_SHELL, axis='X'),
        box(f'RobotUpperArm{side}', (0.22, 0.22, 0.26), 0.05, at(0.17).to_tuple(), MAT_SHELL, rotation),
        cylinder(f'RobotElbow{side}', 0.10, 0.26, at(0.32).to_tuple(), MAT_SHELL, axis='X'),
        box(f'RobotForearm{side}', (0.24, 0.24, 0.24), 0.05, at(0.45).to_tuple(), MAT_SHELL, rotation),
        box(f'RobotFist{side}', (0.26, 0.26, 0.22), 0.05, at(0.615).to_tuple(), MAT_SHELL, rotation),
    ])

# ---- Legs: stubby thighs + wide thick feet with forward toes. ----
for side, sx in (('L', -1), ('R', 1)):
    join(f'RobotLeg{side}', [
        box(f'RobotThigh{side}', (0.24, 0.24, 0.18), 0.04, (sx * 0.22, 0, 0.25), MAT_SHELL),
        box(f'RobotFoot{side}', (0.32, 0.50, 0.20), 0.05, (sx * 0.22, -0.10, 0.10), MAT_BASE),
    ])

for ob in robot:
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

# ---- Proportion + symmetry report. ----
pairs = [('RobotEarL', 'RobotEarR'), ('RobotArmL', 'RobotArmR'), ('RobotLegL', 'RobotLegR')]
for left, right in pairs:
    l, r = bpy.data.objects[left], bpy.data.objects[right]
    assert all(abs(a - b) < 1e-4 for a, b in zip(l.dimensions, r.dimensions)), f'asymmetric: {left}/{right}'
triangles = sum(len(ob.data.polygons) for ob in robot)
print('PARTS', [ob.name for ob in robot])
print('TRIANGLES', triangles)
print('RATIO head_w/chest_w', round(1.36 / 0.82, 3))
print('RATIO head_h/total_h', round(1.00 / 2.42, 3))

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
    'front': ((0.0, -D, 1.25), (0, 0, 1.12)),
    'back': ((0.0, D, 1.25), (0, 0, 1.12)),
    'left': ((-D, 0.0, 1.25), (0, 0, 1.12)),
    'right': ((D, 0.0, 1.25), (0, 0, 1.12)),
    'persp45': ((D * 0.62, -D * 0.78, 1.68), (0, 0, 1.00)),
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
    scene.render.filepath = os.path.join(OUT_DIR, f'v3-{view}.png')
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
