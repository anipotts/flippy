"""Demo scene for the screen recording: a lit, shiny Suzanne in EEVEE rendered view.
Run: flatpak run org.blender.Blender --python scripts/demo_blender_scene.py
"""
import bpy, math
sc = bpy.context.scene
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
def mat(name, col, metal=0.0, rough=0.3, emit=None, strength=0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*col, 1); b.inputs["Metallic"].default_value = metal
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1); b.inputs["Emission Strength"].default_value = strength
    return m
bpy.ops.mesh.primitive_monkey_add(location=(0, 0, 1.1), rotation=(0.35, 0, 0.5))
mk = bpy.context.object; mk.name = "Suzanne"
bpy.ops.object.modifier_add(type='SUBSURF'); mk.modifiers[-1].levels = 2; mk.modifiers[-1].render_levels = 2
bpy.ops.object.shade_smooth()
mk.data.materials.append(mat("Chrome Peach", (1.0, 0.45, 0.35), metal=0.6, rough=0.18))
bpy.ops.mesh.primitive_torus_add(location=(0, 0, 1.1), major_radius=1.75, minor_radius=0.05, rotation=(1.2, 0.2, 0))
bpy.context.object.name = "Halo"
bpy.context.object.data.materials.append(mat("Neon", (0.4, 0.2, 1.0), emit=(0.5, 0.2, 1.0), strength=3))
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.32, location=(1.6, -0.9, 0.32)); bpy.ops.object.shade_smooth()
bpy.context.object.name = "Orb"; bpy.context.object.data.materials.append(mat("Mint", (0.2, 0.95, 0.75), rough=0.05))
bpy.ops.mesh.primitive_cube_add(size=0.5, location=(-1.5, 0.8, 0.25), rotation=(0, 0, 0.6))
bpy.context.object.name = "Block"; bpy.context.object.data.materials.append(mat("Butter", (1.0, 0.85, 0.3), rough=0.4))
bpy.ops.mesh.primitive_plane_add(size=30); bpy.context.object.name = "Floor"
bpy.context.object.data.materials.append(mat("Floor", (0.03, 0.025, 0.05), rough=0.3))
bpy.ops.object.light_add(type='AREA', location=(3, -3, 5)); L = bpy.context.object; L.name = "Key Light"
L.data.energy = 450; L.data.size = 4; L.data.color = (1, 0.8, 0.75); L.rotation_euler = (0.6, 0.4, 0.8)
bpy.ops.object.light_add(type='AREA', location=(-4, 2, 3)); L = bpy.context.object; L.name = "Rim Light"
L.data.energy = 600; L.data.color = (0.4, 0.5, 1.0); L.rotation_euler = (-0.8, -0.9, 0)
bpy.ops.object.camera_add(location=(5.5, -6.2, 3.2)); cam = bpy.context.object; sc.camera = cam
c = cam.constraints.new('TRACK_TO'); c.target = mk
w = sc.world or bpy.data.worlds.new("World"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.015, 0.05, 1)
sc.render.engine = 'BLENDER_EEVEE'
try: sc.eevee.use_raytracing = True
except Exception: pass
bpy.ops.object.select_all(action='DESELECT'); mk.select_set(True); bpy.context.view_layer.objects.active = mk
p = bpy.context.preferences
p.view.show_splash = False
try: bpy.ops.wm.save_userpref()
except Exception as e: print(e)
bpy.context.view_layer.update()
def setup():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                sp = area.spaces.active
                sp.shading.type = 'RENDERED'; sp.overlay.show_floor = False; sp.overlay.show_axis_x = sp.overlay.show_axis_y = False; sp.overlay.show_extras = False; sp.overlay.show_relationship_lines = False
                sp.region_3d.view_rotation = cam.matrix_world.to_quaternion()
                sp.region_3d.view_distance = 7.0
                sp.region_3d.view_location = (0, 0, 0.9)
                sp.region_3d.view_perspective = 'PERSP'
    return None
bpy.app.timers.register(setup, first_interval=1.0)
