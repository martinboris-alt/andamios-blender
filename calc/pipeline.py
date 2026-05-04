"""Pipeline orquestador del cálculo (puro Python, sin bpy).

Centraliza la lógica que `calc/ui.py` ejecuta cuando el usuario pulsa
"Ejecutar cálculo" en Blender. Al estar separado de la UI:

    - es testable sin bpy
    - puede invocarse desde scripts headless / línea de comandos
    - la UI se queda como una capa fina que sólo lee props y delega aquí

API principal:
    is_deck_supporting_ledger(member_id) -> bool
    apply_imperfections_at_top(model, *, direction="FX") -> int
    build_and_solve(model, options) -> (Results, dict[member_id, MemberCheckResult])

`options` es un dict con la misma forma que produce `calc.ui._options_from_props`.
"""

from __future__ import annotations

from typing import Mapping

from .checks import MemberCheckResult, run_all_checks
from .combinations import standard_combos
from .loads import (
    SPAIN_BASIC_WIND,
    apply_self_weight,
    apply_service_load,
    apply_wind_load,
)
from .loads.imperfections import imperfection_angle
from .model import Model
from .releases import compute_pole_lcr_overrides, set_releases_by_type
from .solver import Results, solve


# Diámetro nominal del tubo de andamio Layher / Ringlock EU (Ø 48,3 mm).
DEFAULT_TUBE_DIAMETER = 0.0483

# Heurística para distinguir ledgers que sostienen plataforma de los que
# sólo son barandillas (mid-rail, top-rail, etc.). Si el nombre del miembro
# contiene alguno de estos fragmentos, NO se le aplica carga de servicio.
NON_DECK_LEDGER_KEYWORDS = ("Mid", "Top", "Rail", "_E_", "_TE_")


# ---------------------------------------------------------------------------
# Filtros de miembros
# ---------------------------------------------------------------------------

def is_deck_supporting_ledger(member_id: str) -> bool:
    """Heurística por nombre: ¿este ledger sostiene plataforma?

    Excluye los ledgers cuyo nombre contiene Mid / Top / Rail / `_E_`
    (mid-rails y top-rails de barandilla, que no llevan plataforma encima).
    Asume el patrón de nombres del addon `andamios_addon.py`.
    """
    name = member_id[2:] if member_id.startswith("M_") else member_id
    return not any(kw in name for kw in NON_DECK_LEDGER_KEYWORDS)


# ---------------------------------------------------------------------------
# Imperfecciones globales auto-distribuidas
# ---------------------------------------------------------------------------

def apply_imperfections_at_top(model: Model, *, direction: str = "FX") -> int:
    """Aplica imperfecciones globales EN 1993-1-1 §5.3 sobre los nodos
    superiores del modelo, sin necesidad de un solve previo.

    Estrategia:
        V_total = Σ |w| · L  para todas las cargas distribuidas FZ en
                              casos D y L (gravedad y servicio).
        h       = z_max − z_min                   (altura total)
        m       = nº de columnas en planta        (postes en z = z_min)
        φ       = imperfection_angle(h, m)
        Para cada nodo en z = z_max, añadir nodal_load horizontal de
        magnitud H = φ · V_total / n_top en el caso "I".

    Devuelve el número de nodos cargados (0 si no hay cargas verticales o
    si la geometría es plana en Z).
    """
    if not model.nodes:
        return 0

    V_total = 0.0
    for dl in model.distributed_loads:
        if dl.case not in ("D", "L"):
            continue
        if dl.direction not in ("FZ", "Fz"):
            continue
        if dl.member not in model.members:
            continue
        mem = model.members[dl.member]
        ni = model.nodes[mem.i_node]
        nj = model.nodes[mem.j_node]
        L = ((nj.x - ni.x) ** 2 + (nj.y - ni.y) ** 2 + (nj.z - ni.z) ** 2) ** 0.5
        V_total += abs(0.5 * (dl.w1 + dl.w2)) * L

    if V_total <= 0:
        return 0

    z_max = max(n.z for n in model.nodes.values())
    z_min = min(n.z for n in model.nodes.values())
    h = z_max - z_min
    if h <= 0:
        return 0

    base_xy = {(round(n.x, 3), round(n.y, 3))
               for n in model.nodes.values()
               if abs(n.z - z_min) < 0.01}
    m = max(1, len(base_xy))

    phi = imperfection_angle(h, m)

    top_node_ids = [nid for nid, n in model.nodes.items()
                    if abs(n.z - z_max) < 0.01]
    if not top_node_ids:
        return 0

    H_per_node = phi * V_total / len(top_node_ids)
    for nid in top_node_ids:
        model.add_nodal_load(nid, direction, H_per_node, case="I")
    return len(top_node_ids)


# ---------------------------------------------------------------------------
# Pipeline completo
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Conectividad — fusión de nodos próximos y uniones a media barra
# ---------------------------------------------------------------------------

# Tolerancia espacial para considerar dos nodos como el mismo punto físico.
# 5 mm es seguro frente al ruido de operaciones geométricas (esquinas con
# bisectriz, redondeos de matrix_world, etc.) sin riesgo de fusionar
# elementos físicamente distintos: el tubo tiene Ø 48 mm, así que dos
# extremos a < 5 mm pertenecen a la misma unión real.
NODE_MERGE_TOL = 5e-3


def weld_close_nodes(model: Model, *, tol: float = NODE_MERGE_TOL) -> int:
    """Fusiona nodos del modelo que están a distancia ≤ tol entre sí.

    Para cada cluster de nodos próximos elige uno como representante;
    todas las referencias en miembros / soportes / cargas nodales se
    redirigen al representante. Si un miembro queda con ambos extremos
    iguales tras la fusión se elimina (junto con sus cargas distribuidas).

    Devuelve el número de nodos retirados.
    """
    if len(model.nodes) < 2:
        return 0

    # Mapa nid → canonical_nid. Cada nodo se representa a sí mismo si no
    # encuentra un vecino próximo previo.
    canonical: dict[str, str] = {}
    nodes_list = list(model.nodes.items())
    tol_sq = tol * tol

    for i, (nid, node) in enumerate(nodes_list):
        if nid in canonical:
            continue
        canonical[nid] = nid
        for j in range(i + 1, len(nodes_list)):
            nid2, node2 = nodes_list[j]
            if nid2 in canonical:
                continue
            d_sq = ((node2.x - node.x) ** 2
                    + (node2.y - node.y) ** 2
                    + (node2.z - node.z) ** 2)
            if d_sq <= tol_sq:
                canonical[nid2] = nid

    # Redirigir miembros
    degenerate_member_ids: list[str] = []
    for mid, mem in model.members.items():
        new_i = canonical.get(mem.i_node, mem.i_node)
        new_j = canonical.get(mem.j_node, mem.j_node)
        if new_i != mem.i_node:
            mem.i_node = new_i
        if new_j != mem.j_node:
            mem.j_node = new_j
        if mem.i_node == mem.j_node:
            degenerate_member_ids.append(mid)

    # Eliminar miembros degenerados (y sus cargas distribuidas)
    if degenerate_member_ids:
        deg_set = set(degenerate_member_ids)
        for mid in degenerate_member_ids:
            del model.members[mid]
        model.distributed_loads = [
            dl for dl in model.distributed_loads if dl.member not in deg_set
        ]

    # Redirigir soportes y cargas nodales
    for s in model.supports:
        s.node = canonical.get(s.node, s.node)
    for ld in model.nodal_loads:
        ld.node = canonical.get(ld.node, ld.node)

    # Eliminar nodos no representativos
    n_removed = 0
    for nid in list(model.nodes.keys()):
        if canonical.get(nid) != nid:
            del model.nodes[nid]
            n_removed += 1
    return n_removed


def _split_member_at_existing_node(
    model: Model, member_id: str, node_id: str,
) -> bool:
    """Reemplaza un miembro por dos sub-miembros conectados a través de
    `node_id`. El nodo debe existir y ser distinto de los extremos.

    Las releases del miembro original se preservan sólo en los extremos
    exteriores; las uniones interiores son continuas.
    """
    from .model import Member
    if member_id not in model.members or node_id not in model.nodes:
        return False
    mem = model.members[member_id]
    if node_id == mem.i_node or node_id == mem.j_node:
        return False

    no_release = (False,) * 6
    id_a = f"{member_id}_a"
    id_b = f"{member_id}_b"
    while id_a in model.members:
        id_a += "_"
    while id_b in model.members:
        id_b += "_"

    orig_i = mem.i_node
    orig_j = mem.j_node
    orig_release_i = mem.release_i
    orig_release_j = mem.release_j
    section = mem.section
    material = mem.material
    member_type = mem.member_type

    del model.members[member_id]
    model.members[id_a] = Member(
        id=id_a, i_node=orig_i, j_node=node_id,
        section=section, material=material, member_type=member_type,
        release_i=orig_release_i, release_j=no_release,
    )
    model.members[id_b] = Member(
        id=id_b, i_node=node_id, j_node=orig_j,
        section=section, material=material, member_type=member_type,
        release_i=no_release, release_j=orig_release_j,
    )
    return True


def weld_mid_span_attachments(
    model: Model,
    *,
    tol: float = NODE_MERGE_TOL,
    margin: float = 0.05,
    max_iterations: int = 6,
) -> int:
    """Detecta nodos del modelo que caen sobre la línea media (no en los
    extremos) de algún miembro y parte ese miembro al añadir el nodo
    como nueva unión.

    Es típico del andamio: anclajes (ties) que enganchan a un poste en
    una Z intermedia entre dos rosetas, o cruces de barras que comparten
    un punto físico sin tener un nodo previo allí.

    Parameters
    ----------
    tol : float
        Distancia máxima del nodo a la centerline del miembro para
        considerarse coincidente (m).
    margin : float
        Margen normalizado (0..1) cerca de los extremos donde NO se
        considera el nodo "a media barra". 0,05 → ignora el 5 % en cada
        extremo (que ya debería ser un nodo extremo bien fusionado).
    max_iterations : int
        Máximo de iteraciones del algoritmo (cada split puede crear dos
        miembros nuevos que a su vez podrían tener nodos a media barra).
    """
    total_splits = 0
    tol_sq = tol * tol

    for _ in range(max_iterations):
        iter_splits = 0
        member_ids = list(model.members.keys())
        node_ids = list(model.nodes.keys())

        for mid in member_ids:
            if mid not in model.members:
                continue
            mem = model.members[mid]
            if mem.i_node not in model.nodes or mem.j_node not in model.nodes:
                continue
            ni = model.nodes[mem.i_node]
            nj = model.nodes[mem.j_node]
            vij_x = nj.x - ni.x
            vij_y = nj.y - ni.y
            vij_z = nj.z - ni.z
            ll = vij_x * vij_x + vij_y * vij_y + vij_z * vij_z
            if ll < 1e-12:
                continue

            for nid in node_ids:
                if nid not in model.nodes:
                    continue
                if nid == mem.i_node or nid == mem.j_node:
                    continue
                node = model.nodes[nid]
                vin_x = node.x - ni.x
                vin_y = node.y - ni.y
                vin_z = node.z - ni.z
                t = (vin_x * vij_x + vin_y * vij_y + vin_z * vij_z) / ll
                if t < margin or t > 1.0 - margin:
                    continue
                cx = ni.x + t * vij_x
                cy = ni.y + t * vij_y
                cz = ni.z + t * vij_z
                d_sq = ((node.x - cx) ** 2
                        + (node.y - cy) ** 2
                        + (node.z - cz) ** 2)
                if d_sq > tol_sq:
                    continue

                # Coincidencia: partir el miembro insertando este nodo
                if _split_member_at_existing_node(model, mid, nid):
                    iter_splits += 1
                break  # ya partido este miembro; pasar al siguiente

        total_splits += iter_splits
        if iter_splits == 0:
            break

    return total_splits


def auto_add_base_supports(model: Model, *, tol: float = 0.01) -> int:
    """Añade un empotramiento total a cada nodo del nivel inferior si el
    modelo no tiene aún soportes.

    Los andamios se apoyan en husillos que descansan en el suelo. Ante la
    ausencia de soportes explícitos asumimos que **todos** los nodos en
    z = z_min están empotrados (DX, DY, DZ + RX, RY, RZ restringidos),
    coherente con un andamio anclado a fachada / con husillos sin juego.

    Devuelve el número de soportes añadidos. Si el modelo ya tenía algún
    soporte definido, no añade nada (respeta la configuración del usuario).
    """
    if not model.nodes:
        return 0
    if model.supports:
        return 0       # respetar lo que ya configuró el usuario
    z_min = min(n.z for n in model.nodes.values())
    n = 0
    for nid, node in model.nodes.items():
        if abs(node.z - z_min) < tol:
            model.add_support(
                nid, DX=True, DY=True, DZ=True,
                RX=True, RY=True, RZ=True,
            )
            n += 1
    return n


def _check_results_for_nan(res: Results) -> str | None:
    """Devuelve un mensaje descriptivo si hay desplazamientos NaN, None si todo OK."""
    import math
    for nid, nr in res.nodes.items():
        for component in (nr.DX, nr.DY, nr.DZ, nr.RX, nr.RY, nr.RZ):
            if math.isnan(component):
                return (
                    f"El cálculo produjo desplazamientos no válidos (NaN) en el "
                    f"nodo {nid}. Causa habitual: el modelo no está suficientemente "
                    f"restringido. Revisa los apoyos."
                )
    return None


def build_and_solve(
    model: Model,
    options: Mapping[str, object],
) -> tuple[Results, dict[str, MemberCheckResult]]:
    """Aplica cargas, resuelve y comprueba según `options`.

    `options` debe contener las claves:
        apply_service       (bool)
        service_class       (str — "Q1".."Q6")
        deck_width          (float, m)
        apply_wind          (bool)
        wind_zone           (str — "A"/"B"/"C")
        wind_terrain        (str — "0"/"I"/.../"IV")
        apply_imperfections (bool)
        apply_guardrail     (bool, opcional)
        combo               (str — clave de standard_combos())
        use_pdelta          (bool, opcional, default False) — análisis de
                            2º orden P-Delta. Más lento; recomendado en
                            torres esbeltas (>15 m sin anclajes).

    Asume releases ya configurados (o los configura por defecto si no).
    Asume soportes ya configurados; en caso contrario empotra los nodos del
    nivel inferior automáticamente (caso típico: husillos en el suelo).
    """
    # Conectividad: fusionar nodos próximos y reconocer uniones a media
    # barra ANTES de aplicar cargas (split_member rechaza barras cargadas).
    weld_close_nodes(model)
    weld_mid_span_attachments(model)

    # Empotrar la base si el usuario no añadió soportes (evita sistema singular)
    auto_add_base_supports(model)

    # Releases por defecto si el modelo no los tiene tocados.
    set_releases_by_type(model)

    # Peso propio (siempre)
    apply_self_weight(model)

    # Carga de servicio sobre ledgers que sostienen plataforma
    if options.get("apply_service"):
        deck_ledger_ids = [
            mid for mid, mem in model.members.items()
            if mem.member_type == "ledger" and is_deck_supporting_ledger(mid)
        ]
        if deck_ledger_ids:
            apply_service_load(
                model, deck_ledger_ids,
                klass=str(options["service_class"]),
                deck_width=float(options["deck_width"]),
            )

    # Viento sobre todos los postes
    if options.get("apply_wind"):
        pole_ids = [m.id for m in model.members.values()
                    if m.member_type == "pole"]
        if pole_ids:
            v_b = SPAIN_BASIC_WIND[str(options["wind_zone"])]
            apply_wind_load(
                model, pole_ids,
                diameter=DEFAULT_TUBE_DIAMETER,
                terrain=str(options["wind_terrain"]),
                v_b=v_b,
            )

    # Imperfecciones (después de las cargas verticales para sumar V correcto)
    if options.get("apply_imperfections"):
        apply_imperfections_at_top(model)

    # Carga horizontal en barandilla EN 12811-1 §7.2.1: 0,3 kN puntuales
    # en los nodos top de los postes. Modela la fuerza que la barandilla
    # transferiría al poste si un trabajador apoyara o cayera contra ella.
    if options.get("apply_guardrail"):
        from .loads.guardrail import apply_guardrail_horizontal_load
        apply_guardrail_horizontal_load(model, direction="AUTO", case="Q")

    combos = standard_combos()
    combo_name = str(options.get("combo", "ULS_LeadL"))
    if combo_name not in combos:
        combo_name = "ULS_LeadL"

    use_pdelta = bool(options.get("use_pdelta", False))
    res = solve(
        model,
        combos=combos,
        combo=combo_name,
        check_statics=False,
        use_pdelta=use_pdelta,
    )

    # Sanity check: NaN en desplazamientos = sistema mal restringido.
    # Mejor reportar claramente que dejar pasar resultados sin sentido.
    nan_msg = _check_results_for_nan(res)
    if nan_msg:
        raise RuntimeError(nan_msg)

    # K_φ semi-rígido: si el caller especifica una unión catalogada, los
    # postes se chequean a pandeo con L_cr efectivo (Anexo E EN 1993-1-1)
    # en lugar de asumir K=1,0 (rótulas perfectas, ultraconservador).
    joint_kind = str(options.get("joint_stiffness", "RIGID_ASSUMED"))
    L_cr_overrides: dict[str, float] = {}
    if joint_kind in ("LAYHER_ALLROUND", "LAYHER_HEAVY"):
        from .checks.joints import JOINT_CAPACITIES
        cap_key = ("layher_allround_heavy"
                   if joint_kind == "LAYHER_HEAVY"
                   else "layher_allround")
        K_phi = JOINT_CAPACITIES[cap_key].K_phi
        L_cr_overrides = compute_pole_lcr_overrides(model, K_phi=K_phi)

    checks = run_all_checks(model, res, L_cr_overrides=L_cr_overrides)
    return res, checks


# ---------------------------------------------------------------------------
# Resumen para presentación en lenguaje no-experto
# ---------------------------------------------------------------------------

# Descripciones legibles de las clases de servicio EN 12811-1 §6.2.2.
SERVICE_DESCRIPTION = {
    "Q1": "uso de inspección (≈75 kg/m²)",
    "Q2": "uso ligero (≈150 kg/m²)",
    "Q3": "uso general (≈200 kg/m², ≈4 trabajadores con herramienta)",
    "Q4": "carga elevada (≈300 kg/m², albañilería)",
    "Q5": "almacenaje pesado (≈450 kg/m²)",
    "Q6": "almacenaje muy pesado (≈600 kg/m²)",
}

WIND_DESCRIPTION = {
    "A": "viento moderado (zona A, costa cantábrica/interior, 26 m/s)",
    "B": "viento medio (zona B, costa atlántica, 27 m/s)",
    "C": "viento fuerte (zona C, Canarias/litoral expuesto, 29 m/s)",
}


def format_status_message(
    checks: Mapping[str, MemberCheckResult],
    options: Mapping[str, object] | None = None,
) -> dict:
    """Construye un resumen del cálculo en lenguaje no-experto.

    Devuelve un dict con:
        level     : "ok" | "warning" | "fail"
        title     : frase corta resumen ("ANDAMIO SEGURO", "ATENCIÓN", …)
        subtitle  : descripción de la configuración aplicada
        worst     : utilización máxima encontrada
        n_total   : barras analizadas
        n_failed  : barras con utilización > 1
        n_warning : barras con util entre 0.85 y 1 (cerca del límite)

    `level` se decide así:
        ok       → todos < 0.85 (margen amplio)
        warning  → algunos en 0.85..1.00 pero ningún fallo
        fail     → al menos una barra > 1.00
    """
    n_total = len(checks)
    if n_total == 0:
        return {
            "level": "warning",
            "title": "Sin barras analizables",
            "subtitle": "El modelo no contiene elementos estructurales reconocibles",
            "worst": 0.0, "n_total": 0, "n_failed": 0, "n_warning": 0,
        }

    n_failed = sum(1 for c in checks.values() if c.utilization > 1.0)
    n_warning = sum(1 for c in checks.values() if 0.85 <= c.utilization <= 1.0)
    worst = max(c.utilization for c in checks.values())

    if n_failed > 0:
        level = "fail"
        if n_failed == 1:
            title = "ATENCIÓN: 1 elemento sobrepasado"
        else:
            title = f"ATENCIÓN: {n_failed} elementos sobrepasados"
    elif n_warning > 0:
        level = "warning"
        title = f"Margen ajustado ({n_warning} cerca del límite)"
    else:
        level = "ok"
        title = "Andamio seguro"

    subtitle = _build_subtitle(options or {})

    return {
        "level": level,
        "title": title,
        "subtitle": subtitle,
        "worst": worst,
        "n_total": n_total,
        "n_failed": n_failed,
        "n_warning": n_warning,
    }


def _build_subtitle(options: Mapping[str, object]) -> str:
    """Frase descriptiva del escenario aplicado."""
    parts: list[str] = []

    if options.get("apply_service"):
        klass = str(options.get("service_class", "Q3"))
        desc = SERVICE_DESCRIPTION.get(klass, klass)
        parts.append(f"{desc}")
    else:
        parts.append("sin carga de servicio")

    if options.get("apply_wind"):
        zone = str(options.get("wind_zone", "A"))
        desc = WIND_DESCRIPTION.get(zone, f"zona {zone}")
        parts.append(desc)
    else:
        parts.append("sin viento")

    if options.get("apply_imperfections"):
        parts.append("con imperfecciones EN 1993")

    combo_name = str(options.get("combo", "ULS_LeadL"))
    combo_label = {
        "ULS_LeadL":  "combinación ULS — servicio dominante",
        "ULS_LeadW":  "combinación ULS — viento dominante",
        "ULS_Uplift": "combinación ULS — levantamiento",
        "SLS_char_L": "combinación SLS — característica",
        "SLS_freq_L": "combinación SLS — frecuente",
        "SLS_quasi":  "combinación SLS — casi-permanente",
    }.get(combo_name, combo_name)
    parts.append(combo_label)

    return "Configuración: " + " · ".join(parts)


# ---------------------------------------------------------------------------
# Estado del workflow guiado (Diseño → Validación → Informe)
# ---------------------------------------------------------------------------

def compute_workflow_state(
    *,
    n_structural: int,
    validation_level: object | None,
    n_failed: int = 0,
    n_warning: int = 0,
    n_total: int = 0,
    worst: float = 0.0,
) -> dict:
    """Resume el estado de las 3 fases del workflow.

    Función pura — no depende de bpy. La capa UI extrae los inputs de la
    escena y llama aquí.

    Devuelve:
        {
          "design":     {"state": "empty"|"ok",          "count": int},
          "validation": {"state": "empty"|"ok"|"warning"|"fail",
                         "n_failed", "n_warning", "n_total", "worst"},
          "report":     {"state": "blocked"|"available"},
        }

    Reglas:
        - Diseño OK si n_structural > 0.
        - Validación es lo que diga `validation_level` si es un valor
          conocido, en caso contrario "empty".
        - Informe disponible si la validación se ha ejecutado (cualquier
          nivel salvo empty).
    """
    design_state = "ok" if n_structural > 0 else "empty"

    if validation_level in ("ok", "warning", "fail"):
        validation = {
            "state": str(validation_level),
            "n_failed": int(n_failed),
            "n_warning": int(n_warning),
            "n_total": int(n_total),
            "worst": float(worst),
        }
    else:
        validation = {
            "state": "empty",
            "n_failed": 0, "n_warning": 0, "n_total": 0, "worst": 0.0,
        }

    report_state = "available" if validation["state"] in ("ok", "warning", "fail") else "blocked"

    return {
        "design":     {"state": design_state, "count": int(n_structural)},
        "validation": validation,
        "report":     {"state": report_state},
    }


# ---------------------------------------------------------------------------
# Deformaciones — visualización
# ---------------------------------------------------------------------------

# Umbrales de ratio δ/L para clasificar la deformación de una barra.
# Coherentes con EN 12811-1 (1/200 postes bajo viento, 1/100 plataformas).
DEFLECTION_RATIO_THRESHOLDS = (1 / 1000, 1 / 500, 1 / 300, 1 / 200, 1 / 100)

# Etiqueta narrativa de cada bucket para el panel/informe.
DEFLECTION_BUCKET_LABELS = (
    "muy rígido",
    "deformación pequeña",
    "deformación moderada",
    "cerca del límite postes (L/200)",
    "cerca del límite plataforma (L/100)",
    "deformación excesiva",
)


def _node_displacement_magnitude(node_result) -> float:
    """Magnitud absoluta del desplazamiento de un nodo en metros."""
    dx, dy, dz = node_result.DX, node_result.DY, node_result.DZ
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def deflection_ratio_to_bucket(ratio: float) -> int:
    """Mapea un ratio δ/L a su índice de bucket [0..5]."""
    for i, t in enumerate(DEFLECTION_RATIO_THRESHOLDS):
        if ratio < t:
            return i
    return len(DEFLECTION_RATIO_THRESHOLDS)


def compute_member_deflections(model: Model, results: Results) -> dict[str, dict]:
    """Para cada barra, devuelve la deformación nodal máxima y su ratio.

    Resultado:
        {
          member_id: {
              "max_disp_m":   float,     # magnitud máxima entre i_node y j_node
              "L":            float,     # longitud original
              "ratio":        float,     # max_disp_m / L (adimensional)
              "worst_node":   str,       # id del nodo peor del par
              "bucket":       int,       # 0..5
              "label":        str,       # etiqueta narrativa
          },
          ...
        }
    """
    out: dict[str, dict] = {}
    for mid, mem in model.members.items():
        ni = model.nodes[mem.i_node]
        nj = model.nodes[mem.j_node]
        L = ((nj.x - ni.x) ** 2 + (nj.y - ni.y) ** 2 + (nj.z - ni.z) ** 2) ** 0.5
        if L <= 0:
            continue

        if mem.i_node not in results.nodes or mem.j_node not in results.nodes:
            continue
        d_i = _node_displacement_magnitude(results.nodes[mem.i_node])
        d_j = _node_displacement_magnitude(results.nodes[mem.j_node])
        if d_i >= d_j:
            d_max, worst_node = d_i, mem.i_node
        else:
            d_max, worst_node = d_j, mem.j_node

        ratio = d_max / L
        bucket = deflection_ratio_to_bucket(ratio)
        out[mid] = {
            "max_disp_m": d_max,
            "L": L,
            "ratio": ratio,
            "worst_node": worst_node,
            "bucket": bucket,
            "label": DEFLECTION_BUCKET_LABELS[bucket],
        }
    return out


def find_max_deflection_node(results: Results) -> tuple[str | None, float]:
    """Devuelve (node_id, magnitud_m) del nodo con desplazamiento máximo
    en el modelo. (None, 0.0) si no hay resultados.
    """
    if not results.nodes:
        return None, 0.0
    best_id = None
    best_mag = 0.0
    for nid, nr in results.nodes.items():
        m = _node_displacement_magnitude(nr)
        if m > best_mag:
            best_mag = m
            best_id = nid
    return best_id, best_mag


# ---------------------------------------------------------------------------
# Clasificación básica de fallos por componente dominante
# ---------------------------------------------------------------------------

# Orden de prioridad cuando empatan: combinada > pandeo > flexión > compresión > tracción > cortante
_FAILURE_ORDER = ("combinada", "pandeo", "flexión", "compresión", "tracción", "cortante")


def classify_failure_basic(check) -> str:
    """Identifica el tipo de fallo dominante de un MemberCheckResult.

    Devuelve una etiqueta corta apta para mostrar en la UI:
        "tracción"   |  "compresión"  | "flexión"
        "cortante"   |  "pandeo"      | "combinada"
        "—"           si no hay utilizaciones no nulas

    La utilización combinada (Eq. 6.61/6.62) se considera dominante cuando
    es ≥ 1 (chequeo gobernante real); en otro caso la componente con mayor
    utilización gana.
    """
    sc = check.section_check
    components = {
        "tracción":   sc.tension,
        "compresión": sc.compression,
        "pandeo":     sc.buckling,
        "flexión":    max(sc.bending_y, sc.bending_z),
        "cortante":   max(sc.shear_y, sc.shear_z),
    }

    # Si la combinada es claramente la peor o supera 1, gana ella.
    if sc.combined >= 1.0 or sc.combined > max(components.values(), default=0):
        return "combinada"

    nonzero = {k: v for k, v in components.items() if v > 0}
    if not nonzero:
        return "—"

    max_v = max(nonzero.values())
    # Empate: usa el orden _FAILURE_ORDER
    candidates = [k for k, v in nonzero.items() if abs(v - max_v) < 1e-9]
    for label in _FAILURE_ORDER:
        if label in candidates:
            return label
    return candidates[0]


# ---------------------------------------------------------------------------
# Diagnóstico narrativo del fallo (para usuario no experto)
# ---------------------------------------------------------------------------

# Tabla de explicaciones por (tipo de fallo, tipo de miembro). El "_default"
# se usa cuando el tipo de miembro no está en el catálogo. Los textos están
# pensados para alguien que NO es estructurista: explican cómo se manifiesta
# físicamente el fallo y dan pistas concretas de cómo corregirlo en el
# diseño del andamio.
_DIAGNOSTICS_BY_TYPE: dict[str, dict[str, dict[str, str]]] = {
    "pandeo": {
        "pole": {
            "why": "El poste se está doblando por compresión — pierde "
                   "estabilidad antes de aplastarse.",
            "fix": "Reducir la altura libre entre travesaños (más rosetas) "
                   "o usar perfil reforzado Ø60×3,2 / acero S355.",
        },
        "brace": {
            "why": "La diagonal pandea por compresión axial.",
            "fix": "Acortar la diagonal (vano más estrecho) o usar perfil "
                   "reforzado.",
        },
        "_default": {
            "why": "El elemento pandea por compresión.",
            "fix": "Reducir la longitud entre apoyos o aumentar la sección.",
        },
    },
    "compresión": {
        "pole": {
            "why": "El poste excede su capacidad axial pura — hay demasiada "
                   "carga vertical concentrada sobre él.",
            "fix": "Aumentar la sección (Ø60,3) o añadir más postes para "
                   "repartir la carga.",
        },
        "_default": {
            "why": "El elemento excede su capacidad de compresión axial.",
            "fix": "Reducir la carga aplicada o aumentar la sección.",
        },
    },
    "tracción": {
        "tie": {
            "why": "El anclaje a fachada sufre tracción excesiva (típico "
                   "bajo viento de levantamiento).",
            "fix": "Añadir más anclajes a fachada o usar conexión reforzada "
                   "(ETA del fabricante).",
        },
        "_default": {
            "why": "El elemento excede su capacidad de tracción.",
            "fix": "Reducir la carga o reforzar la sección.",
        },
    },
    "flexión": {
        "ledger": {
            "why": "El travesaño se flexa demasiado bajo la carga de la "
                   "plataforma.",
            "fix": "Reducir el ancho de vano (bay_length) o añadir un "
                   "travesaño intermedio para acortar la luz.",
        },
        "_default": {
            "why": "El elemento se flexa más allá de su capacidad.",
            "fix": "Reducir la luz entre apoyos o aumentar el módulo de la "
                   "sección.",
        },
    },
    "cortante": {
        "_default": {
            "why": "Cortante elevado — raro en tubos circulares, suele "
                   "indicar carga puntual concentrada en una junta.",
            "fix": "Distribuir la carga puntual o reforzar la conexión.",
        },
    },
    "combinada": {
        "pole": {
            "why": "El poste falla por interacción entre axil y momento: "
                   "está siendo aplastado mientras se flexa lateralmente.",
            "fix": "Reducir alguna de las dos solicitaciones — más postes "
                   "(axil) o acortar el vano (flexión por viento).",
        },
        "ledger": {
            "why": "El travesaño falla por la combinación de tracción/"
                   "compresión axial y flexión simultáneas.",
            "fix": "Acortar el vano o reforzar la sección.",
        },
        "_default": {
            "why": "Fallo por interacción entre axil y momento: el "
                   "elemento se aplasta mientras se flexa.",
            "fix": "Reducir alguna de las dos solicitaciones (más postes "
                   "para axil, acortar luz para flexión).",
        },
    },
    "—": {
        "_default": {
            "why": "El elemento está cerca del límite pero no hay una "
                   "componente claramente dominante.",
            "fix": "Revisar el chequeo manualmente o reforzar de forma "
                   "conservadora.",
        },
    },
}


# Etiquetas narrativas de la severidad (para el panel/informe)
_SEVERITY_LABELS = {
    "minor":    "Margen ajustado",
    "serious":  "Sobrepasado",
    "critical": "Muy sobrepasado",
    "ok":       "Holgado",
}


def _classify_severity(utilization: float) -> str:
    """Devuelve la severidad textual según el valor de utilización."""
    if utilization >= 1.3:
        return "critical"
    if utilization >= 1.0:
        return "serious"
    if utilization >= 0.85:
        return "minor"
    return "ok"


def diagnose_failure(check, member_type: str | None = None) -> dict:
    """Para un MemberCheckResult devuelve un diagnóstico narrativo.

    Parameters
    ----------
    check : MemberCheckResult
        Resultado de comprobaciones de la barra.
    member_type : str | None
        "pole" / "ledger" / "brace" / "tie" — si se pasa, se selecciona el
        texto específico de ese tipo; si no, se usa el genérico.

    Returns
    -------
    dict con claves:
        type      etiqueta corta del tipo de fallo (ya producida por
                  classify_failure_basic): "pandeo", "flexión", …
        severity  "ok" | "minor" | "serious" | "critical"
        severity_label  texto humano del nivel ("Sobrepasado", …)
        why       explicación de qué está pasando, en plano
        fix       recomendación concreta de qué cambiar en el diseño
    """
    ftype = classify_failure_basic(check)
    severity = _classify_severity(check.utilization)

    type_table = _DIAGNOSTICS_BY_TYPE.get(ftype) or _DIAGNOSTICS_BY_TYPE["—"]
    by_member = type_table.get(member_type) if member_type else None
    diag = by_member or type_table.get("_default") or {}

    return {
        "type": ftype,
        "severity": severity,
        "severity_label": _SEVERITY_LABELS.get(severity, severity),
        "why": diag.get("why", ""),
        "fix": diag.get("fix", ""),
    }


def deflection_summary(deflections: Mapping[str, Mapping]) -> dict:
    """Resumen del estado de deformación para el panel/informe.

    Devuelve:
        {
          "n_excessive":  nº de barras con bucket == 5 (>L/100)
          "n_warning":    nº de barras con bucket >= 3 (>L/300, cerca del límite)
          "worst_member": id de la barra peor (o None)
          "worst_disp_m": δ máxima en metros
          "worst_ratio":  ratio máximo
          "worst_label":  etiqueta narrativa
        }
    """
    if not deflections:
        return {
            "n_excessive": 0, "n_warning": 0,
            "worst_member": None, "worst_disp_m": 0.0,
            "worst_ratio": 0.0, "worst_label": "",
        }

    n_excessive = sum(1 for d in deflections.values() if d["bucket"] >= 5)
    n_warning = sum(1 for d in deflections.values() if d["bucket"] >= 3)

    worst_id, worst = max(
        deflections.items(),
        key=lambda kv: kv[1]["ratio"],
    )
    return {
        "n_excessive": n_excessive,
        "n_warning": n_warning,
        "worst_member": worst_id,
        "worst_disp_m": worst["max_disp_m"],
        "worst_ratio": worst["ratio"],
        "worst_label": worst["label"],
    }
