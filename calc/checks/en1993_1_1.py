"""Comprobaciones de resistencia y estabilidad según EN 1993-1-1.

Cubre las cláusulas relevantes para andamios:
    §6.2.3   Tracción
    §6.2.4   Compresión
    §6.2.5   Flexión
    §6.2.6   Cortante
    §6.2.9   Flexión + axil (resistencia de sección)
    §6.3.1   Pandeo por compresión
    §6.3.3   Flexo-compresión (interacción Eq. 6.61/6.62, Anexo B)

Valores por defecto:
    γ_M0 = γ_M1 = 1.0       (EN 1993-1-1 §6.1, valor recomendado)
    Curva pandeo: "c"        (CHS conformado en frío — andamio típico)
    C_my = C_mz = 0.9        (Anexo B, distribución conservadora)

Para CHS bisimétricos (Iy = Iz) sin susceptibilidad a torsión-flexión
lateral (χ_LT = 1.0), las ecuaciones 6.61 y 6.62 colapsan en una sola
expresión, simplificando el check de flexo-compresión.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..model import Material, Section


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Factores de imperfección (EN 1993-1-1 Tabla 6.1)
ALPHA_BUCKLING = {
    "a0": 0.13,
    "a":  0.21,
    "b":  0.34,
    "c":  0.49,    # CHS conformado en frío (valor por defecto andamios)
    "d":  0.76,
}

# γ_M recomendados (EN 1993-1-1 §6.1)
GAMMA_M0 = 1.0
GAMMA_M1 = 1.0
GAMMA_M2 = 1.25


# ---------------------------------------------------------------------------
# Capacidades de sección
# ---------------------------------------------------------------------------

def tension_resistance(section: Section, material: Material, *, gamma_M0: float = GAMMA_M0) -> float:
    """N_t,Rd = A · fy / γ_M0 (EN 1993-1-1 §6.2.3, sección bruta)."""
    return section.A * material.fy / gamma_M0


def compression_resistance(section: Section, material: Material, *, gamma_M0: float = GAMMA_M0) -> float:
    """N_c,Rd = A · fy / γ_M0 para clase 1-3 (EN 1993-1-1 §6.2.4)."""
    if section.eu_class >= 4:
        # Clase 4: usar área efectiva (no implementado para CHS típicos
        # de andamio, que son siempre clase 1).
        raise NotImplementedError(
            f"Sección {section.name} es clase 4; usar área efectiva no implementado"
        )
    return section.A * material.fy / gamma_M0


def bending_resistance(section: Section, material: Material, *, gamma_M0: float = GAMMA_M0) -> float:
    """M_c,Rd según clase de sección (EN 1993-1-1 §6.2.5):
        clase 1-2: W_pl · fy / γ_M0
        clase 3:   W_el · fy / γ_M0
        clase 4:   no implementado
    """
    if section.eu_class in (1, 2):
        W = section.Wpl
    elif section.eu_class == 3:
        W = section.Wel
    elif section.eu_class >= 4:
        raise NotImplementedError(f"Sección {section.name} clase 4 — no implementado")
    else:
        # Sección sin clasificar: usa el módulo elástico (conservador)
        W = section.Wel if section.Wel > 0 else section.Wpl
    return W * material.fy / gamma_M0


def shear_resistance(section: Section, material: Material, *, gamma_M0: float = GAMMA_M0) -> float:
    """V_c,Rd = A_v · fy/√3 / γ_M0.

    Para CHS (EN 1993-1-1 §6.2.6(3) Eq. 6.22):
        A_v = 2 · A / π
    """
    A_v = 2.0 * section.A / math.pi
    return A_v * material.fy / (math.sqrt(3.0) * gamma_M0)


# ---------------------------------------------------------------------------
# Pandeo por compresión (§6.3.1)
# ---------------------------------------------------------------------------

def slenderness_lambda_1(material: Material) -> float:
    """λ_1 = π · √(E/fy)  (esbeltez de referencia)."""
    return math.pi * math.sqrt(material.E / material.fy)


def non_dimensional_slenderness(
    section: Section,
    material: Material,
    L_cr: float,
) -> float:
    """λ̄ = (L_cr / i) / λ_1 para clases 1-3.

    L_cr es la longitud de pandeo equivalente (K · L_real) y `i` el radio
    de giro de la sección (almacenado en `Section.i`).
    """
    if section.i <= 0:
        raise ValueError(f"Sección {section.name} sin radio de giro definido")
    if L_cr <= 0:
        raise ValueError(f"L_cr debe ser > 0 (recibido {L_cr})")
    return (L_cr / section.i) / slenderness_lambda_1(material)


def chi_buckling(lambda_bar: float, *, curve: str = "c") -> float:
    """Coeficiente de reducción χ por pandeo (EN 1993-1-1 §6.3.1.2 Eq. 6.49).

    Si λ̄ ≤ 0,2 (o N_Ed/N_cr ≤ 0,04, no se controla aquí) no hay reducción.
    """
    if lambda_bar < 0:
        raise ValueError(f"λ̄ debe ser ≥ 0 (recibido {lambda_bar})")
    if lambda_bar <= 0.2:
        return 1.0
    if curve not in ALPHA_BUCKLING:
        raise ValueError(f"Curva {curve!r} desconocida; opciones: {list(ALPHA_BUCKLING)}")
    alpha = ALPHA_BUCKLING[curve]
    phi = 0.5 * (1.0 + alpha * (lambda_bar - 0.2) + lambda_bar ** 2)
    chi = 1.0 / (phi + math.sqrt(phi * phi - lambda_bar * lambda_bar))
    return min(chi, 1.0)


def buckling_resistance(
    section: Section,
    material: Material,
    L_cr: float,
    *,
    curve: str = "c",
    gamma_M1: float = GAMMA_M1,
) -> float:
    """N_b,Rd = χ · A · fy / γ_M1 (Eq. 6.47, sección bisimétrica clase 1-3)."""
    lambda_bar = non_dimensional_slenderness(section, material, L_cr)
    chi = chi_buckling(lambda_bar, curve=curve)
    return chi * section.A * material.fy / gamma_M1


# ---------------------------------------------------------------------------
# Interacción flexo-compresión (§6.3.3 Eq. 6.61/6.62, Anexo B)
# ---------------------------------------------------------------------------

def k_yy_chs(
    N_Ed: float,
    chi_y: float,
    N_Rk: float,
    lambda_bar_y: float,
    *,
    C_my: float = 0.9,
    gamma_M1: float = GAMMA_M1,
) -> float:
    """Factor de interacción k_yy según Anexo B Tabla B.1 para CHS clase 1-2.

        k_yy = C_my · [1 + (λ̄_y - 0.2) · n]   con cota superior
        k_yy ≤ C_my · (1 + 0.8 · n)
    donde n = N_Ed · γ_M1 / (χ_y · N_Rk).
    """
    if N_Rk <= 0:
        return 0.0
    n = abs(N_Ed) * gamma_M1 / (chi_y * N_Rk)
    k = C_my * (1.0 + (lambda_bar_y - 0.2) * n)
    k_max = C_my * (1.0 + 0.8 * n)
    return min(k, k_max)


def interaction_combined(
    section: Section,
    material: Material,
    *,
    N_Ed: float,
    M_y_Ed: float,
    M_z_Ed: float,
    L_cr: float,
    curve: str = "c",
    C_my: float = 0.9,
    C_mz: float = 0.9,
    gamma_M0: float = GAMMA_M0,
    gamma_M1: float = GAMMA_M1,
) -> float:
    """Verificación de flexo-compresión (Eq. 6.61/6.62) para CHS bisimétrico
    no susceptible a torsión-flexión lateral.

    Como χ_y = χ_z = χ y χ_LT = 1, las dos ecuaciones colapsan en:

        n + k_yy · m_y + k_zy · m_z   ≤ 1

    donde n = N_Ed/(χ N_Rk/γ_M1), m_y = M_y_Ed/M_y_Rk·γ_M1, m_z análogo,
    k_zy = 0.6 · k_yy (Anexo B Tabla B.1).

    Devuelve la utilización (≤ 1 → OK).
    """
    if N_Ed < 0:
        # Convención: N_Ed positiva en compresión para esta función.
        N_Ed = -N_Ed
    N_Rk = section.A * material.fy
    M_Rk = (
        section.Wpl if section.eu_class in (1, 2) and section.Wpl > 0
        else section.Wel
    ) * material.fy

    if N_Ed > 0:
        lambda_bar = non_dimensional_slenderness(section, material, L_cr)
        chi = chi_buckling(lambda_bar, curve=curve)
        n = N_Ed * gamma_M1 / (chi * N_Rk)
        k_yy = k_yy_chs(N_Ed, chi, N_Rk, lambda_bar,
                        C_my=C_my, gamma_M1=gamma_M1)
        k_zz = k_yy_chs(N_Ed, chi, N_Rk, lambda_bar,
                        C_my=C_mz, gamma_M1=gamma_M1)
    else:
        n = 0.0
        k_yy = C_my
        k_zz = C_mz
    k_zy = 0.6 * k_yy

    m_y = abs(M_y_Ed) * gamma_M1 / M_Rk if M_Rk > 0 else 0.0
    m_z = abs(M_z_Ed) * gamma_M1 / M_Rk if M_Rk > 0 else 0.0

    return n + k_yy * m_y + k_zy * m_z


# ---------------------------------------------------------------------------
# Resultado de check
# ---------------------------------------------------------------------------

@dataclass
class SectionCheck:
    """Resultado bruto de comprobaciones de una sección.

    Cada campo es la utilización demanda/capacidad para el chequeo
    correspondiente (≤ 1 → OK). Si la demanda es nula, la utilización es 0.
    """
    tension: float = 0.0
    compression: float = 0.0
    bending_y: float = 0.0
    bending_z: float = 0.0
    shear_y: float = 0.0
    shear_z: float = 0.0
    buckling: float = 0.0
    combined: float = 0.0

    def worst(self) -> float:
        return max(
            self.tension, self.compression,
            self.bending_y, self.bending_z,
            self.shear_y, self.shear_z,
            self.buckling, self.combined,
        )

    def passed(self, limit: float = 1.0) -> bool:
        return self.worst() <= limit


def check_section_resistances(
    section: Section,
    material: Material,
    *,
    N_Ed_t: float = 0.0,        # tracción (positiva)
    N_Ed_c: float = 0.0,        # compresión (positiva)
    M_y_Ed: float = 0.0,
    M_z_Ed: float = 0.0,
    V_y_Ed: float = 0.0,
    V_z_Ed: float = 0.0,
    L_cr: float | None = None,
    curve: str = "c",
    C_my: float = 0.9,
    C_mz: float = 0.9,
    gamma_M0: float = GAMMA_M0,
    gamma_M1: float = GAMMA_M1,
) -> SectionCheck:
    """Calcula utilización para todos los chequeos sobre la sección/miembro.

    Si `L_cr` es None, los chequeos de pandeo y combinado se omiten
    (utilización = 0). Las componentes negativas de N_Ed_t y N_Ed_c se
    interpretan como cero (la convención es signo positivo en su sentido).
    """
    res = SectionCheck()

    if N_Ed_t > 0:
        res.tension = N_Ed_t / tension_resistance(section, material, gamma_M0=gamma_M0)
    if N_Ed_c > 0:
        res.compression = N_Ed_c / compression_resistance(section, material, gamma_M0=gamma_M0)

    M_Rd = bending_resistance(section, material, gamma_M0=gamma_M0)
    if M_Rd > 0:
        res.bending_y = abs(M_y_Ed) / M_Rd
        res.bending_z = abs(M_z_Ed) / M_Rd

    V_Rd = shear_resistance(section, material, gamma_M0=gamma_M0)
    if V_Rd > 0:
        res.shear_y = abs(V_y_Ed) / V_Rd
        res.shear_z = abs(V_z_Ed) / V_Rd

    if L_cr is not None and N_Ed_c > 0:
        N_b_Rd = buckling_resistance(
            section, material, L_cr, curve=curve, gamma_M1=gamma_M1,
        )
        res.buckling = N_Ed_c / N_b_Rd

    if L_cr is not None and (N_Ed_c > 0 or M_y_Ed != 0 or M_z_Ed != 0):
        res.combined = interaction_combined(
            section, material,
            N_Ed=N_Ed_c, M_y_Ed=M_y_Ed, M_z_Ed=M_z_Ed,
            L_cr=L_cr, curve=curve, C_my=C_my, C_mz=C_mz,
            gamma_M0=gamma_M0, gamma_M1=gamma_M1,
        )

    return res
