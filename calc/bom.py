"""Bill of materials (BOM) del andamio.

Helpers puros para enumerar y agregar los elementos físicos del andamio,
calcular sus pesos y producir una tabla agrupada lista para suministros y
subcontratas. La generación del HTML vive en `calc/bom_report.py`.

Categorías reconocidas (por prefijo del nombre del objeto):

    pole          Pole_F* / Pole_B* / Pole_FC* / Pole_BC*
    ledger_floor  Ledger_F0..3 / Ledger_B0..3 / Ledger_TF / Ledger_TC
                  (sin las palabras "Mid", "Top", "Rail", "_E_")
    ledger_rail   Ledger_Mid_* / Ledger_Top_* / Ledger_Rail_*
                  / Ledger_E_* (extremos = barandilla en cierre)
    toe           Toe_*
    brace         Brace_* / HBrace_*
    tie           Tie_*
    plank         Plank_* / Corner_Plank_*
    trapdoor      Trapdoor_*
    ladder        Ladder_*
    husillo       Husillo_* / Spindle_*

Las sub-piezas decorativas (rosetas, sleeves, caps, heads, rods, handles,
pins, bars) se ignoran — su peso se considera parte de la tara del
sistema y no se contabiliza por separado.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


# ---------------------------------------------------------------------------
# Constantes físicas
# ---------------------------------------------------------------------------

# Densidad del acero S235JR — EN 1991-1-1 Tabla A.4
STEEL_RHO = 7850.0           # kg/m³
# Área CHS Ø48,3×3,2 — sección estándar Layher / Ringlock EU
CHS_AREA = 4.534e-4          # m²
# Peso lineal del tubo CHS Ø48,3×3,2 en kg/m
TUBE_WEIGHT_PER_M = STEEL_RHO * CHS_AREA      # ≈ 3,559 kg/m

# Sub-cadenas que identifican piezas no estructurales (decorativas) que
# se ignoran al construir el BOM.
NON_STRUCTURAL_SUBSTRINGS = (
    "_sleeve", "_cap", "_head", "_rod", "_handle", "_pin", "_bar",
    "_TmpCam",
)

# Prefijos de objetos accesorios que no entran en el BOM. Las bisagras y
# asas de trampilla se consideran parte de la propia trampilla (su peso
# está integrado en el catálogo Ringlock EU). Las rosetas SÍ se incluyen
# en el BOM porque son piezas de catálogo independientes que se piden al
# fabricante por separado.
NON_BOM_PREFIXES = (
    "Hinge_",        # bisagras de trampilla (integradas en la trampilla)
    "LidHandle_",    # asas de trampilla (integradas en la trampilla)
)

# Sufijos a IGNORAR en escaleras: una escalera tiene 2 rails (a, b) y
# N steps. Para el BOM contamos UNA escalera ensamblada (peso estimado
# del set completo) usando sólo su pieza "_rail_a" como representante;
# el resto de sub-piezas se descarta.
LADDER_REPRESENTATIVE_SUFFIX = "_rail_a"

# Pesos estimados (kg) para elementos donde no hacemos un cálculo geométrico
# detallado. Valores conservadores tipo Layher.
ESTIMATED_WEIGHT_KG = {
    "ladder":  16.0,        # tramo de escalera transversal típico
    "husillo": 1.6,         # husillo de base regulable
    "rosette": 0.6,         # roseta Layher Allround (Ø120 mm, 8 perforaciones)
}


# ---------------------------------------------------------------------------
# Categorización
# ---------------------------------------------------------------------------

# Mapeo categoría → etiqueta humana y descripción para el informe HTML
CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "pole": {
        "label":       "Postes",
        "description": "Tubos verticales que reciben el peso del andamio. "
                       "CHS Ø48,3×3,2 con uniones de roseta cada "
                       "pole_segment_length m.",
    },
    "ledger_floor": {
        "label":       "Travesaños de planta",
        "description": "Tubos horizontales que sostienen las plataformas. "
                       "Trabajan principalmente a flexión.",
    },
    "ledger_rail": {
        "label":       "Barandillas (mid + top)",
        "description": "Pasamanos a 0,5 m y 1,0 m sobre la plataforma "
                       "según EN 12811-1 §7.2 (barandilla principal).",
    },
    "toe": {
        "label":       "Rodapiés",
        "description": "Tubos horizontales al borde de la plataforma "
                       "para evitar caída de herramientas (mín 150 mm).",
    },
    "brace": {
        "label":       "Cruces de arriostramiento",
        "description": "Diagonales que estabilizan la estructura frente al "
                       "viento y otras acciones horizontales.",
    },
    "tie": {
        "label":       "Anclajes a fachada",
        "description": "Tubos que conectan el andamio al edificio. "
                       "Trasladan las acciones horizontales a la fachada.",
    },
    "plank": {
        "label":       "Plataformas",
        "description": "Bandejas que forman el suelo de trabajo (acero / "
                       "aluminio + LVL según catálogo Ringlock EU).",
    },
    "trapdoor": {
        "label":       "Plataformas con trampilla",
        "description": "Plataformas con compuerta abatible para acceso "
                       "vertical mediante escalera.",
    },
    "ladder": {
        "label":       "Escaleras",
        "description": "Escaleras transversales de acceso entre plantas.",
    },
    "husillo": {
        "label":       "Husillos de base",
        "description": "Pies regulables para nivelación. Permiten "
                       "compensar terreno irregular (use_terrain_z).",
    },
    "rosette": {
        "label":       "Rosetas",
        "description": "Discos perforados (Ø120 mm) soldados al poste cada "
                       "0,5 m. Punto de unión donde la cuña-cabeza de los "
                       "travesaños y diagonales se inserta y bloquea — "
                       "elemento clave del sistema Layher Allround / "
                       "Ringlock EU.",
    },
}


def is_structural_object_name(name: str) -> bool:
    """True si el objeto debe considerarse en el BOM (no decorativo)."""
    return not any(s in name for s in NON_STRUCTURAL_SUBSTRINGS)


def category_for_name(name: str) -> str | None:
    """Devuelve la categoría a la que pertenece un objeto por su nombre,
    o None si no es estructural ni clasificable.

    Si el nombre lleva prefijo de tramo (T0_, T1_, …) se strip-ea antes de
    clasificar — los andamios escalonados generan objetos con esos prefijos
    para evitar colisiones, pero el BOM debe reconocerlos igual."""
    import re as _re
    name = _re.sub(r"^T\d+_", "", name)
    if not is_structural_object_name(name):
        return None
    # Excluir piezas accesorias (rosetas, bisagras, etc.)
    for p in NON_BOM_PREFIXES:
        if name.startswith(p):
            return None

    if name.startswith("Rose_"):
        return "rosette"
    if name.startswith("Pole_"):
        return "pole"
    if name.startswith("Ledger_"):
        # En el addon Ledger_F/B/T/TC son siempre de planta (deck-supporting).
        # Las barandillas no usan el prefijo Ledger_ sino Rail_.
        return "ledger_floor"
    if name.startswith("Rail_"):
        # Mid-rail / Top-rail / Corner-rail / End-rail = barandilla
        return "ledger_rail"
    if name.startswith("Toe_"):
        return "toe"
    if name.startswith(("Brace_", "HBrace_")):
        return "brace"
    if name.startswith("Tie_"):
        return "tie"
    if name.startswith(("Deck_", "Plank_", "Corner_Plank_")):
        return "plank"
    if name.startswith(("Lid_", "Trapdoor_")):
        return "trapdoor"
    if name.startswith("Ladder_"):
        # Sólo contamos un objeto representativo por escalera ensamblada
        # (el "_rail_a"). El peso total de la escalera está en
        # ESTIMATED_WEIGHT_KG y cubre las dos guías + los peldaños.
        if name.endswith(LADDER_REPRESENTATIVE_SUFFIX):
            return "ladder"
        return None
    if name.startswith(("Husillo_", "Spindle_")):
        return "husillo"
    return None


# ---------------------------------------------------------------------------
# Pesos
# ---------------------------------------------------------------------------

def tube_weight_kg(length_m: float, *,
                   rho: float = STEEL_RHO,
                   area: float = CHS_AREA) -> float:
    """Peso de un tubo CHS recto: ρ · A · L."""
    if length_m <= 0:
        return 0.0
    return rho * area * length_m


def deck_weight_kg(deck_id: str, catalog: dict | None = None) -> float:
    """Peso de una plataforma según catálogo. Si `catalog` es None se
    devuelve 0 (caller pasa el catálogo de Ringlock EU desde el addon).

    `catalog` es dict[deck_id, dict] donde cada entry tiene la clave
    `weight_kg`.
    """
    if catalog is None or deck_id not in catalog:
        return 0.0
    entry = catalog[deck_id]
    return float(entry.get("weight_kg", 0.0))


# ---------------------------------------------------------------------------
# Enumeración y agregación
# ---------------------------------------------------------------------------

def aggregate_bom(items: Iterable[dict],
                  *,
                  length_round_m: float = 0.05) -> list[dict]:
    """Agrupa items de un BOM por (categoría, longitud redondeada).

    Cada item en `items` debe tener:
        category    str
        length_m    float    (ignorada para items no-tubo)
        weight_kg   float    (peso individual)
        is_tube     bool
        deck_id     str | None  (sólo para plataformas/trampillas)

    Devuelve lista de grupos:
        category, label, length_m_rounded, count, unit_weight_kg,
        total_weight_kg, deck_id (si aplica)
    Cada grupo está pre-ordenado por categoría → longitud descendente.
    """
    if length_round_m <= 0:
        length_round_m = 0.05

    groups: dict[tuple, dict] = {}

    for it in items:
        cat = it.get("category")
        if not cat:
            continue
        is_tube = bool(it.get("is_tube"))
        if is_tube:
            length_m = float(it.get("length_m", 0.0) or 0.0)
            length_round = round(length_m / length_round_m) * length_round_m
            key = (cat, "tube", round(length_round, 3))
        else:
            deck_id = it.get("deck_id") or "unknown"
            key = (cat, "deck", str(deck_id))

        weight = float(it.get("weight_kg", 0.0) or 0.0)
        if key not in groups:
            label = CATEGORY_LABELS.get(cat, {}).get("label", cat)
            groups[key] = {
                "category": cat,
                "label": label,
                "is_tube": is_tube,
                "length_m": (round(length_round, 3) if is_tube else None),
                "deck_id": (None if is_tube else (it.get("deck_id") or "")),
                "count": 0,
                "unit_weight_kg": weight,
                "total_weight_kg": 0.0,
            }
        g = groups[key]
        g["count"] += 1
        g["total_weight_kg"] += weight
        # En la primera iteración asume todos los items del grupo tienen
        # el mismo peso (correcto si la longitud está bien redondeada).
        # Para mayor precisión, recomputamos como total/count al final.

    # Recompute unit_weight como promedio del grupo (más robusto)
    for g in groups.values():
        if g["count"] > 0:
            g["unit_weight_kg"] = g["total_weight_kg"] / g["count"]

    # Orden: categoría según orden alfabético del CATEGORY_LABELS, dentro
    # de cada categoría por longitud descendente.
    cat_order = list(CATEGORY_LABELS.keys())
    return sorted(
        groups.values(),
        key=lambda g: (
            cat_order.index(g["category"]) if g["category"] in cat_order else 999,
            -(g["length_m"] or 0.0),
            g["deck_id"] or "",
        ),
    )


def _get_addon_deck_catalog() -> dict | None:
    """Devuelve el dict de catálogo Ringlock EU del addon principal,
    o None si no está disponible (entorno de tests sin el addon registrado)."""
    try:
        import andamios_addon
        return getattr(andamios_addon, "_RINGLOCK_DECK_CATALOG", None)
    except ImportError:
        return None


def enumerate_scaffold_objects(scene) -> list[dict]:
    """Recorre la colección Scaffold y produce items para el BOM.

    Cada item tiene:
        name        str   nombre del objeto Blender
        category    str   key de CATEGORY_LABELS
        is_tube     bool  True para tubos CHS, False para plataformas/etc.
        length_m    float (sólo tubos)
        weight_kg   float
        deck_id     str   (sólo plank/trapdoor)
    """
    import bpy
    coll = bpy.data.collections.get("Scaffold")
    if coll is None:
        return []

    catalog = _get_addon_deck_catalog()
    items: list[dict] = []

    for obj in coll.all_objects:
        if obj.type != "MESH":
            continue
        cat = category_for_name(obj.name)
        if cat is None:
            continue

        if cat in ("plank", "trapdoor"):
            deck_id = str(obj.get("andamio_deck_id", "") or "")
            weight = deck_weight_kg(
                deck_id,
                catalog={k: {"weight_kg": v["self_weight_kg"]}
                         for k, v in (catalog or {}).items()},
            ) if catalog else 0.0
            # Fallback si no hay catálogo o deck_id vacío
            if weight <= 0:
                weight = 19.0 if cat == "trapdoor" else 13.0
            items.append({
                "name": obj.name,
                "category": cat,
                "is_tube": False,
                "deck_id": deck_id or ("trapdoor" if cat == "trapdoor" else "plank"),
                "weight_kg": weight,
            })
        elif cat in ("ladder", "husillo", "rosette"):
            items.append({
                "name": obj.name,
                "category": cat,
                "is_tube": False,
                "deck_id": "",
                "weight_kg": ESTIMATED_WEIGHT_KG.get(cat, 5.0),
            })
        else:
            # Tubo CHS — longitud desde bound_box local
            zs = [c[2] for c in obj.bound_box]
            length_m = max(zs) - min(zs)
            items.append({
                "name": obj.name,
                "category": cat,
                "is_tube": True,
                "length_m": float(length_m),
                "weight_kg": tube_weight_kg(length_m),
            })

    return items


def representative_member_per_category(items: list[dict]) -> dict[str, str]:
    """Devuelve `{category_id: name}` con un objeto representativo de
    cada categoría — el más pesado del grupo (suele ser el más visible/
    típico) — para usarlo como "foto promocional" del BOM."""
    by_cat: dict[str, dict] = {}
    for it in items:
        cat = it["category"]
        cur = by_cat.get(cat)
        if cur is None or it["weight_kg"] > cur["weight_kg"]:
            by_cat[cat] = it
    return {cat: it["name"] for cat, it in by_cat.items()}


def summarize_bom(groups: list[dict]) -> dict:
    """Resumen agregado: total kg, total m de tubo, total nº de piezas,
    breakdown por categoría."""
    by_cat: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "weight_kg": 0.0, "tube_length_m": 0.0,
    })
    total_weight = 0.0
    total_pieces = 0
    total_tube_m = 0.0

    for g in groups:
        cat = g["category"]
        by_cat[cat]["count"] += g["count"]
        by_cat[cat]["weight_kg"] += g["total_weight_kg"]
        if g["is_tube"]:
            by_cat[cat]["tube_length_m"] += g["count"] * (g["length_m"] or 0)
            total_tube_m += g["count"] * (g["length_m"] or 0)
        total_weight += g["total_weight_kg"]
        total_pieces += g["count"]

    # Ordenar by_cat según el mismo orden que aggregate_bom
    cat_order = list(CATEGORY_LABELS.keys())
    by_cat_sorted: list[dict] = []
    for cat in cat_order:
        if cat in by_cat:
            entry = dict(by_cat[cat])
            entry["category"] = cat
            entry["label"] = CATEGORY_LABELS[cat]["label"]
            by_cat_sorted.append(entry)

    return {
        "total_weight_kg": total_weight,
        "total_pieces": total_pieces,
        "total_tube_length_m": total_tube_m,
        "by_category": by_cat_sorted,
    }
