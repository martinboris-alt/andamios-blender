"""Genera animaciones WebP comparativas para el tutorial v3.

Cada animación cicla entre 2-3 estados de un mismo andamio cambiando una
sola propiedad — útil para enseñar visualmente cómo afecta cada toggle/
enum al resultado.

Animaciones generadas:
- anim_catalog_cycle.webp     — UNIFORM / GENERIC / LAYHER del bay catalog
- anim_depth_cycle.webp       — 0.640 / 0.732 / 1.090 m profundidad
- anim_pattern_cycle.webp     — FRONT / BACK / BOTH / ALT patrón cruces
- anim_decks_toggle.webp      — con/sin plataformas
- anim_braces_toggle.webp     — con/sin cruces
- anim_ties_toggle.webp       — con/sin anclajes
- anim_floors_grow.webp       — 1→2→3→4→5 plantas
- anim_subdivisions_zoom.webp — NONE / HALF / QUARTER (versión más fina)

Ejecutar:
    /snap/bin/blender --background --python tutorial/build_animations.py
"""

from __future__ import annotations

import math
import os
import sys

import bpy
from mathutils import Vector

import andamios_addon


HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
os.makedirs(ASSETS, exist_ok=True)


# ---------------------------------------------------------------------------
# Reusar setup del build.py principal
# ---------------------------------------------------------------------------

def _wipe_default_objects():
    for obj in list(bpy.data.objects):
        if obj.type in {'MESH', 'CAMERA', 'LIGHT'} and obj.name in (
            'Cube', 'Camera', 'Light',
        ):
            bpy.data.objects.remove(obj, do_unlink=True)


def setup_world_lighting():
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
    sun_data = bpy.data.lights.new("TutSun", type='SUN')
    sun_data.energy = 2.0
    sun_obj = bpy.data.objects.new("TutSun", sun_data)
    sun_obj.location = (10, -8, 12)
    sun_obj.rotation_euler = (math.radians(45), 0, math.radians(40))
    scene.collection.objects.link(sun_obj)
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("TutWorld")
        scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.18, 0.18, 0.20, 1.0)
    bg.inputs['Strength'].default_value = 1.0
    out = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])


def setup_ground():
    old = bpy.data.objects.get('TutGround')
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, -0.02))
    plane = bpy.context.object
    plane.name = 'TutGround'


def setup_render_quality(size=(900, 560)):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = size[0]
    scene.render.resolution_y = size[1]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    sh = scene.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'MATERIAL'
    sh.show_shadows = True
    sh.shadow_intensity = 0.35
    sh.show_cavity = True
    sh.cavity_type = 'BOTH'
    if hasattr(scene.display, 'render_aa'):
        scene.display.render_aa = '8'


def reset_scene():
    coll = bpy.data.collections.get("Scaffold")
    if coll is not None:
        for obj in list(coll.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in list(bpy.data.objects):
        if obj.type == "EMPTY" and obj.name.startswith(("PA", "TUT_", "ANIM_")):
            bpy.data.objects.remove(obj, do_unlink=True)
        elif obj.type == "CAMERA" and obj.name.startswith(("TutCam", "AnimCam")):
            bpy.data.objects.remove(obj, do_unlink=True)
    props = bpy.context.scene.andamios_props
    props.path_points.clear()
    props.calc_failures.clear()


def add_path(points_xy):
    props = bpy.context.scene.andamios_props
    for i, (x, y) in enumerate(points_xy):
        e = bpy.data.objects.new(f"ANIM_P{i}", None)
        e.location = (x, y, 0)
        bpy.context.scene.collection.objects.link(e)
        bpy.context.view_layer.update()
        pp = props.path_points.add()
        pp.obj = e
    bpy.context.view_layer.update()


def scaffold_bbox():
    coll = bpy.data.collections.get("Scaffold")
    if coll is None:
        return None
    pts = []
    for obj in coll.all_objects:
        if obj.type != 'MESH':
            continue
        if obj.name.startswith(('TutGround', 'TutSun')):
            continue
        M = obj.matrix_world
        for c in obj.bound_box:
            pts.append(M @ Vector(c))
    if not pts:
        return None
    bmin = Vector((min(p.x for p in pts),
                   min(p.y for p in pts),
                   min(p.z for p in pts)))
    bmax = Vector((max(p.x for p in pts),
                   max(p.y for p in pts),
                   max(p.z for p in pts)))
    return (bmin, bmax)


def make_camera(name, location, target):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = 50
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = location
    direction = Vector(target) - Vector(location)
    cam_obj.rotation_mode = 'QUATERNION'
    cam_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
    return cam_obj


def render_iso(out_path, size=(900, 560), fixed_distance=None):
    """Render iso del andamio. Si fixed_distance se pasa, usa esa distancia
    fija de cámara (útil para que las animaciones tengan tamaño consistente
    a lo largo de los frames)."""
    bbox = scaffold_bbox()
    if bbox is None:
        return
    bmin, bmax = bbox
    center = (bmin + bmax) * 0.5
    diag = (bmax - bmin).length
    d = fixed_distance if fixed_distance else max(diag * 1.4, 5.0)
    cam_loc = center + Vector((d, -d, d * 0.7))
    cam = make_camera("AnimCam", cam_loc, center)
    bpy.context.scene.camera = cam
    setup_render_quality(size)
    bpy.context.scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)


def render_front(out_path, size=(900, 560), fixed_scale=None):
    """Render frontal ortográfico."""
    bbox = scaffold_bbox()
    if bbox is None:
        return
    bmin, bmax = bbox
    center = (bmin + bmax) * 0.5
    diag = (bmax - bmin).length
    d = max((bmax.y - bmin.y) + diag, 8.0)
    cam_loc = Vector((center.x, bmin.y - d, center.z))
    cam_data = bpy.data.cameras.new("AnimCam")
    cam_data.lens = 50
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = fixed_scale or max(bmax.x - bmin.x, bmax.z - bmin.z) * 1.15
    cam = bpy.data.objects.new("AnimCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = cam_loc
    direction = center - Vector(cam_loc)
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
    bpy.context.scene.camera = cam
    setup_render_quality(size)
    bpy.context.scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)


def build_webp(frame_paths, out_path, duration_ms=1200):
    from PIL import Image
    frames = [Image.open(p).convert('RGBA') for p in frame_paths]
    frames[0].save(
        out_path, save_all=True, append_images=frames[1:],
        duration=duration_ms, loop=0, format='WebP',
        quality=80, method=6,
    )
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  ✓ {os.path.basename(out_path)} ({len(frames)} frames, {size_kb:.0f} KB)")


# ---------------------------------------------------------------------------
# Setup global
# ---------------------------------------------------------------------------

_wipe_default_objects()
setup_world_lighting()
setup_ground()


# ===========================================================================
# Anim 1: catálogo de longitudes UNIFORM / GENERIC / LAYHER
# ===========================================================================
print("[anim] catálogo")
catalog_pngs = []
for label in ('UNIFORM', 'GENERIC', 'LAYHER'):
    reset_scene()
    add_path([(0, 0), (8, 0)])
    props = bpy.context.scene.andamios_props
    props.floor_count = 1
    props.floor_height = 2.0
    props.bay_length_catalog = label
    if label == 'UNIFORM':
        props.section_length = 2.5
    andamios_addon.generate_scaffold(props, bpy.context)
    fp = os.path.join(ASSETS, f"anim_catalog_{label.lower()}.png")
    render_iso(fp, size=(900, 540), fixed_distance=15.0)
    catalog_pngs.append(fp)
build_webp(catalog_pngs, os.path.join(ASSETS, "anim_catalog_cycle.webp"),
           duration_ms=1800)


# ===========================================================================
# Anim 2: profundidad 0.640 / 0.732 / 1.090
# ===========================================================================
print("[anim] profundidad")
depth_pngs = []
for d in (0.640, 0.732, 1.090):
    reset_scene()
    add_path([(0, 0), (6, 0)])
    props = bpy.context.scene.andamios_props
    props.floor_count = 1
    props.floor_height = 2.0
    props.scaffold_depth = d
    andamios_addon.generate_scaffold(props, bpy.context)
    fp = os.path.join(ASSETS, f"anim_depth_{int(d*1000):04d}mm.png")
    render_iso(fp, size=(900, 540), fixed_distance=14.0)
    depth_pngs.append(fp)
build_webp(depth_pngs, os.path.join(ASSETS, "anim_depth_cycle.webp"),
           duration_ms=1800)


# ===========================================================================
# Anim 3: patrón cruces FRONT / BACK / BOTH / ALT
# ===========================================================================
print("[anim] patrón cruces")
pattern_pngs = []
for pat in ('FRONT', 'BACK', 'BOTH', 'ALT'):
    reset_scene()
    add_path([(0, 0), (10, 0)])
    props = bpy.context.scene.andamios_props
    props.floor_count = 2
    props.floor_height = 2.0
    props.brace_pattern = pat
    props.brace_subdivision = 'NONE'
    andamios_addon.generate_scaffold(props, bpy.context)
    fp = os.path.join(ASSETS, f"anim_pattern_{pat.lower()}.png")
    render_iso(fp, size=(900, 540), fixed_distance=18.0)
    pattern_pngs.append(fp)
build_webp(pattern_pngs, os.path.join(ASSETS, "anim_pattern_cycle.webp"),
           duration_ms=1500)


# ===========================================================================
# Anim 4-6: toggles ON/OFF (plataformas, cruces, anclajes)
# ===========================================================================
def render_toggle_pair(prop_name, on_value=True, off_value=False, label=""):
    """Renderiza un mismo andamio con prop_name=on y =off, devuelve los 2 paths."""
    paths = []
    for state, val in (('on', on_value), ('off', off_value)):
        reset_scene()
        add_path([(0, 0), (8, 0)])
        props = bpy.context.scene.andamios_props
        props.floor_count = 2
        props.floor_height = 2.0
        # Si activamos anclajes, hacer altura suficiente para que se vean
        if prop_name == 'add_ties':
            props.floor_count = 4
            if val:
                props.tie_every_bays = 2
                props.tie_every_floors = 1
        setattr(props, prop_name, val)
        andamios_addon.generate_scaffold(props, bpy.context)
        fp = os.path.join(ASSETS, f"anim_{label}_{state}.png")
        d = 18.0 if prop_name == 'add_ties' else 14.0
        render_iso(fp, size=(900, 540), fixed_distance=d)
        paths.append(fp)
    return paths


print("[anim] toggle plataformas")
build_webp(render_toggle_pair('add_decks', label='decks'),
           os.path.join(ASSETS, "anim_decks_toggle.webp"),
           duration_ms=1400)

print("[anim] toggle cruces")
build_webp(render_toggle_pair('add_braces', label='braces'),
           os.path.join(ASSETS, "anim_braces_toggle.webp"),
           duration_ms=1400)

print("[anim] toggle anclajes")
build_webp(render_toggle_pair('add_ties', label='ties'),
           os.path.join(ASSETS, "anim_ties_toggle.webp"),
           duration_ms=1400)


# ===========================================================================
# Anim 7: plantas creciendo 1→2→3→4→5
# ===========================================================================
print("[anim] plantas")
floors_pngs = []
for n_floors in (1, 2, 3, 4, 5):
    reset_scene()
    add_path([(0, 0), (8, 0)])
    props = bpy.context.scene.andamios_props
    props.floor_count = n_floors
    props.floor_height = 2.0
    andamios_addon.generate_scaffold(props, bpy.context)
    fp = os.path.join(ASSETS, f"anim_floors_n{n_floors}.png")
    # Distancia fija escalada con el max esperado (5 plantas × 2m = 10m)
    render_iso(fp, size=(900, 600), fixed_distance=18.0)
    floors_pngs.append(fp)
build_webp(floors_pngs, os.path.join(ASSETS, "anim_floors_grow.webp"),
           duration_ms=900)


# ===========================================================================
# Anim 8: subdivisión zigzag NONE / HALF / QUARTER (front view)
# ===========================================================================
print("[anim] subdivisión cruces (front)")
sub_pngs = []
for sub in ('NONE', 'HALF', 'QUARTER'):
    reset_scene()
    add_path([(0, 0), (8, 0)])
    props = bpy.context.scene.andamios_props
    props.floor_count = 3
    props.floor_height = 2.0
    props.brace_subdivision = sub
    andamios_addon.generate_scaffold(props, bpy.context)
    fp = os.path.join(ASSETS, f"anim_subdiv_{sub.lower()}.png")
    render_front(fp, size=(900, 700), fixed_scale=10.0)
    sub_pngs.append(fp)
build_webp(sub_pngs, os.path.join(ASSETS, "anim_subdivisions_zoom.webp"),
           duration_ms=2000)


print("\nAnimaciones comparativas generadas en", ASSETS)
