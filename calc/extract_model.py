"""Extracción del grafo FEM desde la geometría del addon de andamios.

Recorre las colecciones `Postes`, `Travesaños`, `Cruces` y `Anclajes` dentro
de la colección raíz `Scaffold`, reconstruye los extremos de cada tubo y
devuelve un `Model` puro Python (sin referencias a bpy) listo para alimentar
solver.py.

Reglas de extracción
--------------------
- Cada `_make_tube(p1, p2, ...)` produce un mesh cilíndrico con:
      obj.location = (p1+p2)/2
      obj.rotation_quaternion = (p2-p1).to_track_quat('Z','Y')
      mesh local en eje Z con depth = ||p2-p1||
  Por tanto los extremos mundiales se recuperan con
      world @ (0, 0, ±L/2)
  donde L = max_z − min_z del bound_box local.

- Se aceptan únicamente los nombres con prefijos estructurales:
      Pole_F* / Pole_B*               → "pole"
      Ledger_*                        → "ledger"
      Brace_* / HBrace_*              → "brace"
      Tie_*                           → "tie"

- Se rechazan los sub-componentes decorativos identificables por sufijo:
      _sleeve, _capA, _capB, _cap, _head, _rod, _handle, _pin, _bar

- Los nodos se fusionan con tolerancia `tol` (1 mm por defecto). Este
  redondeo es conservador: las geometrías del addon proceden de operaciones
  algebraicas limpias y la deriva acumulada es muy inferior al milímetro.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .model import Model, S235JR, CHS_48_3x3_2


# Sufijos de objetos no estructurales que pueden aparecer dentro de las
# colecciones target. Cualquier objeto cuyo nombre contenga uno de estos
# fragmentos se ignora silenciosamente.
_NON_STRUCTURAL_SUFFIXES = (
    "_sleeve",
    "_capA", "_capB", "_cap",
    "_head",
    "_rod",
    "_handle",
    "_pin",
    "_bar",
)

_TYPE_BY_PREFIX = (
    ("Pole_F",  "pole"),
    ("Pole_B",  "pole"),
    ("Ledger_", "ledger"),
    ("Brace_",  "brace"),
    ("HBrace_", "brace"),
    ("Tie_",    "tie"),
)

_COLLECTION_NAMES = ("Postes", "Travesaños", "Cruces", "Anclajes")


def _classify(name: str) -> Optional[str]:
    """Devuelve el `member_type` para `name`, o None si debe ignorarse.

    Strip-ea prefijo de tramo (T0_, T1_, …) antes de clasificar — los
    andamios escalonados (multi-tramo) usan esos prefijos para evitar
    colisiones, pero la clasificación FEM debe reconocer los componentes
    por su tipo nominal (Pole_, Ledger_F_, etc.)."""
    import re as _re
    name = _re.sub(r"^T\d+_", "", name)
    for suf in _NON_STRUCTURAL_SUFFIXES:
        if suf in name:
            return None
    for prefix, mtype in _TYPE_BY_PREFIX:
        if name.startswith(prefix):
            return mtype
    return None


def _tube_endpoints(obj):
    """Devuelve los dos extremos mundiales de un tubo construido con
    `_make_tube` (cilindro local en Z).

    Robusto a meshes compartidos (instancing) porque sólo lee el bound_box
    local y la matriz mundial del objeto.
    """
    # bound_box: 8 esquinas del bounding box local en orden Blender.
    zs = [c[2] for c in obj.bound_box]
    z_min, z_max = min(zs), max(zs)
    L = z_max - z_min
    if L < 1e-6:
        return None
    M = obj.matrix_world
    p_a = M @ _vec(0.0, 0.0, z_min)
    p_b = M @ _vec(0.0, 0.0, z_max)
    return (p_a.x, p_a.y, p_a.z), (p_b.x, p_b.y, p_b.z), L


def _vec(x, y, z):
    """Pequeño wrapper para evitar importar mathutils desde los tests."""
    from mathutils import Vector  # import local: sólo se ejecuta con bpy disponible
    return Vector((x, y, z))


def _iter_target_objects(scene):
    """Itera por todos los objetos mesh dentro de las colecciones target."""
    root = None
    for c in scene.collection.children_recursive:
        if c.name == "Scaffold":
            root = c
            break
    if root is None:
        return
    by_name = {c.name: c for c in root.children_recursive}
    for cname in _COLLECTION_NAMES:
        coll = by_name.get(cname)
        if coll is None:
            continue
        for obj in coll.all_objects:
            if obj.type != "MESH":
                continue
            yield obj


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def extract_from_scene(
    scene=None,
    *,
    tol: float = 1e-3,
    material=None,
    section=None,
) -> Model:
    """Construye un `Model` desde la escena de Blender activa.

    Parameters
    ----------
    scene : bpy.types.Scene, opcional
        Si es None, usa `bpy.context.scene`.
    tol : float
        Tolerancia de fusión de nodos en metros (1 mm por defecto).
    material, section
        Material y sección a aplicar a TODAS las barras en Fase 1.
        En Fase 4 se diferenciará por tipo de elemento.
    """
    import bpy  # import local: el paquete no debe romper sin Blender
    if scene is None:
        scene = bpy.context.scene
    bpy.context.view_layer.update()       # garantiza matrix_world coherente

    if material is None:
        material = S235JR
    if section is None:
        section = CHS_48_3x3_2

    model = Model()
    model.add_material(material)
    model.add_section(section)

    skipped = 0
    accepted = 0
    for obj in _iter_target_objects(scene):
        mtype = _classify(obj.name)
        if mtype is None:
            skipped += 1
            continue
        ends = _tube_endpoints(obj)
        if ends is None:
            skipped += 1
            continue
        (ax, ay, az), (bx, by, bz), _L = ends
        ni = model.get_or_create_node(ax, ay, az, tol=tol)
        nj = model.get_or_create_node(bx, by, bz, tol=tol)
        if ni == nj:
            # Tubo degenerado tras snapping (no debería pasar)
            skipped += 1
            continue
        model.add_member(
            i_node=ni,
            j_node=nj,
            section=section.name,
            material=material.name,
            member_type=mtype,
            id=f"M_{obj.name}",
        )
        accepted += 1

    # Adjuntamos un mini-resumen al model como atributo arbitrario para
    # que los operadores de Blender lo puedan reportar.
    model._extract_summary = {     # type: ignore[attr-defined]
        "accepted": accepted,
        "skipped": skipped,
    }
    return model


def extract_from_iter(
    objects: Iterable,
    *,
    tol: float = 1e-3,
    material=None,
    section=None,
) -> Model:
    """Variante para tests / scripts: recibe un iterable de objetos en lugar
    de buscar la colección Scaffold."""
    import bpy  # noqa: F401
    if material is None:
        material = S235JR
    if section is None:
        section = CHS_48_3x3_2

    model = Model()
    model.add_material(material)
    model.add_section(section)

    for obj in objects:
        mtype = _classify(obj.name)
        if mtype is None:
            continue
        ends = _tube_endpoints(obj)
        if ends is None:
            continue
        (ax, ay, az), (bx, by, bz), _L = ends
        ni = model.get_or_create_node(ax, ay, az, tol=tol)
        nj = model.get_or_create_node(bx, by, bz, tol=tol)
        if ni == nj:
            continue
        model.add_member(
            i_node=ni,
            j_node=nj,
            section=section.name,
            material=material.name,
            member_type=mtype,
            id=f"M_{obj.name}",
        )
    return model
