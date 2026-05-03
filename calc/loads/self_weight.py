"""Peso propio por barra (acción permanente G).

Para cada barra del modelo se calcula la carga lineal vertical:

    q = ρ · A · g            [N/m]

donde ρ es la densidad del material asignado, A el área de la sección y g la
aceleración gravitatoria. Se aplica como `DistributedLoad` en dirección
global FZ con signo negativo (hacia abajo).

Esta carga se asigna **siempre** al caso `"D"` (Dead) salvo que se indique
otro. Las combinaciones EN 1990 se aplican en solver.solve().
"""

from __future__ import annotations

from ..model import Model


GRAVITY = 9.81      # m/s², EN 1991-1-1 §3.4 (1)


def apply_self_weight(
    model: Model,
    *,
    g: float = GRAVITY,
    case: str = "D",
) -> int:
    """Añade el peso propio como carga distribuida a cada barra.

    Devuelve el número de barras afectadas. Si el modelo no contiene
    barras todavía, devuelve 0.
    """
    n = 0
    for mem in model.members.values():
        try:
            mat = model.materials[mem.material]
            sec = model.sections[mem.section]
        except KeyError as exc:
            raise KeyError(
                f"Material/sección no registrados en la barra {mem.id}: {exc}"
            ) from exc
        w = mat.rho * sec.A * g                # N/m, positivo
        model.add_distributed_load(mem.id, "FZ", -w, -w, case=case)
        n += 1
    return n
