"""Catálogo de aceros estructurales para andamios (EN 10025-2).

Valores por defecto para los aceros típicos de andamio multidireccional:
módulo de Young, módulo de cizalla, coeficiente de Poisson, densidad y
límites elástico/último a temperatura ambiente. Los valores siguen la
EN 1993-1-1 §3.2 y EN 10025-2.

El catálogo es un dict `MATERIALS` indexado por nombre. Para añadir una
calidad nueva, registra otra entrada o llama a `register_material`.
"""

from __future__ import annotations

from .model import Material, S235JR


_E = 210e9                      # Pa, EN 1993-1-1 §3.2.6 (1)
_NU = 0.3                       # EN 1993-1-1 §3.2.6 (1)
_G = _E / (2.0 * (1.0 + _NU))   # ≈ 80.77 GPa
_RHO = 7850.0                   # kg/m³, EN 1991-1-1 Tabla A.4


def _steel(name: str, fy: float, fu: float) -> Material:
    return Material(name=name, E=_E, G=_G, nu=_NU, rho=_RHO, fy=fy, fu=fu)


# fy según EN 10025-2 para t ≤ 16 mm; fu rango medio del intervalo de norma.
S275JR = _steel("S275JR", fy=275e6, fu=430e6)
S355JR = _steel("S355JR", fy=355e6, fu=510e6)


MATERIALS: dict[str, Material] = {
    S235JR.name: S235JR,
    S275JR.name: S275JR,
    S355JR.name: S355JR,
}


def get_material(name: str) -> Material:
    """Devuelve un Material por nombre. Acepta variantes con / sin guión."""
    if name in MATERIALS:
        return MATERIALS[name]
    norm = name.replace("-", "").replace(" ", "").upper()
    for key, mat in MATERIALS.items():
        if key.replace("-", "").upper() == norm:
            return mat
    raise KeyError(f"Material desconocido: {name}; disponibles: {list(MATERIALS)}")


def register_material(mat: Material) -> None:
    """Registra un material adicional en el catálogo global."""
    MATERIALS[mat.name] = mat
