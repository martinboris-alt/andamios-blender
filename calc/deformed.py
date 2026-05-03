"""Visualización tipo ANSYS de la geometría deformada.

Tras un cálculo, cada tubo del andamio se desplaza ligeramente en sus dos
extremos según el campo de desplazamientos FEM. Los desplazamientos reales
suelen ser de pocos milímetros — invisibles en la escala del andamio. Se
amplifican por un factor `scale` (típico ×100) para que el modo de
deformación sea claro a simple vista.

Pipeline:
    1. `calc_run` (en ui.py) almacena en cada tubo un custom prop
       `_calc_disp = [dx_i, dy_i, dz_i, dx_j, dy_j, dz_j]` con el
       desplazamiento de sus dos extremos.
    2. `build_deformed_overlay(scene, scale)` lee esa info de cada
       objeto (sin necesidad de re-solver) y construye duplicados
       trasladados/rotados/escalados en la colección `Scaffold_Deformed`.
    3. `clear_deformed_overlay(scene)` elimina la colección.

Ventaja vs. recolocar la geometría original: el usuario ve **a la vez**
el andamio sin deformar y el deformado, igual que ANSYS muestra el
modelo de partida y el desplazado superpuesto.
"""

from __future__ import annotations

SCAFFOLD_COLLECTION_NAME = "Scaffold"
DEFORMED_COLLECTION_NAME = "Scaffold_Deformed"
DEFORMED_OBJ_SUFFIX = "_def"
CUSTOM_PROP_DISP = "_calc_disp"

# Paleta para la geometría deformada. A diferencia de la utilización, aquí
# el bucket 0 ("muy rígido") se pinta en GRIS para que actúe como contexto
# estructural sin competir visualmente con los miembros que sí se deforman.
# Estilo ANSYS: la silueta del andamio se conserva, sólo destacan en color
# las zonas que efectivamente se mueven.
DEFORMED_COLORS = (
    (0.50, 0.50, 0.50, 1.0),     # gris — sin deformación apreciable (contexto)
    (0.65, 0.85, 0.40, 1.0),     # verde-amarillo apagado — deformación pequeña
    (1.00, 1.00, 0.20, 1.0),     # amarillo — deformación moderada
    (1.00, 0.55, 0.10, 1.0),     # naranja — cerca del límite postes (L/200)
    (1.00, 0.20, 0.20, 1.0),     # rojo — cerca del límite plataforma (L/100)
    (0.50, 0.00, 0.00, 1.0),     # rojo oscuro — deformación excesiva
)
MAT_PREFIX_DEFORMED = "Calc_Deformed_"


def _ensure_deformed_materials():
    import bpy
    mats = []
    for i, color in enumerate(DEFORMED_COLORS):
        name = f"{MAT_PREFIX_DEFORMED}{i}"
        m = bpy.data.materials.get(name)
        if m is None:
            m = bpy.data.materials.new(name=name)
            m.use_nodes = False
        m.diffuse_color = color
        mats.append(m)
    return mats


def _ensure_deformed_collection(scene):
    import bpy
    coll = bpy.data.collections.get(DEFORMED_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(DEFORMED_COLLECTION_NAME)
        scene.collection.children.link(coll)
    return coll


def _set_scaffold_visibility(scene, *, visible: bool) -> None:
    """Activa/desactiva la visibilidad de la colección Scaffold.

    Se usa para que la vista deformada muestre **sólo** la geometría
    desplazada (estilo ANSYS) sin que el modelo original confunda al
    usuario. No elimina la colección — sólo cambia `hide_viewport`.
    """
    import bpy
    coll = bpy.data.collections.get(SCAFFOLD_COLLECTION_NAME)
    if coll is None:
        return
    coll.hide_viewport = (not visible)
    # También en el layer del view layer activo, para que se note al instante.
    try:
        layer_coll = bpy.context.view_layer.layer_collection.children.get(
            SCAFFOLD_COLLECTION_NAME
        )
        if layer_coll is not None:
            layer_coll.hide_viewport = (not visible)
    except (AttributeError, RuntimeError):
        pass


def _clear_collection_objects(coll):
    import bpy
    for obj in list(coll.objects):
        # Si tiene mesh propia exclusiva, también la eliminamos
        mesh = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _tube_local_endpoints(obj):
    """Recupera (z_min, z_max, longitud) en coordenadas locales del tubo."""
    zs = [c[2] for c in obj.bound_box]
    z_min, z_max = min(zs), max(zs)
    return z_min, z_max, (z_max - z_min)


def store_tube_displacements(model, results) -> int:
    """Persiste en cada objeto Blender el desplazamiento de sus dos extremos.

    El custom prop `_calc_disp` tiene 6 floats: (dx, dy, dz)_i, (dx, dy, dz)_j.
    Devuelve el número de objetos actualizados.
    """
    import bpy
    n = 0
    for mid, mem in model.members.items():
        obj_name = mid[2:] if mid.startswith("M_") else mid
        obj = bpy.data.objects.get(obj_name)
        if obj is None or obj.type != "MESH":
            continue
        ri = results.nodes.get(mem.i_node)
        rj = results.nodes.get(mem.j_node)
        if ri is None or rj is None:
            continue
        obj[CUSTOM_PROP_DISP] = [
            ri.DX, ri.DY, ri.DZ,
            rj.DX, rj.DY, rj.DZ,
        ]
        n += 1
    return n


def _displacement_to_bucket(d_max: float, length: float) -> int:
    """Mapea (δ_max, L) al bucket de color usando los mismos umbrales que
    `pipeline.deflection_ratio_to_bucket`."""
    from .pipeline import deflection_ratio_to_bucket
    if length <= 0:
        return 0
    return deflection_ratio_to_bucket(d_max / length)


def build_deformed_overlay(scene, *, scale: float = 100.0) -> int:
    """Construye la geometría deformada superpuesta.

    Para cada objeto del scaffold con custom prop `_calc_disp`:
        1. Recupera los desplazamientos i, j almacenados.
        2. Calcula los extremos deformados: p_def = p + scale · disp.
        3. Crea un duplicado del objeto en la colección Scaffold_Deformed
           reposicionado, rotado y escalado para coincidir con el segmento
           deformado.
        4. Aplica un material de la paleta según |disp| / longitud_local.

    Devuelve el número de tubos copiados.
    """
    import bpy
    from mathutils import Vector

    coll = _ensure_deformed_collection(scene)
    _clear_collection_objects(coll)
    mats = _ensure_deformed_materials()

    n = 0
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        if CUSTOM_PROP_DISP not in obj:
            continue
        # Si es uno de los duplicados antiguos lo saltamos (precaución)
        if obj.name.endswith(DEFORMED_OBJ_SUFFIX):
            continue

        disp_raw = obj.get(CUSTOM_PROP_DISP)
        try:
            d = list(disp_raw)
        except TypeError:
            continue
        if len(d) != 6:
            continue
        dxi, dyi, dzi, dxj, dyj, dzj = d

        # Extremos en mundo a partir de la matriz del objeto
        z_min, z_max, old_length = _tube_local_endpoints(obj)
        if old_length <= 1e-9:
            continue
        M = obj.matrix_world
        p_i = M @ Vector((0.0, 0.0, z_min))
        p_j = M @ Vector((0.0, 0.0, z_max))

        # Extremos deformados (amplificados)
        d_i_v = Vector((dxi, dyi, dzi)) * scale
        d_j_v = Vector((dxj, dyj, dzj)) * scale
        p_i_def = p_i + d_i_v
        p_j_def = p_j + d_j_v

        # Geometría del duplicado
        midpoint = (p_i_def + p_j_def) * 0.5
        delta = p_j_def - p_i_def
        new_length = delta.length
        if new_length <= 1e-9:
            continue

        # Mesh propia para que cada copia pueda llevar su material
        new_mesh = obj.data.copy()
        new_mesh.materials.clear()

        # Bucket por desplazamiento real (no amplificado) frente a longitud original
        d_max_real = max(d_i_v.length, d_j_v.length) / scale if scale > 0 else 0
        bucket = _displacement_to_bucket(d_max_real, old_length)
        new_mesh.materials.append(mats[bucket])

        copy = bpy.data.objects.new(obj.name + DEFORMED_OBJ_SUFFIX, new_mesh)
        coll.objects.link(copy)

        copy.location = midpoint
        copy.rotation_mode = 'QUATERNION'
        copy.rotation_quaternion = delta.to_track_quat('Z', 'Y')
        # Reescalar Z para ajustar la longitud (el resto de ejes igual)
        copy.scale = (1.0, 1.0, new_length / old_length)
        # Sin selección ni interacción: sólo visualización
        copy.hide_select = True

        n += 1

    if n > 0:
        # Ocultar la geometría original para que la deformada se lea sola
        # (estilo ANSYS — sólo se ve el modelo desplazado).
        _set_scaffold_visibility(scene, visible=False)

    return n


def clear_deformed_overlay(scene) -> int:
    """Elimina la colección Scaffold_Deformed y todos sus objetos.

    También restaura la visibilidad de la colección Scaffold (que se
    oculta automáticamente al mostrar la vista deformada).
    """
    import bpy
    coll = bpy.data.collections.get(DEFORMED_COLLECTION_NAME)
    n = 0
    if coll is not None:
        n = len(coll.objects)
        _clear_collection_objects(coll)
        try:
            scene.collection.children.unlink(coll)
        except RuntimeError:
            pass
        bpy.data.collections.remove(coll)
    # Devolver visibilidad al modelo original
    _set_scaffold_visibility(scene, visible=True)
    return n
