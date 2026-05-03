"""Validación analítica de Fase 1 — voladizo CHS Ø48,3×3,2 con carga puntual.

Caso canónico de viga en voladizo (Bernoulli-Euler):
    δ_z = -P · L³ / (3 · E · I)
    M_emp = P · L
    R_z   = P  (reacción vertical en empotramiento)

Una sola barra discretizada como un único elemento finito basta porque las
funciones de forma cúbicas de Hermite son exactas para flexión lineal sin
carga distribuida en el vano.

Geometría:
    L = 3.000 m
    P = 1000 N (vertical, hacia abajo, en el extremo libre)
    Material: S235JR (E = 210 GPa)
    Sección:  CHS Ø48,3 × 3,2 (I = 1.158·10⁻⁷ m⁴)

Valores esperados:
    δ_z   ≈ -3.694 · 10⁻⁴ m
    M_emp ≈ 3000 N·m
"""

from __future__ import annotations

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.solver import solve


@pytest.fixture
def cantilever_model() -> tuple[Model, float, float]:
    """Construye el voladizo y devuelve (model, L, P)."""
    L = 3.0
    P = 1000.0

    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0.0, 0.0, 0.0, id="A")
    m.add_node(L,   0.0, 0.0, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="M1")

    # Empotramiento perfecto en A
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    # Carga vertical descendente en el extremo libre
    m.add_nodal_load("B", direction="FZ", magnitude=-P, case="D")
    return m, L, P


def test_tip_deflection(cantilever_model):
    model, L, P = cantilever_model
    res = solve(model, check_statics=False)

    # δ_analytical = -P·L³/(3·E·I)
    EI = S235JR.E * CHS_48_3x3_2.Iy
    delta_an = -P * L ** 3 / (3.0 * EI)
    delta_num = res.nodes["B"].DZ

    rel_err = abs(delta_num - delta_an) / abs(delta_an)
    assert rel_err < 5e-3, (
        f"Desplazamiento del extremo fuera de tolerancia: "
        f"analítico={delta_an:.6e} m, FEM={delta_num:.6e} m, error={rel_err:.2%}"
    )


def test_fixed_end_moment(cantilever_model):
    model, L, P = cantilever_model
    res = solve(model, check_statics=False)

    # |M_y| en el empotramiento = P·L
    moment_an = P * L
    # La reacción de momento en A iguala el momento interno del empotramiento
    moment_num = abs(res.nodes["A"].RxnMY)

    rel_err = abs(moment_num - moment_an) / moment_an
    assert rel_err < 5e-3, (
        f"Momento en empotramiento fuera de tolerancia: "
        f"analítico={moment_an:.3f} N·m, FEM={moment_num:.3f} N·m, error={rel_err:.2%}"
    )

    # Y el máximo a lo largo de la barra debe ser igualmente PL
    moment_max = res.members["M1"].moment_y_max
    rel_err_mem = abs(moment_max - moment_an) / moment_an
    assert rel_err_mem < 5e-3


def test_vertical_reaction(cantilever_model):
    model, L, P = cantilever_model
    res = solve(model, check_statics=True)
    # Equilibrio vertical: la reacción en A iguala la carga aplicada en B
    rxn = res.nodes["A"].RxnFZ
    assert abs(rxn - P) < 1e-3, f"Reacción vertical incorrecta: {rxn}"


def test_no_extra_dof(cantilever_model):
    """Sólo δ_z y θ_y deberían ser no nulos en el extremo libre.
    Resto de DOFs ≈ 0 dentro de la precisión de máquina.
    """
    model, _L, _P = cantilever_model
    res = solve(model, check_statics=False)
    nB = res.nodes["B"]
    assert abs(nB.DX) < 1e-9
    assert abs(nB.DY) < 1e-9
    assert abs(nB.RX) < 1e-9
    assert abs(nB.RZ) < 1e-9
    # δ_z y θ_y no nulos
    assert abs(nB.DZ) > 1e-6
    assert abs(nB.RY) > 1e-6
