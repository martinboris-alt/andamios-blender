"""Coloreado del viewport de Blender en función de la utilización por barra.

Crea un set de materiales `Calc_Util_<bucket>` con colores graduados
verde→rojo y los asigna al slot 0 de cada tubo según su utilización.
Preserva el material original en una custom property `_calc_orig_mat`
para poder restaurarlo después.

Mapeo de buckets (utilización demanda/capacidad EN 1993-1-1):

    bucket 0   u < 0.50    verde brillante      (holgura amplia)
    bucket 1   u < 0.70    verde-amarillo       (holgura razonable)
    bucket 2   u < 0.85    amarillo             (cerca del límite)
    bucket 3   u < 1.00    naranja              (al límite, OK)
    bucket 4   u < 1.30    rojo                 (FALLO)
    bucket 5   u ≥ 1.30    rojo oscuro          (fallo grave)

Las membranas existentes en el addon (`color_pole`, `color_ledger`, etc.)
quedan intactas hasta que se llame a `apply_check_colors`. El operador de
restauración devuelve cada objeto a su material original.
"""

from __future__ import annotations

from typing import Mapping

from .checks import MemberCheckResult


# Colores RGBA por bucket (orden ascendente de utilización)
UTIL_COLORS: list[tuple[float, float, float, float]] = [
    (0.20, 0.90, 0.20, 1.0),     # verde brillante
    (0.60, 0.90, 0.20, 1.0),     # verde-amarillo
    (1.00, 1.00, 0.20, 1.0),     # amarillo
    (1.00, 0.55, 0.10, 1.0),     # naranja
    (1.00, 0.20, 0.20, 1.0),     # rojo
    (0.50, 0.00, 0.00, 1.0),     # rojo oscuro
]
UTIL_THRESHOLDS: list[float] = [0.50, 0.70, 0.85, 1.00, 1.30]

# Para deformaciones reusamos la misma paleta de 6 buckets — el coloreado
# es coherente visualmente entre ambos modos (rojo siempre = problema).
DEFL_COLORS = UTIL_COLORS

CUSTOM_PROP_ORIG_MAT = "_calc_orig_mat"
MAT_PREFIX_UTIL = "Calc_Util_"
MAT_PREFIX_DEFL = "Calc_Defl_"
# Compatibilidad con código antiguo
MAT_PREFIX = MAT_PREFIX_UTIL


def util_to_bucket(util: float) -> int:
    """Devuelve el índice de bucket [0..5] para una utilización."""
    for i, t in enumerate(UTIL_THRESHOLDS):
        if util < t:
            return i
    return len(UTIL_COLORS) - 1


def _ensure_palette_materials(prefix: str, colors):
    """Crea o reutiliza los materiales `<prefix>0..N` y los devuelve."""
    import bpy
    mats = []
    for i, color in enumerate(colors):
        name = f"{prefix}{i}"
        m = bpy.data.materials.get(name)
        if m is None:
            m = bpy.data.materials.new(name=name)
            m.use_nodes = False
        m.diffuse_color = color
        mats.append(m)
    return mats


def _ensure_util_materials():
    return _ensure_palette_materials(MAT_PREFIX_UTIL, UTIL_COLORS)


def _ensure_defl_materials():
    return _ensure_palette_materials(MAT_PREFIX_DEFL, DEFL_COLORS)


def _resolve_obj_name(member_id: str) -> str:
    """Recupera el nombre del objeto Blender desde el id de la barra.

    `extract_model.py` construye los ids como `M_<obj_name>`. Esta función
    es el inverso. Para ids que no siguen ese patrón, devuelve el id tal cual.
    """
    return member_id[2:] if member_id.startswith("M_") else member_id


def apply_check_colors(checks: Mapping[str, MemberCheckResult]) -> dict[int, int]:
    """Reemplaza el material slot 0 de cada barra del modelo por su bucket.

    `checks` es el `dict[member_id → MemberCheckResult]` devuelto por
    `run_all_checks`. Se silencian las barras cuyo objeto Blender no
    pueda localizarse (e.g. el modelo se ha regenerado entre análisis y
    los nombres han cambiado).

    Devuelve un dict `{bucket_index: count}` para diagnóstico.
    """
    import bpy
    mats = _ensure_util_materials()
    counts: dict[int, int] = {i: 0 for i in range(len(mats))}

    for mid, res in checks.items():
        obj_name = _resolve_obj_name(mid)
        obj = bpy.data.objects.get(obj_name)
        if obj is None or obj.type != "MESH":
            continue
        bucket = util_to_bucket(res.utilization)

        # Guardar material original sólo la primera vez
        if CUSTOM_PROP_ORIG_MAT not in obj:
            if obj.material_slots and obj.material_slots[0].material is not None:
                obj[CUSTOM_PROP_ORIG_MAT] = obj.material_slots[0].material.name
            else:
                obj[CUSTOM_PROP_ORIG_MAT] = ""

        # Reasignar al material del bucket
        if not obj.material_slots:
            obj.data.materials.append(mats[bucket])
        else:
            obj.material_slots[0].material = mats[bucket]
        counts[bucket] += 1

    return counts


def apply_deflection_colors(deflections) -> dict[int, int]:
    """Reemplaza el material slot 0 de cada barra por su bucket de
    deformación. `deflections` es el dict que devuelve
    `pipeline.compute_member_deflections`.
    """
    import bpy
    mats = _ensure_defl_materials()
    counts: dict[int, int] = {i: 0 for i in range(len(mats))}

    for mid, info in deflections.items():
        obj_name = _resolve_obj_name(mid)
        obj = bpy.data.objects.get(obj_name)
        if obj is None or obj.type != "MESH":
            continue
        bucket = int(info["bucket"])
        if bucket >= len(mats):
            bucket = len(mats) - 1

        if CUSTOM_PROP_ORIG_MAT not in obj:
            if obj.material_slots and obj.material_slots[0].material is not None:
                obj[CUSTOM_PROP_ORIG_MAT] = obj.material_slots[0].material.name
            else:
                obj[CUSTOM_PROP_ORIG_MAT] = ""

        if not obj.material_slots:
            obj.data.materials.append(mats[bucket])
        else:
            obj.material_slots[0].material = mats[bucket]
        counts[bucket] += 1

    return counts


def restore_original_colors() -> int:
    """Restaura los materiales originales de todos los objetos coloreados
    por `apply_check_colors`. Devuelve el número de objetos restaurados."""
    import bpy
    n = 0
    for obj in bpy.data.objects:
        if CUSTOM_PROP_ORIG_MAT not in obj:
            continue
        orig_name = str(obj[CUSTOM_PROP_ORIG_MAT])
        if orig_name and orig_name in bpy.data.materials and obj.material_slots:
            obj.material_slots[0].material = bpy.data.materials[orig_name]
        del obj[CUSTOM_PROP_ORIG_MAT]
        n += 1
    return n
