"""Cargas de viento según EN 1991-1-4 con anejo nacional España (CTE DB-SE-AE).

Modelo de cálculo (EN 1991-1-4 §4.3 - §4.5):

    v_b = c_dir · c_season · v_b,0
    c_r(z) = k_r · ln(max(z, z_min) / z_0)
    k_r    = 0.19 · (z_0 / z_0,II) ** 0.07
    v_m(z) = c_r(z) · c_o(z) · v_b
    I_v(z) = k_l / (c_o(z) · ln(max(z, z_min) / z_0))
    q_p(z) = [1 + 7 · I_v(z)] · ½ · ρ_air · v_m(z)²

Categorías de terreno (EN 1991-1-4 Tabla 4.1):

    Cat 0    z_0 = 0,003 m   z_min = 1 m     (mar)
    Cat I    z_0 = 0,01  m   z_min = 1 m     (lago, llanura)
    Cat II   z_0 = 0,05  m   z_min = 2 m     (campo abierto)        ← referencia
    Cat III  z_0 = 0,3   m   z_min = 5 m     (suburbano)
    Cat IV   z_0 = 1,0   m   z_min = 10 m    (urbano denso)

Anejo nacional España — CTE DB-SE-AE Anejo D (zonas de viento):

    Zona A   v_b,0 = 26 m/s
    Zona B   v_b,0 = 27 m/s
    Zona C   v_b,0 = 29 m/s

Para andamios la EN 12811-1 §6.2.7 remite a EN 1991-1-4 con los coeficientes de
fuerza específicos de mallas/cubrición. Esta implementación deja `c_f` y la
dimensión perpendicular `diameter` como parámetros explícitos del caller — es
el usuario quien decide si modela el andamio "abierto" (sólo tubos, c_f por
solidez) o "cubierto" (mallas, c_f efectivo).

`apply_wind_load` aplica una carga lineal w = c_f · q_p(z_mid) · D a cada
barra indicada, evaluando q_p en el midpoint del tubo. Para una variación
fina de q_p(z) sobre un poste que cruza varias plantas, subdivide la barra
previamente con `Model.split_member` (Fase 2).
"""

from __future__ import annotations

import math
from typing import Iterable

from ..model import Model


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

RHO_AIR = 1.25       # kg/m³, EN 1991-1-4 §4.5(1) recomendado
K_L_DEFAULT = 1.0    # turbulence factor, EN 1991-1-4 §4.4(1) recomendado

# z_0,II — rugosidad de referencia (categoría II)
_Z0_REF = 0.05

# Tabla 4.1
TERRAIN_PARAMS: dict[str, dict[str, float]] = {
    "0":   {"z_0": 0.003, "z_min": 1.0},
    "I":   {"z_0": 0.01,  "z_min": 1.0},
    "II":  {"z_0": 0.05,  "z_min": 2.0},
    "III": {"z_0": 0.3,   "z_min": 5.0},
    "IV":  {"z_0": 1.0,   "z_min": 10.0},
}

# CTE DB-SE-AE Anejo D — velocidades básicas por zona (m/s, periodo de retorno 50 años)
SPAIN_BASIC_WIND: dict[str, float] = {
    "A": 26.0,
    "B": 27.0,
    "C": 29.0,
}


# ---------------------------------------------------------------------------
# Cálculo de q_p(z)
# ---------------------------------------------------------------------------

def basic_velocity_pressure(v_b: float, rho_air: float = RHO_AIR) -> float:
    """q_b = ½ · ρ · v_b² (Pa)."""
    return 0.5 * rho_air * v_b * v_b


def roughness_factor(z: float, terrain: str = "II") -> float:
    """c_r(z) según EN 1991-1-4 §4.3.2."""
    if terrain not in TERRAIN_PARAMS:
        raise ValueError(
            f"Terreno {terrain!r} desconocido; opciones: {list(TERRAIN_PARAMS)}"
        )
    z_0 = TERRAIN_PARAMS[terrain]["z_0"]
    z_min = TERRAIN_PARAMS[terrain]["z_min"]
    z_eval = max(z, z_min)
    k_r = 0.19 * (z_0 / _Z0_REF) ** 0.07
    return k_r * math.log(z_eval / z_0)


def turbulence_intensity(
    z: float,
    terrain: str = "II",
    *,
    c_o: float = 1.0,
    k_l: float = K_L_DEFAULT,
) -> float:
    """I_v(z) según EN 1991-1-4 §4.4."""
    z_0 = TERRAIN_PARAMS[terrain]["z_0"]
    z_min = TERRAIN_PARAMS[terrain]["z_min"]
    z_eval = max(z, z_min)
    return k_l / (c_o * math.log(z_eval / z_0))


def peak_velocity_pressure(
    z: float,
    *,
    terrain: str = "II",
    v_b: float = 26.0,
    c_o: float = 1.0,
    k_l: float = K_L_DEFAULT,
    rho_air: float = RHO_AIR,
) -> float:
    """Presión de velocidad de pico q_p(z) en Pa (EN 1991-1-4 §4.5).

    z          altura sobre el suelo en m (se aplica el clamp z ≥ z_min)
    terrain    categoría 0 / I / II / III / IV
    v_b        velocidad básica del viento (m/s); en España usar SPAIN_BASIC_WIND
    c_o        factor de orografía (1.0 si terreno plano)
    k_l        factor de turbulencia (1.0 recomendado por EN)
    rho_air    densidad del aire (1.25 kg/m³ recomendado)
    """
    c_r = roughness_factor(z, terrain)
    v_m = c_r * c_o * v_b
    I_v = turbulence_intensity(z, terrain, c_o=c_o, k_l=k_l)
    return (1.0 + 7.0 * I_v) * 0.5 * rho_air * v_m * v_m


# ---------------------------------------------------------------------------
# Aplicación al modelo
# ---------------------------------------------------------------------------

def apply_wind_load(
    model: Model,
    member_ids: Iterable[str],
    *,
    diameter: float,
    c_f: float = 1.3,
    terrain: str = "II",
    v_b: float = 26.0,
    c_o: float = 1.0,
    k_l: float = K_L_DEFAULT,
    rho_air: float = RHO_AIR,
    direction: str = "FX",
    case: str = "W",
) -> int:
    """Aplica una carga lineal de viento a las barras indicadas.

    Para cada barra se evalúa q_p en el midpoint (cota z del centroide) y se
    añade una `DistributedLoad` global de magnitud:

        w = c_f · q_p(z_mid) · diameter           [N/m]

    Parameters
    ----------
    model : Model
    member_ids : iterable de str
        Ids de las barras a cargar (típicamente postes verticales).
    diameter : float
        Dimensión expuesta perpendicular al viento, en metros (ej. 0.0483
        para tubo de andamio Ø48,3 mm).
    c_f : float
        Coeficiente de fuerza. 1.3 valor conservador para tubos lisos
        circulares (EN 1991-1-4 §7.9). Para andamios cubiertos con malla
        usar el valor de norma o ETA del fabricante.
    direction : str
        "FX" o "FY" (viento en X o Y); siempre dirección global, sentido
        positivo. Para viento contrario aplicar de nuevo con signo opuesto
        en `c_f` o en `direction` no — usar dos casos ("W+", "W-").

    Devuelve el número de barras cargadas. Si `member_ids` está vacío, 0.
    """
    if direction not in ("FX", "FY"):
        raise ValueError(f"direction debe ser FX o FY (recibido {direction!r})")
    if diameter <= 0:
        raise ValueError(f"diameter debe ser > 0 (recibido {diameter})")

    n = 0
    for mid in member_ids:
        if mid not in model.members:
            raise ValueError(f"Barra {mid} no existe en el modelo")
        mem = model.members[mid]
        ni = model.nodes[mem.i_node]
        nj = model.nodes[mem.j_node]
        z_mid = 0.5 * (ni.z + nj.z)
        q = peak_velocity_pressure(
            z_mid, terrain=terrain, v_b=v_b, c_o=c_o, k_l=k_l, rho_air=rho_air,
        )
        w = c_f * q * diameter        # N/m
        model.add_distributed_load(mid, direction, w, w, case=case)
        n += 1
    return n
