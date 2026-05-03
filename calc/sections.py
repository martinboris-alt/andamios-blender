"""Catálogo de secciones tubulares CHS para andamios.

Perfiles habituales en andamios multidireccionales:
    - Ø48,3 × 3,2 mm    (estándar Layher / Ringlock EU)
    - Ø48,3 × 4,0 mm    (variante reforzada)
    - Ø60,3 × 3,2 mm    (poste reforzado / torre de carga)

Para cada perfil se calculan A, I (= Iy = Iz por bisimetría), J, Wel, Wpl,
i (radio de giro) y la clase EN 1993-1-1 según fy del acero. Los valores
siguen las fórmulas de un tubo circular hueco puro:

    A   = π/4 (D² − d²)
    I   = π/64 (D⁴ − d⁴)
    J   = 2 I               (tubo cerrado bisimétrico)
    Wel = I / (D/2)
    Wpl = (D³ − d³) / 6     (módulo plástico exacto del CHS)
    i   = √(I / A)

Clasificación EN 1993-1-1 Tabla 5.2 (perfiles a flexo-compresión):
    Clase 1 si  D/t ≤ 50 ε²
    Clase 2 si  D/t ≤ 70 ε²
    Clase 3 si  D/t ≤ 90 ε²
    Clase 4 en otro caso
con ε = √(235 / fy_MPa).
"""

from __future__ import annotations

import math

from .model import Section, CHS_48_3x3_2


# ---------------------------------------------------------------------------
# Cálculo de propiedades
# ---------------------------------------------------------------------------

def _chs_full(D: float, t: float) -> dict[str, float]:
    """Propiedades geométricas exactas de un CHS de diámetro `D` y espesor `t`."""
    d = D - 2.0 * t
    A = math.pi / 4.0 * (D * D - d * d)
    I = math.pi / 64.0 * (D ** 4 - d ** 4)
    J = 2.0 * I
    Wel = I / (D / 2.0)
    Wpl = (D ** 3 - d ** 3) / 6.0
    i = math.sqrt(I / A)
    return {"A": A, "I": I, "J": J, "Wel": Wel, "Wpl": Wpl, "i": i}


def classify_chs(D: float, t: float, fy: float) -> int:
    """Devuelve la clase EN 1993-1-1 del CHS dado su fy en Pa."""
    fy_mpa = fy / 1e6
    eps2 = 235.0 / fy_mpa
    ratio = D / t
    if ratio <= 50.0 * eps2:
        return 1
    if ratio <= 70.0 * eps2:
        return 2
    if ratio <= 90.0 * eps2:
        return 3
    return 4


def make_chs_section(name: str, D: float, t: float, fy: float = 235e6) -> Section:
    """Construye una `Section` CHS lista para el modelo."""
    p = _chs_full(D, t)
    return Section(
        name=name,
        A=p["A"],
        Iy=p["I"],
        Iz=p["I"],
        J=p["J"],
        Wel=p["Wel"],
        Wpl=p["Wpl"],
        i=p["i"],
        eu_class=classify_chs(D, t, fy),
    )


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

# CHS_48_3x3_2 ya está definido en model.py para que extract_model.py funcione
# sin importar este módulo. Lo importamos para garantizar coherencia y lo
# añadimos al catálogo aquí.

CHS_48_3x4_0 = make_chs_section("CHS_48.3x4.0", D=0.0483, t=0.0040)
CHS_60_3x3_2 = make_chs_section("CHS_60.3x3.2", D=0.0603, t=0.0032)


SECTIONS: dict[str, Section] = {
    CHS_48_3x3_2.name: CHS_48_3x3_2,
    CHS_48_3x4_0.name: CHS_48_3x4_0,
    CHS_60_3x3_2.name: CHS_60_3x3_2,
}


def get_section(name: str) -> Section:
    if name in SECTIONS:
        return SECTIONS[name]
    raise KeyError(f"Sección desconocida: {name}; disponibles: {list(SECTIONS)}")


def register_section(sec: Section) -> None:
    SECTIONS[sec.name] = sec
