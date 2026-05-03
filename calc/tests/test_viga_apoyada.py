"""Validación analítica de Fase 2 — viga simplemente apoyada con carga uniforme.

Casos canónicos (Bernoulli-Euler):

    δ_centro = -5 q L⁴ / (384 E I)
    M_centro =  q L² / 8
    R_apoyo  =  q L / 2

Se verifica:
    1. Carga distribuida explícita aplicada vía `add_distributed_load`.
    2. Peso propio vía `loads.self_weight.apply_self_weight`.
    3. Subdivisión vía `Model.split_member` (necesaria para que el nodo
       central exista y se pueda leer su desplazamiento).
    4. Reparto de carga de servicio EN 12811-1 vía `apply_service_load`.

Para una viga prismática Euler-Bernoulli con vector de cargas consistente,
las soluciones nodales son exactas independientemente del número de
elementos. Con N=4 sub-barras el nodo central está disponible y la flecha
coincide con la analítica al nivel de redondeo numérico.
"""

from __future__ import annotations

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.loads import (
    GRAVITY,
    SERVICE_CLASSES,
    apply_self_weight,
    apply_service_load,
)
from calc.solver import solve


L_BEAM = 4.0
N_SUBDIV = 4


def _supports_simple_beam(m: Model) -> None:
    """Apoyo articulado en A + corredera vertical en C, dejando libre la
    flexión en plano XZ y la torsión sin cargar."""
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True)
    m.add_support("C", DY=True, DZ=True, RX=True)


def _build_simple_beam() -> tuple[Model, str]:
    """Devuelve (model, mid_node_id) — viga AC con N_SUBDIV sub-elementos."""
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0.0,    0.0, 0.0, id="A")
    m.add_node(L_BEAM, 0.0, 0.0, id="C")
    m.add_member("A", "C", CHS_48_3x3_2.name, S235JR.name, "ledger", id="V")
    m.split_member("V", N_SUBDIV)
    _supports_simple_beam(m)
    mid_id = m.find_node(L_BEAM / 2.0, 0.0, 0.0)
    assert mid_id is not None, "split_member no creó el nodo central"
    return m, mid_id


def _max_bending_moment(res) -> float:
    """Máximo |M_y| sobre todas las sub-barras."""
    return max(mr.moment_y_max for mr in res.members.values())


# ---------------------------------------------------------------------------
# Carga distribuida explícita
# ---------------------------------------------------------------------------

def test_uniform_load_deflection_and_moment():
    """δ = 5qL⁴/384EI y M = qL²/8 con carga uniforme aplicada manualmente."""
    w = 200.0     # N/m, descendente

    m, mid_id = _build_simple_beam()
    for sub_id in m.members:
        m.add_distributed_load(sub_id, "FZ", -w, -w)

    res = solve(m, check_statics=True)

    EI = S235JR.E * CHS_48_3x3_2.Iy
    delta_an = -5.0 * w * L_BEAM ** 4 / (384.0 * EI)
    delta_num = res.nodes[mid_id].DZ
    rel_err_d = abs(delta_num - delta_an) / abs(delta_an)
    assert rel_err_d < 5e-3, (
        f"Flecha en centro fuera de tolerancia: "
        f"analítico={delta_an:.6e} m, FEM={delta_num:.6e} m, error={rel_err_d:.2%}"
    )

    moment_an = w * L_BEAM ** 2 / 8.0
    moment_num = _max_bending_moment(res)
    rel_err_m = abs(moment_num - moment_an) / moment_an
    assert rel_err_m < 5e-3, (
        f"Momento máximo fuera de tolerancia: "
        f"analítico={moment_an:.3f} N·m, FEM={moment_num:.3f} N·m, error={rel_err_m:.2%}"
    )

    rxn_a = res.nodes["A"].RxnFZ
    rxn_c = res.nodes["C"].RxnFZ
    expected = w * L_BEAM / 2.0
    assert abs(rxn_a - expected) < 1e-3
    assert abs(rxn_c - expected) < 1e-3


# ---------------------------------------------------------------------------
# Peso propio
# ---------------------------------------------------------------------------

def test_self_weight_distributed_value():
    """`apply_self_weight` debe registrar w = ρ·A·g en cada barra."""
    m, _ = _build_simple_beam()
    n = apply_self_weight(m)

    expected_w = S235JR.rho * CHS_48_3x3_2.A * GRAVITY
    assert n == N_SUBDIV
    assert len(m.distributed_loads) == N_SUBDIV
    for dl in m.distributed_loads:
        assert dl.direction == "FZ"
        assert dl.w1 == pytest.approx(-expected_w, rel=1e-12)
        assert dl.w2 == pytest.approx(-expected_w, rel=1e-12)
        assert dl.case == "D"


def test_self_weight_simple_beam_matches_analytic():
    """La flecha de la viga apoyada bajo peso propio coincide con la
    fórmula analítica."""
    m, mid_id = _build_simple_beam()
    apply_self_weight(m)
    res = solve(m, check_statics=True)

    q = S235JR.rho * CHS_48_3x3_2.A * GRAVITY
    EI = S235JR.E * CHS_48_3x3_2.Iy
    delta_an = -5.0 * q * L_BEAM ** 4 / (384.0 * EI)
    delta_num = res.nodes[mid_id].DZ
    rel_err = abs(delta_num - delta_an) / abs(delta_an)
    assert rel_err < 5e-3, (
        f"Flecha bajo peso propio fuera de tolerancia: "
        f"analítico={delta_an:.6e} m, FEM={delta_num:.6e} m, error={rel_err:.2%}"
    )


# ---------------------------------------------------------------------------
# split_member: protección frente a doble subdivisión con cargas
# ---------------------------------------------------------------------------

def test_split_member_rejects_loaded_member():
    """Subdividir una barra ya cargada debe fallar para evitar ambigüedad
    en el remapeo de cargas."""
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(L_BEAM, 0, 0, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "ledger", id="V")
    m.add_distributed_load("V", "FZ", -100.0)

    with pytest.raises(ValueError, match="cargas distribuidas"):
        m.split_member("V", 4)


# ---------------------------------------------------------------------------
# Carga de servicio EN 12811-1
# ---------------------------------------------------------------------------

def test_service_load_distribution_two_ledgers():
    """Q3 sobre dos ledgers separados deck_width=0.61 m debe producir
    w = -q · b / 2 en cada uno."""
    deck_w = 0.61
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0,    0,      0, id="A")
    m.add_node(2.5,  0,      0, id="B")
    m.add_node(0,    deck_w, 0, id="C")
    m.add_node(2.5,  deck_w, 0, id="D")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LF")
    m.add_member("C", "D", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LB")

    n = apply_service_load(m, ["LF", "LB"], klass="Q3", deck_width=deck_w)
    expected_w = -SERVICE_CLASSES["Q3"] * deck_w / 2.0

    assert n == 2
    assert len(m.distributed_loads) == 2
    for dl in m.distributed_loads:
        assert dl.case == "L"
        assert dl.direction == "FZ"
        assert dl.w1 == pytest.approx(expected_w, rel=1e-12)


def test_service_load_unknown_class_raises():
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(1, 0, 0, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "ledger", id="L")
    with pytest.raises(ValueError, match="desconocida"):
        apply_service_load(m, ["L"], klass="Q9", deck_width=0.32)
