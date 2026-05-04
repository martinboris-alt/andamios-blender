bl_info = {
    "name": "Andamios trayectoria",
    "author": "mjuica",
    "version": (0, 7, 16),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Andamios",
    "description": "Genera andamios paramétricos a lo largo de una polilínea (con esquinas) + cálculo estructural FEM",
    "category": "Add Mesh",
}

import bpy
import bmesh
from math import atan2, ceil, sqrt, tan, sin, cos, radians, pi
from mathutils import Vector
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import (
    FloatProperty, IntProperty, BoolProperty,
    PointerProperty, EnumProperty, StringProperty,
    CollectionProperty, FloatVectorProperty,
)
from bpy.types import Panel, Operator, PropertyGroup, UIList

SCAFFOLD_COLLECTION = "Scaffold"
TUBE_DIAM = 0.0489  # 48.3 mm typical scaffold tube (EN 39 / EN 12810 nominal: 48.3 mm)
PLANK_THICKNESS = 0.04
PLANK_WIDTH = 0.32
TOEBOARD_HEIGHT = 0.15


# ===========================================================================
# Sistema Ringlock europeo — constantes (EN 12810 / EN 12811 / EN 39)
# ---------------------------------------------------------------------------
# Conjunto de constantes que definen el sistema multidireccional Ringlock europeo,
# compatible de facto con Layher Allround, PERI UP Flex/Rosett, ULMA BRIO y Doka
# Ringlock. Estos valores son los que tipifica EN 12810/EN 12811 para los andamios
# de fachada con componentes prefabricados.
# ===========================================================================

SYSTEM_FAMILY = "Ringlock_EU"
LONGITUDINAL_MODULES = (0.73, 1.09, 1.57, 2.07, 2.57, 3.07)   # luces estándar en m
ROSETTE_PITCH_M = 0.50                                         # separación rosetas
SYSTEM_WIDTHS = (0.73, 1.09)                                   # anchuras de andamio
TUBE_OUTER_DIAMETER = 0.0483                                   # m, Ø48,3 mm nominal
TUBE_WALL_THICKNESS = 0.0032                                   # m, 3,2 mm
DECK_WIDTHS = (0.32, 0.61)                                     # anchuras estándar bandeja
COMPATIBLE_BRANDS = (
    "Layher_Allround", "PERI_UP", "ULMA_BRIO", "Doka_Ringlock", "Generic_Ringlock_EU",
)
APPLICABLE_STANDARDS = (
    "EN 12810-1", "EN 12810-2", "EN 12811-1", "EN 12811-2", "EN 12811-3",
)
LOAD_CLASS_QK = {1: 0.75, 2: 1.50, 3: 2.00, 4: 3.00, 5: 4.50, 6: 6.00}  # kN/m²
DECK_GAP_MAX_MM = 25.0                                         # EN 12811-1


# ---------------------------------------------------------------------------
# Catálogo de bandejas Ringlock europeo (5 referencias precargadas)
# ---------------------------------------------------------------------------
# Valores estructurales (MRd, VRd, EI) son CONSERVADORES calculados desde la sección
# y la fy del material — no provienen de catálogo de fabricante específico. Marcado
# `is_estimated=True` para que el informe estructural lo señale. Cuando dispongamos
# de DoP / certificados Layher/PERI/ULMA, sustituir los valores aquí.
# ---------------------------------------------------------------------------

def _ringlock_deck(id_code, display_name, manufacturer, length, width, mass_kg,
                   construction, load_class, MRd, VRd, EI, functional="standard",
                   slip="R10", surface="perforated_antislip", is_estimated=True):
    return {
        "id_code": id_code,
        "display_name": display_name,
        "manufacturer": manufacturer,
        "system_family": SYSTEM_FAMILY,
        "system_compatibility": SYSTEM_FAMILY,
        "nominal_length": length,
        "deck_width": width,
        "total_width": width + 0.020,           # +20 mm por ganchos laterales
        "profile_height": 0.060 if "steel" in construction else 0.050,
        "hook_pitch": length,
        "hook_type": "claw_hinged",
        "construction_type": construction,
        "self_weight_kg": mass_kg,
        "weight_per_m2": mass_kg / max(0.01, length * width),
        "horizontal_projected_area": length * width,
        "vertical_projected_area": length * (0.060 if "steel" in construction else 0.050),
        "load_class": load_class,
        "qk_uniform_kN_m2": LOAD_CLASS_QK.get(load_class, 1.5),
        "F1_concentrated_kN": 1.5,
        "F2_concentrated_kN": 1.0,
        "MRd_kNm": MRd,
        "VRd_kN": VRd,
        "EI_kNm2": EI,
        "delta_admissible_ratio": 1.0 / 100.0,
        "slip_class": slip,
        "gap_to_adjacent_max_mm": DECK_GAP_MAX_MM,
        "integrated_toeboard": False,
        "anti_uplift": True,
        "fire_class": None,
        "functional_type": functional,
        "surface_finish": surface,
        "ce_marked": True,
        "certified_standards": APPLICABLE_STANDARDS,
        "is_estimated": is_estimated,
    }


# Helper: genera todas las longitudes para un perfil dado.
def _build_catalog():
    cat = {}
    # 6.1 Acero galvanizado, 0.32 m de ancho — disponible en TODAS las longitudes
    for L in LONGITUDINAL_MODULES:
        cls = 5 if L <= 1.57 else (4 if L <= 2.57 else 3)
        kg = 8.0 * L            # 8 kg/m
        # Conservadores aproximados (sección U 50×30×1.5 mm S350GD+Z, fy=350 MPa)
        MRd = 0.85 * (350e3 * 5e-6) / 1.10                   # kN·m
        VRd = 0.85 * (350e3 / 1.732 * 1.5e-4) / 1.10         # kN
        EI = 210e6 * 8e-7                                     # kN·m² aprox
        cat[f"Deck_Steel_032_{int(L*100):03d}"] = _ringlock_deck(
            id_code=f"Deck_Steel_032_{int(L*100):03d}",
            display_name=f"Deck Steel 0.32 × {L:.2f} m (clase {cls})",
            manufacturer="Generic_Ringlock_EU",
            length=L, width=0.32, mass_kg=kg,
            construction="steel", load_class=cls,
            MRd=round(MRd, 2), VRd=round(VRd, 1), EI=round(EI, 1),
        )
    # 6.2 Acero 0.61 m (perfil doble)
    for L in LONGITUDINAL_MODULES:
        cls = 5 if L <= 1.57 else (4 if L <= 2.57 else 3)
        kg = 14.0 * L           # ≈ 14 kg/m (doble perfil)
        cat[f"Deck_Steel_061_{int(L*100):03d}"] = _ringlock_deck(
            id_code=f"Deck_Steel_061_{int(L*100):03d}",
            display_name=f"Deck Steel 0.61 × {L:.2f} m (clase {cls})",
            manufacturer="Generic_Ringlock_EU",
            length=L, width=0.61, mass_kg=kg,
            construction="steel", load_class=cls,
            MRd=round(0.85 * 350e3 * 9e-6 / 1.10, 2),
            VRd=round(0.85 * 350e3 / 1.732 * 2.5e-4 / 1.10, 1),
            EI=round(210e6 * 1.5e-6, 1),
        )
    # 6.3 Marco aluminio + tablero LVL fenólico, 0.61 m
    for L in (1.57, 2.07, 2.57, 3.07):
        cat[f"Deck_AluLVL_061_{int(L*100):03d}"] = _ringlock_deck(
            id_code=f"Deck_AluLVL_061_{int(L*100):03d}",
            display_name=f"Deck Alu+LVL 0.61 × {L:.2f} m",
            manufacturer="Generic_Ringlock_EU",
            length=L, width=0.61, mass_kg=6.0 * L,           # más ligera
            construction="alu_lvl", load_class=3,
            MRd=round(0.75 * 260e3 * 8e-6 / 1.10, 2),
            VRd=round(0.75 * 260e3 / 1.732 * 2e-4 / 1.10, 1),
            EI=round(70e6 * 2e-6, 1),
            surface="phenolic_antislip",
        )
    # 6.4 Aluminio extruido completo, 0.32 m
    for L in (1.57, 2.07, 2.57, 3.07):
        cat[f"Deck_Aluminum_032_{int(L*100):03d}"] = _ringlock_deck(
            id_code=f"Deck_Aluminum_032_{int(L*100):03d}",
            display_name=f"Deck Aluminium 0.32 × {L:.2f} m",
            manufacturer="Generic_Ringlock_EU",
            length=L, width=0.32, mass_kg=4.5 * L,
            construction="aluminum", load_class=4,
            MRd=round(0.85 * 260e3 * 5e-6 / 1.10, 2),
            VRd=round(0.85 * 260e3 / 1.732 * 1.5e-4 / 1.10, 1),
            EI=round(70e6 * 8e-7, 1),
            surface="embossed",
        )
    # 6.5 Trampilla con escalera plegable (Alu+LVL 0.61 m)
    for L in (2.57, 3.07):
        cat[f"Deck_Trapdoor_AluLVL_061_{int(L*100):03d}"] = _ringlock_deck(
            id_code=f"Deck_Trapdoor_AluLVL_061_{int(L*100):03d}",
            display_name=f"Deck Trapdoor 0.61 × {L:.2f} m",
            manufacturer="Generic_Ringlock_EU",
            length=L, width=0.61, mass_kg=11.0 * L,            # +escalera
            construction="alu_lvl", load_class=3,
            MRd=round(0.75 * 260e3 * 8e-6 / 1.10, 2),
            VRd=round(0.75 * 260e3 / 1.732 * 2e-4 / 1.10, 1),
            EI=round(70e6 * 2e-6, 1),
            functional="trapdoor_with_ladder",
            surface="phenolic_antislip",
        )
    return cat


_RINGLOCK_DECK_CATALOG = _build_catalog()


def _deck_spec(deck_id):
    """Return the deck spec dict from the catalog, or None if not found."""
    return _RINGLOCK_DECK_CATALOG.get(deck_id)


def _find_matching_deck(target_length, target_width, material_pref="ANY", tol_mm=5.0):
    """Find the catalog deck whose nominal_length and deck_width best match the target.
    Returns (deck_id, length_error_mm, width_error_mm, exact_match_bool) or (None,...,False)
    if no entry passes the material filter.

    Scoring prioritises length match (more critical for span), then width."""
    best = None
    best_score = float('inf')
    for did, spec in _RINGLOCK_DECK_CATALOG.items():
        if material_pref != 'ANY':
            ct = spec["construction_type"]
            if material_pref == 'STEEL' and not ct.startswith("steel"):
                continue
            if material_pref == 'ALUMINUM' and ct != "aluminum":
                continue
            if material_pref == 'ALU_LVL' and ct != "alu_lvl":
                continue
        len_err = abs(spec["nominal_length"] - target_length)
        width_err = abs(spec["deck_width"] - target_width)
        score = len_err * 100 + width_err * 50
        if score < best_score:
            best_score = score
            best = did
    if best is None:
        return None, None, None, False
    spec = _RINGLOCK_DECK_CATALOG[best]
    len_err_mm = (spec["nominal_length"] - target_length) * 1000.0
    w_err_mm = (spec["deck_width"] - target_width) * 1000.0
    exact = abs(len_err_mm) <= tol_mm and abs(w_err_mm) <= tol_mm
    return best, len_err_mm, w_err_mm, exact


def deck_to_fem_loads(deck_id, bay_len=None, ledger_a_id=None, ledger_b_id=None):
    """Cargas que la bandeja transmite a sus dos travesaños receptores.

    No modela la bandeja como elemento viga del FEM (sobre-discretización innecesaria):
    devuelve cargas equivalentes que el solver puede aplicar a los ledgers.
    Stub para Fase estructural — los datos están listos, falta el solver que los consuma.
    """
    spec = _deck_spec(deck_id)
    if spec is None:
        return None
    g = 9.81
    sw_total_kN = spec["self_weight_kg"] * g / 1000.0
    qk = spec["qk_uniform_kN_m2"]
    return {
        "deck_id": deck_id,
        "self_weight_total_kN": round(sw_total_kN, 3),
        "self_weight_per_ledger_kN": round(sw_total_kN * 0.5, 3),
        "qk_uniform_kN_m2": qk,
        "qk_lineal_per_ledger_kN_m": round(qk * spec["deck_width"] * 0.5, 3),
        "F1_concentrated_kN": spec["F1_concentrated_kN"],
        "F2_concentrated_kN": spec["F2_concentrated_kN"],
        "ledger_a_id": ledger_a_id,
        "ledger_b_id": ledger_b_id,
        "bay_len": bay_len if bay_len is not None else spec["nominal_length"],
    }


def deck_verify_self_bending(deck_id, span, qd_design_kN_m2):
    """Verifica la bandeja como viga biapoyada con luz `span` y carga `qd_design` kN/m².
    EN 12811-1: comprobación local del propio deck. Devuelve util por concepto y pass/fail.
    """
    spec = _deck_spec(deck_id)
    if spec is None or span <= 1e-3:
        return None
    q = qd_design_kN_m2 * spec["deck_width"]      # kN/m
    L = span
    MEd = q * L * L / 8.0                          # kN·m
    VEd = q * L * 0.5                              # kN
    EI = max(0.001, spec["EI_kNm2"])
    delta_mm = 5.0 * q * (L ** 4) / (384.0 * EI) * 1000.0
    delta_lim_mm = L * spec["delta_admissible_ratio"] * 1000.0
    util_M = MEd / max(0.001, spec["MRd_kNm"])
    util_V = VEd / max(0.001, spec["VRd_kN"])
    util_d = delta_mm / max(0.001, delta_lim_mm)
    util_max = max(util_M, util_V, util_d)
    return {
        "deck_id": deck_id,
        "span": L,
        "qd_design": qd_design_kN_m2,
        "MEd_kNm": round(MEd, 3),  "MRd_kNm": spec["MRd_kNm"],  "util_M": round(util_M, 3),
        "VEd_kN":  round(VEd,  2), "VRd_kN":  spec["VRd_kN"],   "util_V": round(util_V, 3),
        "delta_mm": round(delta_mm, 2), "delta_lim_mm": round(delta_lim_mm, 2),
        "util_delta": round(util_d, 3),
        "util_max": round(util_max, 3),
        "pass": util_max <= 1.0,
    }


def _deck_catalog_enum_items(self, context):
    """Lista filtrable para EnumProperty. Filtros tomados de la prop activa."""
    props = context.scene.andamios_props
    items = []
    for k, v in _RINGLOCK_DECK_CATALOG.items():
        # Filtros opcionales
        if props.deck_filter_width != 'ANY':
            target = float(props.deck_filter_width)
            if abs(v["deck_width"] - target) > 0.01:
                continue
        if props.deck_filter_class != 'ANY':
            if v["load_class"] != int(props.deck_filter_class):
                continue
        if props.deck_filter_material != 'ANY':
            if not v["construction_type"].startswith(props.deck_filter_material.lower()):
                continue
        items.append((k, v["display_name"], f"{v['load_class']} kN class · {v['self_weight_kg']:.1f} kg"))
    if not items:
        items.append(('NONE', '— sin coincidencias —', ''))
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_collection(name, parent=None):
    parent = parent or bpy.context.scene.collection
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        parent.children.link(coll)
    elif coll.name not in {c.name for c in parent.children}:
        parent.children.link(coll)
    return coll


def _clear_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        return
    for child in list(coll.children):
        _clear_collection(child.name)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)


_TUBE_MESH_CACHE = {}   # (length, diameter, coll_name) → mesh
_BOX_MESH_CACHE = {}    # (sx, sy, sz, coll_name) → mesh


def _make_tube(p1, p2, diameter, name, coll):
    """Tube with mesh data SHARED across identical (length, diameter, collection)
    instances within a single generation. Drastically reduces mesh count for poles,
    standard ledgers, etc."""
    p1, p2 = Vector(p1), Vector(p2)
    direction = p2 - p1
    length = direction.length
    if length < 1e-6:
        return None
    mid = (p1 + p2) * 0.5
    key = (round(length, 4), round(diameter, 4), coll.name)
    mesh = _TUBE_MESH_CACHE.get(key)
    if mesh is None:
        mesh = bpy.data.meshes.new(f"TubeM_{coll.name}_{int(length*1000)}x{int(diameter*1000)}")
        bm = bmesh.new()
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            segments=12,
            radius1=diameter * 0.5,
            radius2=diameter * 0.5,
            depth=length,
        )
        bm.to_mesh(mesh)
        bm.free()
        _TUBE_MESH_CACHE[key] = mesh
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.location = mid
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = direction.to_track_quat('Z', 'Y')
    return obj


def _make_box(center, size, name, coll, rotation_z=0.0):
    """Box with mesh data SHARED across identical (sx, sy, sz, collection) instances."""
    cx, cy, cz = center
    sx, sy, sz = size
    key = (round(sx, 4), round(sy, 4), round(sz, 4), coll.name)
    mesh = _BOX_MESH_CACHE.get(key)
    if mesh is None:
        mesh = bpy.data.meshes.new(f"BoxM_{coll.name}_{int(sx*1000)}x{int(sy*1000)}x{int(sz*1000)}")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
        bm.to_mesh(mesh)
        bm.free()
        _BOX_MESH_CACHE[key] = mesh
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.location = (cx, cy, cz)
    obj.rotation_euler = (0.0, 0.0, rotation_z)
    return obj


def _make_rosette(pos, outer_diameter, inner_diameter, thickness, name, coll):
    """Annular rosette (Layher Allround style) wrapping around a pole.

    The hole has `inner_diameter` (≈ pole diameter) so the pole visually passes through
    the rosette and welds to it. The disc extends outward to `outer_diameter`.
    """
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    segments = 16
    z_bot = -thickness * 0.5
    z_top = thickness * 0.5
    R_o = outer_diameter * 0.5
    R_i = max(0.001, inner_diameter * 0.5)

    v_ob, v_ot, v_ib, v_it = [], [], [], []
    for s in range(segments):
        ang = 2.0 * pi * s / segments
        cs = cos(ang)
        sn = sin(ang)
        v_ob.append(bm.verts.new((R_o * cs, R_o * sn, z_bot)))
        v_ot.append(bm.verts.new((R_o * cs, R_o * sn, z_top)))
        v_ib.append(bm.verts.new((R_i * cs, R_i * sn, z_bot)))
        v_it.append(bm.verts.new((R_i * cs, R_i * sn, z_top)))
    bm.verts.ensure_lookup_table()
    for i in range(segments):
        j = (i + 1) % segments
        bm.faces.new([v_it[i], v_ot[i], v_ot[j], v_it[j]])           # top annulus
        bm.faces.new([v_ib[j], v_ob[j], v_ob[i], v_ib[i]])           # bottom annulus
        bm.faces.new([v_ob[i], v_ob[j], v_ot[j], v_ot[i]])           # outer side
        bm.faces.new([v_it[i], v_it[j], v_ib[j], v_ib[i]])           # inner side
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.location = pos
    return obj


def _make_jack_base(top_pos, jack_height, name, coll):
    """Husillo de base: vástago + plato cuadrado bajo el pole.

    top_pos: posición donde el pole empieza (= top del husillo).
    El husillo se extiende hacia abajo por jack_height; el plato apoya en el suelo.
    """
    if jack_height <= 0.001:
        return None
    plate_z_bottom = top_pos.z - jack_height
    plate_thickness = 0.02
    plate_center = Vector((top_pos.x, top_pos.y, plate_z_bottom + plate_thickness * 0.5))
    plate = _make_box(plate_center, (0.15, 0.15, plate_thickness), f"{name}_plate", coll)
    rod_bot = Vector((top_pos.x, top_pos.y, plate_z_bottom + plate_thickness))
    _make_tube(rod_bot, top_pos, TUBE_DIAM * 0.85, f"{name}_rod", coll)
    return plate


def _make_quad_plank(quad_xy, name, coll, thickness, z_top):
    """Create a planar 4-vertex plank from XY-positions. Top face at z_top."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    z_bot = z_top - thickness
    v_bot = [bm.verts.new((p.x, p.y, z_bot)) for p in quad_xy]
    v_top = [bm.verts.new((p.x, p.y, z_top)) for p in quad_xy]
    bm.verts.ensure_lookup_table()
    bm.faces.new(list(reversed(v_bot)))
    bm.faces.new(v_top)
    for k in range(4):
        nxt = (k + 1) % 4
        bm.faces.new([v_bot[k], v_bot[nxt], v_top[nxt], v_top[k]])
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def _make_trapdoor_lid(hinge_world, hinge_dir_xy, away_dir_xy, length, width, thickness, open_angle_rad, name, coll):
    """Create a hinged trapdoor lid as a tilted-up plank.

    hinge_world: world position of the hinge edge midpoint (Vector)
    hinge_dir_xy: unit XY vector along the hinge edge (mesh-local +x)
    away_dir_xy:  unit XY vector pointing from the hinge into the lid when CLOSED
    length:       lid dimension along the hinge
    width:        lid dimension from hinge to free edge (when closed)
    open_angle_rad: 0 = lid lying flat on the deck, pi/2 = vertical
    """
    h = Vector(hinge_dir_xy).normalized()
    a_closed = Vector(away_dir_xy).normalized()
    up = Vector((0.0, 0.0, 1.0))
    # Rotation around the hinge axis: y' = y cos θ + z sin θ, z' = -y sin θ + z cos θ
    a_tilted = a_closed * cos(open_angle_rad) + up * sin(open_angle_rad)
    z_tilted = -a_closed * sin(open_angle_rad) + up * cos(open_angle_rad)

    half_l = length * 0.5
    base = [
        h * (-half_l),
        h * ( half_l),
        h * ( half_l) + a_tilted * width,
        h * (-half_l) + a_tilted * width,
    ]
    top = [v + z_tilted * thickness for v in base]

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    v_bot = [bm.verts.new((p.x, p.y, p.z)) for p in base]
    v_top = [bm.verts.new((p.x, p.y, p.z)) for p in top]
    bm.verts.ensure_lookup_table()
    bm.faces.new(list(reversed(v_bot)))
    bm.faces.new(v_top)
    for k in range(4):
        nxt = (k + 1) % 4
        bm.faces.new([v_bot[k], v_bot[nxt], v_top[nxt], v_top[k]])
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.location = hinge_world
    return obj


def _make_hinge_marker(hinge_world, hinge_axis_xy, lid_length, name, coll):
    """Two cylindrical knuckles + a thin pin going through them along the hinge axis.

    The pin makes the hinge geometry obvious from any angle — workers can see at a
    glance which way the trapdoor opens.
    """
    a = Vector(hinge_axis_xy).normalized()
    knuckle_len = 0.06
    knuckle_diam = 0.035
    pin_diam = TUBE_DIAM * 0.20
    pin_len = lid_length * 0.85
    objs = []
    for offset_factor, suffix in ((-0.30, "L"), (+0.30, "R")):
        center = hinge_world + a * (offset_factor * lid_length)
        p1 = center - a * (knuckle_len * 0.5)
        p2 = center + a * (knuckle_len * 0.5)
        o = _make_tube(p1, p2, knuckle_diam, f"{name}_{suffix}", coll)
        if o is not None:
            objs.append(o)
    p1 = hinge_world - a * (pin_len * 0.5)
    p2 = hinge_world + a * (pin_len * 0.5)
    o = _make_tube(p1, p2, pin_diam, f"{name}_pin", coll)
    if o is not None:
        objs.append(o)
    return objs


def _make_lid_handle(hinge_world, hinge_dir_xy, away_dir_xy, lid_length, lid_width,
                     open_angle_rad, name, coll):
    """U-shaped handle on the free edge of the trapdoor lid.

    Two short posts perpendicular to the lid surface joined by a horizontal bar.
    Spans ~40 % of the hinge-edge length.
    """
    h = Vector(hinge_dir_xy).normalized()
    a_closed = Vector(away_dir_xy).normalized()
    up = Vector((0.0, 0.0, 1.0))
    a_tilted = a_closed * cos(open_angle_rad) + up * sin(open_angle_rad)
    z_tilted = -a_closed * sin(open_angle_rad) + up * cos(open_angle_rad)
    free_mid = hinge_world + a_tilted * (lid_width * 0.92)
    handle_height = 0.05
    handle_span = lid_length * 0.40
    p_left = free_mid + h * (-handle_span * 0.5)
    p_right = free_mid + h * (+handle_span * 0.5)
    p_left_top = p_left + z_tilted * handle_height
    p_right_top = p_right + z_tilted * handle_height
    handle_d = TUBE_DIAM * 0.30
    _make_tube(p_left, p_left_top, handle_d, f"{name}_l", coll)
    _make_tube(p_right, p_right_top, handle_d, f"{name}_r", coll)
    _make_tube(p_left_top, p_right_top, handle_d, f"{name}_bar", coll)


_MATERIAL_COLORS = {
    "Postes":      (0.20, 0.45, 0.85, 1.0),   # azul acero
    "Travesaños":  (0.40, 0.65, 0.95, 1.0),   # azul claro
    "Plataformas": (0.55, 0.35, 0.15, 1.0),   # marrón madera
    "Cruces":      (0.95, 0.45, 0.10, 1.0),   # naranja diagonal
    "Escaleras":   (0.85, 0.15, 0.15, 1.0),   # rojo
    "Barandillas": (1.00, 0.85, 0.00, 1.0),   # amarillo seguridad
    "Trampillas":  (0.20, 0.70, 0.30, 1.0),   # verde (tapa)
    "Anclajes":    (0.85, 0.85, 0.85, 1.0),   # gris claro (ties)
    "Husillos":    (0.55, 0.55, 0.60, 1.0),   # gris oscuro (jacks)
    "Acoples":     (0.30, 0.30, 0.35, 1.0),   # gris muy oscuro (rosettes)
}


_CATEGORY_PROP_MAP = {
    "Postes":      "color_postes",
    "Travesaños":  "color_travesanos",
    "Plataformas": "color_plataformas",
    "Cruces":      "color_cruces",
    "Escaleras":   "color_escaleras",
    "Barandillas": "color_barandillas",
    "Trampillas":  "color_trampillas",
    "Anclajes":    "color_anclajes",
    "Husillos":    "color_husillos",
    "Acoples":     "color_acoples",
}


def _get_category_material(category, props=None):
    name = f"Andamio_{category}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    # Pull color from user-configurable property if available, else fall back to defaults
    col = None
    if props is not None:
        prop_name = _CATEGORY_PROP_MAP.get(category)
        if prop_name and hasattr(props, prop_name):
            col = tuple(getattr(props, prop_name))
    if col is None:
        col = _MATERIAL_COLORS.get(category, (0.7, 0.7, 0.7, 1.0))
    mat.diffuse_color = col
    if mat.use_nodes:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = col
    return mat


def _apply_category_materials(root_coll, props=None):
    for sub in root_coll.children:
        mat = _get_category_material(sub.name, props)
        for obj in sub.objects:
            if obj.data is None or not hasattr(obj.data, "materials"):
                continue
            if len(obj.data.materials) == 0:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[0] = mat


def _ladder(p_bottom, p_top, width, rung_count, name, coll, side_axis=None):
    p_bot = Vector(p_bottom)
    p_top = Vector(p_top)
    up = p_top - p_bot
    if up.length < 1e-6 or rung_count <= 0:
        return []
    if side_axis is not None:
        side_v = Vector(side_axis)
        side_v.z = 0.0
        if side_v.length < 1e-6:
            side_v = Vector((1.0, 0.0, 0.0))
        side = side_v.normalized() * (width * 0.5)
    else:
        side = Vector((up.y, -up.x, 0.0))
        if side.length < 1e-6:
            side = Vector((1.0, 0.0, 0.0))
        side = side.normalized() * (width * 0.5)

    rail_d = TUBE_DIAM * 0.6
    rung_d = TUBE_DIAM * 0.5

    objs = []
    rail_a = _make_tube(p_bot + side, p_top + side, rail_d, f"{name}_rail_a", coll)
    rail_b = _make_tube(p_bot - side, p_top - side, rail_d, f"{name}_rail_b", coll)
    objs += [o for o in (rail_a, rail_b) if o]

    # Distribute rungs leaving a clearance from each extremity (~0.15 m, capped at 10 % of L
    # so very short ladders still get rungs).
    total_length = up.length
    clearance = min(0.15, total_length * 0.10)
    usable = max(1e-3, total_length - 2.0 * clearance)
    for i in range(rung_count):
        t = (clearance + (i + 0.5) * usable / rung_count) / total_length
        center_low = p_bot + (p_top - p_bot) * t
        a = center_low + side
        b = center_low - side
        r = _make_tube(a, b, rung_d, f"{name}_rung_{i:02d}", coll)
        if r:
            objs.append(r)
    return objs


def _ladder_handrail(p_bottom, p_top, side_axis, width, height, name, coll):
    """Pasamanos lateral elevado paralelo a un lado de la escalera.

    Geometría: un tubo a `height` sobre el `rail_a` de la escalera (lado +side)
    + 2 verticales cortos que conectan riel y pasamanos en los extremos.
    Sirve para el agarre del trabajador durante el ascenso (EN 12811 §7.2).

    Naming: `{name}_handrail`, `{name}_handrail_post_bot`, `{name}_handrail_post_top`.
    Estas piezas NO se cuentan como escalera independiente en BOM
    (`category_for_name` sólo cuenta `_rail_a`); van como sub-piezas.
    """
    p_bot = Vector(p_bottom)
    p_top = Vector(p_top)
    if (p_top - p_bot).length < 1e-6 or height <= 0:
        return []
    side_v = Vector(side_axis)
    side_v.z = 0.0
    if side_v.length < 1e-6:
        side_v = Vector((1.0, 0.0, 0.0))
    side = side_v.normalized() * (width * 0.5)
    up = Vector((0.0, 0.0, height))

    rail_d = TUBE_DIAM * 0.6   # mismo grosor que rieles principales
    post_d = TUBE_DIAM * 0.5

    rail_bot = p_bot + side          # extremo inferior del pasamanos = riel_a inferior
    rail_top = p_top + side          # extremo superior
    handrail_bot = rail_bot + up
    handrail_top = rail_top + up

    objs = []
    handrail = _make_tube(handrail_bot, handrail_top, rail_d,
                          f"{name}_handrail", coll)
    if handrail:
        objs.append(handrail)
    post_bot = _make_tube(rail_bot, handrail_bot, post_d,
                          f"{name}_handrail_post_bot", coll)
    if post_bot:
        objs.append(post_bot)
    post_top = _make_tube(rail_top, handrail_top, post_d,
                          f"{name}_handrail_post_top", coll)
    if post_top:
        objs.append(post_top)
    return objs


# ---------------------------------------------------------------------------
# Generator (polyline + corner handling)
# ---------------------------------------------------------------------------

_BAY_LENGTH_CATALOGS = {
    'GENERIC': [1.0, 1.5, 2.0, 2.5, 3.0],
    'LAYHER':  [0.73, 1.09, 1.40, 1.57, 1.73, 2.07, 2.57, 3.07],
}

_POLE_LENGTH_CATALOGS = {
    'GENERIC': [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
    'LAYHER':  [0.5, 1.0, 1.5, 2.0, 3.0, 4.0],
}


def _bay_lengths_for_segment(segment_length, catalog_lengths, max_leftover=0.05):
    """Find the combination of standard bay lengths that fits `segment_length` with the
    smallest possible leftover (compensation piece appended at the end if > max_leftover).

    Algorithm: dynamic programming over cm-discretised target. Reconstructs prefering the
    largest standard pieces (fewer joints, fewer pieces).
    """
    if not catalog_lengths or segment_length <= 0.01:
        return [max(0.0, segment_length)]

    target_cm = max(1, round(segment_length * 100))
    lens_cm = sorted({round(L * 100) for L in catalog_lengths if L > 0}, reverse=True)
    if not lens_cm:
        return [segment_length]

    reachable = [False] * (target_cm + 1)
    reachable[0] = True
    for i in range(target_cm + 1):
        if not reachable[i]:
            continue
        for L in lens_cm:
            j = i + L
            if j <= target_cm:
                reachable[j] = True

    best_cm = target_cm
    while best_cm > 0 and not reachable[best_cm]:
        best_cm -= 1

    pieces_cm = []
    cur = best_cm
    while cur > 0:
        for L in lens_cm:
            if L <= cur and reachable[cur - L]:
                pieces_cm.append(L)
                cur -= L
                break
        else:
            break

    pieces = [L / 100.0 for L in pieces_cm]
    leftover = segment_length - sum(pieces)
    if leftover > max_leftover:
        pieces.append(leftover)
    elif pieces and abs(leftover) > 1e-3:
        pieces[-1] += leftover
    return pieces


def _path_objects(props):
    return [item.obj for item in props.path_points if item.obj is not None]


def _compute_path_geometry(props):
    """Return (P, forwards, perps, seg_lens, front_corners, back_corners).

    P: world positions flattened to base_z (length n_verts).
    forwards/perps/seg_lens: per-segment unit vectors and lengths (length n_segs).
    front_corners: same as P (vertex positions on the front row).
    back_corners: per-vertex back-row positions, with bisector offset at interior corners
                  so the perpendicular distance to each adjacent segment equals depth.

    The "back" side is to the left of forward (90° CCW perp). Build your polyline
    so the scaffold extends to that side relative to the path direction.
    """
    objs = _path_objects(props)
    if len(objs) < 2:
        raise RuntimeError("Añade al menos 2 puntos a la trayectoria.")

    use_terrain = bool(getattr(props, 'use_terrain_z', False))
    base_z = props.base_z
    P = []
    for o in objs:
        v = o.matrix_world.translation.copy()
        if not use_terrain:
            v.z = base_z
        # Otherwise keep each empty's actual Z (= terrain elevation at that point)
        P.append(v)

    closed = bool(getattr(props, 'closed_loop', False)) and len(P) >= 3
    n_pts = len(P)
    n_segs = n_pts if closed else n_pts - 1
    forwards = []
    perps = []
    seg_lens = []
    for i in range(n_segs):
        i_next = (i + 1) % n_pts
        d = P[i_next] - P[i]
        L = d.length
        if L < 1e-3:
            raise RuntimeError(f"Los puntos {i} y {i_next} coinciden — sepáralos.")
        f = d / L
        forwards.append(f)
        perps.append(Vector((-f.y, f.x, 0.0)).normalized())
        seg_lens.append(L)

    depth = max(0.3, props.scaffold_depth)
    front_corners = list(P)
    back_corners = []
    for i, p in enumerate(P):
        if closed:
            i_prev = (i - 1) % n_pts
            n1, n2 = perps[i_prev], perps[i]
            cos_a = max(-1.0, min(1.0, forwards[i_prev].dot(forwards[i])))
            cos_half = sqrt(max(0.0, (1.0 + cos_a) * 0.5))
            bis = n1 + n2
            if cos_half < 1e-3 or bis.length < 1e-6:
                back_corners.append(p + n1 * depth)
            else:
                back_corners.append(p + bis.normalized() * (depth / cos_half))
        else:
            if i == 0:
                back_corners.append(p + perps[0] * depth)
            elif i == n_segs:
                back_corners.append(p + perps[-1] * depth)
            else:
                n1, n2 = perps[i - 1], perps[i]
                cos_a = max(-1.0, min(1.0, forwards[i - 1].dot(forwards[i])))
                cos_half = sqrt(max(0.0, (1.0 + cos_a) * 0.5))
                bis = n1 + n2
                if cos_half < 1e-3 or bis.length < 1e-6:
                    back_corners.append(p + n1 * depth)
                else:
                    back_corners.append(p + bis.normalized() * (depth / cos_half))

    # For closed loops, append a wrap-around so front_corners[i+1] works for the last segment
    if closed:
        front_corners.append(front_corners[0])
        back_corners.append(back_corners[0])

    return P, forwards, perps, seg_lens, front_corners, back_corners


def generate_scaffold(props, context):
    """Build the scaffold along the polyline. Return a stats dict."""
    # Reset mesh caches: previous generation's meshes are about to be removed via
    # _clear_collection (and become orphans), so any stale references would point to
    # invalid Blender data.
    _TUBE_MESH_CACHE.clear()
    _BOX_MESH_CACHE.clear()
    P, forwards, perps, seg_lens, front_corners, back_corners = _compute_path_geometry(props)
    n_segs = len(seg_lens)  # accounts for the closing segment in loop mode

    floor_count = max(1, props.floor_count)
    floor_h = max(0.5, props.floor_height)
    depth = max(0.3, props.scaffold_depth)
    total_height = floor_count * floor_h
    total_length = sum(seg_lens)

    # Per-segment bay subdivisions: GENERIC / LAYHER use a catalog of standard lengths
    # plus a compensation piece at the end; UNIFORM divides evenly by section_length.
    catalog_key = props.bay_length_catalog
    if catalog_key == 'UNIFORM':
        seg_bay_lengths = []
        for i in range(n_segs):
            bc = max(1, int(ceil(seg_lens[i] / max(0.1, props.section_length))))
            bl = seg_lens[i] / bc
            seg_bay_lengths.append([bl] * bc)
    else:
        catalog = _BAY_LENGTH_CATALOGS.get(catalog_key, _BAY_LENGTH_CATALOGS['GENERIC'])
        seg_bay_lengths = [_bay_lengths_for_segment(seg_lens[i], catalog) for i in range(n_segs)]

    # Build the ordered list of node positions along the path. With non-uniform bay lengths
    # we interpolate by accumulated distance instead of by index ratio.
    nodes_front = [front_corners[0]]
    nodes_back = [back_corners[0]]
    bay_segment = []
    is_corner = [True]
    bay_is_compensation = []  # True if a bay is the leftover compensation piece

    for i in range(n_segs):
        bay_list = seg_bay_lengths[i]
        cumulative = 0.0
        seg_total = sum(bay_list) if bay_list else seg_lens[i]
        if seg_total <= 1e-6:
            seg_total = seg_lens[i]
        # Identify which bay is the compensation: leftover whose length isn't in the catalog
        comp_idx = None
        if catalog_key != 'UNIFORM':
            cat_set = {round(L, 4) for L in _BAY_LENGTH_CATALOGS[catalog_key]}
            for k, bl in enumerate(bay_list):
                if round(bl, 4) not in cat_set:
                    comp_idx = k
                    break
        for j, bl in enumerate(bay_list):
            cumulative += bl
            bay_is_compensation.append(j == comp_idx)
            if j < len(bay_list) - 1:
                t = cumulative / seg_total
                f_pos = front_corners[i] + (front_corners[i + 1] - front_corners[i]) * t
                b_pos = back_corners[i] + (back_corners[i + 1] - back_corners[i]) * t
                nodes_front.append(f_pos)
                nodes_back.append(b_pos)
                is_corner.append(False)
                bay_segment.append(i)
            else:
                nodes_front.append(front_corners[i + 1])
                nodes_back.append(back_corners[i + 1])
                is_corner.append(True)
                bay_segment.append(i)

    n_nodes = len(nodes_front)
    n_bays = n_nodes - 1
    closed = bool(getattr(props, 'closed_loop', False)) and len(P) >= 3
    # In closed mode, the last node is a duplicate of node 0 (added via the front_corners
    # wrap). For pole placement and node-indexed loops we use n_unique_nodes; for bay loops
    # we keep n_bays unchanged so `nodes_front[i+1]` naturally wraps at the duplicate.
    n_unique_nodes = n_nodes - 1 if closed else n_nodes

    # ── Terrain Z handling ──────────────────────────────────────────────
    # When `use_terrain_z` is on, each empty's Z is treated as the terrain elevation at
    # that point. The scaffold must remain LEVEL (all platforms at the same height), so:
    #   ref_z = max(p.z for p in P) + jack_height   (highest pole gets the minimum jack)
    #   per-pole jack length = ref_z - terrain_z[i]
    # All node Z values are then snapped to ref_z so the rest of the geometry (ledgers,
    # planks, ladders) generates LEVEL automatically.
    use_terrain = bool(getattr(props, 'use_terrain_z', False))
    if use_terrain:
        ground_max = max(p.z for p in P)
        ref_z = ground_max + max(0.0, props.jack_height)
        # Save original Z per node (the actual terrain elevation under each pole)
        ground_z_front = [n.z for n in nodes_front]
        ground_z_back = [n.z for n in nodes_back]
        # Snap all nodes to the level reference so the rest of the generation builds level
        nodes_front = [Vector((n.x, n.y, ref_z)) for n in nodes_front]
        nodes_back = [Vector((n.x, n.y, ref_z)) for n in nodes_back]
    else:
        ref_z = props.base_z
        ground_z_front = [ref_z] * n_nodes
        ground_z_back = [ref_z] * n_nodes

    # Reset and create collections
    _clear_collection(SCAFFOLD_COLLECTION)
    root = _ensure_collection(SCAFFOLD_COLLECTION)
    coll_poles = _ensure_collection("Postes", root)
    coll_ledgers = _ensure_collection("Travesaños", root)
    coll_decks = _ensure_collection("Plataformas", root)
    coll_braces = _ensure_collection("Cruces", root)
    coll_ladders = _ensure_collection("Escaleras", root)
    coll_rails = _ensure_collection("Barandillas", root)
    coll_lids = _ensure_collection("Trampillas", root)
    coll_ties = _ensure_collection("Anclajes", root)
    coll_jacks = _ensure_collection("Husillos", root)
    coll_rosettes = _ensure_collection("Acoples", root)

    stats = {
        "vertices": len(P),
        "segments": n_segs,
        "bays": n_bays,
        "total_length": total_length,
        "floor_count": floor_count,
        "floor_height": floor_h,
        "depth": depth,
        "total_height": total_height,
        "poles": 0,
        "ledgers": 0,
        "decks": 0,
        "braces": 0,
        "ladders": 0,
        "rails": 0,
        "corners": (sum(1 for c in is_corner[:n_unique_nodes] if c)
                    if closed else sum(1 for c in is_corner if c) - 2),
        "corner_ledgers": 0,   # transverse ledgers at corners (non-standard length)
        "corner_planks": 0,    # corner deck pieces (dedicated trapezoidal platform)
        "decks_unmatched": 0,  # planks whose bay length doesn't fit any catalog deck (±5 mm)
        "deck_total_weight_kg": 0.0,
    }
    deck_mat_pref_local = props.deck_material_pref

    # The pole reaches EXACTLY the top rail rosette (= +1.0 m above the top deck) when
    # guardrails are on; without guardrails, the pole stops at the top deck. No extra
    # round-up: the DP / uniform splitting in `_emit_pole_stack` absorbs leftovers into
    # the last segment so we never overshoot into a phantom piece above the structure.
    if props.guardrails:
        pole_top_offset = 1.0
    else:
        pole_top_offset = 0.0
    pole_height = total_height + pole_top_offset

    # Bays that get an internal ladder + trapdoors in their decks.
    # Two modes: auto (every N bays) or manual (per-ladder slider with snap to nearest bay).
    ladder_bays = set()
    if props.add_ladders and n_bays >= 1:
        if props.use_manual_ladders and len(props.ladder_slots) > 0:
            # Snap each slider position to the nearest bay center along the polyline
            bay_center_dists = []
            cum = 0.0
            for k in range(n_bays):
                bay_len_k = (nodes_front[k + 1] - nodes_front[k]).length
                bay_center_dists.append(cum + bay_len_k * 0.5)
                cum += bay_len_k
            total_path = cum if cum > 0 else 1.0
            for slot in props.ladder_slots:
                target = max(0.0, min(1.0, slot.position)) * total_path
                best_idx = min(range(n_bays), key=lambda k: abs(bay_center_dists[k] - target))
                ladder_bays.add(best_idx)
        else:
            every = max(1, props.ladder_every)
            ladder_bays.update(range(0, n_bays, every))

    # Inclined ladders with a STANDARD length: the user-defined ladder_length determines the
    # tilt for the given floor_h. Each ladder spans one floor (rise = floor_h, hypotenuse =
    # ladder_length). Rungs are TRANSVERSE (across the bay, perpendicular to the path).
    # Trapdoors ZIG-ZAG per floor: a ladder leaning +forward tops at the +fwd half of the bay
    # (so its trapdoor lands there); the next ladder leans -forward, topping at the -fwd half.
    # The hinge of each lid sits on the side OPPOSITE the ladder lean (the "support / closing"
    # edge that the ladder rests against), so the lid opens away from the climber.
    LADDER_WIDTH = max(0.30, props.ladder_width)
    HOLE_ALONG = 0.55
    HOLE_PERP = 0.50
    LID_OPEN_DEG = max(0.0, props.lid_open_deg)
    LADDER_GRIP_EXT = 0.0  # rails terminate exactly at the deck edge so the lid can close
    L_LEN = max(floor_h + 0.05, props.ladder_length)
    tilt_dx = sqrt(max(0.0001, L_LEN * L_LEN - floor_h * floor_h))  # horizontal span per floor

    def _ladder_dirn(n_idx):
        """All ladders lean in the same +fwd direction; trapdoors stack vertically.
        (Kept as a function so a future zig-zag option can override per-floor easily.)"""
        return 1.0

    # 1) Vertical poles at every node, both rows. Optional jack base under each pole.
    # If pole_segment_length > 0, the pole is split into standard segments with a sleeve
    # (slightly larger cylinder) at each splice — matches real construction (Layher poles
    # come in 0.5 / 1.0 / 2.0 / 3.0 / 4.0 m lengths joined by a manguito).
    jack_h = max(0.0, props.jack_height)
    seg_L = max(0.0, props.pole_segment_length)
    SLEEVE_LEN = 0.18   # length of the sleeve on each splice
    SLEEVE_DIAM = TUBE_DIAM * 1.15

    pole_catalog_key = props.pole_length_catalog

    def _emit_pole_stack(bot, top, name_root, side_coll):
        """Generate one pole as a stack of standard-length segments + sleeves.

        Three modes:
        - UNIFORM (legacy): uses `pole_segment_length` as a single fixed size.
        - GENERIC / LAYHER: DP combines several standard sizes (0.5/1.0/1.5/2.0/3.0/4.0 m
          for Layher) so the stack uses real catalog pieces instead of one repeated size.

        Returns list of (z_lo, z_hi, segment_obj) per emitted segment.
        """
        out = []
        height = (top - bot).z
        if height < 0.05:
            return out
        # Determine the segment length sequence
        if pole_catalog_key == 'UNIFORM':
            if seg_L < 0.05:
                obj = _make_tube(bot, top, TUBE_DIAM, name_root, side_coll)
                out.append((bot.z, top.z, obj))
                return out
            n_full = int(height // seg_L)
            leftover = height - n_full * seg_L
            if leftover < 0.10 and n_full > 0:
                seg_lengths_p = [seg_L] * (n_full - 1) + [seg_L + leftover]
            else:
                seg_lengths_p = [seg_L] * n_full + ([leftover] if leftover > 0.05 else [])
        else:
            catalog = _POLE_LENGTH_CATALOGS.get(pole_catalog_key, _POLE_LENGTH_CATALOGS['GENERIC'])
            seg_lengths_p = _bay_lengths_for_segment(height, catalog)
        # Emit segments + sleeves at splices
        z_cum = bot.z
        for s_idx, sl in enumerate(seg_lengths_p):
            seg_bot = Vector((bot.x, bot.y, z_cum))
            seg_top = Vector((bot.x, bot.y, z_cum + sl))
            seg_obj = _make_tube(seg_bot, seg_top, TUBE_DIAM, f"{name_root}_s{s_idx}", side_coll)
            out.append((z_cum, z_cum + sl, seg_obj))
            z_cum += sl
            if s_idx < len(seg_lengths_p) - 1:
                splice_bot = Vector((bot.x, bot.y, z_cum - SLEEVE_LEN * 0.5))
                splice_top = Vector((bot.x, bot.y, z_cum + SLEEVE_LEN * 0.5))
                _make_tube(splice_bot, splice_top, SLEEVE_DIAM, f"{name_root}_sleeve{s_idx}", side_coll)
        return out

    pole_F_segments = {}
    pole_B_segments = {}
    for i in range(n_unique_nodes):
        p = nodes_front[i]
        bot = p.copy()
        top = p + Vector((0, 0, pole_height))
        tag = "C" if is_corner[i] else "_"
        pole_F_segments[i] = _emit_pole_stack(bot, top, f"Pole_F{tag}_{i:03d}", coll_poles)
        if use_terrain:
            j_len = ref_z - ground_z_front[i]
        else:
            j_len = jack_h
        if j_len > 0.001:
            _make_jack_base(bot, j_len, f"Jack_F{tag}_{i:03d}", coll_jacks)
        stats["poles"] += 1
    for i in range(n_unique_nodes):
        p = nodes_back[i]
        bot = p.copy()
        top = p + Vector((0, 0, pole_height))
        tag = "C" if is_corner[i] else "_"
        pole_B_segments[i] = _emit_pole_stack(bot, top, f"Pole_B{tag}_{i:03d}", coll_poles)
        if use_terrain:
            j_len = ref_z - ground_z_back[i]
        else:
            j_len = jack_h
        if j_len > 0.001:
            _make_jack_base(bot, j_len, f"Jack_B{tag}_{i:03d}", coll_jacks)
        stats["poles"] += 1

    def _parent_to_segment(child_obj, segments_list, z_value):
        """Find the segment whose z-range contains z_value and parent the child to it,
        preserving its world position. Computes the parent matrix manually from `location`
        and `rotation_quaternion` because `matrix_world` is not refreshed until the
        depsgraph re-runs (would return identity for a freshly-created object)."""
        if child_obj is None:
            return
        from mathutils import Matrix
        for z_lo, z_hi, seg_obj in segments_list:
            if seg_obj is None:
                continue
            if z_lo - 0.001 <= z_value <= z_hi + 0.001:
                if seg_obj.rotation_mode == 'QUATERNION':
                    rot = seg_obj.rotation_quaternion
                else:
                    rot = seg_obj.rotation_euler.to_quaternion()
                seg_world = Matrix.Translation(seg_obj.location) @ rot.to_matrix().to_4x4()
                child_obj.parent = seg_obj
                child_obj.matrix_parent_inverse = seg_world.inverted()
                return

    # 2) Per floor: longitudinal ledgers, transverse ledgers, decks, rails, toe boards
    for f in range(1, floor_count + 1):
        z = f * floor_h
        zv = Vector((0, 0, z))

        # Longitudinal ledgers along front and back, per bay
        for i in range(n_bays):
            a = nodes_front[i] + zv
            b = nodes_front[i + 1] + zv
            _make_tube(a, b, TUBE_DIAM, f"Ledger_F_F{f}_{i:03d}", coll_ledgers)
            a2 = nodes_back[i] + zv
            b2 = nodes_back[i + 1] + zv
            _make_tube(a2, b2, TUBE_DIAM, f"Ledger_B_F{f}_{i:03d}", coll_ledgers)
            stats["ledgers"] += 2

        # Transverse ledgers at every node (front to back). At interior corners, the back
        # node sits at the bisector offset, so the transverse length is depth/cos(α/2)
        # instead of `depth` — a non-standard piece tagged `Ledger_TC_` for the BOM.
        for i in range(n_unique_nodes):
            a = nodes_front[i] + zv
            b = nodes_back[i] + zv
            # In closed mode, EVERY polyline vertex is an interior corner; in open mode,
            # only the ones strictly inside the polyline (not the two endpoints).
            if closed:
                is_interior_corner = is_corner[i]
            else:
                is_interior_corner = is_corner[i] and 0 < i < n_nodes - 1
            tag = "TC" if is_interior_corner else "T"
            _make_tube(a, b, TUBE_DIAM, f"Ledger_{tag}_F{f}_{i:03d}", coll_ledgers)
            stats["ledgers"] += 1
            if is_interior_corner:
                stats["corner_ledgers"] = stats.get("corner_ledgers", 0) + 1

        # Decks per bay — solid, or pierced with a trapdoor when the bay carries an internal ladder
        if props.add_decks:
            for i in range(n_bays):
                seg = bay_segment[i]
                fwd = forwards[seg]
                prp = perps[seg]
                yaw = atan2(fwd.y, fwd.x)
                bay_len = (nodes_front[i + 1] - nodes_front[i]).length
                bay_center = (nodes_front[i] + nodes_front[i + 1]) * 0.5 + prp * (depth * 0.5)
                bay_center.z = ref_z + z + TUBE_DIAM * 0.5 + PLANK_THICKNESS * 0.5

                if i in ladder_bays:
                    # Trapdoor for floor f is the top of ladder index (f-1).
                    # Zig-zag: dirn alternates per floor, putting the hole at +fwd or -fwd
                    # half of the bay. Hinge is on the OPPOSITE side from the ladder's lean
                    # (the "closing/support edge" the ladder top rests against), so the lid
                    # opens away from the climber.
                    dirn = _ladder_dirn(f - 1)
                    h_a = min(HOLE_ALONG, max(0.3, bay_len * 0.5 - 0.1))
                    h_p = min(HOLE_PERP, max(0.3, depth - 0.2))
                    # Ladder top rests at the FREE edge of the hole (= dirn*tilt_dx/2).
                    # Hinge is OPPOSITE the lean direction so the lid opens away from the
                    # climber. Hole spans from free edge (top_x) BACK toward the hinge by h_a.
                    free_edge_x = dirn * (tilt_dx * 0.5)
                    hinge_local_x = free_edge_x - dirn * h_a
                    hole_cx = (free_edge_x + hinge_local_x) * 0.5  # = dirn*(tilt_dx-h_a)/2
                    hole_cy = 0.0
                    xL, xR = -bay_len * 0.5, bay_len * 0.5
                    yL, yR = -depth * 0.5, depth * 0.5
                    hxL, hxR = hole_cx - h_a * 0.5, hole_cx + h_a * 0.5
                    hyL, hyR = hole_cy - h_p * 0.5, hole_cy + h_p * 0.5
                    # Standardised planks: split a plank into two forward-segments only if
                    # its perp range overlaps the hole's perp range; otherwise full plank.
                    n_planks = max(1, props.deck_planks_count)
                    plank_w = max(0.05, props.deck_plank_width)
                    half_total = n_planks * plank_w * 0.5
                    half_depth = depth * 0.5
                    for k in range(n_planks):
                        plank_perp = -half_total + (k + 0.5) * plank_w
                        py_min = plank_perp - plank_w * 0.5
                        py_max = plank_perp + plank_w * 0.5
                        if py_min < -half_depth - 1e-6 or py_max > half_depth + 1e-6:
                            continue
                        overlaps_hole = (py_min < hyR and py_max > hyL)
                        deck_z = ref_z + z + TUBE_DIAM * 0.5 + PLANK_THICKNESS * 0.5
                        if overlaps_hole:
                            for tag, x_min, x_max in (("a", xL, hxL), ("b", hxR, xR)):
                                seg_len = x_max - x_min
                                if seg_len <= 0.05:
                                    continue
                                seg_cx = (x_min + x_max) * 0.5
                                seg_c = bay_center + fwd * seg_cx + prp * plank_perp
                                seg_c.z = deck_z
                                _make_box(
                                    seg_c,
                                    (seg_len - 0.005, plank_w - 0.005, PLANK_THICKNESS),
                                    f"Deck_F{f}_{i:03d}_p{k}{tag}",
                                    coll_decks,
                                    rotation_z=yaw,
                                )
                                stats["decks"] += 1
                        else:
                            plank_c = bay_center + prp * plank_perp
                            plank_c.z = deck_z
                            _make_box(
                                plank_c,
                                (max(0.1, bay_len - 0.01), plank_w - 0.005, PLANK_THICKNESS),
                                f"Deck_F{f}_{i:03d}_p{k}",
                                coll_decks,
                                rotation_z=yaw,
                            )
                            stats["decks"] += 1
                    # Hinge sits OPPOSITE the lean: for dirn=+1 the hinge is on the -fwd
                    # side of the hole, for dirn=-1 on the +fwd side. The lid extends from
                    # the hinge in +dirn*fwd direction when closed and lifts up opening in
                    # -dirn*fwd direction (= opposite to ladder lean) — matching the safety
                    # rule the user described.
                    hinge_world = bay_center + fwd * hinge_local_x
                    hinge_world.z = ref_z + z + PLANK_THICKNESS
                    away = fwd.copy() * dirn
                    lid_obj = _make_trapdoor_lid(
                        hinge_world=hinge_world,
                        hinge_dir_xy=prp,
                        away_dir_xy=away,
                        length=h_p,
                        width=h_a,
                        thickness=PLANK_THICKNESS,
                        open_angle_rad=radians(LID_OPEN_DEG),
                        name=f"Lid_F{f}_{i:03d}",
                        coll=coll_lids,
                    )
                    # Catalog binding for the lid: the trapdoor deck variant from the
                    # catalog matches a real Layher/PERI/ULMA Trapdoor_AluLVL piece.
                    if lid_obj is not None:
                        td_id, _, _, td_exact = _find_matching_deck(
                            bay_len, 0.61, 'ALU_LVL')
                        # Force-search a Trapdoor_* variant that matches bay_len
                        for did, sp in _RINGLOCK_DECK_CATALOG.items():
                            if "Trapdoor" in did and abs(sp["nominal_length"] - bay_len) < 0.05:
                                td_id, td_exact = did, True
                                break
                        if td_id is not None:
                            lid_obj["andamio_deck_id"] = td_id
                            lid_obj["andamio_deck_role"] = "trapdoor_lid"
                    _make_hinge_marker(
                        hinge_world=hinge_world,
                        hinge_axis_xy=prp,
                        lid_length=h_p,
                        name=f"Hinge_F{f}_{i:03d}",
                        coll=coll_lids,
                    )
                    _make_lid_handle(
                        hinge_world=hinge_world,
                        hinge_dir_xy=prp,
                        away_dir_xy=away,
                        lid_length=h_p,
                        lid_width=h_a,
                        open_angle_rad=radians(LID_OPEN_DEG),
                        name=f"LidHandle_F{f}_{i:03d}",
                        coll=coll_lids,
                    )
                else:
                    # Solid decking — N standardised planks placed side-by-side in perp.
                    # Planks that don't fit within `depth` are skipped (so the user sees how
                    # many fit for the chosen scaffold_depth).
                    n_planks = max(1, props.deck_planks_count)
                    plank_w = max(0.05, props.deck_plank_width)
                    half_total = n_planks * plank_w * 0.5
                    half_depth = depth * 0.5
                    for k in range(n_planks):
                        plank_perp = -half_total + (k + 0.5) * plank_w
                        # Skip if plank exceeds the bay's perp range
                        if (plank_perp - plank_w * 0.5) < -half_depth - 1e-6 \
                           or (plank_perp + plank_w * 0.5) > half_depth + 1e-6:
                            continue
                        plank_center = bay_center + prp * plank_perp
                        plank_center.z = ref_z + z + TUBE_DIAM * 0.5 + PLANK_THICKNESS * 0.5
                        plank_obj = _make_box(
                            plank_center,
                            (max(0.1, bay_len - 0.01), plank_w - 0.005, PLANK_THICKNESS),
                            f"Deck_F{f}_{i:03d}_p{k}",
                            coll_decks,
                            rotation_z=yaw,
                        )
                        # Catalog binding (Fase 2): each solid plank gets a Ringlock EU
                        # catalog deck_id that best matches its (length, width, material).
                        deck_id, len_err_mm, w_err_mm, exact = _find_matching_deck(
                            bay_len, plank_w, deck_mat_pref_local)
                        if plank_obj is not None and deck_id is not None:
                            plank_obj["andamio_deck_id"] = deck_id
                            plank_obj["andamio_deck_len_err_mm"] = len_err_mm
                            plank_obj["andamio_deck_w_err_mm"] = w_err_mm
                            plank_obj["andamio_deck_exact_match"] = exact
                            sp = _deck_spec(deck_id)
                            if sp is not None:
                                stats["deck_total_weight_kg"] += sp["self_weight_kg"]
                            if not exact:
                                stats["decks_unmatched"] += 1
                        stats["decks"] += 1

            # Corner planks — dedicated piece at each interior vertex, equivalent to the
            # manufacturer's "corner platform" (Layher Allround has these as catalog parts).
            # Single quadrilateral (A, B, C, D) sat on top of the transverse ledger.
            if props.add_corner_planks:
                # In closed loop, all vertices are interior corners; in open mode skip endpoints.
                k_range = range(0, n_unique_nodes) if closed else range(1, n_nodes - 1)
                for k in k_range:
                    if not is_corner[k]:
                        continue
                    seg_in = bay_segment[(k - 1) % n_bays] if closed else bay_segment[k - 1]
                    seg_out = bay_segment[k % n_bays] if closed else bay_segment[k]
                    if seg_in == seg_out:
                        continue
                    A = nodes_front[k]
                    B = A + perps[seg_in] * depth
                    C = nodes_back[k]
                    D = A + perps[seg_out] * depth
                    # Sit on top of the ledger (small offset above the deck z so the plank
                    # rests on the transverse ledger instead of intersecting it)
                    _make_quad_plank(
                        [A, B, C, D],
                        f"Corner_Plank_F{f}_{k:03d}",
                        coll_decks,
                        PLANK_THICKNESS,
                        z_top=ref_z + z + PLANK_THICKNESS + 0.005,
                    )
                    stats["decks"] += 1
                    stats["corner_planks"] += 1

        # Guardrails (top + mid) and toe boards
        if props.guardrails:
            for rail_h, tag in ((0.5, "mid"), (1.0, "top")):
                rz = Vector((0, 0, rail_h))
                for i in range(n_bays):
                    a = nodes_front[i] + zv + rz
                    b = nodes_front[i + 1] + zv + rz
                    _make_tube(a, b, TUBE_DIAM * 0.85, f"Rail_F_{tag}_F{f}_{i:03d}", coll_rails)
                    a2 = nodes_back[i] + zv + rz
                    b2 = nodes_back[i + 1] + zv + rz
                    _make_tube(a2, b2, TUBE_DIAM * 0.85, f"Rail_B_{tag}_F{f}_{i:03d}", coll_rails)
                    stats["rails"] += 2
            for i in range(n_bays):
                seg = bay_segment[i]
                fwd = forwards[seg]
                yaw = atan2(fwd.y, fwd.x)
                bay_len = (nodes_front[i + 1] - nodes_front[i]).length
                # Toeboards extend the FULL bay length so adjacent bays meet exactly at the
                # poles (no 5 cm gap at the corner). Standardised piece length stays = bay_len.
                cf = (nodes_front[i] + nodes_front[i + 1]) * 0.5 + zv + Vector((0, 0, TOEBOARD_HEIGHT * 0.5 + PLANK_THICKNESS))
                _make_box(
                    cf,
                    (max(0.1, bay_len), 0.025, TOEBOARD_HEIGHT),
                    f"Toe_F_F{f}_{i:03d}",
                    coll_rails,
                    rotation_z=yaw,
                )
                # Back toeboard length matches the back row's actual segment length, which at
                # interior corners may be slightly different from bay_len (bisector offset).
                back_len = (nodes_back[i + 1] - nodes_back[i]).length
                cb = (nodes_back[i] + nodes_back[i + 1]) * 0.5 + zv + Vector((0, 0, TOEBOARD_HEIGHT * 0.5 + PLANK_THICKNESS))
                # Re-derive yaw for the back toeboard so it rotates along the back-row chord
                back_dir = (nodes_back[i + 1] - nodes_back[i])
                back_yaw = atan2(back_dir.y, back_dir.x) if back_dir.length > 1e-6 else yaw
                _make_box(
                    cb,
                    (max(0.1, back_len), 0.025, TOEBOARD_HEIGHT),
                    f"Toe_B_F{f}_{i:03d}",
                    coll_rails,
                    rotation_z=back_yaw,
                )
                stats["rails"] += 2

            # End-cap rails AND toeboard at the open ends of the polyline. Closed loops
            # have no endpoints to close, so this is skipped there.
            if props.guardrails and not closed:
                for end_idx in (0, n_nodes - 1):
                    # Top + mid transverse rails
                    for rail_h, tag in ((0.5, "mid"), (1.0, "top")):
                        rz = Vector((0, 0, rail_h))
                        a = nodes_front[end_idx] + zv + rz
                        b = nodes_back[end_idx] + zv + rz
                        _make_tube(a, b, TUBE_DIAM * 0.85, f"Rail_E_{tag}_F{f}_{end_idx:03d}", coll_rails)
                        stats["rails"] += 1
                    # Transverse toeboard at the open end
                    fp = nodes_front[end_idx] + zv
                    bp = nodes_back[end_idx] + zv
                    end_dir = (bp - fp)
                    end_len = end_dir.length
                    if end_len > 0.05:
                        end_yaw = atan2(end_dir.y, end_dir.x)
                        center_t = (fp + bp) * 0.5 + Vector((0, 0, TOEBOARD_HEIGHT * 0.5 + PLANK_THICKNESS))
                        _make_box(
                            center_t,
                            (max(0.1, end_len), 0.025, TOEBOARD_HEIGHT),
                            f"Toe_E_F{f}_{end_idx:03d}",
                            coll_rails,
                            rotation_z=end_yaw,
                        )
                        stats["rails"] += 1

            # Corner toeboard wedge: at each interior polyline vertex, add a small toeboard
            # piece centred at back_corner_k along the bisector to bridge the kink between
            # the two adjacent back-row toeboards.
            # End-cap pieces for top + mid rails at corners: short tubes that bridge the
            # angle change between adjacent segments' rails (otherwise the rails meet at
            # an unfinished L-joint at each corner pole).
            corner_range_rails = range(0, n_unique_nodes) if closed else range(1, n_nodes - 1)
            for k in corner_range_rails:
                if not is_corner[k]:
                    continue
                seg_in = bay_segment[(k - 1) % n_bays] if closed else bay_segment[k - 1]
                seg_out = bay_segment[k % n_bays] if closed else bay_segment[k]
                if seg_in == seg_out:
                    continue
                bis = perps[seg_in] + perps[seg_out]
                if bis.length < 1e-6:
                    continue
                bis = bis.normalized()
                for rail_h, tag in ((0.5, "mid"), (1.0, "top")):
                    rz = Vector((0, 0, rail_h))
                    # Front rail caps: at the polyline vertex (front_corner = nodes_front[k])
                    cf_pos = nodes_front[k] + zv + rz
                    f_dir = (forwards[seg_in] + forwards[seg_out])
                    if f_dir.length > 1e-6:
                        f_dir = f_dir.normalized()
                        a = cf_pos - f_dir * 0.10
                        b = cf_pos + f_dir * 0.10
                        _make_tube(a, b, TUBE_DIAM * 0.85, f"Rail_C_{tag}_F{f}_{k:03d}_F", coll_rails)
                        stats["rails"] += 1
                    # Back rail caps along the bisector at back_corner_k
                    cb_pos = nodes_back[k] + zv + rz
                    a2 = cb_pos - bis * 0.10
                    b2 = cb_pos + bis * 0.10
                    _make_tube(a2, b2, TUBE_DIAM * 0.85, f"Rail_C_{tag}_F{f}_{k:03d}_B", coll_rails)
                    stats["rails"] += 1

            wedge_range = range(0, n_unique_nodes) if closed else range(1, n_nodes - 1)
            for k in wedge_range:
                if not is_corner[k]:
                    continue
                seg_in = bay_segment[(k - 1) % n_bays] if closed else bay_segment[k - 1]
                seg_out = bay_segment[k % n_bays] if closed else bay_segment[k]
                if seg_in == seg_out:
                    continue
                bis = perps[seg_in] + perps[seg_out]
                if bis.length < 1e-6:
                    continue
                bis = bis.normalized()
                bc_pos = nodes_back[k] + zv + Vector((0, 0, TOEBOARD_HEIGHT * 0.5 + PLANK_THICKNESS))
                bis_yaw = atan2(bis.y, bis.x)
                _make_box(
                    bc_pos,
                    (0.18, 0.025, TOEBOARD_HEIGHT),
                    f"Toe_C_F{f}_{k:03d}",
                    coll_rails,
                    rotation_z=bis_yaw,
                )
                stats["rails"] += 1

    # 3) Diagonal braces — alternating bays per floor (i+f even). Distribution between
    # front and back rows depends on `brace_pattern`. Skip ladder + compensation bays.
    HEAD_LEN = 0.06
    HEAD_DIAM = TUBE_DIAM * 1.20

    def _emit_brace(a, b, name_prefix):
        _make_tube(a, b, TUBE_DIAM * 0.85, name_prefix, coll_braces)
        axis = b - a
        if axis.length > 1e-6:
            axis_n = axis.normalized()
            a_head = a + axis_n * (HEAD_LEN * 0.5)
            b_head = b - axis_n * (HEAD_LEN * 0.5)
            _make_tube(a - axis_n * 0.005, a_head, HEAD_DIAM, f"{name_prefix}_capA", coll_braces)
            _make_tube(b_head, b + axis_n * 0.005, HEAD_DIAM, f"{name_prefix}_capB", coll_braces)

    # Subdivisión de la cruce en sub-tramos zigzag entre rosetas intermedias.
    # subdivs=1 → cruce esquina a esquina (default). subdivs=2/4 → patrón N
    # alternando dirección up-right / up-left para formar red triangulada.
    _SUBDIVS_MAP = {'NONE': 1, 'HALF': 2, 'QUARTER': 4}
    subdivs = _SUBDIVS_MAP.get(getattr(props, 'brace_subdivision', 'NONE'), 1)

    def _emit_brace_set(node_a, node_b, base_z, name_prefix):
        """Genera 1 (subdivs=1) o N sub-cruces zigzag entre `node_a` (poste
        izquierdo) y `node_b` (poste derecho), de `base_z` a `base_z+floor_h`.

        Patrón N: el sub-tramo k va de (lado_alt, z_k) → (lado_alt+1, z_{k+1})
        con `lado_alt` alternando A↔B en cada paso. Forma una zigzag
        triangulada estructuralmente equivalente a la cruz completa.
        """
        if subdivs <= 1:
            a = node_a + Vector((0, 0, base_z))
            b = node_b + Vector((0, 0, base_z + floor_h))
            _emit_brace(a, b, name_prefix)
            return 1
        step = floor_h / subdivs
        n_emitted = 0
        for k in range(subdivs):
            z_low = base_z + k * step
            z_hi = base_z + (k + 1) * step
            # Alternar dirección: par → up-right, impar → up-left
            if k % 2 == 0:
                a = node_a + Vector((0, 0, z_low))
                b = node_b + Vector((0, 0, z_hi))
            else:
                a = node_b + Vector((0, 0, z_low))
                b = node_a + Vector((0, 0, z_hi))
            _emit_brace(a, b, f"{name_prefix}s{k}")
            n_emitted += 1
        return n_emitted

    if props.add_braces:
        pattern = props.brace_pattern
        for f in range(floor_count):
            base_z = f * floor_h
            for i in range(n_bays):
                if (i + f) % 2 != 0:
                    continue
                if i in ladder_bays:
                    continue
                if i < len(bay_is_compensation) and bay_is_compensation[i]:
                    continue
                # Decide which face(s) get the diagonal based on the pattern
                if pattern == 'FRONT':
                    do_front, do_back = True, False
                elif pattern == 'BACK':
                    do_front, do_back = False, True
                elif pattern == 'BOTH':
                    do_front, do_back = True, True
                elif pattern == 'ALT':
                    parity4 = (i + f) % 4
                    do_front = (parity4 == 0)
                    do_back = (parity4 == 2)
                else:
                    do_front, do_back = True, False
                if do_front:
                    n = _emit_brace_set(
                        nodes_front[i], nodes_front[i + 1],
                        base_z, f"Brace_F{f}_{i:03d}_F",
                    )
                    stats["braces"] += n
                if do_back:
                    n = _emit_brace_set(
                        nodes_back[i], nodes_back[i + 1],
                        base_z, f"Brace_F{f}_{i:03d}_B",
                    )
                    stats["braces"] += n

    # 3b) Horizontal in-plane diagonals (rigidizadores). They lie flat at floor level
    # going from one corner of a bay to the diagonally-opposite corner, bracing the deck
    # plane against racking. Configurable cadence per-floor and per-bay.
    if props.add_horizontal_braces:
        h_every_f = max(1, props.h_brace_every_floors)
        h_every_b = max(1, props.h_brace_every_bays)
        for f in range(1, floor_count + 1):
            if (f - 1) % h_every_f != 0:
                continue
            zv_h = Vector((0, 0, f * floor_h))
            for i in range(n_bays):
                if i % h_every_b != 0:
                    continue
                if i in ladder_bays:
                    continue
                if i < len(bay_is_compensation) and bay_is_compensation[i]:
                    continue
                a = nodes_front[i] + zv_h
                b = nodes_back[i + 1] + zv_h
                _make_tube(a, b, TUBE_DIAM * 0.85, f"HBrace_F{f}_{i:03d}", coll_braces)
                stats["braces"] += 1

    # 4) Inclined ladders — one per floor, tilted LADDER_TILT_DEG° in the +forward direction.
    # Rungs are TRANSVERSE (perpendicular to the path) because the rails are separated along
    # the perp direction. The ladder TOP reaches the -fwd edge of the trapdoor at each floor.
    if ladder_bays:
        rungs_per_floor = max(2, int(round(floor_h / 0.28)))
        for i in sorted(ladder_bays):
            seg = bay_segment[i]
            fwd = forwards[seg]
            prp = perps[seg]
            center_xy = (nodes_front[i] + nodes_front[i + 1]) * 0.5 + prp * (depth * 0.5)
            for f_idx in range(floor_count):
                d = _ladder_dirn(f_idx)
                bot_xy = center_xy - fwd * (d * tilt_dx * 0.5)
                top_xy = center_xy + fwd * (d * tilt_dx * 0.5)
                # First ladder rests on the actual terrain (not the level base of the
                # scaffold) so the worker steps off onto the ground, not a phantom Z.
                # Higher-floor ladders rest on the deck below at the level reference.
                if f_idx == 0 and use_terrain:
                    if closed:
                        i_n = (i + 1) % n_unique_nodes
                    else:
                        i_n = min(i + 1, len(ground_z_front) - 1)
                    z_bot = (ground_z_front[i] + ground_z_front[i_n]) * 0.5
                else:
                    z_bot = ref_z + f_idx * floor_h
                z_top = ref_z + (f_idx + 1) * floor_h
                base = Vector((bot_xy.x, bot_xy.y, z_bot))
                top = Vector((top_xy.x, top_xy.y, z_top))
                # Extend the rails LADDER_GRIP_EXT past the deck along the rise so the
                # rails reach above the trapdoor edge for the climber to grab.
                rise = (top - base)
                top = top + rise.normalized() * LADDER_GRIP_EXT
                _ladder(
                    base, top,
                    width=LADDER_WIDTH,
                    rung_count=rungs_per_floor,
                    name=f"Ladder_{i:03d}_F{f_idx}",
                    coll=coll_ladders,
                    side_axis=prp,
                )
                if props.add_ladder_handrail:
                    _ladder_handrail(
                        base, top,
                        side_axis=prp,
                        width=LADDER_WIDTH,
                        height=props.ladder_handrail_height,
                        name=f"Ladder_{i:03d}_F{f_idx}",
                        coll=coll_ladders,
                    )
                # Foot plate under the ladder base on the floor below (visual support)
                foot_z = z_bot + 0.01
                foot_center = Vector((bot_xy.x, bot_xy.y, foot_z))
                _make_box(
                    foot_center,
                    (0.20, 0.20, 0.02),
                    f"Ladder_{i:03d}_F{f_idx}_foot",
                    coll_ladders,
                )
                stats["ladders"] += 1

    # 4b) Rosettes welded every `rosette_pitch` (default 0.5 m) along the FULL pole height.
    # Layher Allround real poles carry one rosette every 0.5 m regardless of which
    # structural element attaches there. This guarantees that any horizontal (ledger,
    # rail, brace) at any 0.5 m increment finds an anchor — modular for any config.
    # Each rosette is parented to the pole segment containing its Z so the assembly
    # behaves as discrete pieces.
    if props.add_rosettes:
        ROSETTE_DIAM = 0.13
        ROSETTE_INNER = TUBE_DIAM   # hole matches pole diameter so it visually wraps
        ROSETTE_THK = 0.010
        ROSETTE_PITCH = max(0.05, props.rosette_pitch)
        # Build the list of Z heights at which to weld rosettes (from ref_z up to pole top).
        pole_top_z = ref_z + pole_height
        rosette_zs = []
        z_step = 0.0
        # Round pole_top to avoid float drift losing the last increment
        while ref_z + z_step <= pole_top_z + 1e-3:
            rosette_zs.append(ref_z + z_step)
            z_step += ROSETTE_PITCH
        for z_at in rosette_zs:
            z_off_cm = round((z_at - ref_z) * 100)
            for i in range(n_unique_nodes):
                p = nodes_front[i]
                pos = Vector((p.x, p.y, z_at))
                rose = _make_rosette(pos, ROSETTE_DIAM, ROSETTE_INNER, ROSETTE_THK,
                                     f"Rose_F_Z{z_off_cm:04d}_{i:03d}", coll_rosettes)
                _parent_to_segment(rose, pole_F_segments.get(i, []), z_at)
            for i in range(n_unique_nodes):
                p = nodes_back[i]
                pos = Vector((p.x, p.y, z_at))
                rose = _make_rosette(pos, ROSETTE_DIAM, ROSETTE_INNER, ROSETTE_THK,
                                     f"Rose_B_Z{z_off_cm:04d}_{i:03d}", coll_rosettes)
                _parent_to_segment(rose, pole_B_segments.get(i, []), z_at)

    # 5) Façade ties — small tubes from each front pole pointing inward (-perp) toward the
    # building, every N bays × every M floors. Required by EN 12810 to stabilise the scaffold.
    if props.add_ties:
        every_b = max(1, props.tie_every_bays)
        every_m = max(1, props.tie_every_floors)
        tie_len = max(0.05, props.tie_length)
        # Use polyline-vertex nodes preferentially (every corner gets a tie); also stride
        # through the rest of the front nodes by every_b.
        tie_node_indices = set(range(0, n_unique_nodes, every_b))
        tie_node_indices.update(k for k, c in enumerate(is_corner[:n_unique_nodes]) if c)
        for i in sorted(tie_node_indices):
            seg = bay_segment[min(i, n_bays - 1)]
            prp = perps[seg]
            for f in range(every_m, floor_count + 1, every_m):
                front_anchor = nodes_front[i].copy()
                front_anchor.z = ref_z + f * floor_h
                wall_point = front_anchor - prp * tie_len
                _make_tube(front_anchor, wall_point, TUBE_DIAM * 0.7, f"Tie_F{f}_{i:03d}", coll_ties)

    # 6) Apply per-category viewport colours so each component type is distinguishable
    _apply_category_materials(root, props)

    return stats


def _audit_decks_in_scene():
    """Walk every Plataformas object that has andamio_deck_id and compute aggregates.
    Returns dict with totals + worst-case utilization (no FEM, just SLS local check)."""
    scaffold = bpy.data.collections.get(SCAFFOLD_COLLECTION)
    if scaffold is None:
        return None
    decks_coll = scaffold.children.get("Plataformas")
    lids_coll = scaffold.children.get("Trampillas")
    pool = list(decks_coll.objects) if decks_coll else []
    if lids_coll:
        pool.extend(lids_coll.objects)
    n_with_id = 0
    n_unmatched = 0
    total_weight_kg = 0.0
    worst_util = 0.0
    worst_name = "—"
    n_pass = 0
    n_fail = 0
    by_id = {}
    for o in pool:
        did = o.get("andamio_deck_id")
        if did is None:
            continue
        spec = _deck_spec(did)
        if spec is None:
            continue
        n_with_id += 1
        if o.get("andamio_deck_exact_match") is False:
            n_unmatched += 1
        total_weight_kg += spec["self_weight_kg"]
        by_id[did] = by_id.get(did, 0) + 1
        # Skip trapdoor lids in bending verification: they are visually small flaps
        # but the catalog spec they reference is the FULL trapdoor deck (the same one
        # already verified via the surrounding deck planks). Verifying twice would
        # double-count and applying nominal_length to the lid mesh inflates utilisation.
        if o.get("andamio_deck_role") == "trapdoor_lid":
            continue
        L = spec["nominal_length"]
        qd = 1.5 * spec["qk_uniform_kN_m2"]
        v = deck_verify_self_bending(did, L, qd)
        if v is not None:
            if v["pass"]:
                n_pass += 1
            else:
                n_fail += 1
            if v["util_max"] > worst_util:
                worst_util = v["util_max"]
                worst_name = o.name
    return {
        "n_with_id": n_with_id,
        "n_unmatched": n_unmatched,
        "total_weight_kg": round(total_weight_kg, 1),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "worst_util": round(worst_util, 3),
        "worst_name": worst_name,
        "by_id": dict(sorted(by_id.items())),
    }


RINGLOCK_DECK_WIDTHS = (0.19, 0.32, 0.61)


def _suggest_deck_cover(depth_m, tol_mm=DECK_GAP_MAX_MM, n_max=6):
    """Search Ringlock plank-width combinations that cover `depth_m`.

    Allowed plank widths: {0.19, 0.32, 0.61} (standard Ringlock EU sizes).
    Prefers (a) within-tol candidates with no overhang, (b) uniform sets, (c) fewer planks.
    Returns dict {widths, sum, gap_mm, uniform, n, within_tol} — never None.
    If no in-tol combo exists, returns the best fallback with within_tol=False."""
    from itertools import combinations_with_replacement
    EPS_MM = 0.5  # absorb float-precision noise (FloatProperty truncates to ~7 digits)
    best = None       # within tolerance, no overhang
    fallback = None   # closest by |gap_mm|, even with overhang
    for n in range(1, n_max + 1):
        for combo in combinations_with_replacement(RINGLOCK_DECK_WIDTHS, n):
            s = sum(combo)
            gap_mm = (depth_m - s) * 1000.0
            uniform = (len(set(combo)) == 1)
            fb_key = (abs(gap_mm), 0 if uniform else 1, n)
            if fallback is None or fb_key < fallback[0]:
                fallback = (fb_key, combo, gap_mm, uniform)
            if gap_mm < -EPS_MM or gap_mm > tol_mm:
                continue
            key = (max(0.0, gap_mm), 0 if uniform else 1, n)
            if best is None or key < best[0]:
                best = (key, combo, gap_mm, uniform)
    chosen, gap_mm, uniform, within = (
        (best[1], best[2], best[3], True) if best is not None
        else (fallback[1], fallback[2], fallback[3], False)
    )
    return {
        "widths": sorted(chosen, reverse=True),
        "sum": round(sum(chosen), 4),
        "gap_mm": round(gap_mm, 1),
        "uniform": uniform,
        "n": len(chosen),
        "within_tol": within,
    }


def _format_summary(stats):
    extra = ""
    n_tc = stats.get('corner_ledgers', 0)
    n_cp = stats.get('corner_planks', 0)
    if n_tc or n_cp:
        extra = f"  (esquina: {n_tc} traveseros TC, {n_cp} plataformas)"
    return (
        f"{stats['vertices']} pts · {stats['segments']} tramos · {stats['bays']} vanos  |  "
        f"L={stats['total_length']:.2f} m  H={stats['total_height']:.2f} m  esquinas:{stats['corners']}{extra}  |  "
        f"Postes:{stats['poles']}  Travesaños:{stats['ledgers']}  "
        f"Plataformas:{stats['decks']}  Cruces:{stats['braces']}  "
        f"Escaleras:{stats['ladders']}  Barandillas:{stats['rails']}"
    )


# ---------------------------------------------------------------------------
# Auto-update handler
# ---------------------------------------------------------------------------

_AUTO_BUSY = False
_AUTO_PENDING = False
_AUTO_LAST = {"path": None}
_AUTO_SUPPRESS = False  # set during preset application to coalesce multiple prop changes


def _path_signature(props):
    sig = []
    for item in props.path_points:
        if item.obj is None:
            sig.append(None)
        else:
            t = item.obj.matrix_world.translation
            sig.append((item.obj.name, round(t.x, 6), round(t.y, 6), round(t.z, 6)))
    return tuple(sig)


def _auto_deferred_regen():
    global _AUTO_BUSY, _AUTO_PENDING
    _AUTO_PENDING = False
    scene = bpy.context.scene
    props = getattr(scene, "andamios_props", None)
    if props is None or not props.auto_update:
        return None
    n_path = len(_path_objects(props))
    if n_path < 2:
        return None
    _AUTO_BUSY = True
    try:
        from calc import diagnostics as _diag
        with _diag.breadcrumb_op(
            "auto_regen",
            n_path=n_path,
            floors=int(getattr(props, "floor_count", 0)),
            depth=float(getattr(props, "scaffold_depth", 0.0)),
            catalog=str(getattr(props, "bay_length_catalog", "?")),
        ):
            stats = generate_scaffold(props, bpy.context)
            props.last_summary = _format_summary(stats)
    except Exception as e:
        print(f"[Andamios auto-update] {e}")
    finally:
        _AUTO_BUSY = False
    return None


@bpy.app.handlers.persistent
def _auto_on_depsgraph(scene, depsgraph=None):
    global _AUTO_BUSY, _AUTO_PENDING, _AUTO_LAST
    if _AUTO_BUSY or _AUTO_PENDING:
        return
    props = getattr(scene, "andamios_props", None)
    if props is None or not props.auto_update:
        return
    if len(_path_objects(props)) < 2:
        return
    sig = _path_signature(props)
    if _AUTO_LAST.get("path") == sig:
        return
    _AUTO_LAST["path"] = sig
    _AUTO_PENDING = True
    try:
        from calc import diagnostics as _diag
        _diag.log_breadcrumb("auto_depsgraph_fire", path_sig_len=len(sig))
    except Exception:
        pass
    bpy.app.timers.register(_auto_deferred_regen, first_interval=0.0)


def _auto_register():
    if _auto_on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_auto_on_depsgraph)


def _auto_unregister():
    if _auto_on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_auto_on_depsgraph)


_PRESETS = {
    'LAYHER_73':  {'scaffold_depth': 0.732, 'deck_planks_count': 2, 'deck_plank_width': 0.32, 'bay_length_catalog': 'LAYHER'},
    'LAYHER_109': {'scaffold_depth': 1.090, 'deck_planks_count': 3, 'deck_plank_width': 0.32, 'bay_length_catalog': 'LAYHER'},
    'GENERIC_1M': {'scaffold_depth': 1.000, 'deck_planks_count': 3, 'deck_plank_width': 0.32, 'bay_length_catalog': 'GENERIC'},
    'NARROW':     {'scaffold_depth': 0.640, 'deck_planks_count': 2, 'deck_plank_width': 0.32, 'bay_length_catalog': 'GENERIC'},
}


def _apply_preset(self, context):
    global _AUTO_SUPPRESS
    preset = self.preset
    if preset == 'CUSTOM':
        return
    cfg = _PRESETS.get(preset)
    if not cfg:
        return
    _AUTO_SUPPRESS = True
    try:
        for k, v in cfg.items():
            setattr(self, k, v)
    finally:
        _AUTO_SUPPRESS = False
    if self.auto_update and not _AUTO_PENDING and not _AUTO_BUSY:
        bpy.app.timers.register(_auto_deferred_regen, first_interval=0.0)


def _on_color_change(self, context):
    """Color-only update: refresh materials for the existing scaffold without rebuilding
    geometry. Significantly faster than a full regen when the user only tweaks colours."""
    if _AUTO_SUPPRESS:
        return
    root = bpy.data.collections.get(SCAFFOLD_COLLECTION)
    if root is not None:
        _apply_category_materials(root, self)


def _on_prop_change_regen(self, context):
    """Generic property-change callback: triggers auto-regen if auto_update is on.
    Suppressed during preset application via `_AUTO_SUPPRESS` so a preset that touches
    several properties causes only one regen at the end (not one per prop)."""
    if _AUTO_SUPPRESS:
        return
    if getattr(self, "auto_update", False) and not _AUTO_PENDING and not _AUTO_BUSY:
        bpy.app.timers.register(_auto_deferred_regen, first_interval=0.0)


def _on_auto_update_toggle(self, context):
    global _AUTO_LAST
    _AUTO_LAST = {"path": None}
    if self.auto_update and len(_path_objects(self)) >= 2:
        if not _AUTO_PENDING and not _AUTO_BUSY:
            bpy.app.timers.register(_auto_deferred_regen, first_interval=0.0)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class ANDAMIOS_PathPoint(PropertyGroup):
    obj: PointerProperty(
        type=bpy.types.Object,
        name="Punto",
        description="Empty u objeto cuya posición define un vértice de la trayectoria",
    )


def _polyline_position_at_t(props, t):
    """World XYZ at parameter t (0..1) along the polyline. Honours `closed_loop` and
    `use_terrain_z` (interpolated terrain Z; otherwise base_z)."""
    objs = _path_objects(props)
    if len(objs) < 2:
        return None
    use_terrain = bool(getattr(props, 'use_terrain_z', False))
    base_z_local = props.base_z
    P = []
    for o in objs:
        v = o.matrix_world.translation.copy()
        if not use_terrain:
            v.z = base_z_local
        P.append(v)
    closed = bool(getattr(props, 'closed_loop', False)) and len(P) >= 3
    n_pts = len(P)
    n_segs = n_pts if closed else n_pts - 1
    seg_data = []
    for i in range(n_segs):
        i_next = (i + 1) % n_pts
        seg_data.append((P[i], P[i_next], (P[i_next] - P[i]).length))
    total = sum(s[2] for s in seg_data)
    if total <= 1e-6:
        return P[0].copy()
    target = max(0.0, min(1.0, t)) * total
    cum = 0.0
    for (a, b, L) in seg_data:
        if cum + L >= target - 1e-9:
            local_t = (target - cum) / L if L > 0 else 0.0
            return a.lerp(b, local_t)
        cum += L
    return P[-1].copy()


def _update_ladder_indicator(slot, props):
    """Place a slot's indicator empty at the polyline parameter `slot.position`."""
    if slot.indicator is None:
        return
    pos = _polyline_position_at_t(props, slot.position)
    if pos is None:
        return
    slot.indicator.location = (pos.x, pos.y, pos.z + 0.5)


def _update_all_ladder_indicators(props):
    for slot in props.ladder_slots:
        _update_ladder_indicator(slot, props)


def _on_ladder_slot_change(self, context):
    """Move the slot's indicator immediately, then trigger auto-regen if enabled."""
    props = context.scene.andamios_props
    _update_ladder_indicator(self, props)
    if props.auto_update and not _AUTO_PENDING and not _AUTO_BUSY:
        bpy.app.timers.register(_auto_deferred_regen, first_interval=0.0)


class ANDAMIOS_FailureEntry(PropertyGroup):
    """Una entrada en la lista de elementos críticos del cálculo."""
    member_id: StringProperty(default="")
    utilization: FloatProperty(default=0.0)
    failure_type: StringProperty(default="—")
    severity: StringProperty(default="ok")
    severity_label: StringProperty(default="")
    why: StringProperty(default="")
    fix: StringProperty(default="")
    member_type: StringProperty(default="")
    coords_x: FloatProperty(default=0.0)
    coords_y: FloatProperty(default=0.0)
    coords_z: FloatProperty(default=0.0)


class ANDAMIOS_LadderSlot(PropertyGroup):
    position: FloatProperty(
        name="Pos",
        default=0.5, min=0.0, max=1.0,
        subtype='FACTOR',
        description="Posición a lo largo de la trayectoria (0=inicio, 1=fin). Hace snap al vano más cercano",
        update=_on_ladder_slot_change,
    )
    indicator: PointerProperty(
        type=bpy.types.Object,
        name="Indicador",
        description="Empty visible en el viewport que se mueve con el slider",
    )


class ANDAMIOS_Props(PropertyGroup):
    path_points: CollectionProperty(type=ANDAMIOS_PathPoint)
    active_path_index: IntProperty(default=0, min=0)

    preset: EnumProperty(
        name="Preset",
        items=[
            ('CUSTOM',     "Personalizado", "Sin preset (configura cada propiedad manualmente)"),
            ('LAYHER_73',  "Layher 73",     "Profundidad 0.732 m, 2 bandejas, catálogo Layher"),
            ('LAYHER_109', "Layher 109",    "Profundidad 1.09 m, 3 bandejas, catálogo Layher"),
            ('GENERIC_1M', "Genérico 1 m",  "Profundidad 1.0 m, 3 bandejas, catálogo Genérico"),
            ('NARROW',     "Estrecho",      "Profundidad 0.64 m, 2 bandejas, catálogo Genérico"),
        ],
        default='CUSTOM',
        description="Preset que ajusta profundidad, número/ancho de bandejas y catálogo de longitudes",
        update=_apply_preset,
    )

    floor_count: IntProperty(
        name="Nº de plantas",
        default=2, min=1, max=20,
        update=_on_prop_change_regen,
    )
    floor_height: FloatProperty(
        name="Altura por planta (m)",
        default=2.0, min=1.0, max=4.0, unit='LENGTH',
        update=_on_prop_change_regen,
    )
    scaffold_depth: FloatProperty(
        name="Profundidad (m)",
        default=0.732, min=0.3, max=2.0, unit='LENGTH',
        update=_on_prop_change_regen,
    )
    section_length: FloatProperty(
        name="Longitud de tramo (m)",
        default=2.5, min=0.5, max=4.0, unit='LENGTH',
        description="Longitud objetivo de cada vano. Sólo se usa con catálogo Uniforme.",
        update=_on_prop_change_regen,
    )
    bay_length_catalog: EnumProperty(
        name="Catálogo vanos (horizontal)",
        items=[
            ('GENERIC', "Mixto múltiplos 0,5 m", "Combina piezas de 1.0/1.5/2.0/2.5/3.0 m. Encaja exacto con planificaciones en múltiplos de 0.5 m"),
            ('LAYHER',  "Layher Allround (catálogo real)", "Combina piezas Layher reales: 0.73/1.09/1.40/1.57/1.73/2.07/2.57/3.07 m"),
            ('UNIFORM', "Iguales (divide en N partes)",  "Reparte el tramo en partes iguales del tamaño 'Longitud objetivo' (ningún vano estandarizado)"),
        ],
        default='GENERIC',
        description="Cómo subdividir cada tramo HORIZONTAL de la polilínea en vanos (longitud entre postes). Las dos primeras opciones usan piezas estándar + pieza de compensación al final del tramo si no encaja exacto",
        update=_on_prop_change_regen,
    )
    base_z: FloatProperty(
        name="Z base (m)",
        default=0.0, unit='LENGTH',
        description="Altura del pie del andamio. Anula la Z de los puntos de la trayectoria.",
        update=_on_prop_change_regen,
    )
    closed_loop: BoolProperty(
        name="Trayectoria cerrada",
        default=False,
        description="Conecta el último punto con el primero formando un loop alrededor de un edificio",
        update=_on_prop_change_regen,
    )
    use_terrain_z: BoolProperty(
        name="Terreno irregular",
        default=False,
        description="Cada empty mantiene su Z propia (= cota del terreno). Los husillos se ajustan automáticamente para nivelar el andamio: ref_z = max(P.z) + jack_height",
        update=_on_prop_change_regen,
    )
    jack_height: FloatProperty(
        name="Husillo de base (m)",
        default=0.0, min=0.0, max=1.0, unit='LENGTH',
        description="Altura del husillo de base bajo cada poste (0 = sin husillo)",
        update=_on_prop_change_regen,
    )
    add_rosettes: BoolProperty(
        name="Rosetas (acoples)",
        default=True,
        description="Genera rosetas a lo largo de los postes cada `rosette_pitch` metros",
        update=_on_prop_change_regen,
    )
    rosette_pitch: FloatProperty(
        name="Cada (m)",
        default=0.5, min=0.10, max=2.0, unit='LENGTH',
        description="Distancia vertical entre rosetas soldadas al poste (Layher Allround = 0.5 m)",
        update=_on_prop_change_regen,
    )
    pole_segment_length: FloatProperty(
        name="Longitud poste (m)",
        default=0.0, min=0.0, max=4.0, unit='LENGTH',
        description="Longitud estandarizada (modo Uniforme) de cada segmento de poste. 0 = poste continuo. Ignorado si el catálogo no es Uniforme",
        update=_on_prop_change_regen,
    )
    pole_length_catalog: EnumProperty(
        name="Catálogo postes (vertical)",
        items=[
            ('UNIFORM', "Uniforme (longitud fija)",        "Usa el valor 'Longitud poste' como tamaño único del segmento (modo legacy)"),
            ('GENERIC', "Mixto múltiplos 0,5 m",           "Combina piezas de 0.5/1.0/1.5/2.0/2.5/3.0 m hasta cubrir la altura"),
            ('LAYHER',  "Layher Allround (catálogo real)", "Combina piezas Layher reales: 0.5/1.0/1.5/2.0/3.0/4.0 m"),
        ],
        default='UNIFORM',
        description="Cómo segmentar cada poste VERTICAL en piezas. Los modos Mixto y Layher combinan piezas estándar hasta cubrir la altura completa de cada poste",
        update=_on_prop_change_regen,
    )
    add_ties: BoolProperty(
        name="Anclajes a fachada",
        default=False,
        description="Genera anclajes (ties) desde los postes delanteros hacia la fachada",
        update=_on_prop_change_regen,
    )
    tie_every_bays: IntProperty(
        name="Anclaje cada N vanos",
        default=4, min=1, max=20,
        update=_on_prop_change_regen,
    )
    tie_every_floors: IntProperty(
        name="Anclaje cada M plantas",
        default=2, min=1, max=10,
        update=_on_prop_change_regen,
    )
    tie_length: FloatProperty(
        name="Longitud anclaje (m)",
        default=0.5, min=0.1, max=2.0, unit='LENGTH',
        update=_on_prop_change_regen,
    )
    add_decks: BoolProperty(name="Plataformas", default=True, update=_on_prop_change_regen)
    add_corner_planks: BoolProperty(
        name="Plataforma de esquina",
        default=True,
        description="Genera una pieza de esquina dedicada (trapezoide) en cada vértice interior. Equivale a la 'corner platform' del catálogo Layher",
        update=_on_prop_change_regen,
    )
    deck_planks_count: IntProperty(
        name="Bandejas por vano",
        default=3, min=1, max=6,
        description="Número de bandejas estandarizadas colocadas en paralelo dentro de cada vano",
        update=_on_prop_change_regen,
    )
    deck_plank_width: FloatProperty(
        name="Ancho bandeja (m)",
        default=0.32, min=0.15, max=0.50, unit='LENGTH',
        description="Ancho estandarizado de cada bandeja (e.g. 0.32 m, 0.19 m)",
        update=_on_prop_change_regen,
    )
    deck_material_pref: EnumProperty(
        name="Material bandeja",
        items=[
            ('ANY',      "Cualquiera",  "Cualquier construcción del catálogo"),
            ('STEEL',    "Acero",       "Acero galvanizado S350GD+Z (más pesado, más MRd)"),
            ('ALUMINUM', "Aluminio",    "Aluminio extruido EN AW-6082 T6 (ligero)"),
            ('ALU_LVL',  "Alu+LVL",     "Marco aluminio + tablero LVL fenólico"),
        ],
        default='STEEL',
        description="Preferencia de material al asignar bandejas del catálogo a cada vano",
        update=_on_prop_change_regen,
    )
    guardrails: BoolProperty(name="Barandillas + rodapié", default=True, update=_on_prop_change_regen)
    add_braces: BoolProperty(name="Cruces (diagonales)", default=True, update=_on_prop_change_regen)
    brace_pattern: EnumProperty(
        name="Patrón cruces",
        items=[
            ('FRONT', "Solo frontal",   "Diagonales solo en la cara frontal del andamio"),
            ('BACK',  "Solo posterior", "Diagonales solo en la cara posterior del andamio"),
            ('BOTH',  "Ambas caras",    "Diagonales en ambas caras (mismas bays)"),
            ('ALT',   "Alternadas",     "Frontal y posterior alternando bays (cada 4)"),
        ],
        default='FRONT',
        description="Distribución de las diagonales entre las caras frontal y posterior del andamio",
        update=_on_prop_change_regen,
    )
    brace_subdivision: EnumProperty(
        name="Subdivisión cruces",
        items=[
            ('NONE',    "Cruz completa",
             "Una diagonal por bay×planta esquina-a-esquina (≈2,9 m en Layher 2,07×2 m)"),
            ('HALF',    "Sub-cruces ½ altura (zigzag)",
             "Dos diagonales por bay×planta ancladas a roseta intermedia, formando "
             "patrón en N. Cada pieza ≈2,3 m. Usa más material pero piezas más manejables."),
            ('QUARTER', "Sub-cruces ¼ altura (zigzag fino)",
             "Cuatro diagonales por bay×planta ancladas a rosetas cada 0,5 m. "
             "Cada pieza ≈2,1 m. Sólo recomendado en torres de altura ≥15 m."),
        ],
        default='NONE',
        description="Subdivide cada cruce diagonal en sub-tramos zigzag entre rosetas "
                    "intermedias del poste. Reduce la longitud máxima de pieza a costa "
                    "de más unidades. Patrón N triangulado (estructuralmente válido).",
        update=_on_prop_change_regen,
    )
    add_horizontal_braces: BoolProperty(
        name="Cruces en planta (rigidizan torsión)",
        default=False,
        description="Genera diagonales en el plano horizontal del deck (vistas desde arriba forman aspas), cada N plantas y M vanos. Rigidizan el andamio frente a torsión (racking)",
        update=_on_prop_change_regen,
    )
    h_brace_every_floors: IntProperty(
        name="Diag. horiz. cada N plantas",
        default=2, min=1, max=10,
        update=_on_prop_change_regen,
    )
    h_brace_every_bays: IntProperty(
        name="Diag. horiz. cada M vanos",
        default=4, min=1, max=20,
        update=_on_prop_change_regen,
    )
    add_ladders: BoolProperty(name="Escaleras", default=True, update=_on_prop_change_regen)
    ladder_every: IntProperty(
        name="Escalera cada N vanos",
        default=3, min=1, max=20,
        update=_on_prop_change_regen,
    )
    use_manual_ladders: BoolProperty(
        name="Posición manual de escaleras",
        default=False,
        description="Define la posición de cada escalera con sliders (en vez de cada N vanos). Snap al centro del vano más cercano",
        update=_on_prop_change_regen,
    )
    ladder_slots: CollectionProperty(type=ANDAMIOS_LadderSlot)
    active_ladder_slot: IntProperty(default=0, min=0)
    ladder_length: FloatProperty(
        name="Longitud de escalera (m)",
        default=2.5, min=1.5, max=5.0, unit='LENGTH',
        description="Longitud estándar de cada tramo de escalera. La inclinación se calcula a partir de esta longitud y la altura por planta.",
        update=_on_prop_change_regen,
    )
    ladder_width: FloatProperty(
        name="Anchura escalera (m)",
        default=0.42, min=0.30, max=0.80, unit='LENGTH',
        description="Separación entre rieles (= longitud de los peldaños)",
        update=_on_prop_change_regen,
    )
    add_ladder_handrail: BoolProperty(
        name="Pasamanos lateral (escalera)",
        default=True,
        description=(
            "Añade un tubo paralelo a un lado de la escalera, elevado "
            "sobre los rieles principales, para que el trabajador se "
            "agarre durante el ascenso. Equivale a la pieza Layher "
            "Steigleiterschutzgeländer (EN 12811-1 §7.2 — protección "
            "personal en accesos verticales)"
        ),
        update=_on_prop_change_regen,
    )
    ladder_handrail_height: FloatProperty(
        name="Altura pasamanos (m)",
        default=0.90, min=0.70, max=1.20, unit='LENGTH',
        description=(
            "Distancia vertical entre el riel de la escalera y el "
            "pasamanos elevado. 0,9-1,0 m es el rango ergonómico estándar "
            "para que el trabajador llegue al agarre sin esfuerzo durante "
            "el ascenso"
        ),
        update=_on_prop_change_regen,
    )
    lid_open_deg: FloatProperty(
        name="Apertura tapa (°)",
        default=85.0, min=0.0, max=120.0,
        description="Ángulo de apertura visible de la tapa de la trampilla",
        update=_on_prop_change_regen,
    )
    auto_update: BoolProperty(
        name="Auto-actualizar al mover la trayectoria",
        default=False,
        description="Regenera el andamio automáticamente al mover cualquier punto de la polilínea",
        update=_on_auto_update_toggle,
    )

    # Colores por categoría (Fase D, #30) — se aplican al material correspondiente
    color_postes:      FloatVectorProperty(name="Postes",      subtype='COLOR', size=4, default=(0.20, 0.45, 0.85, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_travesanos:  FloatVectorProperty(name="Travesaños",  subtype='COLOR', size=4, default=(0.40, 0.65, 0.95, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_plataformas: FloatVectorProperty(name="Plataformas", subtype='COLOR', size=4, default=(0.55, 0.35, 0.15, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_cruces:      FloatVectorProperty(name="Cruces",      subtype='COLOR', size=4, default=(0.95, 0.45, 0.10, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_escaleras:   FloatVectorProperty(name="Escaleras",   subtype='COLOR', size=4, default=(0.85, 0.15, 0.15, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_barandillas: FloatVectorProperty(name="Barandillas", subtype='COLOR', size=4, default=(1.00, 0.85, 0.00, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_trampillas:  FloatVectorProperty(name="Trampillas",  subtype='COLOR', size=4, default=(0.20, 0.70, 0.30, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_anclajes:    FloatVectorProperty(name="Anclajes",    subtype='COLOR', size=4, default=(0.85, 0.85, 0.85, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_husillos:    FloatVectorProperty(name="Husillos",    subtype='COLOR', size=4, default=(0.55, 0.55, 0.60, 1.0), min=0.0, max=1.0, update=_on_color_change)
    color_acoples:     FloatVectorProperty(name="Acoples",     subtype='COLOR', size=4, default=(0.30, 0.30, 0.35, 1.0), min=0.0, max=1.0, update=_on_color_change)

    # ── Catálogo Ringlock EU de bandejas (Fase 1) ───────────────────────────
    deck_filter_width: EnumProperty(
        name="Filtro ancho",
        items=[
            ('ANY',  "Cualquiera", ""),
            ('0.32', "0.32 m",     ""),
            ('0.61', "0.61 m",     ""),
        ],
        default='ANY',
    )
    deck_filter_class: EnumProperty(
        name="Filtro clase",
        items=[
            ('ANY', "Cualquiera", ""),
            ('1',   "Clase 1",    "0.75 kN/m²"),
            ('2',   "Clase 2",    "1.50 kN/m²"),
            ('3',   "Clase 3",    "2.00 kN/m²"),
            ('4',   "Clase 4",    "3.00 kN/m²"),
            ('5',   "Clase 5",    "4.50 kN/m²"),
            ('6',   "Clase 6",    "6.00 kN/m²"),
        ],
        default='ANY',
    )
    deck_filter_material: EnumProperty(
        name="Filtro material",
        items=[
            ('ANY',      "Cualquiera",     ""),
            ('STEEL',    "Acero",          ""),
            ('ALUMINUM', "Aluminio",       ""),
            ('ALU_LVL',  "Alu + LVL",      ""),
        ],
        default='ANY',
    )
    selected_deck_id: EnumProperty(
        name="Bandeja seleccionada",
        items=_deck_catalog_enum_items,
        description="Bandeja del catálogo Ringlock EU. Filtra arriba si quieres reducir la lista",
    )

    last_summary: StringProperty(default="")

    # ------------------------------------------------------------------
    # Propiedades del módulo de cálculo estructural (calc/)
    # ------------------------------------------------------------------
    calc_apply_service: BoolProperty(
        name="Carga de uso",
        default=True,
        description=(
            "Considera el peso de los trabajadores y materiales sobre las "
            "plataformas. Sin esto sólo se calcula con el peso del propio "
            "andamio (irrealmente bajo)"
        ),
    )
    calc_service_class: EnumProperty(
        name="Tipo de uso",
        items=[
            ("Q1", "Inspección — 75 kg/m²",
             "Solo se camina por encima, sin herramientas pesadas"),
            ("Q2", "Uso ligero — 150 kg/m²",
             "Pintura, limpieza, instalaciones ligeras"),
            ("Q3", "Uso general — 200 kg/m²",
             "Trabajo habitual de fachada (≈4 trabajadores con herramienta)"),
            ("Q4", "Carga elevada — 300 kg/m²",
             "Albañilería, reparaciones con material acopiado"),
            ("Q5", "Almacenaje pesado — 450 kg/m²",
             "Almacenamiento de materiales pesados sobre el andamio"),
            ("Q6", "Almacenaje muy pesado — 600 kg/m²",
             "Almacenamiento intensivo (raro en andamio de fachada)"),
        ],
        default="Q3",
        description="Clase de servicio EN 12811-1 — selecciona según el uso "
                    "previsto del andamio",
    )
    calc_service_deck_width: FloatProperty(
        name="Ancho de tablón (m)",
        default=0.61,
        min=0.1,
        max=2.0,
        precision=2,
        description=(
            "Ancho útil del paño de plataforma que cada par de travesaños "
            "soporta. 0,61 m es el estándar Layher para 2 tablones de ancho"
        ),
    )

    calc_apply_wind: BoolProperty(
        name="Viento",
        default=True,
        description=(
            "Aplica la presión de viento sobre los postes según el CTE "
            "DB-SE-AE. Necesario para certificar el andamio en exterior"
        ),
    )
    calc_wind_zone: EnumProperty(
        name="Zona del viento",
        items=[
            ("A", "Zona A — costa cantábrica e interior",
             "26 m/s, viento moderado (la mayor parte de España)"),
            ("B", "Zona B — costa atlántica",
             "27 m/s, viento medio (Galicia, Andalucía atlántica)"),
            ("C", "Zona C — Canarias y litoral expuesto",
             "29 m/s, viento fuerte"),
        ],
        default="A",
        description="Zona de viento del CTE DB-SE-AE Anejo D según la "
                    "ubicación geográfica del andamio",
    )
    calc_wind_terrain: EnumProperty(
        name="Tipo de entorno",
        items=[
            ("0", "Mar abierto",   "Sin obstáculos (frente marítimo, lago grande)"),
            ("I", "Campo llano",   "Llanura sin árboles, terrenos costeros"),
            ("II", "Campo abierto", "Lo más habitual: terreno con setos y construcciones aisladas"),
            ("III", "Suburbano",   "Zona urbana con edificaciones bajas dispersas"),
            ("IV", "Urbano denso", "Centros de ciudad con edificios de 5+ plantas"),
        ],
        default="II",
        description="Categoría de terreno EN 1991-1-4: cuanto más expuesto "
                    "al viento, más alta la velocidad efectiva",
    )

    calc_apply_imperfections: BoolProperty(
        name="Tolerancias de montaje",
        default=True,
        description=(
            "Considera que los postes nunca están perfectamente verticales "
            "(EN 1993-1-1 §5.3). Aplica una fuerza horizontal equivalente "
            "≈0,5 % del peso total. Recomendado siempre activado"
        ),
    )

    calc_apply_guardrail: BoolProperty(
        name="Carga en barandilla (EN 12811 §7.2)",
        default=False,
        description=(
            "Aplica 0,3 kN puntuales horizontales en los postes a la altura "
            "de la barandilla, según exige EN 12811-1 §7.2.1 (carga de "
            "protección personal contra caídas). Activar para verificar "
            "que los postes resisten también este cortante adicional"
        ),
    )

    calc_use_pdelta: BoolProperty(
        name="Análisis P-Δ (2º orden geométrico)",
        default=False,
        description=(
            "Activa análisis de segundo orden P-Delta: la rigidez se "
            "recalcula iterativamente teniendo en cuenta la posición "
            "deformada de los postes. Captura la amplificación de "
            "momentos cuando la cúspide del andamio se desploma bajo "
            "carga (efecto P·Δ). Más lento (~2-5×) pero requerido por "
            "EN 1993-1-1 §5.2 cuando α_cr ≤ 10. RECOMENDADO en torres "
            "esbeltas (>15 m sin anclajes) o si el cálculo lineal da "
            "utilizaciones próximas a 1,0 — el segundo orden puede "
            "subir el resultado un 10-20 %"
        ),
    )

    calc_color_mode: EnumProperty(
        name="Visualización",
        items=[
            ("utilization", "Utilización (riesgo de fallo)",
             "Colorea cada barra según su grado de aprovechamiento de la "
             "capacidad. Rojo = al límite o sobrepasada"),
            ("deflection", "Deformación (cuánto se mueve)",
             "Colorea cada barra según cuánto se ha desplazado al cargar. "
             "Rojo = deformación excesiva (>L/100)"),
        ],
        default="utilization",
        description="Qué propiedad muestran los colores en el viewport tras "
                    "ejecutar el cálculo. Cambia el modo y vuelve a pulsar "
                    "Ejecutar para ver la otra capa de información",
    )

    calc_failures: CollectionProperty(type=ANDAMIOS_FailureEntry)
    calc_failures_index: IntProperty(default=0)

    calc_deformation_scale: FloatProperty(
        name="Amplificación deformada (×)",
        default=100.0,
        min=1.0,
        max=1000.0,
        precision=0,
        description=(
            "Factor de exageración para la geometría deformada. "
            "Las deformaciones reales son de pocos milímetros (invisibles a "
            "simple vista); ×100 las hace claramente perceptibles. Sólo "
            "afecta a la visualización: el cálculo no cambia"
        ),
    )

    calc_combo: EnumProperty(
        name="Caso a comprobar",
        items=[
            ("ULS_LeadL", "Resistencia — uso dominante",
             "Comprueba la rotura cuando el peso de trabajo es lo crítico "
             "(útil cuando hay mucha carga sobre las plataformas)"),
            ("ULS_LeadW", "Resistencia — viento dominante",
             "Comprueba la rotura cuando el viento es lo crítico "
             "(el caso más exigente para andamios altos / expuestos)"),
            ("ULS_Uplift", "Resistencia — levantamiento por viento",
             "Verifica que el viento no levanta la estructura "
             "(carga de uso minorada)"),
            ("SLS_char_L", "Servicio — deformación característica",
             "Comprueba flecha y deformaciones bajo cargas habituales"),
            ("SLS_freq_L", "Servicio — deformación frecuente",
             "Como característica pero con cargas reducidas (frecuencia diaria)"),
            ("SLS_quasi", "Servicio — deformación casi-permanente",
             "Cargas que actúan la mayor parte del tiempo"),
        ],
        default="ULS_LeadL",
        description="Selecciona qué tipo de comprobación quieres realizar. "
                    "Para certificar un andamio normalmente se ejecutan "
                    "ULS — uso dominante y ULS — viento dominante",
    )


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _new_empty(name, location, scene_collection):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = 'PLAIN_AXES'
    obj.empty_display_size = 0.5
    scene_collection.objects.link(obj)
    obj.location = location
    return obj


def _next_point_name(props):
    used = {it.obj.name for it in props.path_points if it.obj is not None}
    i = 0
    while True:
        name = f"Andamio_P{i:02d}"
        if name not in used and name not in bpy.data.objects:
            return name
        i += 1


class ANDAMIOS_OT_path_add(Operator):
    bl_idname = "andamios.path_add"
    bl_label = "Añadir punto a la trayectoria"
    bl_options = {'REGISTER', 'UNDO'}

    at_cursor: BoolProperty(default=False)

    def execute(self, context):
        props = context.scene.andamios_props
        item = props.path_points.add()
        if self.at_cursor:
            cursor = context.scene.cursor.location.copy()
            name = _next_point_name(props)
            obj = _new_empty(name, cursor, context.scene.collection)
            item.obj = obj
        props.active_path_index = len(props.path_points) - 1
        return {'FINISHED'}


class ANDAMIOS_OT_path_remove(Operator):
    bl_idname = "andamios.path_remove"
    bl_label = "Eliminar punto"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.andamios_props.path_points) > 0

    def execute(self, context):
        props = context.scene.andamios_props
        idx = props.active_path_index
        if 0 <= idx < len(props.path_points):
            props.path_points.remove(idx)
            props.active_path_index = max(0, min(idx, len(props.path_points) - 1))
        return {'FINISHED'}


class ANDAMIOS_OT_path_move(Operator):
    bl_idname = "andamios.path_move"
    bl_label = "Mover punto"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    def execute(self, context):
        props = context.scene.andamios_props
        idx = props.active_path_index
        n = len(props.path_points)
        if n < 2:
            return {'CANCELLED'}
        if self.direction == 'UP' and idx > 0:
            props.path_points.move(idx, idx - 1)
            props.active_path_index = idx - 1
        elif self.direction == 'DOWN' and idx < n - 1:
            props.path_points.move(idx, idx + 1)
            props.active_path_index = idx + 1
        return {'FINISHED'}


def _next_indicator_name():
    i = 0
    while True:
        name = f"Andamio_LadderHandle_{i:02d}"
        if name not in bpy.data.objects:
            return name
        i += 1


class ANDAMIOS_OT_ladder_add(Operator):
    bl_idname = "andamios.ladder_add"
    bl_label = "Añadir escalera"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.andamios_props
        slot = props.ladder_slots.add()
        n = len(props.ladder_slots)
        # Distribute evenly along the path on add
        for i, s in enumerate(props.ladder_slots):
            s.position = (i + 0.5) / n
        # Create indicator empty (cone pointing up)
        name = _next_indicator_name()
        ind = bpy.data.objects.new(name, None)
        ind.empty_display_type = 'CONE'
        ind.empty_display_size = 0.40
        ind.show_name = True
        context.scene.collection.objects.link(ind)
        slot.indicator = ind
        # Position all indicators (their slot positions just changed)
        _update_all_ladder_indicators(props)
        props.active_ladder_slot = n - 1
        return {'FINISHED'}


class ANDAMIOS_OT_ladder_remove(Operator):
    bl_idname = "andamios.ladder_remove"
    bl_label = "Eliminar escalera"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.andamios_props.ladder_slots) > 0

    def execute(self, context):
        props = context.scene.andamios_props
        idx = props.active_ladder_slot
        if 0 <= idx < len(props.ladder_slots):
            slot = props.ladder_slots[idx]
            if slot.indicator is not None:
                bpy.data.objects.remove(slot.indicator, do_unlink=True)
            props.ladder_slots.remove(idx)
            props.active_ladder_slot = max(0, min(idx, len(props.ladder_slots) - 1))
        return {'FINISHED'}


class ANDAMIOS_OT_generate(Operator):
    bl_idname = "andamios.generate"
    bl_label = "Generar / Actualizar andamios"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.andamios_props
        try:
            from calc import diagnostics as _diag
            with _diag.breadcrumb_op(
                "manual_generate",
                n_path=len(_path_objects(props)),
                floors=int(getattr(props, "floor_count", 0)),
                catalog=str(getattr(props, "bay_length_catalog", "?")),
            ):
                stats = generate_scaffold(props, context)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        msg = _format_summary(stats)
        props.last_summary = msg
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class ANDAMIOS_OT_diag_export(Operator):
    """Exporta un informe de diagnóstico del addon (breadcrumbs +
    faulthandler log + estado actual) a un .txt para enviar."""
    bl_idname = "andamios.diag_export"
    bl_label = "Exportar diagnóstico (.txt)"
    bl_description = (
        "Genera un informe con las últimas operaciones del addon, "
        "los crashes capturados por faulthandler y un snapshot del "
        "estado actual. Útil cuando Blender se cierra de golpe — "
        "envía este fichero para diagnosticar la causa."
    )

    filepath: StringProperty(subtype='FILE_PATH')
    filename_ext = ".txt"

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = bpy.path.abspath("//andamios_diag.txt")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            from calc import diagnostics as _diag
            text = _diag.export_diagnostic_text(context.scene)
        except Exception as e:
            self.report({'ERROR'}, f"No se pudo generar el informe: {e}")
            return {'CANCELLED'}
        try:
            with open(bpy.path.abspath(self.filepath), 'w', encoding='utf-8') as f:
                f.write(text)
        except OSError as e:
            self.report({'ERROR'}, f"No se pudo escribir: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Diagnóstico escrito en {self.filepath}")
        return {'FINISHED'}


class ANDAMIOS_OT_reset_colors(Operator):
    bl_idname = "andamios.reset_colors"
    bl_label = "Restablecer colores por defecto"
    bl_description = "Vuelve a los colores originales del addon para todas las categorías"
    bl_options = {'REGISTER', 'UNDO'}

    _DEFAULTS = {
        "color_postes":      (0.20, 0.45, 0.85, 1.0),
        "color_travesanos":  (0.40, 0.65, 0.95, 1.0),
        "color_plataformas": (0.55, 0.35, 0.15, 1.0),
        "color_cruces":      (0.95, 0.45, 0.10, 1.0),
        "color_escaleras":   (0.85, 0.15, 0.15, 1.0),
        "color_barandillas": (1.00, 0.85, 0.00, 1.0),
        "color_trampillas":  (0.20, 0.70, 0.30, 1.0),
        "color_anclajes":    (0.85, 0.85, 0.85, 1.0),
        "color_husillos":    (0.55, 0.55, 0.60, 1.0),
        "color_acoples":     (0.30, 0.30, 0.35, 1.0),
    }

    def execute(self, context):
        props = context.scene.andamios_props
        for prop, val in self._DEFAULTS.items():
            setattr(props, prop, val)
        self.report({'INFO'}, "Colores restablecidos a los valores por defecto")
        return {'FINISHED'}


class ANDAMIOS_OT_diag_clear(Operator):
    """Borra el log de breadcrumbs (empezar de cero)."""
    bl_idname = "andamios.diag_clear"
    bl_label = "Limpiar log de diagnóstico"
    bl_description = "Borra el historial de operaciones registradas por el addon"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            from calc import diagnostics as _diag
            _diag.clear_breadcrumbs()
            _diag.log_breadcrumb("diag_log_cleared")
        except Exception as e:
            self.report({'ERROR'}, f"Error: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, "Log de diagnóstico limpiado")
        return {'FINISHED'}


class ANDAMIOS_OT_clear(Operator):
    bl_idname = "andamios.clear"
    bl_label = "Borrar andamios"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _clear_collection(SCAFFOLD_COLLECTION)
        context.scene.andamios_props.last_summary = ""
        return {'FINISHED'}


class ANDAMIOS_OT_deck_audit(Operator):
    bl_idname = "andamios.deck_audit"
    bl_label = "Auditoría bandejas"
    bl_description = "Recorre todas las bandejas, verifica EN 12811-1 y reporta utilizaciones"
    bl_options = {'REGISTER'}

    def execute(self, context):
        audit = _audit_decks_in_scene()
        if audit is None:
            self.report({'ERROR'}, "Genera el andamio primero")
            return {'CANCELLED'}
        msg = (
            f"{audit['n_with_id']} bandejas catalogadas · "
            f"peso {audit['total_weight_kg']:.1f} kg · "
            f"OK {audit['n_pass']} / FAIL {audit['n_fail']} · "
            f"peor util = {audit['worst_util']:.3f} ({audit['worst_name']})"
        )
        self.report({'INFO'}, msg)
        # Detailed breakdown to system console
        print("\n=== AUDITORÍA RINGLOCK EU ===")
        print(f"  Bandejas catalogadas: {audit['n_with_id']}")
        print(f"  Peso total:           {audit['total_weight_kg']:.1f} kg")
        print(f"  No-match (>5 mm):     {audit['n_unmatched']}")
        print(f"  Verificación SLS:     {audit['n_pass']} OK / {audit['n_fail']} FAIL")
        print(f"  Peor utilización:     {audit['worst_util']:.3f} → {audit['worst_name']}")
        print(f"  Distribución por id:")
        for did, n in audit['by_id'].items():
            spec = _deck_spec(did)
            print(f"    {n:3d}× {did:30s}  ({spec['self_weight_kg']:.1f} kg/u, clase {spec['load_class']})")
        # Save into the scene props so the panel can show a snapshot
        context.scene.andamios_props.last_summary = msg
        return {'FINISHED'}


class ANDAMIOS_OT_deck_auto_cover(Operator):
    bl_idname = "andamios.deck_auto_cover"
    bl_label = "Auto-cubrir bandejas"
    bl_description = (
        "Busca la mejor combinación de bandejas Ringlock (0.19/0.32/0.61 m) que cubra "
        "scaffold_depth con hueco ≤ 25 mm (EN 12811-1). "
        "Si la combinación es uniforme la aplica y regenera; si es mixta sólo la reporta."
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.andamios_props
        sug = _suggest_deck_cover(props.scaffold_depth, DECK_GAP_MAX_MM)
        widths_txt = " + ".join(f"{w:.2f}" for w in sug["widths"])
        gap = sug["gap_mm"]
        gap_disp = max(0.0, gap) if sug["within_tol"] else gap
        if sug["uniform"] and sug["within_tol"]:
            props.deck_planks_count = sug["n"]
            props.deck_plank_width = sug["widths"][0]
            bpy.ops.andamios.generate()
            self.report(
                {'INFO'},
                f"Aplicado {sug['n']}× {sug['widths'][0]:.2f} m → hueco {gap_disp:.0f} mm",
            )
            return {'FINISHED'}
        if sug["within_tol"]:
            self.report(
                {'WARNING'},
                f"Mejor combinación: {widths_txt} m (hueco {gap_disp:.0f} mm). "
                f"Es mixta — props uniformes no la pueden aplicar; ajusta manualmente.",
            )
        else:
            self.report(
                {'WARNING'},
                f"Sin combinación dentro de tolerancia. "
                f"Mejor aproximación: {widths_txt} m (gap {gap:+.0f} mm).",
            )
        return {'FINISHED'}


class ANDAMIOS_OT_export_bom(Operator):
    bl_idname = "andamios.export_bom"
    bl_label = "Exportar lista de materiales (CSV)"

    filepath: StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        self.filepath = bpy.path.abspath("//andamios_bom.csv")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        coll = bpy.data.collections.get(SCAFFOLD_COLLECTION)
        if coll is None:
            self.report({'ERROR'}, "Genera primero el andamio.")
            return {'CANCELLED'}
        counts = {sub.name: len(sub.objects) for sub in coll.children}
        try:
            with open(bpy.path.abspath(self.filepath), 'w', encoding='utf-8') as f:
                f.write("Categoria,Cantidad\n")
                for k, v in counts.items():
                    f.write(f"{k},{v}\n")
        except OSError as e:
            self.report({'ERROR'}, f"No se pudo escribir: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Exportado a {self.filepath}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class ANDAMIOS_UL_path(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=f"P{index}", icon='EMPTY_AXIS')
            row.prop(item, "obj", text="")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=f"P{index}")


class ANDAMIOS_UL_ladders(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=f"L{index}", icon='MOD_DECIM')
            row.prop(item, "position", text="", slider=True)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=f"L{index}")


class ANDAMIOS_PT_panel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Andamios"
    bl_label = "Andamios trayectoria"

    def draw(self, context):
        layout = self.layout
        props = context.scene.andamios_props

        # Preset rápido en lo alto del panel + guía inline para principiantes
        layout.prop(props, "preset")
        guide = layout.column(align=True); guide.scale_y = 0.85
        guide.label(
            text="Cambia: profundidad, nº y ancho de bandejas, catálogo de vanos",
            icon='INFO',
        )
        if props.preset != 'CUSTOM':
            cfg = _PRESETS.get(props.preset, {})
            derived = False
            for k, expected in cfg.items():
                actual = getattr(props, k, None)
                if isinstance(expected, float) and isinstance(actual, float):
                    if abs(actual - expected) > 1e-4:
                        derived = True; break
                elif actual != expected:
                    derived = True; break
            if derived:
                guide.label(
                    text="Has cambiado algo · pon 'Personalizado' para no liarte",
                    icon='QUESTION',
                )

        box = layout.box()
        box.label(text="Trayectoria (polilínea)", icon='IPO_LINEAR')
        row = box.row()
        row.template_list(
            "ANDAMIOS_UL_path", "",
            props, "path_points",
            props, "active_path_index",
            rows=4,
        )
        col = row.column(align=True)
        op = col.operator("andamios.path_add", icon='ADD', text="")
        op.at_cursor = False
        col.operator("andamios.path_remove", icon='REMOVE', text="")
        col.separator()
        op = col.operator("andamios.path_move", icon='TRIA_UP', text="")
        op.direction = 'UP'
        op = col.operator("andamios.path_move", icon='TRIA_DOWN', text="")
        op.direction = 'DOWN'
        col.separator()
        op = col.operator("andamios.path_add", icon='CURSOR', text="")
        op.at_cursor = True
        box.prop(props, "base_z")
        box.prop(props, "jack_height")
        # Catálogo de postes (selector en línea como con bays)
        row_pc = box.row(align=True)
        row_pc.prop(props, "pole_length_catalog", expand=True)
        sub_pl = box.row()
        sub_pl.enabled = (props.pole_length_catalog == 'UNIFORM')
        sub_pl.prop(props, "pole_segment_length")
        row_r = box.row(align=True)
        row_r.prop(props, "add_rosettes")
        sub_r = row_r.row()
        sub_r.enabled = props.add_rosettes
        sub_r.prop(props, "rosette_pitch")
        box.prop(props, "closed_loop")
        box.prop(props, "use_terrain_z")

        box = layout.box()
        box.label(text="Dimensiones", icon='ARROW_LEFTRIGHT')
        # Catálogo de longitudes como botones expandidos
        row = box.row(align=True)
        row.prop(props, "bay_length_catalog", expand=True)
        # section_length sólo aplica con UNIFORM
        sec = box.row()
        sec.enabled = (props.bay_length_catalog == 'UNIFORM')
        sec.prop(props, "section_length")
        box.prop(props, "scaffold_depth")
        box.prop(props, "floor_count")
        box.prop(props, "floor_height")
        # Validation warnings
        n_planks_fit = int(props.scaffold_depth / max(0.05, props.deck_plank_width)) if props.add_decks else 0
        if props.add_decks and n_planks_fit < props.deck_planks_count:
            box.label(
                text=iface_("⚠ Solo entran %d bandejas en %.2f m") % (
                    n_planks_fit, props.scaffold_depth,
                ),
                icon='ERROR',
            )
        if props.add_ladders:
            from math import sqrt as _sqrt
            try:
                _tilt = _sqrt(max(0.0, props.ladder_length ** 2 - props.floor_height ** 2))
                est_bay_len = props.section_length
                if _tilt > est_bay_len - 0.1:
                    box.label(
                        text=iface_("⚠ tilt %.2f m > vano %.2f m: la base puede salir") % (
                            _tilt, est_bay_len,
                        ),
                        icon='ERROR',
                    )
            except ValueError:
                pass

        box = layout.box()
        box.label(text="Componentes", icon='MOD_BUILD')
        box.prop(props, "add_decks")
        sub_d = box.row(align=True)
        sub_d.enabled = props.add_decks
        sub_d.prop(props, "deck_planks_count")
        sub_d.prop(props, "deck_plank_width")
        sub_cp = box.row()
        sub_cp.enabled = props.add_decks
        sub_cp.prop(props, "add_corner_planks")
        sub_dm = box.row()
        sub_dm.enabled = props.add_decks
        sub_dm.prop(props, "deck_material_pref")
        box.prop(props, "guardrails")
        box.prop(props, "add_braces")
        sub_bp = box.row()
        sub_bp.enabled = props.add_braces
        sub_bp.prop(props, "brace_pattern")
        sub_sd = box.row()
        sub_sd.enabled = props.add_braces
        sub_sd.prop(props, "brace_subdivision")
        box.prop(props, "add_horizontal_braces")
        sub_h = box.row(align=True)
        sub_h.enabled = props.add_horizontal_braces
        sub_h.prop(props, "h_brace_every_floors")
        sub_h.prop(props, "h_brace_every_bays")
        row = box.row(align=True)
        row.prop(props, "add_ladders")
        sub = row.row()
        sub.enabled = props.add_ladders and not props.use_manual_ladders
        sub.prop(props, "ladder_every")
        sub_m = box.row()
        sub_m.enabled = props.add_ladders
        sub_m.prop(props, "use_manual_ladders")
        if props.use_manual_ladders:
            ladder_box = box.box()
            ladder_box.enabled = props.add_ladders
            row_l = ladder_box.row()
            row_l.template_list(
                "ANDAMIOS_UL_ladders", "",
                props, "ladder_slots",
                props, "active_ladder_slot",
                rows=3,
            )
            col_l = row_l.column(align=True)
            col_l.operator("andamios.ladder_add", icon='ADD', text="")
            col_l.operator("andamios.ladder_remove", icon='REMOVE', text="")
        sub2 = box.row(align=True)
        sub2.enabled = props.add_ladders
        sub2.prop(props, "ladder_length")
        sub2.prop(props, "ladder_width")
        sub3 = box.row()
        sub3.enabled = props.add_ladders
        sub3.prop(props, "lid_open_deg")
        sub_h = box.row(align=True)
        sub_h.enabled = props.add_ladders
        sub_h.prop(props, "add_ladder_handrail")
        sub_h2 = box.row()
        sub_h2.enabled = props.add_ladders and props.add_ladder_handrail
        sub_h2.prop(props, "ladder_handrail_height")

        box.prop(props, "add_ties")
        sub_t = box.row(align=True)
        sub_t.enabled = props.add_ties
        sub_t.prop(props, "tie_every_bays")
        sub_t.prop(props, "tie_every_floors")
        sub_t2 = box.row()
        sub_t2.enabled = props.add_ties
        sub_t2.prop(props, "tie_length")

        # ── Catálogo Ringlock EU de bandejas (Fase 1) ───────────────────────
        box = layout.box()
        box.label(text="Bandejas — Catálogo Ringlock EU", icon='MESH_PLANE')
        rowf = box.row(align=True)
        rowf.prop(props, "deck_filter_width", text="Ancho")
        rowf.prop(props, "deck_filter_class", text="Clase")
        rowf.prop(props, "deck_filter_material", text="Material")
        box.prop(props, "selected_deck_id", text="")
        spec = _deck_spec(props.selected_deck_id)
        if spec is not None:
            info = box.column(align=True)
            info.label(
                text=iface_("%.2f m × %.2f m · %s") % (
                    spec['nominal_length'], spec['deck_width'], spec['construction_type'],
                ),
                icon='INFO',
            )
            info.label(
                text=iface_("Clase %s → qk = %.2f kN/m²") % (
                    spec['load_class'], spec['qk_uniform_kN_m2'],
                ),
            )
            info.label(
                text=iface_("Peso: %.1f kg · MRd = %.2f kN·m · VRd = %.1f kN") % (
                    spec['self_weight_kg'], spec['MRd_kNm'], spec['VRd_kN'],
                ),
            )
            info.label(
                text=iface_("Sistema: %s · CE") % (spec['system_compatibility'],),
            )
            if spec.get("is_estimated"):
                info.label(text=iface_("⚠ Valores estructurales conservadores estimados"), icon='ERROR')
        # Indicador de cobertura: hueco perp entre las N bandejas y el back row.
        if props.add_decks:
            tot_planks_w = props.deck_planks_count * props.deck_plank_width
            gap_perp_mm = (props.scaffold_depth - tot_planks_w) * 1000.0
            cov = box.row()
            if gap_perp_mm > DECK_GAP_MAX_MM:
                cov.label(
                    text=iface_("⚠ Hueco perp %.0f mm > %d mm (EN 12811-1)") % (
                        gap_perp_mm, int(DECK_GAP_MAX_MM),
                    ),
                    icon='ERROR',
                )
            elif gap_perp_mm < -1:
                cov.label(
                    text=iface_("⚠ Bandejas exceden depth en %.0f mm") % (-gap_perp_mm,),
                    icon='ERROR',
                )
            else:
                cov.label(
                    text=iface_("Hueco perp %.0f mm ≤ %d mm ✓") % (
                        gap_perp_mm, int(DECK_GAP_MAX_MM),
                    ),
                    icon='CHECKMARK',
                )
        # Sugerencia de combinación (visible siempre que el hueco esté fuera de tolerancia)
        if props.add_decks:
            sug = _suggest_deck_cover(props.scaffold_depth, DECK_GAP_MAX_MM)
            current_gap_in_tol = 0 <= gap_perp_mm <= DECK_GAP_MAX_MM
            if not current_gap_in_tol and sug["within_tol"]:
                w_txt = " + ".join(f"{w:.2f}" for w in sug["widths"])
                box.label(
                    text=iface_("💡 Sugerido: %s m → hueco %.0f mm") % (
                        w_txt, sug['gap_mm'],
                    ),
                    icon='LIGHT',
                )
        # Botones de auditoría y auto-cubrir
        row_da = box.row(align=True)
        row_da.operator("andamios.deck_audit", icon='VIEWZOOM')
        row_da.operator("andamios.deck_auto_cover", icon='SHADERFX')

        # Colores agrupados por función: Estructura · Acceso · Seguridad
        box = layout.box()
        head = box.row(align=True)
        head.label(text="Colores", icon='COLOR')
        head.operator("andamios.reset_colors", text="", icon='LOOP_BACK')

        box.label(text="Estructura", icon='MOD_BUILD')
        g1 = box.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        g1.prop(props, "color_postes", text="Postes")
        g1.prop(props, "color_travesanos", text="Travesaños")
        g1.prop(props, "color_cruces", text="Cruces")
        g1.prop(props, "color_anclajes", text="Anclajes")
        g1.prop(props, "color_husillos", text="Husillos")
        g1.prop(props, "color_acoples", text="Acoples")

        box.separator()
        box.label(text="Acceso", icon='ANIM')
        g2 = box.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        g2.prop(props, "color_plataformas", text="Plataformas")
        g2.prop(props, "color_escaleras", text="Escaleras")
        g2.prop(props, "color_trampillas", text="Trampillas")

        box.separator()
        box.label(text="Seguridad", icon='LOCKED')
        g3 = box.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        g3.prop(props, "color_barandillas", text="Barandillas")

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("andamios.generate", text="Generar / Actualizar", icon='FILE_REFRESH')
        row = layout.row(align=True)
        row.operator("andamios.clear", icon='X')
        row.operator("andamios.export_bom", icon='EXPORT')
        layout.prop(props, "auto_update", icon='AUTO')

        if props.last_summary:
            box = layout.box()
            box.label(text="Resumen:", icon='INFO')
            for line in props.last_summary.split("  |  "):
                box.label(text=line)

        # Reporte de errores del addon (no confundir con "Comprobar modelo"
        # del cálculo, que valida la geometría). Esta sección es solo para
        # cuando Blender ha fallado o se ha cerrado y necesitamos depurar.
        diag_box = layout.box()
        diag_box.label(text="Reporte de errores", icon='CONSOLE')
        diag_box.label(text="(Solo para depurar fallos)", icon='INFO')
        diag_row = diag_box.row(align=True)
        diag_row.operator("andamios.diag_export", text="Exportar log", icon='TEXT')
        diag_row.operator("andamios.diag_clear", text="", icon='TRASH')


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

CLASSES = (
    ANDAMIOS_PathPoint,
    ANDAMIOS_LadderSlot,
    ANDAMIOS_FailureEntry,
    ANDAMIOS_Props,
    ANDAMIOS_OT_path_add,
    ANDAMIOS_OT_path_remove,
    ANDAMIOS_OT_path_move,
    ANDAMIOS_OT_ladder_add,
    ANDAMIOS_OT_ladder_remove,
    ANDAMIOS_OT_generate,
    ANDAMIOS_OT_clear,
    ANDAMIOS_OT_deck_audit,
    ANDAMIOS_OT_deck_auto_cover,
    ANDAMIOS_OT_export_bom,
    ANDAMIOS_OT_reset_colors,
    ANDAMIOS_OT_diag_export,
    ANDAMIOS_OT_diag_clear,
    ANDAMIOS_UL_path,
    ANDAMIOS_UL_ladders,
    ANDAMIOS_PT_panel,
)


def _ensure_calc_on_path():
    """Asegura que el directorio que contiene este archivo (donde vive calc/)
    está en sys.path. Necesario al ejecutar desde el Text Editor de Blender,
    que NO añade automáticamente la carpeta del script al path."""
    import os
    import sys
    here = None
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        # __file__ no definido (text block en memoria). Probamos a localizarlo
        # a través del Text Editor activo.
        try:
            text = bpy.context.space_data.text
            if text and text.filepath:
                here = os.path.dirname(os.path.abspath(bpy.path.abspath(text.filepath)))
        except Exception:
            pass
    if here and here not in sys.path:
        sys.path.insert(0, here)
        print(f"[andamios] sys.path += {here}")


def _ensure_user_site_packages():
    """Añade el directorio de paquetes de usuario (~/.local/.../site-packages)
    a sys.path. Blender embebe Python con `ENABLE_USER_SITE = False`, así que
    los módulos instalados con `pip install --user` (PyNite, scipy, etc.)
    no son visibles por defecto. Esta función los expone manualmente."""
    import os
    import site
    import sys
    user_site = site.getusersitepackages()
    if user_site and os.path.isdir(user_site) and user_site not in sys.path:
        sys.path.append(user_site)
        print(f"[andamios] sys.path += {user_site}")


def _ensure_pynite():
    """Auto-instala PyNiteFEA y numpy usando el pip de Blender si no están presentes."""
    try:
        from Pynite import FEModel3D  # noqa: F401
        return True
    except ImportError:
        pass
    import sys
    import subprocess
    python_exe = sys.executable
    print("[andamios] PyNiteFEA no encontrado — instalando dependencias de cálculo…")
    try:
        subprocess.run(
            [python_exe, "-m", "pip", "install", "--user", "--quiet",
             "PyNiteFEA", "numpy"],
            check=True,
            capture_output=True,
        )
        _ensure_user_site_packages()
        from Pynite import FEModel3D  # noqa: F401
        print("[andamios] PyNiteFEA instalado correctamente")
        return True
    except Exception as exc:
        print(f"[andamios] No se pudo instalar PyNiteFEA automáticamente: {exc}")
        return False


def register():
    _ensure_calc_on_path()
    _ensure_user_site_packages()
    # i18n primero — para que las clases que se registran a continuación
    # encuentren el dict listo cuando Blender renderice por primera vez.
    try:
        import i18n as _i18n
        _i18n.register()
    except Exception as e:
        print(f"[andamios] i18n no disponible: {e}")
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.andamios_props = PointerProperty(type=ANDAMIOS_Props)
    _auto_register()
    _ensure_pynite()
    # Diagnóstico: faulthandler + breadcrumb del registro. Antes de cualquier
    # otra cosa que pueda romper, para no perder el rastro del propio
    # arranque.
    try:
        from calc import diagnostics as _diag
        log_path = _diag.enable_faulthandler()
        _diag.log_breadcrumb(
            "addon_register",
            version=".".join(str(x) for x in bl_info["version"]),
            faulthandler_log=str(log_path) if log_path else None,
        )
    except Exception as e:
        print(f"[andamios] Diagnóstico no disponible: {e}")
    try:
        from calc import ui as _calc_ui
        _calc_ui.register()
        print("[andamios] Cálculo estructural registrado correctamente")
    except Exception as e:
        import traceback
        print(f"[andamios] Cálculo estructural no disponible: {type(e).__name__}: {e}")
        traceback.print_exc()
    # Tutorial guiado in-Blender (overlay + state machine). Independiente
    # del cálculo: si el usuario no tiene PyNiteFEA, esto sigue funcionando.
    try:
        import tutorial_guide as _tut
        _tut.register()
        print("[andamios] Tutorial guiado registrado")
    except Exception as e:
        print(f"[andamios] Tutorial guiado no disponible: {e}")


def unregister():
    try:
        from calc import diagnostics as _diag
        _diag.log_breadcrumb("addon_unregister")
        _diag.disable_faulthandler()
    except Exception:
        pass
    try:
        import tutorial_guide as _tut
        _tut.unregister()
    except Exception:
        pass
    try:
        from calc import ui as _calc_ui
        _calc_ui.unregister()
    except Exception:
        pass
    _auto_unregister()
    del bpy.types.Scene.andamios_props
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    try:
        import i18n as _i18n
        _i18n.unregister()
    except Exception:
        pass


if __name__ == "__main__":
    register()
