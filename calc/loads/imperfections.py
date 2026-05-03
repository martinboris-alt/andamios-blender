"""Imperfecciones globales según EN 1993-1-1 §5.3.2.

Para tener en cuenta las desviaciones constructivas iniciales (postes que no
están perfectamente verticales, juegos de unión, etc.) la EN 1993-1-1 modela
una inclinación equivalente:

    φ = φ₀ · α_h · α_m

con
    φ₀  = 1/200                              valor base
    α_h = 2/√h    con  2/3 ≤ α_h ≤ 1         h = altura total del andamio (m)
    α_m = √(½ · (1 + 1/m))                   m = número de columnas
                                              (postes contribuyentes en una alineación)

Esta inclinación se sustituye en el análisis por **fuerzas horizontales
equivalentes** aplicadas a cada nivel:

    H_i = φ · V_i

donde V_i es la suma de las cargas verticales que llegan al nivel i. Para
andamios típicos esto se traduce en una fuerza horizontal por nodo de planta
proporcional a la carga vertical que ese nodo soporta.

El caller pasa `vertical_loads` como dict {node_id: V_i (N positivo)}. Esta
implementación deliberadamente no calcula V_i a partir del modelo: el
reparto de cargas verticales por nodo depende del esquema constructivo del
andamio y se considera responsabilidad del usuario o de un pre-procesador
posterior. Las fuerzas horizontales se añaden como `NodalLoad` en el caso
indicado (por defecto `"I"` — Imperfections).
"""

from __future__ import annotations

from typing import Mapping

from ..model import Model


PHI_0 = 1.0 / 200.0


def alpha_h(h: float) -> float:
    """Factor de reducción por altura. EN 1993-1-1 §5.3.2(3).

    α_h = 2/√h, acotado a [2/3, 1].
    """
    if h <= 0:
        raise ValueError(f"h debe ser > 0 (recibido {h})")
    raw = 2.0 / (h ** 0.5)
    return max(2.0 / 3.0, min(1.0, raw))


def alpha_m(m: int) -> float:
    """Factor de reducción por número de columnas. EN 1993-1-1 §5.3.2(3).

    α_m = √(½ · (1 + 1/m)). Para m=1 da 1.0 (sin reducción).
    """
    if m < 1:
        raise ValueError(f"m debe ser ≥ 1 (recibido {m})")
    return (0.5 * (1.0 + 1.0 / m)) ** 0.5


def imperfection_angle(h: float, m: int = 1) -> float:
    """Ángulo de imperfección global φ (rad)."""
    return PHI_0 * alpha_h(h) * alpha_m(m)


def apply_horizontal_imperfection(
    model: Model,
    vertical_loads: Mapping[str, float],
    *,
    h: float,
    m: int = 1,
    direction: str = "FX",
    case: str = "I",
) -> tuple[int, float]:
    """Añade fuerzas horizontales equivalentes a las imperfecciones globales.

    Por cada `(node_id, V_i)` en `vertical_loads` se añade una `NodalLoad`
    horizontal de magnitud `H_i = φ · V_i` en `direction` (signo positivo).
    Para considerar viento desde el otro lado, llamar de nuevo con
    `direction` en sentido contrario o usar otro caso.

    Parameters
    ----------
    model : Model
    vertical_loads : dict[str, float]
        Carga vertical (compresión, en N positivo) que llega a cada nodo.
    h : float
        Altura total del andamio en m (para α_h).
    m : int
        Número de columnas en la alineación (para α_m). 1 = sin reducción.
    direction : str
        "FX" o "FY" (sentido global de la imperfección).
    case : str
        Caso de carga; por defecto "I" (Imperfections).

    Returns
    -------
    (n_nodes, phi) : tuple
        Número de nodos cargados y ángulo φ aplicado.
    """
    if direction not in ("FX", "FY"):
        raise ValueError(f"direction debe ser FX o FY (recibido {direction!r})")

    phi = imperfection_angle(h, m)
    n = 0
    for nid, V in vertical_loads.items():
        if nid not in model.nodes:
            raise ValueError(f"Nodo {nid} no existe")
        H = phi * V
        model.add_nodal_load(nid, direction, H, case=case)
        n += 1
    return n, phi
