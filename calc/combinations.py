"""Combinaciones de acciones según EN 1990 §6.4.

Estados límite últimos (ELU / ULS) — Eq. 6.10:

    Σ γ_G,j · G_k,j  +  γ_Q,1 · Q_k,1  +  Σ γ_Q,i · ψ_0,i · Q_k,i

donde la acción variable Q_k,1 se considera dominante y el resto se reducen
con su factor de combinación ψ_0,i.

Estados límite de servicio (ELS / SLS) — Eq. 6.14a / 6.15a / 6.16a:

    Característica:    Σ G_k,j  +  Q_k,1  +  Σ ψ_0,i · Q_k,i
    Frecuente:         Σ G_k,j  +  ψ_1,1 · Q_k,1  +  Σ ψ_2,i · Q_k,i
    Casi-permanente:   Σ G_k,j  +  Σ ψ_2,i · Q_k,i

Convención de casos en este addon:
    "D"  Dead          peso propio (calc.loads.self_weight)
    "L"  Live          servicio EN 12811-1 (calc.loads.service_load)
    "W"  Wind          viento EN 1991-1-4 (calc.loads.wind)
    "I"  Imperfection  imperfecciones EN 1993-1-1 (calc.loads.imperfections)

Factores por defecto (EN 1990 Tabla A1.1 + A1.2(B), edificación):
    γ_G       = 1.35      (acciones permanentes desfavorables)
    γ_G,inf   = 1.00      (acciones permanentes favorables, p. ej. levantamiento)
    γ_Q       = 1.50      (acciones variables desfavorables)
    ψ_0_L     = 0.7       (servicio sobre andamios — por analogía con uso C/D)
    ψ_0_W     = 0.6       (viento)
    ψ_1_L     = 0.7       (servicio, frecuente)
    ψ_1_W     = 0.2       (viento, frecuente)
    ψ_2_L     = 0.6       (servicio, casi-permanente)
    ψ_2_W     = 0.0       (viento, casi-permanente)

Las imperfecciones (caso "I") se factorizan con el mismo coeficiente que la
acción permanente porque son efectos geométricos asociados a las cargas
verticales: γ_G en ULS, 1.0 en SLS.

Las combinaciones se devuelven como `dict[str, dict[str, float]]` listo para
pasar al `solver.solve(combos=...)` y a `FEModel3D.add_load_combo`.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

GAMMA_G = 1.35
GAMMA_G_INF = 1.0
GAMMA_Q = 1.5

PSI_0 = {"L": 0.7, "W": 0.6}
PSI_1 = {"L": 0.7, "W": 0.2}
PSI_2 = {"L": 0.6, "W": 0.0}


# ---------------------------------------------------------------------------
# ULS — Eq. 6.10
# ---------------------------------------------------------------------------

def uls_eq_6_10(
    *,
    gamma_G: float = GAMMA_G,
    gamma_G_inf: float = GAMMA_G_INF,
    gamma_Q: float = GAMMA_Q,
    psi_0: dict[str, float] | None = None,
    include_uplift: bool = True,
) -> dict[str, dict[str, float]]:
    """Devuelve las combinaciones ULS persistentes EN 1990 Eq. 6.10.

    Genera una combinación con cada acción variable como dominante:
        ULS_LeadL : 1.35 D + 1.5 L + 1.5·ψ_0_W·W + 1.35 I
        ULS_LeadW : 1.35 D + 1.5·ψ_0_L·L + 1.5 W + 1.35 I

    Si `include_uplift` (default True) añade además:
        ULS_Uplift : 1.0 D + 1.5 W + 1.0 I

    útil para verificar levantamiento de apoyos cuando el viento se opone
    a la gravedad. `gamma_G_inf` se aplica también al caso "I" en uplift
    porque las imperfecciones se atan al peso propio, que aquí va minorado.
    """
    if psi_0 is None:
        psi_0 = PSI_0

    combos = {
        "ULS_LeadL": {
            "D": gamma_G,
            "L": gamma_Q,
            "W": gamma_Q * psi_0["W"],
            "I": gamma_G,
        },
        "ULS_LeadW": {
            "D": gamma_G,
            "L": gamma_Q * psi_0["L"],
            "W": gamma_Q,
            "I": gamma_G,
        },
    }
    if include_uplift:
        combos["ULS_Uplift"] = {
            "D": gamma_G_inf,
            "W": gamma_Q,
            "I": gamma_G_inf,
        }
    return combos


# ---------------------------------------------------------------------------
# SLS
# ---------------------------------------------------------------------------

def sls_characteristic(
    *,
    psi_0: dict[str, float] | None = None,
    leading: str = "L",
) -> dict[str, dict[str, float]]:
    """Combinación característica EN 1990 Eq. 6.14a:

        D + Q_lead + Σ ψ_0,i Q_i + I

    Por defecto la acción dominante es servicio "L".
    """
    if psi_0 is None:
        psi_0 = PSI_0
    others = {k: psi_0[k] for k in psi_0 if k != leading}
    factors: dict[str, float] = {"D": 1.0, "I": 1.0, leading: 1.0}
    factors.update(others)
    return {f"SLS_char_{leading}": factors}


def sls_frequent(
    *,
    psi_1: dict[str, float] | None = None,
    psi_2: dict[str, float] | None = None,
    leading: str = "L",
) -> dict[str, dict[str, float]]:
    """Combinación frecuente EN 1990 Eq. 6.15a:

        D + ψ_1,lead Q_lead + Σ ψ_2,i Q_i + I
    """
    if psi_1 is None:
        psi_1 = PSI_1
    if psi_2 is None:
        psi_2 = PSI_2
    others = {k: psi_2[k] for k in psi_2 if k != leading}
    factors: dict[str, float] = {"D": 1.0, "I": 1.0, leading: psi_1[leading]}
    factors.update(others)
    return {f"SLS_freq_{leading}": factors}


def sls_quasi_permanent(
    *,
    psi_2: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    """Combinación casi-permanente EN 1990 Eq. 6.16a:

        D + Σ ψ_2,i Q_i + I
    """
    if psi_2 is None:
        psi_2 = PSI_2
    factors: dict[str, float] = {"D": 1.0, "I": 1.0}
    factors.update(psi_2)
    return {"SLS_quasi": factors}


# ---------------------------------------------------------------------------
# Atajos
# ---------------------------------------------------------------------------

def standard_combos(
    *,
    include_sls: bool = True,
    include_uplift: bool = True,
) -> dict[str, dict[str, float]]:
    """Devuelve el set completo ULS + SLS habitual para un andamio."""
    combos = uls_eq_6_10(include_uplift=include_uplift)
    if include_sls:
        combos.update(sls_characteristic())
        combos.update(sls_frequent())
        combos.update(sls_quasi_permanent())
    return combos
