"""Genera los assets del tutorial v3 con encuadres cinemáticos.

Mejoras v3:
- Encuadre apretado: andamio ocupa ~85% del frame
- Iluminación 3-point (key + fill) con sun lights
- Suelo SOLO bajo la huella del andamio (no plano 40x40)
- Cámara con lente 80 mm (menos distorsión)
- Forzar bmin.z = 0 ignorando objetos colgantes
- Target a 55% del alto del andamio (no centro)

Ejecutar:
    /snap/bin/blender --background --python tutorial/build.py
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
# Setup escena
# ---------------------------------------------------------------------------

def wipe_default_objects():
    for obj in list(bpy.data.objects):
        if obj.type in {'MESH', 'CAMERA', 'LIGHT'} and obj.name in (
            'Cube', 'Camera', 'Light',
        ):
            bpy.data.objects.remove(obj, do_unlink=True)


def setup_lighting():
    """3-point: key + fill. Sin rim light (WORKBENCH no la utiliza bien)."""
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
    # Key
    key = bpy.data.lights.new("TutKey", type='SUN')
    key.energy = 3.5
    key.angle = math.radians(5)
    key_obj = bpy.data.objects.new("TutKey", key)
    key_obj.rotation_euler = (math.radians(50), 0, math.radians(35))
    scene.collection.objects.link(key_obj)
    # Fill
    fill = bpy.data.lights.new("TutFill", type='SUN')
    fill.energy = 1.2
    fill.angle = math.radians(15)
    fill_obj = bpy.data.objects.new("TutFill", fill)
    fill_obj.rotation_euler = (math.radians(35), 0, math.radians(-110))
    scene.collection.objects.link(fill_obj)


def setup_world():
    """Background con gradiente sutil — limitación: WORKBENCH ignora world
    nodes en algunos casos, pero los setea por si Cycles está activo."""
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("TutWorld")
        scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.86, 0.90, 0.94, 1.0)  # azul muy claro
    bg.inputs['Strength'].default_value = 1.0
    out = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])


def setup_ground(bbox):
    """Plano del tamaño justo bajo la huella, a z=0."""
    old = bpy.data.objects.get('TutGround')
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    if bbox is None:
        return
    bmin, bmax = bbox
    size_x = (bmax.x - bmin.x) + 4.0
    size_y = (bmax.y - bmin.y) + 4.0
    cx = (bmin.x + bmax.x) / 2
    cy = (bmin.y + bmax.y) / 2
    bpy.ops.mesh.primitive_plane_add(size=1, location=(cx, cy, -0.02))
    plane = bpy.context.object
    plane.name = 'TutGround'
    plane.scale = (size_x, size_y, 1)
    mat = bpy.data.materials.get('TutGround_M')
    if mat is None:
        mat = bpy.data.materials.new('TutGround_M')
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (0.93, 0.93, 0.94, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.95
    plane.data.materials.append(mat)


def setup_render_quality(size=(1600, 1000)):
    """WORKBENCH con shadows + cavity + studio matcap. Background azul claro."""
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = size[0]
    scene.render.resolution_y = size[1]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    sh = scene.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'MATERIAL'
    sh.show_shadows = True
    sh.shadow_intensity = 0.4
    sh.show_cavity = True
    sh.cavity_type = 'BOTH'
    sh.cavity_ridge_factor = 0.4
    sh.cavity_valley_factor = 1.2
    sh.curvature_ridge_factor = 1.5
    sh.curvature_valley_factor = 1.5
    if hasattr(scene.display, 'render_aa'):
        scene.display.render_aa = '16'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'Medium High Contrast'


def scaffold_bbox():
    """BBox solo del Scaffold, sin auxiliares."""
    coll = bpy.data.collections.get("Scaffold")
    if coll is None:
        return None
    pts = []
    for obj in coll.all_objects:
        if obj.type != 'MESH':
            continue
        if obj.name.startswith(('TutGround', 'TutKey', 'TutFill', 'TutSun')):
            continue
        M = obj.matrix_world
        for c in obj.bound_box:
            pts.append(M @ Vector(c))
    if not pts:
        return None
    bmin = Vector((min(p.x for p in pts), min(p.y for p in pts),
                   min(p.z for p in pts)))
    bmax = Vector((max(p.x for p in pts), max(p.y for p in pts),
                   max(p.z for p in pts)))
    return (bmin, bmax)


# ---------------------------------------------------------------------------
# CÁMARA: encuadre apretado
# ---------------------------------------------------------------------------

def fit_camera_iso(bbox, *, padding=0.10, lens_mm=80, azim_deg=40, elev_deg=28):
    """Cámara iso 3/4 con framing apretado.

    Forzando bmin.z = 0 (objetos colgantes ignorados). Target a 55% del alto.
    """
    bmin_orig, bmax = bbox
    bmin = Vector((bmin_orig.x, bmin_orig.y, 0.0))
    size = bmax - bmin
    target = Vector((
        (bmin.x + bmax.x) * 0.5,
        (bmin.y + bmax.y) * 0.5,
        size.z * 0.55,
    ))
    diag_xy = (size.x ** 2 + size.y ** 2) ** 0.5
    span = max(diag_xy, size.z * 1.1)

    cam_data = bpy.data.cameras.new("TutCamIso")
    cam_data.lens = lens_mm
    cam_data.clip_start = 0.1
    cam_data.clip_end = 200
    cam_obj = bpy.data.objects.new("TutCamIso", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)

    fov_rad = 2 * math.atan(36 / (2 * lens_mm))
    needed_d = span * (1 + 2 * padding) / (2 * math.tan(fov_rad / 2))
    elev = math.radians(elev_deg)
    azim = math.radians(azim_deg)
    horiz = needed_d * math.cos(elev)
    vert = needed_d * math.sin(elev)
    cam_obj.location = target + Vector((
        horiz * math.cos(azim),
        -horiz * math.sin(azim),
        vert,
    ))
    direction = target - Vector(cam_obj.location)
    cam_obj.rotation_mode = 'QUATERNION'
    cam_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
    return cam_obj


def fit_camera_front(bbox, *, padding=0.08):
    """Cámara ortográfica frontal (mirando -Y)."""
    bmin_orig, bmax = bbox
    bmin = Vector((bmin_orig.x, bmin_orig.y, 0.0))
    size = bmax - bmin
    target = Vector((
        (bmin.x + bmax.x) * 0.5,
        (bmin.y + bmax.y) * 0.5,
        size.z * 0.5,
    ))
    cam_data = bpy.data.cameras.new("TutCamFront")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = max(size.x, size.z) * (1 + 2 * padding)
    cam_obj = bpy.data.objects.new("TutCamFront", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = Vector((target.x, bmin.y - size.y - 5, target.z))
    direction = target - Vector(cam_obj.location)
    cam_obj.rotation_mode = 'QUATERNION'
    cam_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
    return cam_obj


def fit_camera_top(bbox, *, padding=0.08):
    """Cámara ortográfica vista en planta (mirando -Z)."""
    bmin_orig, bmax = bbox
    bmin = Vector((bmin_orig.x, bmin_orig.y, 0.0))
    size = bmax - bmin
    target = Vector((
        (bmin.x + bmax.x) * 0.5,
        (bmin.y + bmax.y) * 0.5,
        0,
    ))
    cam_data = bpy.data.cameras.new("TutCamTop")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = max(size.x, size.y) * (1 + 2 * padding)
    cam_obj = bpy.data.objects.new("TutCamTop", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = Vector((target.x, target.y, bmax.z + 10))
    direction = target - Vector(cam_obj.location)
    cam_obj.rotation_mode = 'QUATERNION'
    cam_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
    return cam_obj


def render_view(out_path, view='iso', size=(1600, 1000), iso_azim=None,
                 fixed_bbox=None):
    """Renderiza una vista (iso/front/top) con encuadre apretado.

    `iso_azim`: azimut en grados para forzar la cámara iso desde un ángulo
    específico (None = default 40°).
    `fixed_bbox`: si se pasa (tupla bmin, bmax), encuadra la cámara con ESE
    bbox en lugar del bbox actual del Scaffold. Esencial para animaciones:
    si cada frame tiene su propio bbox, la cámara salta entre frames y se
    ve "desfasado". Pasar el bbox del frame MÁS grande hace que todos los
    frames compartan el mismo encuadre.
    """
    bbox_for_camera = fixed_bbox if fixed_bbox is not None else scaffold_bbox()
    if bbox_for_camera is None:
        return
    # El ground SIEMPRE se dibuja al tamaño del bbox actual (no del fijo),
    # para que el suelo cubra exactamente la huella visible.
    actual_bbox = scaffold_bbox()
    if actual_bbox is not None:
        setup_ground(actual_bbox)
    if view == 'iso':
        cam = fit_camera_iso(bbox_for_camera,
                              azim_deg=iso_azim if iso_azim is not None else 40)
    elif view == 'front':
        cam = fit_camera_front(bbox_for_camera)
    elif view == 'top':
        cam = fit_camera_top(bbox_for_camera)
    else:
        return
    bpy.context.scene.camera = cam
    setup_render_quality(size)
    bpy.context.scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  ✓ {os.path.basename(out_path)} ({view}, {size_kb:.0f} KB)")


# ---------------------------------------------------------------------------
# Animación orbit con encuadre fijo
# ---------------------------------------------------------------------------

def render_orbit_webp(out_path, n_frames=36, size=(900, 560), duration_ms=80):
    """Cámara orbitando 360° manteniendo el target y la distancia fijos."""
    import tempfile
    from PIL import Image

    bbox = scaffold_bbox()
    if bbox is None:
        return
    setup_ground(bbox)

    bmin_orig, bmax = bbox
    bmin = Vector((bmin_orig.x, bmin_orig.y, 0.0))
    size_v = bmax - bmin
    target = Vector((
        (bmin.x + bmax.x) * 0.5,
        (bmin.y + bmax.y) * 0.5,
        size_v.z * 0.55,
    ))
    diag_xy = (size_v.x ** 2 + size_v.y ** 2) ** 0.5
    span = max(diag_xy, size_v.z * 1.1)
    lens_mm = 80
    fov_rad = 2 * math.atan(36 / (2 * lens_mm))
    radius = span * 1.20 / (2 * math.tan(fov_rad / 2))
    elev = math.radians(28)
    height_offset = radius * math.sin(elev)
    horiz_radius = radius * math.cos(elev)

    setup_render_quality(size)
    scene = bpy.context.scene

    with tempfile.TemporaryDirectory() as td:
        frame_paths = []
        for f in range(n_frames):
            angle = 2 * math.pi * f / n_frames
            cam_loc = Vector((
                target.x + math.cos(angle) * horiz_radius,
                target.y + math.sin(angle) * horiz_radius,
                target.z + height_offset,
            ))
            cam_data = bpy.data.cameras.new("Orbit")
            cam_data.lens = lens_mm
            cam = bpy.data.objects.new("Orbit", cam_data)
            scene.collection.objects.link(cam)
            cam.location = cam_loc
            direction = target - Vector(cam_loc)
            cam.rotation_mode = 'QUATERNION'
            cam.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
            scene.camera = cam
            fp = os.path.join(td, f"frame_{f:03d}.png")
            scene.render.filepath = fp
            bpy.ops.render.render(write_still=True)
            frame_paths.append(fp)
            bpy.data.objects.remove(cam, do_unlink=True)

        frames = [Image.open(p).convert('RGBA') for p in frame_paths]
        frames[0].save(
            out_path, save_all=True, append_images=frames[1:],
            duration=duration_ms, loop=0, format='WebP',
            quality=85, method=6,
        )
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  ✓ {os.path.basename(out_path)} ({n_frames} frames, {size_kb:.0f} KB)")


# ---------------------------------------------------------------------------
# Helpers de scene
# ---------------------------------------------------------------------------

def reset_scene():
    coll = bpy.data.collections.get("Scaffold")
    if coll is not None:
        for obj in list(coll.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in list(bpy.data.objects):
        if obj.type == "EMPTY" and obj.name.startswith(("PA", "TUT_")):
            bpy.data.objects.remove(obj, do_unlink=True)
        elif obj.type == "CAMERA" and obj.name.startswith("TutCam"):
            bpy.data.objects.remove(obj, do_unlink=True)
    props = bpy.context.scene.andamios_props
    props.path_points.clear()
    props.calc_failures.clear()


def add_path(points_xy):
    props = bpy.context.scene.andamios_props
    for i, (x, y) in enumerate(points_xy):
        e = bpy.data.objects.new(f"TUT_P{i}", None)
        e.location = (x, y, 0)
        bpy.context.scene.collection.objects.link(e)
        bpy.context.view_layer.update()
        pp = props.path_points.add()
        pp.obj = e
    bpy.context.view_layer.update()


def build_webp(frame_paths, out_path, duration_ms=900):
    from PIL import Image
    frames = [Image.open(p).convert('RGBA') for p in frame_paths]
    frames[0].save(
        out_path, save_all=True, append_images=frames[1:],
        duration=duration_ms, loop=0, format='WebP',
        quality=85, method=6,
    )
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  ✓ {os.path.basename(out_path)} ({len(frames)} frames, {size_kb:.0f} KB)")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

wipe_default_objects()
setup_lighting()
setup_world()


# ---- Ejemplo 1: recto ------------------------------------------------------
print("[ex1] Andamio recto")
reset_scene()
add_path([(0, 0), (8, 0)])
props = bpy.context.scene.andamios_props
props.floor_count = 2
props.floor_height = 2.0
props.brace_subdivision = 'NONE'
props.brace_pattern = 'BOTH'
props.add_ties = False
andamios_addon.generate_scaffold(props, bpy.context)
for v in ('iso', 'front', 'top'):
    render_view(os.path.join(ASSETS, f"ex1_recto_{v}.png"), v)


# ---- Ejemplo 2: L-shape ----------------------------------------------------
print("[ex2] Andamio L-shape")
reset_scene()
add_path([(0, 0), (6, 0), (6, 4)])
props = bpy.context.scene.andamios_props
props.floor_count = 2
props.brace_subdivision = 'NONE'
props.brace_pattern = 'BOTH'
andamios_addon.generate_scaffold(props, bpy.context)
# Para el L necesitamos azim distinto para que se vean los dos tramos
render_view(os.path.join(ASSETS, "ex2_lshape_iso.png"), 'iso', iso_azim=130)
render_view(os.path.join(ASSETS, "ex2_lshape_top.png"), 'top')


# ---- Ejemplo 3: TORRE FLAGSHIP — andamio cerrado 5 plantas con anclajes
# y sub-cruces zigzag. Para hero/orbit de la landing.
print("[ex3] Flagship — torre cerrada 5 plantas")
reset_scene()
add_path([(0, 0), (5, 0), (5, 5), (0, 5)])
props = bpy.context.scene.andamios_props
props.floor_count = 5
props.floor_height = 2.0
props.scaffold_depth = 0.732
props.closed_loop = True
props.brace_pattern = 'BOTH'
props.brace_subdivision = 'HALF'    # zigzag — más visualmente interesante
props.add_ties = True
props.tie_every_bays = 2
props.tie_every_floors = 2
props.tie_length = 0.5
andamios_addon.generate_scaffold(props, bpy.context)
# Vistas
render_view(os.path.join(ASSETS, "ex3_ushape_iso.png"), 'iso', iso_azim=130)
render_view(os.path.join(ASSETS, "ex3_ushape_front.png"), 'front')
render_view(os.path.join(ASSETS, "ex3_ushape_top.png"), 'top')
# Export GLB
bpy.ops.object.select_all(action='DESELECT')
for obj in bpy.data.collections["Scaffold"].all_objects:
    obj.select_set(True)
bpy.ops.export_scene.gltf(
    filepath=os.path.join(ASSETS, "ex3_ushape.glb"),
    export_format='GLB',
    use_selection=True,
    export_apply=True,
    export_yup=True,
)
print("  ✓ ex3_ushape.glb")
# Orbit con cámara fija (definida internamente)
print("  rendering orbit WebP (48 frames)...")
render_orbit_webp(os.path.join(ASSETS, "anim_orbit_ushape.webp"),
                  n_frames=48, size=(960, 600))


# ---- Ejemplo 4: Brace HALF / QUARTER --------------------------------------
for label, sub in [('half', 'HALF'), ('quarter', 'QUARTER')]:
    print(f"[ex4] Brace subdivision={sub}")
    reset_scene()
    add_path([(0, 0), (8, 0)])
    props = bpy.context.scene.andamios_props
    props.floor_count = 3
    props.brace_subdivision = sub
    andamios_addon.generate_scaffold(props, bpy.context)
    for v in ('iso', 'front'):
        render_view(os.path.join(ASSETS, f"ex4_braces_{label}_{v}.png"), v)


# ---- Ejemplo 5: anclajes ---------------------------------------------------
print("[ex5] Anclajes a fachada")
reset_scene()
add_path([(0, 0), (8, 0)])
props = bpy.context.scene.andamios_props
props.floor_count = 4
props.brace_subdivision = 'NONE'
props.add_ties = True
props.tie_every_bays = 2
props.tie_every_floors = 1
props.tie_length = 0.5
andamios_addon.generate_scaffold(props, bpy.context)
render_view(os.path.join(ASSETS, "ex5_ties_iso.png"), 'iso')


# ---- Ejemplo 6: escalera ---------------------------------------------------
print("[ex6] Escalera + trampilla")
reset_scene()
add_path([(0, 0), (10, 0)])
props = bpy.context.scene.andamios_props
props.floor_count = 2
props.add_ladders = True
props.add_lid_handle = True
andamios_addon.generate_scaffold(props, bpy.context)
render_view(os.path.join(ASSETS, "ex6_ladder_iso.png"), 'iso')


# ---- Ejemplo 7: torre ------------------------------------------------------
print("[ex7] Torre cerrada")
reset_scene()
add_path([(0, 0), (3, 0), (3, 3), (0, 3)])
props = bpy.context.scene.andamios_props
props.floor_count = 4
props.closed_loop = True
andamios_addon.generate_scaffold(props, bpy.context)
for v in ('iso', 'front'):
    render_view(os.path.join(ASSETS, f"ex7_torre_{v}.png"), v)


# ---- Animación "How it works" — orbit cinematográfico ---------------------
# Antes era una animación tipo "andamio creciendo de 1→6 plantas" pero
# entre frames había mucho espacio vacío (frame de 1 planta diminuto en
# bbox alto del f6). Ahora: orbit 360° del andamio completo — siempre
# llena el frame.
# Modelo: U-shape de 4 plantas con sub-cruces zigzag, anclajes y
# trampillas — claramente diferenciado del flagship (torre cerrada de
# 5 plantas) sin ser repetitivo.
print("[howitworks] Orbit del U-shape para HowItWorks")
reset_scene()
add_path([(0, 0), (8, 0), (8, 4)])
props = bpy.context.scene.andamios_props
props.floor_count = 4
props.floor_height = 2.0
props.scaffold_depth = 0.732
props.brace_pattern = 'BOTH'
props.brace_subdivision = 'HALF'
props.add_ties = True
props.tie_every_bays = 2
props.tie_every_floors = 2
props.tie_length = 0.5
andamios_addon.generate_scaffold(props, bpy.context)
render_orbit_webp(os.path.join(ASSETS, "anim_construction.webp"),
                  n_frames=36, size=(1100, 720))


print("\nTodos los assets generados en", ASSETS)
