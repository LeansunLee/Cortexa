# Cortexa mascot robot — generated with Blender 4.5 LTS.
# Run:  blender --background --factory-startup --python build_robot.py
# Outputs: cortexa-robot.glb (frontend/public/themes/robot/) + preview.png
# Material names are contractual: the frontend repaints Shell / Accent / Eye by theme.
import bpy
import math
import os
from mathutils import Vector

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
GLB_PATH = os.path.join(OUT_DIR, 'cortexa-robot.glb')
PNG_PATH = os.path.join(OUT_DIR, 'preview.png')

bpy.ops.wm.read_factory_settings(use_empty=True)


def principled(name, base, rough=0.35, metal=0.05, emissive=None, emissive_strength=0.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*base, 1.0)
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    if emissive is not None:
        emission = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
        emission.default_value = (*emissive, 1.0)
        bsdf.inputs['Emission Strength'].default_value = emissive_strength
    return material


MAT_SHELL = principled('Shell', (0.949, 0.929, 0.878), rough=0.38, metal=0.02)
MAT_ACCENT = principled('Accent', (0.918, 0.412, 0.243), rough=0.30, metal=0.05)
MAT_SCREEN = principled('Screen', (0.125, 0.140, 0.160), rough=0.28, metal=0.10)
MAT_EYE = principled('Eye', (1.0, 1.0, 1.0), rough=0.2, emissive=(1.0, 1.0, 1.0), emissive_strength=4.0)
MAT_BASE = principled('Base', (0.220, 0.236, 0.256), rough=0.50, metal=0.15)

robot = []


def smooth(ob):
    try:
        bpy.ops.object.shade_auto_smooth(angle=math.radians(60))
    except AttributeError:
        bpy.ops.object.shade_smooth()


def rounded_box(name, dims, radius, location, material, segments=6):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = ob.modifiers.new('Round', 'BEVEL')
    bevel.width = min(radius, min(dims) * 0.49)
    bevel.segments = segments
    smooth(ob)
    ob.data.materials.append(material)
    robot.append(ob)
    return ob


def cylinder(name, radius, depth, location, material, rotation=(0, 0, 0), vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location,
                                        rotation=rotation, vertices=vertices)
    ob = bpy.context.active_object
    ob.name = name
    smooth(ob)
    ob.data.materials.append(material)
    robot.append(ob)
    return ob


def sphere(name, radius, location, material, scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location, segments=32, ring_count=16)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    bpy.ops.object.shade_smooth()
    ob.data.materials.append(material)
    robot.append(ob)
    return ob


# Head — rounded box with dark screen face.
rounded_box('RobotHead', (1.14, 0.92, 0.84), 0.16, (0, 0, 1.28), MAT_SHELL, segments=8)
rounded_box('RobotScreen', (0.84, 0.10, 0.54), 0.09, (0, -0.45, 1.30), MAT_SCREEN, segments=6)
# Glowing eyes.
cylinder('RobotEyeL', 0.088, 0.03, (-0.185, -0.505, 1.32), MAT_EYE, rotation=(math.pi / 2, 0, 0))
cylinder('RobotEyeR', 0.088, 0.03, (0.185, -0.505, 1.32), MAT_EYE, rotation=(math.pi / 2, 0, 0))
# Antenna with accent tip.
cylinder('RobotAntenna', 0.018, 0.18, (0, 0, 1.79), MAT_SHELL)
sphere('RobotAntennaTip', 0.058, (0, 0, 1.90), MAT_ACCENT)
# Side ear discs.
cylinder('RobotEarL', 0.15, 0.09, (-0.60, 0, 1.28), MAT_ACCENT, rotation=(0, math.pi / 2, 0))
cylinder('RobotEarR', 0.15, 0.09, (0.60, 0, 1.28), MAT_ACCENT, rotation=(0, math.pi / 2, 0))
# Body with a round chest button.
rounded_box('RobotBody', (0.92, 0.80, 0.78), 0.20, (0, 0, 0.52), MAT_SHELL, segments=8)
cylinder('RobotChest', 0.085, 0.05, (0, -0.415, 0.60), MAT_ACCENT, rotation=(math.pi / 2, 0, 0))
# Stubby arms, angled slightly outward.
arm_l = sphere('RobotArmL', 0.13, (-0.55, 0, 0.56), MAT_SHELL, scale=(0.78, 1.0, 1.32))
arm_l.rotation_euler.z = math.radians(-9)
arm_r = sphere('RobotArmR', 0.13, (0.55, 0, 0.56), MAT_SHELL, scale=(0.78, 1.0, 1.32))
arm_r.rotation_euler.z = math.radians(9)
# Dark pedestal base.
base = cylinder('RobotBase', 0.46, 0.16, (0, 0, 0.08), MAT_BASE)
bevel = base.modifiers.new('Round', 'BEVEL')
bevel.width = 0.035
bevel.segments = 4
smooth(base)

for ob in robot:
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ---- Render-only scenery (never exported). ----
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
    direction = Vector(target) - ob.location
    ob.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def area_light(name, power, location, target, size=2):
    light_data = bpy.data.lights.new(name, 'AREA')
    light_data.energy = power
    light_data.size = size
    light = bpy.data.objects.new(name, light_data)
    scene.collection.objects.link(light)
    light.location = location
    look_at(light, target)


area_light('Key', 90, (2.8, -2.4, 3.4), (0, 0, 0.8))
area_light('Fill', 28, (-3.4, -1.6, 2.2), (0, 0, 0.8), size=3)
area_light('Rim', 45, (-1.6, 3.0, 2.6), (0, 0, 0.9), size=2.5)

camera_data = bpy.data.cameras.new('Camera')
camera_data.lens = 52
camera = bpy.data.objects.new('Camera', camera_data)
scene.collection.objects.link(camera)
front_view = os.environ.get('ROBOT_VIEW') == 'front'
camera.location = (0.0, -3.15, 1.00) if front_view else (2.15, -3.05, 1.45)
look_at(camera, (0, -0.05, 0.80) if front_view else (0, -0.05, 0.84))
scene.camera = camera

scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 96
scene.cycles.use_denoising = True
scene.render.resolution_x = 880
scene.render.resolution_y = 1080
scene.render.filepath = os.path.join(OUT_DIR, 'preview-front.png') if front_view else PNG_PATH
bpy.ops.render.render(write_still=True)
print('RENDER_OK', PNG_PATH)

# ---- GLB export: robot objects only. ----
bpy.ops.object.select_all(action='DESELECT')
for ob in robot:
    ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=GLB_PATH, export_format='GLB', use_selection=True,
                          export_apply=True, export_yup=True)
print('GLB_OK', GLB_PATH, os.path.getsize(GLB_PATH), 'bytes')

BLEND_PATH = os.path.join(OUT_DIR, 'cortexa-robot-v1.blend')
bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
print('BLEND_OK', BLEND_PATH)
