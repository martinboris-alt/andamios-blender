"""Comprobaciones de resistencia y servicio para el modelo FEM.

Submódulos:
    en1993_1_1   — capacidades sección + pandeo + interacción flexo-compresión.
    en12811      — comprobaciones de servicio (deflexión, barandillas).
    joints       — uniones EN 74 + ETA Layher Allround.

Función agregada `run_all_checks(model, results, *, L_cr_factor, ...)` que
recorre todas las barras del modelo, evalúa las comprobaciones EN 1993-1-1
y devuelve un dict {member_id: SectionCheck} con la utilización por barra.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import Model
from ..solver import Results
from .en1993_1_1 import (
    ALPHA_BUCKLING,
    GAMMA_M0,
    GAMMA_M1,
    SectionCheck,
    bending_resistance,
    buckling_resistance,
    check_section_resistances,
    chi_buckling,
    compression_resistance,
    interaction_combined,
    k_yy_chs,
    non_dimensional_slenderness,
    shear_resistance,
    slenderness_lambda_1,
    tension_resistance,
)
from .en12811 import (
    DEFLECTION_LIMIT_PLATFORM,
    DEFLECTION_LIMIT_WIND,
    GUARDRAIL_HORIZONTAL_LOAD,
    GUARDRAIL_VERTICAL_LOAD,
    check_deflection_limit,
    check_guardrail_capacity,
)
from .joints import (
    GAMMA_M2,
    JOINT_CAPACITIES,
    JointCapacity,
    JointCheck,
    LAYHER_ALLROUND_HEAVY,
    LAYHER_ALLROUND_M,
    check_joint,
    get_joint,
)


# Curva por defecto para CHS conformados en frío de andamio (EN 1993-1-1
# Tabla 6.2). El usuario puede pasar otra a `run_all_checks`.
CURVE_BY_TYPE: dict[str, str] = {
    "pole":   "c",
    "ledger": "c",
    "brace":  "c",
    "tie":    "c",
}


@dataclass
class MemberCheckResult:
    """Resumen de comprobaciones para una barra."""
    member: str
    section: str
    material: str
    L: float
    L_cr: float
    section_check: SectionCheck

    @property
    def utilization(self) -> float:
        return self.section_check.worst()

    @property
    def passed(self) -> bool:
        return self.section_check.passed()


def run_all_checks(
    model: Model,
    results: Results,
    *,
    L_cr_factor: float = 1.0,
    L_cr_overrides: dict[str, float] | None = None,
    curve_by_type: dict[str, str] | None = None,
    C_my: float = 0.9,
    C_mz: float = 0.9,
    gamma_M0: float = GAMMA_M0,
    gamma_M1: float = GAMMA_M1,
) -> dict[str, MemberCheckResult]:
    """Recorre todas las barras del modelo y evalúa los chequeos EN 1993-1-1.

    Parameters
    ----------
    model : Model
    results : Results
        Salida de `solver.solve(model, ...)`.
    L_cr_factor : float
        Factor de longitud de pandeo por defecto (K · L_real). 1.0 ≡ pinned-
        pinned. Para postes interiores Layher se suele usar 1.0; para postes
        de planta superior K ≈ 1.7 y se debe pasar via `L_cr_overrides`.
    L_cr_overrides : dict[str, float] | None
        Override absoluto de L_cr por id de miembro (m). Tiene prioridad
        sobre `L_cr_factor`.
    curve_by_type : dict[str, str] | None
        Curva de pandeo por tipo de miembro (default: CURVE_BY_TYPE).
    C_my, C_mz, gamma_M0, gamma_M1 : ver en1993_1_1.check_section_resistances.
    """
    L_cr_overrides = L_cr_overrides or {}
    curve_by_type = curve_by_type or CURVE_BY_TYPE

    out: dict[str, MemberCheckResult] = {}
    for mid, mem in model.members.items():
        if mid not in results.members:
            continue
        mres = results.members[mid]
        section = model.sections[mem.section]
        material = model.materials[mem.material]

        L = mres.length
        L_cr = L_cr_overrides.get(mid, L_cr_factor * L)

        N_axial_max = mres.axial_max     # +tracción
        N_axial_min = mres.axial_min     # -compresión (si negativo)
        N_t = max(0.0, N_axial_max)
        N_c = max(0.0, -N_axial_min)

        check = check_section_resistances(
            section, material,
            N_Ed_t=N_t,
            N_Ed_c=N_c,
            M_y_Ed=mres.moment_y_max,
            M_z_Ed=mres.moment_z_max,
            V_y_Ed=mres.shear_y_max,
            V_z_Ed=mres.shear_z_max,
            L_cr=L_cr,
            curve=curve_by_type.get(mem.member_type, "c"),
            C_my=C_my, C_mz=C_mz,
            gamma_M0=gamma_M0, gamma_M1=gamma_M1,
        )

        out[mid] = MemberCheckResult(
            member=mid,
            section=section.name,
            material=material.name,
            L=L,
            L_cr=L_cr,
            section_check=check,
        )
    return out


__all__ = [
    # EN 1993-1-1
    "ALPHA_BUCKLING",
    "GAMMA_M0",
    "GAMMA_M1",
    "SectionCheck",
    "bending_resistance",
    "buckling_resistance",
    "check_section_resistances",
    "chi_buckling",
    "compression_resistance",
    "interaction_combined",
    "k_yy_chs",
    "non_dimensional_slenderness",
    "shear_resistance",
    "slenderness_lambda_1",
    "tension_resistance",
    # EN 12811-1
    "DEFLECTION_LIMIT_PLATFORM",
    "DEFLECTION_LIMIT_WIND",
    "GUARDRAIL_HORIZONTAL_LOAD",
    "GUARDRAIL_VERTICAL_LOAD",
    "check_deflection_limit",
    "check_guardrail_capacity",
    # Joints (EN 74 + ETA)
    "GAMMA_M2",
    "JOINT_CAPACITIES",
    "JointCapacity",
    "JointCheck",
    "LAYHER_ALLROUND_HEAVY",
    "LAYHER_ALLROUND_M",
    "check_joint",
    "get_joint",
    # Pipeline
    "CURVE_BY_TYPE",
    "MemberCheckResult",
    "run_all_checks",
]
