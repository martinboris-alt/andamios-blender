"""Captura automática de imágenes del viewport para incluir en el informe.

Usa una cámara temporal posicionada en una vista 3/4 isométrica encuadrando
la barra a fotografiar. La imagen se renderiza con `bpy.ops.render.opengl`
(rápido y con el aspecto del viewport — adecuado para documentación) y se
devuelve como bytes PNG, listos para embeber en el HTML como base64.

Diseño:
    1. Localiza el objeto Blender por nombre (strip del prefijo `M_` que
       añade extract_model.py).
    2. Calcula el bounding-box mundial del objeto y extrae centro + diagonal.
    3. Crea una cámara temporal a `distance = diagonal · k` del centro,
       en una dirección fija (3/4 isométrica) mirando al centro.
    4. Configura `scene.camera` y `scene.render` (resolución + formato PNG).
    5. Renderiza con OpenGL a un fichero temporal, lee los bytes y limpia.
    6. Restaura la configuración de render anterior.

Headless-compatible: el OpenGL renderer no necesita un viewport activo si
la escena tiene una cámara asignada.
"""

from __future__ import annotations

import os
import tempfile


# Distancia: factor por el que se multiplica la diagonal del bbox para
# situar la cámara. Con 4× se ve la barra con un margen razonable.
DISTANCE_FACTOR = 4.0
# Distancia mínima absoluta (m) — evita que la cámara quede demasiado
# cerca para tubos muy cortos.
MIN_DISTANCE = 2.0
# Lente (mm). 35 mm da una vista ligeramente angular sin distorsión grosera.
CAMERA_LENS_MM = 35.0


def _resolve_obj_name(member_id: str) -> str:
    return member_id[2:] if member_id.startswith("M_") else member_id


def capture_member_screenshot(
    scene,
    member_id: str,
    *,
    size: int = 600,
    background_white: bool = True,
) -> bytes | None:
    """Captura una imagen del miembro indicado mediante cámara temporal.

    Devuelve los bytes PNG, o None si el objeto no se encuentra. Restaura
    la configuración de render que tuviera la escena.
    """
    import bpy
    from mathutils import Vector

    obj_name = _resolve_obj_name(member_id)
    obj = bpy.data.objects.get(obj_name)
    # Si la deformada está activa el original puede estar oculto — buscamos
    # el duplicado deformado como fallback.
    if obj is None:
        from .deformed import DEFORMED_OBJ_SUFFIX
        obj = bpy.data.objects.get(obj_name + DEFORMED_OBJ_SUFFIX)
    if obj is None:
        return None

    # Bounding box mundial del objeto
    bbox_corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [p.x for p in bbox_corners]
    ys = [p.y for p in bbox_corners]
    zs = [p.z for p in bbox_corners]
    bbox_min = Vector((min(xs), min(ys), min(zs)))
    bbox_max = Vector((max(xs), max(ys), max(zs)))
    center = (bbox_min + bbox_max) * 0.5
    diagonal = (bbox_max - bbox_min).length

    distance = max(diagonal * DISTANCE_FACTOR, MIN_DISTANCE)

    # Dirección 3/4 isométrica: ligeramente lateral + un poco arriba
    direction = Vector((1.0, -1.0, 0.7)).normalized()
    cam_loc = center + direction * distance

    # Cámara temporal
    cam_data = bpy.data.cameras.new("Calc_TmpCam")
    cam_data.lens = CAMERA_LENS_MM
    cam_obj = bpy.data.objects.new("Calc_TmpCam", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = cam_loc
    look_dir = (center - cam_loc).normalized()
    cam_obj.rotation_mode = 'QUATERNION'
    cam_obj.rotation_quaternion = look_dir.to_track_quat('-Z', 'Y')

    # Guardar estado actual de render
    prev_cam = scene.camera
    prev_filepath = scene.render.filepath
    prev_x = scene.render.resolution_x
    prev_y = scene.render.resolution_y
    prev_format = scene.render.image_settings.file_format
    prev_film_transparent = getattr(scene.render, "film_transparent", False)

    # Configurar
    scene.camera = cam_obj
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    scene.render.filepath = tmp.name
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.image_settings.file_format = 'PNG'

    if background_white:
        # Fondo blanco para que el informe sea legible al imprimir
        try:
            scene.render.film_transparent = False
            world = scene.world
            if world is not None:
                world.use_nodes = False
                world.color = (1.0, 1.0, 1.0)
        except (AttributeError, RuntimeError):
            pass

    # Workbench engine: rápido, look de viewport, funciona headless.
    # OpenGL render era más rápido en GUI pero falla en --background.
    prev_engine = scene.render.engine

    png_bytes: bytes | None = None
    try:
        scene.render.engine = 'BLENDER_WORKBENCH'
        bpy.ops.render.render(write_still=True)
        with open(tmp.name, "rb") as fh:
            png_bytes = fh.read()
    except Exception as e:                                  # pragma: no cover
        print(f"[andamios] error capturando screenshot de {obj_name}: {e}")
    finally:
        # Restaurar estado
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        scene.camera = prev_cam
        scene.render.filepath = prev_filepath
        scene.render.resolution_x = prev_x
        scene.render.resolution_y = prev_y
        scene.render.image_settings.file_format = prev_format
        scene.render.engine = prev_engine
        try:
            scene.render.film_transparent = prev_film_transparent
        except AttributeError:
            pass
        # Limpiar cámara temporal
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)

    return png_bytes


# Materiales temporales para resaltar el elemento protagonista de cada foto.
HIGHLIGHT_GRAY_NAME = "Calc_Highlight_Gray"
HIGHLIGHT_HOT_NAME = "Calc_Highlight_Hot"


def _ensure_highlight_materials():
    """Crea o reutiliza los materiales temporales de resalto."""
    import bpy
    gray = bpy.data.materials.get(HIGHLIGHT_GRAY_NAME)
    if gray is None:
        gray = bpy.data.materials.new(HIGHLIGHT_GRAY_NAME)
        gray.use_nodes = False
    gray.diffuse_color = (0.78, 0.78, 0.78, 1.0)
    hot = bpy.data.materials.get(HIGHLIGHT_HOT_NAME)
    if hot is None:
        hot = bpy.data.materials.new(HIGHLIGHT_HOT_NAME)
        hot.use_nodes = False
    hot.diffuse_color = (1.00, 0.20, 0.10, 1.0)        # rojo brillante
    return gray, hot


def _set_scaffold_visible_temporarily(scene):
    """Devuelve un dict con el estado previo de visibilidad de Scaffold y
    fuerza su visibilidad al activo."""
    import bpy
    state: dict = {"coll": None, "prev": None, "layer": None, "layer_prev": None}
    coll = bpy.data.collections.get("Scaffold")
    if coll is None:
        return state
    state["coll"] = coll
    state["prev"] = coll.hide_viewport
    coll.hide_viewport = False
    try:
        layer = bpy.context.view_layer.layer_collection.children.get("Scaffold")
        if layer is not None:
            state["layer"] = layer
            state["layer_prev"] = layer.hide_viewport
            layer.hide_viewport = False
    except (AttributeError, RuntimeError):
        pass
    return state


def _restore_scaffold_visibility(state):
    if state.get("coll") is not None:
        state["coll"].hide_viewport = state["prev"]
    if state.get("layer") is not None:
        state["layer"].hide_viewport = state["layer_prev"]


def capture_failures_batch(
    scene, member_ids, *, size: int = 600,
) -> dict[str, bytes]:
    """Captura screenshots de varios miembros con resalto: pinta todo el
    Scaffold en gris claro y la barra protagonista en rojo brillante, para
    que cada foto del informe identifique al instante el elemento del
    que se habla.

    Devuelve dict `{member_id: png_bytes}` (omite los miembros que no
    se han podido encontrar). Restaura todos los materiales y la
    visibilidad de Scaffold al terminar.
    """
    import bpy
    out: dict[str, bytes] = {}
    if not member_ids:
        return out

    scaffold_coll = bpy.data.collections.get("Scaffold")
    if scaffold_coll is None:
        # Sin colección Scaffold no podemos hacer nada útil; cae al modo
        # simple sin highlight.
        for mid in member_ids:
            png = capture_member_screenshot(scene, mid, size=size)
            if png:
                out[mid] = png
        return out

    visibility = _set_scaffold_visible_temporarily(scene)
    gray_mat, hot_mat = _ensure_highlight_materials()

    # Snapshot del material slot 0 de cada objeto mesh del Scaffold
    snapshots: dict[str, object] = {}
    for obj in scaffold_coll.all_objects:
        if obj.type != "MESH" or not obj.material_slots:
            continue
        snapshots[obj.name] = obj.material_slots[0].material

    # Aplicar gris a todos
    for obj_name in snapshots:
        obj = bpy.data.objects.get(obj_name)
        if obj and obj.material_slots:
            obj.material_slots[0].material = gray_mat

    try:
        for mid in member_ids:
            obj_name = _resolve_obj_name(mid)
            obj = bpy.data.objects.get(obj_name)
            if obj is None or obj.type != "MESH":
                continue
            # Resaltar el target
            had_slot = bool(obj.material_slots)
            if had_slot:
                prev_mat_for_target = obj.material_slots[0].material
                obj.material_slots[0].material = hot_mat
            else:
                obj.data.materials.append(hot_mat)
                prev_mat_for_target = None

            # Capturar
            png = capture_member_screenshot(scene, mid, size=size)
            if png:
                out[mid] = png

            # Volver a gris (para no afectar la siguiente captura)
            if had_slot:
                obj.material_slots[0].material = gray_mat
            else:
                # No tenía slot; quitamos el material que añadimos
                if obj.data.materials:
                    obj.data.materials.pop(index=0)
    finally:
        # Restaurar materiales originales
        for obj_name, mat in snapshots.items():
            obj = bpy.data.objects.get(obj_name)
            if obj and obj.material_slots:
                obj.material_slots[0].material = mat
        # Restaurar visibilidad de Scaffold
        _restore_scaffold_visibility(visibility)

    return out


def png_to_base64_data_url(png_bytes: bytes) -> str:
    """Convierte bytes PNG en data-URL listo para `<img src="...">`."""
    import base64
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Vistas globales del andamio (overview): isometría, alzados, planta
# ---------------------------------------------------------------------------

def _scaffold_world_bbox(coll):
    """Calcula el bounding box mundial de toda la colección Scaffold."""
    from mathutils import Vector
    bmin = Vector((float("inf"), float("inf"), float("inf")))
    bmax = Vector((float("-inf"), float("-inf"), float("-inf")))
    found = False
    for obj in coll.all_objects:
        if obj.type != "MESH":
            continue
        found = True
        for corner in obj.bound_box:
            wc = obj.matrix_world @ Vector(corner)
            for i in range(3):
                if wc[i] < bmin[i]:
                    bmin[i] = wc[i]
                if wc[i] > bmax[i]:
                    bmax[i] = wc[i]
    if not found:
        return None
    return bmin, bmax


# Direcciones de cámara para cada vista global. Vector apunta DESDE el centro
# del andamio HACIA donde se sitúa la cámara.
_OVERVIEW_VIEW_DIRECTIONS = {
    "iso":   (1.0, -1.0, 0.7),          # isometría 3/4
    "front": (0.0, -1.0, 0.0),          # alzado frontal — mira en +Y
    "side":  (1.0,  0.0, 0.0),          # alzado lateral — mira en -X
    "top":   (0.0,  0.0, 1.0),          # planta — mira hacia abajo
}

# Etiquetas legibles para el HTML
OVERVIEW_VIEW_LABELS = {
    "iso":   "Isométrica",
    "front": "Alzado frontal",
    "side":  "Alzado lateral",
    "top":   "Planta",
    "cad":   "Plano técnico (CAD)",
}


def capture_overview_view(
    scene,
    view: str,
    *,
    size: int = 800,
    ortho: bool | None = None,
    cad_style: bool = False,
) -> bytes | None:
    """Captura una vista global del andamio completo.

    `view` ∈ {"iso", "front", "side", "top"}. Para `front`/`side`/`top` la
    cámara se pone en ortográfica por defecto (estilo plano técnico).
    Para `iso` perspectiva por defecto.

    `cad_style=True` fuerza el shading con line art (outline marcado +
    fondo blanco + iluminación plana) — útil para "plano CAD".
    """
    import bpy
    from mathutils import Vector

    if view not in _OVERVIEW_VIEW_DIRECTIONS:
        raise ValueError(f"Vista desconocida: {view!r}")
    if ortho is None:
        ortho = (view != "iso")

    coll = bpy.data.collections.get("Scaffold")
    if coll is None:
        return None
    bbox = _scaffold_world_bbox(coll)
    if bbox is None:
        return None
    bmin, bmax = bbox
    center = (bmin + bmax) * 0.5
    diagonal = (bmax - bmin).length
    if diagonal <= 1e-6:
        return None

    direction = Vector(_OVERVIEW_VIEW_DIRECTIONS[view]).normalized()
    distance = max(diagonal * 1.5, 5.0)
    cam_loc = center + direction * distance

    # Cámara temporal
    cam_data = bpy.data.cameras.new("Calc_TmpOverview")
    cam_data.lens = 50
    if ortho:
        cam_data.type = 'ORTHO'
        # Margen para que la estructura quepa con holgura
        cam_data.ortho_scale = diagonal * 1.15
    cam_obj = bpy.data.objects.new("Calc_TmpOverview", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = cam_loc
    look_dir = (center - cam_loc).normalized()
    cam_obj.rotation_mode = 'QUATERNION'
    # Para top view, evitar look_dir (0,0,-1) con up='Y' que es válido
    cam_obj.rotation_quaternion = look_dir.to_track_quat('-Z', 'Y')

    # Estado previo de render
    prev_cam = scene.camera
    prev_filepath = scene.render.filepath
    prev_x = scene.render.resolution_x
    prev_y = scene.render.resolution_y
    prev_format = scene.render.image_settings.file_format
    prev_engine = scene.render.engine
    prev_world_color = None
    prev_shading_light = None
    prev_shading_color_type = None
    prev_shading_single_color = None

    scene.camera = cam_obj
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    scene.render.filepath = tmp.name
    scene.render.resolution_x = size
    # Top view aspect ratio adaptable a planta: rectangular si bbox alargado
    if view == "top":
        # Usar relación bbox X/Y para que la planta no se distorsione
        ratio = max(0.4, min(2.5,
                             (bmax[0]-bmin[0]) / max(0.001, bmax[1]-bmin[1])))
        scene.render.resolution_y = int(size / ratio)
    else:
        scene.render.resolution_y = size
    scene.render.image_settings.file_format = 'PNG'

    # Fondo blanco (preferido en informes técnicos)
    world = scene.world
    if world is not None:
        try:
            prev_world_color = tuple(world.color)
            world.use_nodes = False
            world.color = (1.0, 1.0, 1.0)
        except (AttributeError, RuntimeError):
            pass

    # Shading CAD: iluminación plana + un solo color
    if cad_style:
        try:
            shading = scene.display.shading
            prev_shading_light = shading.light
            prev_shading_color_type = shading.color_type
            prev_shading_single_color = tuple(shading.single_color)
            shading.light = 'FLAT'
            shading.color_type = 'SINGLE'
            shading.single_color = (0.85, 0.85, 0.85)   # gris claro
        except (AttributeError, RuntimeError):
            pass

    png_bytes: bytes | None = None
    try:
        scene.render.engine = 'BLENDER_WORKBENCH'
        bpy.ops.render.render(write_still=True)
        with open(tmp.name, "rb") as fh:
            png_bytes = fh.read()
    except Exception as e:                                  # pragma: no cover
        print(f"[andamios] error capturando vista {view}: {e}")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        scene.camera = prev_cam
        scene.render.filepath = prev_filepath
        scene.render.resolution_x = prev_x
        scene.render.resolution_y = prev_y
        scene.render.image_settings.file_format = prev_format
        scene.render.engine = prev_engine
        if prev_world_color is not None and world is not None:
            try:
                world.color = prev_world_color
            except (AttributeError, RuntimeError):
                pass
        if cad_style and prev_shading_light is not None:
            try:
                scene.display.shading.light = prev_shading_light
                scene.display.shading.color_type = prev_shading_color_type
                scene.display.shading.single_color = prev_shading_single_color
            except (AttributeError, RuntimeError):
                pass
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)

    return png_bytes


def capture_overview_set(
    scene,
    *,
    size: int = 800,
    include_cad: bool = True,
) -> dict[str, bytes]:
    """Captura un set de vistas globales del andamio:
        - iso   isometría 3/4 perspectiva
        - front alzado frontal ortográfico
        - side  alzado lateral ortográfico
        - top   planta ortográfica
        - cad   (opcional) plano técnico estilo CAD desde isometría

    Devuelve dict `{view: png_bytes}` (omite las que fallen).
    """
    out: dict[str, bytes] = {}
    for view in ("iso", "front", "side", "top"):
        png = capture_overview_view(scene, view, size=size)
        if png:
            out[view] = png
    if include_cad:
        png = capture_overview_view(scene, "iso", size=size, cad_style=True)
        if png:
            out["cad"] = png
    return out
