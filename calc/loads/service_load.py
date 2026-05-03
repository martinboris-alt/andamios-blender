"""Cargas de servicio según EN 12811-1 (acción variable Q).

EN 12811-1 §6.2.2 Tabla 3 define seis clases de carga uniforme sobre la
superficie de plataforma:

    Q1 = 0,75 kN/m²   (inspección)
    Q2 = 1,50 kN/m²   (uso ligero)
    Q3 = 2,00 kN/m²   (uso general — andamio de fachada típico)
    Q4 = 3,00 kN/m²   (carga elevada, p. ej. albañilería)
    Q5 = 4,50 kN/m²   (almacenaje pesado)
    Q6 = 6,00 kN/m²   (almacenaje muy pesado)

`apply_service_load` reparte la presión de plataforma sobre los travesaños
(ledgers) que la sostienen, convirtiéndola en una carga lineal:

    w = q · b / n                          [N/m]

donde:
    q = presión de la clase elegida        [N/m²]
    b = ancho de plataforma (perpendicular al ledger, m)
    n = número de ledgers que comparten el ancho tributario
        (típicamente 2 — un par front/back en un mismo bay)

La función no inspecciona la geometría: el caller pasa explícitamente la
lista de ids de ledger y el ancho. La detección automática del par
front/back desde el grafo se aborda en una fase posterior.
"""

from __future__ import annotations

from typing import Iterable

from ..model import Model


# Presiones en N/m² (EN 12811-1 Tabla 3)
SERVICE_CLASSES: dict[str, float] = {
    "Q1": 750.0,
    "Q2": 1500.0,
    "Q3": 2000.0,
    "Q4": 3000.0,
    "Q5": 4500.0,
    "Q6": 6000.0,
}


def apply_service_load(
    model: Model,
    ledger_ids: Iterable[str],
    *,
    klass: str = "Q3",
    deck_width: float,
    n_ledgers_per_pair: int = 2,
    case: str = "L",
) -> int:
    """Aplica la carga de servicio EN 12811-1 sobre los ledgers indicados.

    Parameters
    ----------
    model : Model
        Modelo donde se registrarán las cargas distribuidas.
    ledger_ids : iterable de str
        Ids de las barras tipo `ledger` que sostienen la plataforma.
    klass : str
        Clase de servicio (Q1..Q6).
    deck_width : float
        Ancho del paño de plataforma soportado, en metros.
    n_ledgers_per_pair : int
        Número de ledgers que comparten la zona tributaria. Por defecto 2
        (un par front + back en un mismo bay).
    case : str
        Caso de carga al que asignar la `DistributedLoad` (por defecto
        `"L"`, Live).

    Devuelve el número de ledgers afectados.
    """
    if klass not in SERVICE_CLASSES:
        raise ValueError(
            f"Clase {klass!r} desconocida; disponibles: {list(SERVICE_CLASSES)}"
        )
    if deck_width <= 0:
        raise ValueError(f"deck_width debe ser > 0 (recibido {deck_width})")
    if n_ledgers_per_pair < 1:
        raise ValueError("n_ledgers_per_pair debe ser ≥ 1")

    q = SERVICE_CLASSES[klass]
    w = q * deck_width / n_ledgers_per_pair       # N/m, positivo
    n = 0
    for mid in ledger_ids:
        if mid not in model.members:
            raise ValueError(f"Barra {mid} no existe en el modelo")
        model.add_distributed_load(mid, "FZ", -w, -w, case=case)
        n += 1
    return n
