"""Comprobaciones de uniones de andamio según EN 74 + ETAs de fabricante.

EN 74-1/-2/-3 cubre acoplamientos y uniones de andamio. Para sistemas de
andamio multidireccional con conexión de roseta + cuña (Layher Allround,
Plettac, Ringlock genérico) los valores característicos se obtienen de la
**Evaluación Técnica Europea (ETA)** del fabricante.

Este módulo provee:

    1. Catálogos típicos de capacidades (LAYHER_ALLROUND como referencia).
    2. `check_joint(N_Ed, V_Ed, M_Ed, joint_type, gamma_M2)` que aplica una
       interacción lineal:

            (N_Ed / N_Rd)² + (V_Ed / V_Rd)² + (M_Ed / M_Rd) ≤ 1

       ajustada por γ_M2 = 1.25 (EN 1993-1-8 §2.2 valor recomendado para
       conexiones).

Los valores en `LAYHER_ALLROUND` son **conservadores** y representan
una unión de roseta tipo cabeza M con cuña; la práctica habitual exige
sustituirlos por los de la ETA correspondiente al producto exacto que se
vaya a usar en obra.
"""

from __future__ import annotations

from dataclasses import dataclass


# γ_M2 EN 1993-1-8 §2.2 (conexiones)
GAMMA_M2 = 1.25


@dataclass(frozen=True)
class JointCapacity:
    """Capacidades características de una unión de andamio (valores Rk)."""
    name: str
    F_t_Rk: float        # N, tracción axial (cabeza arrancada)
    F_c_Rk: float        # N, compresión axial (carga puntual)
    V_Rk: float          # N, cortante en la cabeza (por dirección)
    M_Rk: float          # N·m, momento flector en la cuña
    K_phi: float         # N·m/rad, rigidez rotacional secante (semi-rígida)


# ---------------------------------------------------------------------------
# Catálogo de referencia
# ---------------------------------------------------------------------------

# Valores conservadores tipo Layher Allround (orientativos — usar la ETA
# real del producto en producción).
LAYHER_ALLROUND_M = JointCapacity(
    name="Layher Allround M (rosette + wedge)",
    F_t_Rk=18_000.0,     # 18 kN
    F_c_Rk=70_000.0,     # 70 kN
    V_Rk=28_000.0,       # 28 kN
    M_Rk=9_000.0,        # 9 kN·m
    K_phi=80_000.0,      # 80 kN·m/rad
)

# Variante reforzada (postes Ø60,3) — capacidades aproximadamente +30%.
LAYHER_ALLROUND_HEAVY = JointCapacity(
    name="Layher Allround Heavy",
    F_t_Rk=23_000.0,
    F_c_Rk=90_000.0,
    V_Rk=36_000.0,
    M_Rk=12_000.0,
    K_phi=100_000.0,
)

JOINT_CAPACITIES: dict[str, JointCapacity] = {
    "layher_allround":       LAYHER_ALLROUND_M,
    "layher_allround_heavy": LAYHER_ALLROUND_HEAVY,
}


def get_joint(name: str) -> JointCapacity:
    if name not in JOINT_CAPACITIES:
        raise KeyError(
            f"Unión {name!r} desconocida; disponibles: {list(JOINT_CAPACITIES)}"
        )
    return JOINT_CAPACITIES[name]


# ---------------------------------------------------------------------------
# Comprobación
# ---------------------------------------------------------------------------

@dataclass
class JointCheck:
    axial: float = 0.0       # N_Ed / N_Rd
    shear: float = 0.0       # V_Ed / V_Rd
    bending: float = 0.0     # M_Ed / M_Rd
    interaction: float = 0.0 # combinada cuadrática

    def worst(self) -> float:
        return max(self.axial, self.shear, self.bending, self.interaction)

    def passed(self, limit: float = 1.0) -> bool:
        return self.worst() <= limit


def check_joint(
    *,
    N_Ed: float = 0.0,
    V_Ed: float = 0.0,
    M_Ed: float = 0.0,
    joint: JointCapacity | str = "layher_allround",
    gamma_M2: float = GAMMA_M2,
) -> JointCheck:
    """Comprobación de unión EN 74 + ETA con interacción lineal-cuadrática.

    `N_Ed` se interpreta como tracción si es positiva, compresión si
    negativa. La capacidad usada es F_t_Rk para tracción y F_c_Rk para
    compresión. Cortante y momento se toman en valor absoluto.

    Interacción:

        u_int = (N/N_Rd)² + (V/V_Rd)² + (M/M_Rd)
    """
    if isinstance(joint, str):
        joint = get_joint(joint)

    # Capacidades de diseño
    F_Rd = (joint.F_t_Rk if N_Ed >= 0 else joint.F_c_Rk) / gamma_M2
    V_Rd = joint.V_Rk / gamma_M2
    M_Rd = joint.M_Rk / gamma_M2

    res = JointCheck()
    if F_Rd > 0 and N_Ed != 0:
        res.axial = abs(N_Ed) / F_Rd
    if V_Rd > 0 and V_Ed != 0:
        res.shear = abs(V_Ed) / V_Rd
    if M_Rd > 0 and M_Ed != 0:
        res.bending = abs(M_Ed) / M_Rd

    res.interaction = res.axial ** 2 + res.shear ** 2 + res.bending
    return res
