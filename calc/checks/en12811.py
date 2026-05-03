"""Comprobaciones específicas EN 12811-1 para andamios de servicio.

Cubre los aspectos no estructurales puros, complementarios al EN 1993:
    §6.2.5    Deflexión vertical de plataformas (δ ≤ L/100 con carga clase Q).
    §6.2.7    Comprobación de deformación bajo viento (δ_h ≤ L/200).
    §7.2.1    Capacidades mínimas de barandillas (300 N horizontal en cualquier
              punto, 0,5 kN vertical) — devuelto como check de capacidad nodal.

Estas funciones reciben magnitudes ya calculadas (deflexión, fuerza nodal
sobre la barandilla, etc.) y devuelven utilización demanda/capacidad. El
caller obtiene la deflexión del solver via `pynite_model.members[id]
.max_deflection('dz', combo)` o equivalente.
"""

from __future__ import annotations


# Límites de servicio EN 12811-1 §6.2.5 / §6.2.7
DEFLECTION_LIMIT_PLATFORM = 1.0 / 100.0    # δ ≤ L/100 (plataforma bajo Q)
DEFLECTION_LIMIT_WIND     = 1.0 / 200.0    # δ_h ≤ L/200 (viento sobre poste)

# Cargas mínimas barandillas EN 12811-1 §7.2.1
GUARDRAIL_HORIZONTAL_LOAD = 300.0     # N, en cualquier punto
GUARDRAIL_VERTICAL_LOAD   = 500.0     # N (0.5 kN)


def check_deflection_limit(
    delta: float,
    L: float,
    *,
    limit_factor: float = DEFLECTION_LIMIT_PLATFORM,
) -> float:
    """Comprobación δ ≤ L · limit_factor.

    Devuelve utilización |δ| · (1/limit_factor) / L. ≤ 1 → OK.
    `delta` y `L` en las mismas unidades; el signo de `delta` se ignora.
    """
    if L <= 0:
        raise ValueError(f"L debe ser > 0 (recibido {L})")
    if limit_factor <= 0:
        raise ValueError(f"limit_factor debe ser > 0 (recibido {limit_factor})")
    return abs(delta) / (L * limit_factor)


def check_guardrail_capacity(
    F_horizontal_demand: float,
    F_vertical_demand: float,
) -> tuple[float, float]:
    """Comprueba que la capacidad mínima exigida por EN 12811-1 §7.2.1 se
    cumple. Devuelve (util_h, util_v) — utilización debe ser ≤ 1.

    Convención: el caller pasa la **capacidad** medida del sistema de
    barandilla (no la demanda). La función calcula:

        util_h = GUARDRAIL_HORIZONTAL_LOAD / F_horizontal_capacity
        util_v = GUARDRAIL_VERTICAL_LOAD   / F_vertical_capacity

    Si la capacidad supera el mínimo normativo, util ≤ 1 → OK.
    """
    if F_horizontal_demand <= 0 or F_vertical_demand <= 0:
        raise ValueError("Las capacidades deben ser > 0")
    util_h = GUARDRAIL_HORIZONTAL_LOAD / F_horizontal_demand
    util_v = GUARDRAIL_VERTICAL_LOAD / F_vertical_demand
    return util_h, util_v
