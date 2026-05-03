"""Auto-corrección iterativa del diseño del andamio.

Funcionamiento estilo ANSYS: el usuario pulsa un botón y el addon prueba
sucesivos cambios al diseño hasta lograr que la estructura cumpla. Cada
iteración:

    1. Ejecuta el cálculo con la configuración actual.
    2. Si `util_max < target` y no hay fallos, declara éxito.
    3. En otro caso, decide el siguiente fix con `decide_next_fix`.
    4. Aplica el fix a las propiedades del addon y regenera la geometría.
    5. Vuelve al paso 1, hasta `max_iterations` o hasta que no haya más
       acciones disponibles.

`decide_next_fix` es una función pura sin dependencia de bpy: recibe el
estado actual de las props relevantes y un resumen de fallos, devuelve un
dict describiendo el siguiente cambio o None si ya no hay más opciones.

Estrategia priorizada:
    a) Activar `add_braces` si está desactivado.
    b) Activar `add_horizontal_braces` si está desactivado.
    c) Reducir `bay_length` si los fallos son de flexión / combinada o
       afectan a `ledger`.
    d) Reducir `pole_segment_length` si los fallos son de pandeo o afectan
       a `pole`.
    e) Si todo está al mínimo, devolver None (no convergerá).
"""

from __future__ import annotations

from typing import Sequence


# Pasos descendentes de tamaño. Inspirados en el catálogo Layher pero
# extendidos para dejar al algoritmo más margen de mejora.
BAY_STEPS: Sequence[float] = (3.07, 2.57, 2.07, 1.57, 1.40, 1.09, 0.73)
POLE_SEG_STEPS: Sequence[float] = (4.0, 3.0, 2.0, 1.5, 1.0, 0.5)

# Las props del addon que el auto-fix puede modificar (y que se incluyen
# en el snapshot/restore).
SNAPSHOT_PROPS: Sequence[str] = (
    "add_braces",
    "add_horizontal_braces",
    "bay_length_catalog",
    "bay_length",
    "pole_segment_length",
    "pole_length_catalog",
)


def next_lower_step(value: float, steps: Sequence[float],
                    *, eps: float = 1e-3) -> float | None:
    """Devuelve el step disponible inmediatamente menor que `value`,
    o None si `value` ya está por debajo del mínimo."""
    available = sorted({float(s) for s in steps})
    candidate = None
    for s in available:
        if s < value - eps:
            candidate = s
    return candidate


def decide_next_fix(
    props_state: dict,
    failures: list[dict],
    *,
    bay_steps: Sequence[float] = BAY_STEPS,
    pole_steps: Sequence[float] = POLE_SEG_STEPS,
) -> dict | None:
    """Decide la siguiente acción correctiva.

    Parameters
    ----------
    props_state : dict
        Snapshot de las props relevantes (claves: add_braces,
        add_horizontal_braces, bay_length_catalog, bay_length,
        pole_segment_length, pole_length_catalog). Sólo las que vayan a
        leerse o cambiarse.
    failures : list[dict]
        Lista de entradas con keys `member_id`, `utilization`,
        `failure_type`, `member_type`. Sólo se consideran las de util > 1.

    Returns
    -------
    dict con keys:
        prop      str — nombre de la prop a modificar
        before    cualquier — valor previo
        after     cualquier — valor nuevo
        action    str — descripción humana del cambio
    o None si no hay más fixes disponibles.
    """
    # 1. Activar cruces si están off
    if props_state.get("add_braces") is False:
        return {
            "prop": "add_braces",
            "before": False, "after": True,
            "action": "Activar cruces de arriostramiento",
        }
    if props_state.get("add_horizontal_braces") is False:
        return {
            "prop": "add_horizontal_braces",
            "before": False, "after": True,
            "action": "Activar cruces horizontales en plano del deck",
        }

    # Filtrar fallos críticos
    crit = [f for f in failures if float(f.get("utilization", 0)) > 1.0]
    if not crit:
        # Sin fallos críticos pero el caller pidió mejora — bajamos
        # vano para reducir margen ajustado.
        crit = sorted(
            failures, key=lambda f: float(f.get("utilization", 0)), reverse=True,
        )[:1]
        if not crit:
            return None

    # Contar tipos
    type_counts: dict[str, int] = {}
    member_counts: dict[str, int] = {}
    for f in crit:
        t = str(f.get("failure_type", ""))
        m = str(f.get("member_type", ""))
        type_counts[t] = type_counts.get(t, 0) + 1
        member_counts[m] = member_counts.get(m, 0) + 1

    # ¿Domina pandeo en postes?
    pandeo = type_counts.get("pandeo", 0)
    flexion = type_counts.get("flexión", 0) + type_counts.get("flex", 0)
    combinada = type_counts.get("combinada", 0)
    n_pole = member_counts.get("pole", 0)
    n_ledger = member_counts.get("ledger", 0)

    # Heurística: si hay pandeo o el tipo dominante es pole + combinada,
    # primero baja pole_segment. Si la mayoría son ledgers o flex,
    # baja bay_length.
    prefer_pole_seg = (
        pandeo > 0 and pandeo >= flexion
    ) or (n_pole > n_ledger and combinada > 0)

    # 2. Reducir pole_segment_length
    if prefer_pole_seg:
        cur = float(props_state.get("pole_segment_length", 0))
        new = next_lower_step(cur, pole_steps) if cur > 0 else pole_steps[0]
        if new is not None and new != cur:
            return {
                "prop": "pole_segment_length",
                "before": cur, "after": new,
                "action": (f"Reducir altura de segmento de poste "
                           f"{cur:.2f} → {new:.2f} m (más rosetas)"),
            }

    # 3. Reducir bay_length (forzar UNIFORM si hace falta)
    if props_state.get("bay_length_catalog") != "UNIFORM":
        old_cat = props_state.get("bay_length_catalog")
        return {
            "prop": "bay_length_catalog",
            "before": old_cat, "after": "UNIFORM",
            "action": (f"Cambiar catálogo de vanos a UNIFORM "
                       f"para poder reducirlo paso a paso"),
        }
    cur = float(props_state.get("bay_length", 0))
    new = next_lower_step(cur, bay_steps) if cur > 0 else bay_steps[0]
    if new is not None and new != cur:
        return {
            "prop": "bay_length",
            "before": cur, "after": new,
            "action": f"Reducir vano {cur:.2f} → {new:.2f} m (más postes)",
        }

    # 4. Si bay_length ya está al mínimo pero seguimos teniendo pandeo
    #    en postes, probamos a reducir pole_segment.
    if not prefer_pole_seg:
        cur = float(props_state.get("pole_segment_length", 0))
        new = next_lower_step(cur, pole_steps) if cur > 0 else pole_steps[0]
        if new is not None and new != cur:
            return {
                "prop": "pole_segment_length",
                "before": cur, "after": new,
                "action": (f"Reducir altura de segmento de poste "
                           f"{cur:.2f} → {new:.2f} m (más rosetas)"),
            }

    # No hay más fixes
    return None


def snapshot_props(props) -> dict:
    """Captura las props relevantes del PropertyGroup en un dict."""
    out: dict = {}
    for name in SNAPSHOT_PROPS:
        try:
            out[name] = getattr(props, name)
        except AttributeError:
            continue
    return out


def restore_props(props, snapshot: dict) -> int:
    """Restaura las props desde un snapshot."""
    n = 0
    for name, value in snapshot.items():
        try:
            setattr(props, name, value)
            n += 1
        except (AttributeError, TypeError):
            pass
    return n
