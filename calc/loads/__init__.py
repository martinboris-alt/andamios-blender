"""Aplicación de cargas a un Model.

Submódulos:
    self_weight    — peso propio por barra (G).
    service_load   — clases de servicio EN 12811-1 (Q).
    wind           — viento EN 1991-1-4 + anejo nacional España (W).
    imperfections  — imperfecciones globales EN 1993-1-1 §5.3 (I).

Las combinaciones (1.35 G + 1.5 Q, 0.9 G + 1.5 W, …) se construyen con
`calc.combinations` y se pasan a `solver.solve(combos=...)`.
"""

from .self_weight import GRAVITY, apply_self_weight
from .service_load import SERVICE_CLASSES, apply_service_load
from .wind import (
    RHO_AIR,
    SPAIN_BASIC_WIND,
    TERRAIN_PARAMS,
    apply_wind_load,
    basic_velocity_pressure,
    peak_velocity_pressure,
    roughness_factor,
    turbulence_intensity,
)
from .imperfections import (
    PHI_0,
    alpha_h,
    alpha_m,
    apply_horizontal_imperfection,
    imperfection_angle,
)

__all__ = [
    # self_weight
    "GRAVITY",
    "apply_self_weight",
    # service_load
    "SERVICE_CLASSES",
    "apply_service_load",
    # wind
    "RHO_AIR",
    "SPAIN_BASIC_WIND",
    "TERRAIN_PARAMS",
    "apply_wind_load",
    "basic_velocity_pressure",
    "peak_velocity_pressure",
    "roughness_factor",
    "turbulence_intensity",
    # imperfections
    "PHI_0",
    "alpha_h",
    "alpha_m",
    "apply_horizontal_imperfection",
    "imperfection_angle",
]
