"""Validador del modelo y la escena del addon Andamios.

Antes de ejecutar el cálculo FEM (que puede colgar Blender o tardar minutos),
recorrer un conjunto de chequeos rápidos que avisan al usuario si la
geometría está incompleta, mal configurada o fuera de los rangos
normativos típicos. Igual que un "linter" pero del modelo estructural.

Filosofía
---------
- **ERROR**: el cálculo no puede correr o dará resultado sin sentido.
  El usuario debe corregir antes de pulsar Ejecutar.
- **WARNING**: el cálculo correrá pero el resultado puede no reflejar la
  realidad o no cumplir normativa. Recomendado revisar.
- **INFO**: estadística informativa, no requiere acción.

Cada check devuelve `ValidationIssue` con un código corto (E1, W3, ...)
para que la UI pueda enlazar a documentación.

Helpers puros (sin bpy) en `validate_model`. Helpers que tocan la escena
Blender (props, collections) en `validate_scene` — guardado por
`try: import bpy` para que los tests puros no requieran Blender.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Model


# ---------------------------------------------------------------------------
# Tipo de retorno
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """Una incidencia detectada por un chequeo del validador.

    `level`: "ERROR" / "WARNING" / "INFO"
    `code`:  identificador corto (E1, W3...) para enlazar a la UI/docs.
    `message`: texto en plano explicando qué pasa.
    `suggestion`: pista concreta para corregirlo (None si es informativo).
    """
    level: str
    code: str
    message: str
    suggestion: str | None = None

    @property
    def is_blocking(self) -> bool:
        return self.level == "ERROR"


# ---------------------------------------------------------------------------
# Chequeos sobre el Model (puros, sin bpy)
# ---------------------------------------------------------------------------

def validate_model(model: Model) -> list[ValidationIssue]:
    """Recorre el modelo y devuelve la lista de incidencias detectadas.

    Lista ordenada por severidad: ERROR primero, luego WARNING, luego INFO.
    Lista vacía == el modelo está limpio y listo para resolver.
    """
    issues: list[ValidationIssue] = []

    # E1: Modelo sin miembros
    if not model.members:
        issues.append(ValidationIssue(
            level="ERROR", code="E1",
            message="El modelo no contiene barras estructurales.",
            suggestion="Genera el andamio (botón 'Generar / Actualizar') "
                       "antes de calcular.",
        ))
        return issues   # sin barras, los demás chequeos no aplican

    # E2: Modelo sin nodos (caso degenerado)
    if not model.nodes:
        issues.append(ValidationIssue(
            level="ERROR", code="E2",
            message="El modelo no tiene nodos.",
            suggestion="Vuelve a regenerar la geometría — la extracción ha fallado.",
        ))
        return issues

    # E3: Miembros referenciando nodos inexistentes
    missing_refs = []
    for mid, mem in model.members.items():
        if mem.i_node not in model.nodes:
            missing_refs.append((mid, mem.i_node))
        if mem.j_node not in model.nodes:
            missing_refs.append((mid, mem.j_node))
    if missing_refs:
        issues.append(ValidationIssue(
            level="ERROR", code="E3",
            message=f"{len(missing_refs)} barras referencian nodos inexistentes.",
            suggestion="Indica un fallo de extracción — regenera la geometría "
                       "o reporta el bug con el informe de diagnóstico.",
        ))

    # W1: Modelo demasiado pequeño para ser un andamio real
    n_poles = sum(1 for m in model.members.values() if m.member_type == "pole")
    if n_poles < 4:
        issues.append(ValidationIssue(
            level="WARNING", code="W1",
            message=f"Solo {n_poles} postes en el modelo.",
            suggestion="Un andamio típico tiene al menos 4 postes (2 bays). "
                       "Si esto es un test, ignora el aviso.",
        ))

    # W2: Miembros de longitud (casi) cero
    zero_len_members: list[str] = []
    for mid, mem in model.members.items():
        n_i = model.nodes.get(mem.i_node)
        n_j = model.nodes.get(mem.j_node)
        if n_i is None or n_j is None:
            continue
        dx = n_j.x - n_i.x
        dy = n_j.y - n_i.y
        dz = n_j.z - n_i.z
        L = (dx*dx + dy*dy + dz*dz) ** 0.5
        if L < 1e-3:
            zero_len_members.append(mid)
    if zero_len_members:
        sample = ", ".join(zero_len_members[:5])
        more = f" (+{len(zero_len_members) - 5} más)" if len(zero_len_members) > 5 else ""
        issues.append(ValidationIssue(
            level="WARNING", code="W2",
            message=f"{len(zero_len_members)} barras con longitud < 1 mm: {sample}{more}",
            suggestion="Suelen ser duplicados que el welding no pudo fusionar. "
                       "El solver las ignorará pero indica un bug en la "
                       "geometría — reporta el caso.",
        ))

    # W3: Sin soportes definidos (auto_add_base_supports los añadirá pero
    # es mejor avisar para que el usuario sea consciente)
    if not model.supports:
        issues.append(ValidationIssue(
            level="WARNING", code="W3",
            message="No hay soportes definidos en el modelo.",
            suggestion="El pipeline empotrará automáticamente los nodos en z "
                       "mínimo (caso husillos sobre suelo). Si tu andamio "
                       "está colgado o apoyado en otra cota, añade soportes "
                       "manualmente.",
        ))

    # W4: Postes huérfanos (no conectan con ningún otro poste/ledger).
    # Detección simple: para cada poste, busca si comparte nodo con otro
    # miembro estructural distinto.
    nodes_by_member: dict[str, set[str]] = {}
    for mid, mem in model.members.items():
        for nid in (mem.i_node, mem.j_node):
            nodes_by_member.setdefault(nid, set()).add(mid)
    orphans: list[str] = []
    for mid, mem in model.members.items():
        if mem.member_type != "pole":
            continue
        connected = (
            len(nodes_by_member.get(mem.i_node, set()) - {mid}) +
            len(nodes_by_member.get(mem.j_node, set()) - {mid})
        )
        if connected == 0:
            orphans.append(mid)
    if orphans:
        sample = ", ".join(orphans[:3])
        more = f" (+{len(orphans) - 3} más)" if len(orphans) > 3 else ""
        issues.append(ValidationIssue(
            level="WARNING", code="W4",
            message=f"{len(orphans)} postes desconectados de la estructura: {sample}{more}",
            suggestion="Sin conexiones, estos postes no transmiten cargas y "
                       "son inestables. Comprueba que los travesaños llegan "
                       "a sus nodos.",
        ))

    # I1: Resumen para tener un acuse de recibo positivo
    n_ledgers = sum(1 for m in model.members.values() if m.member_type == "ledger")
    n_braces  = sum(1 for m in model.members.values() if m.member_type == "brace")
    n_ties    = sum(1 for m in model.members.values() if m.member_type == "tie")
    issues.append(ValidationIssue(
        level="INFO", code="I1",
        message=(f"Modelo: {len(model.nodes)} nodos · {len(model.members)} barras "
                 f"({n_poles}P + {n_ledgers}L + {n_braces}D + {n_ties}T)"),
    ))

    return issues


# ---------------------------------------------------------------------------
# Chequeos sobre la escena Blender (con bpy)
# ---------------------------------------------------------------------------

def validate_scene(scene) -> list[ValidationIssue]:
    """Chequea la escena Blender (props del addon + collection Scaffold).

    Complementa `validate_model` con verificaciones que dependen del
    contexto Blender. Devuelve lista vacía si no hay problemas.
    """
    issues: list[ValidationIssue] = []
    try:
        import bpy
    except ImportError:
        return [ValidationIssue(
            level="ERROR", code="E_BPY",
            message="bpy no disponible — esta función requiere Blender.",
        )]

    props = getattr(scene, "andamios_props", None)
    if props is None:
        issues.append(ValidationIssue(
            level="ERROR", code="E10",
            message="La escena no tiene `andamios_props` registrado.",
            suggestion="Reabre el addon (registrarlo crea las props).",
        ))
        return issues

    # E11: path_points con menos de 2 puntos
    path_pts = [pp for pp in props.path_points if pp.obj is not None]
    if len(path_pts) < 2:
        issues.append(ValidationIssue(
            level="ERROR", code="E11",
            message=f"La polilínea tiene solo {len(path_pts)} punto(s).",
            suggestion="Necesitas ≥ 2 empties en la lista 'Trayectoria' para "
                       "definir el recorrido del andamio.",
        ))

    # E12: path_points con entry vacía (obj=None)
    n_empty = sum(1 for pp in props.path_points if pp.obj is None)
    if n_empty:
        issues.append(ValidationIssue(
            level="ERROR", code="E12",
            message=f"{n_empty} entradas de la polilínea sin empty asignado.",
            suggestion="Pulsa la X para eliminarlas, o asigna un empty a cada "
                       "fila de la lista.",
        ))

    # Collection Scaffold
    coll = bpy.data.collections.get("Scaffold")
    if coll is None or not coll.all_objects:
        issues.append(ValidationIssue(
            level="ERROR", code="E13",
            message="No existe la colección 'Scaffold' o está vacía.",
            suggestion="Pulsa 'Generar / Actualizar' para crear la geometría.",
        ))

    # W10: altura > 8 m sin anclajes
    floor_count = int(getattr(props, "floor_count", 0))
    floor_height = float(getattr(props, "floor_height", 2.0))
    total_h = floor_count * floor_height
    if total_h > 8.0 and not bool(getattr(props, "add_ties", False)):
        issues.append(ValidationIssue(
            level="WARNING", code="W10",
            message=f"Andamio de {total_h:.1f} m sin anclajes a fachada.",
            suggestion="EN 12811-2 exige anclajes para alturas > 8 m. "
                       "Activa 'Anclajes a fachada' en el panel de generación.",
        ))

    # W11: viento alto + sin anclajes
    wind_zone = str(getattr(props, "calc_wind_zone", "A"))
    wind_active = bool(getattr(props, "calc_apply_wind", False))
    has_ties = bool(getattr(props, "add_ties", False))
    if wind_active and wind_zone in ("B", "C") and not has_ties:
        issues.append(ValidationIssue(
            level="WARNING", code="W11",
            message=f"Viento zona {wind_zone} sin anclajes a fachada.",
            suggestion="En zonas de viento B/C los anclajes son críticos. "
                       "Activa 'Anclajes a fachada' o el cálculo dará "
                       "utilizaciones muy altas en los postes.",
        ))

    # W12: scaffold_depth anormalmente estrecho
    depth = float(getattr(props, "scaffold_depth", 0.732))
    if depth < 0.55:
        issues.append(ValidationIssue(
            level="WARNING", code="W12",
            message=f"Profundidad {depth*1000:.0f} mm < 600 mm.",
            suggestion="Andamios de servicio EN 12811-1 usan típicamente "
                       "≥ 0,6 m de profundidad para que las bandejas "
                       "estándar quepan.",
        ))

    # W13: anchos / encajes de bandejas
    plank_w = float(getattr(props, "deck_plank_width", 0.32))
    plank_n = int(getattr(props, "deck_planks_count", 0))
    add_decks = bool(getattr(props, "add_decks", False))
    if add_decks and plank_n > 0 and plank_w > 0:
        cubierto = plank_n * plank_w
        gap_mm = (depth - cubierto) * 1000
        if gap_mm > 30:
            issues.append(ValidationIssue(
                level="WARNING", code="W13",
                message=(f"{plank_n} bandejas × {plank_w*1000:.0f} mm "
                         f"dejan {gap_mm:.0f} mm de hueco perpendicular."),
                suggestion="EN 12811-1 limita los huecos a ≤ 25 mm. Revisa "
                           "el número de bandejas o usa el 'Auto-cubrir' "
                           "del panel.",
            ))
        elif gap_mm < -10:   # solapamiento (overhang)
            issues.append(ValidationIssue(
                level="WARNING", code="W13",
                message=(f"{plank_n} bandejas × {plank_w*1000:.0f} mm "
                         f"sobrepasan el ancho del bay en {-gap_mm:.0f} mm."),
                suggestion="Reduce el número de bandejas o el ancho — "
                           "actualmente las bandejas no caben.",
            ))

    # W14: floor_height fuera del rango habitual
    if floor_height < 1.5:
        issues.append(ValidationIssue(
            level="WARNING", code="W14",
            message=f"Altura de planta {floor_height:.2f} m < 1,5 m.",
            suggestion="Altura mínima funcional habitual = 1,5 m (carga + "
                       "tránsito de personal). Revisa floor_height.",
        ))
    elif floor_height > 2.5:
        issues.append(ValidationIssue(
            level="WARNING", code="W14",
            message=f"Altura de planta {floor_height:.2f} m > 2,5 m.",
            suggestion="Por encima de 2,5 m las cargas de peso propio en "
                       "ledgers superan el catálogo Layher estándar. "
                       "Revisa floor_height.",
        ))

    return issues


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def summarize_issues(issues: list[ValidationIssue]) -> tuple[int, int, int, str]:
    """Devuelve (n_errors, n_warnings, n_info, status_label).

    status_label ∈ {"ok", "warning", "blocked"} para semáforo de UI.
    """
    n_err = sum(1 for i in issues if i.level == "ERROR")
    n_wrn = sum(1 for i in issues if i.level == "WARNING")
    n_inf = sum(1 for i in issues if i.level == "INFO")
    if n_err > 0:
        status = "blocked"
    elif n_wrn > 0:
        status = "warning"
    else:
        status = "ok"
    return n_err, n_wrn, n_inf, status
