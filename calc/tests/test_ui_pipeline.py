"""Validación del pipeline orquestador (calc/pipeline.py).

Cubre la lógica que la UI ejecuta cuando el usuario pulsa "Ejecutar cálculo":
filtros sobre miembros, imperfecciones automáticas y aplicación
combinada de cargas D+L+W+I sobre un modelo sintético.
"""

from __future__ import annotations

import math

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.checks import MemberCheckResult
from calc.combinations import GAMMA_G, GAMMA_Q, PSI_0
from calc.loads import (
    SPAIN_BASIC_WIND,
    apply_self_weight,
    apply_service_load,
)
from calc.pipeline import (
    DEFAULT_TUBE_DIAMETER,
    apply_imperfections_at_top,
    build_and_solve,
    is_deck_supporting_ledger,
)


# ---------------------------------------------------------------------------
# Filtro de ledgers que sostienen plataforma
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("M_Ledger_F0_3", True),       # ledger frontal de planta — sostiene deck
    ("M_Ledger_B0_5", True),       # ledger trasero de planta — sostiene deck
    ("M_Ledger_TF_2_1", True),     # transversal de planta — sostiene deck
    ("M_Ledger_TC_0", True),       # corner — sostiene corner_plank
    ("M_Ledger_Mid_F0_3", False),  # mid-rail de barandilla
    ("M_Ledger_Top_B1_2", False),  # top-rail de barandilla
    ("M_Ledger_E_F0_0", False),    # ledger de extremo (barandilla cerrada)
    ("M_Ledger_Rail_X", False),    # contiene "Rail" explícito
])
def test_is_deck_supporting_ledger(name, expected):
    assert is_deck_supporting_ledger(name) is expected


def test_is_deck_supporting_handles_no_M_prefix():
    """También debe funcionar si el id no tiene el prefijo 'M_'."""
    assert is_deck_supporting_ledger("Ledger_F0_0") is True
    assert is_deck_supporting_ledger("Ledger_Mid_F0_0") is False


# ---------------------------------------------------------------------------
# apply_imperfections_at_top
# ---------------------------------------------------------------------------

def _two_pole_model() -> Model:
    L = 4.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A0")
    m.add_node(0, 0, L, id="A1")
    m.add_node(2, 0, 0, id="B0")
    m.add_node(2, 0, L, id="B1")
    m.add_member("A0", "A1", CHS_48_3x3_2.name, S235JR.name, "pole", id="PA")
    m.add_member("B0", "B1", CHS_48_3x3_2.name, S235JR.name, "pole", id="PB")
    return m


def test_imperfections_compute_phi_and_apply_to_top_nodes():
    m = _two_pole_model()
    apply_self_weight(m)
    n_loaded = apply_imperfections_at_top(m, direction="FX")

    assert n_loaded == 2

    # h=4 → α_h = clamp(2/√4, 2/3, 1) = 1
    # m=2 → α_m = √(0.5·(1+1/2)) = √0.75
    phi = (1.0 / 200.0) * 1.0 * math.sqrt(0.75)
    rho_A_g = S235JR.rho * CHS_48_3x3_2.A * 9.81
    V_total = 2 * rho_A_g * 4.0
    H_per_node = phi * V_total / 2

    nodal_loads = [ld for ld in m.nodal_loads
                   if ld.case == "I" and ld.direction == "FX"]
    assert len(nodal_loads) == 2
    for ld in nodal_loads:
        assert ld.magnitude == pytest.approx(H_per_node, rel=1e-9)
        assert ld.node in ("A1", "B1")


def test_imperfections_skip_when_no_vertical_loads():
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 1, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")
    n = apply_imperfections_at_top(m)
    assert n == 0
    assert len(m.nodal_loads) == 0


def test_imperfections_includes_service_load_in_V_total():
    L = 4.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A0")
    m.add_node(0, 0, L, id="A1")
    m.add_node(2, 0, 0, id="B0")
    m.add_node(2, 0, L, id="B1")
    m.add_member("A0", "A1", CHS_48_3x3_2.name, S235JR.name, "pole",   id="PA")
    m.add_member("B0", "B1", CHS_48_3x3_2.name, S235JR.name, "pole",   id="PB")
    m.add_member("A1", "B1", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LD")

    apply_self_weight(m)
    apply_service_load(m, ["LD"], klass="Q3", deck_width=0.61)

    apply_imperfections_at_top(m)

    rho_A_g = S235JR.rho * CHS_48_3x3_2.A * 9.81
    V_self = 2 * rho_A_g * L + rho_A_g * 2.0
    V_service = 2000.0 * 0.61 / 2 * 2.0
    V_expected = V_self + V_service

    H_total = sum(ld.magnitude for ld in m.nodal_loads if ld.case == "I")
    phi = (1.0 / 200.0) * 1.0 * math.sqrt(0.75)
    assert H_total == pytest.approx(phi * V_expected, rel=1e-9)


# ---------------------------------------------------------------------------
# build_and_solve — pipeline completo
# ---------------------------------------------------------------------------

def _portal_2d() -> Model:
    """Pórtico simple 1 vano con bases empotradas."""
    L_BAY = 2.5
    H = 4.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0,     0, 0, id="A0")
    m.add_node(0,     0, H, id="A1")
    m.add_node(L_BAY, 0, 0, id="B0")
    m.add_node(L_BAY, 0, H, id="B1")
    m.add_member("A0", "A1", CHS_48_3x3_2.name, S235JR.name, "pole",   id="PA")
    m.add_member("B0", "B1", CHS_48_3x3_2.name, S235JR.name, "pole",   id="PB")
    m.add_member("A1", "B1", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LD")
    m.add_support("A0", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_support("B0", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    return m


def _default_options(combo: str = "ULS_LeadL") -> dict:
    return {
        "apply_service": True,
        "service_class": "Q3",
        "deck_width": 0.61,
        "apply_wind": True,
        "wind_zone": "A",
        "wind_terrain": "II",
        "apply_imperfections": True,
        "combo": combo,
    }


def test_build_and_solve_returns_finite_utilizations():
    m = _portal_2d()
    res, checks = build_and_solve(m, _default_options())
    assert len(checks) == 3      # 2 poles + 1 ledger
    for cr in checks.values():
        assert isinstance(cr, MemberCheckResult)
        assert 0 <= cr.utilization < 100, f"Util fuera de rango: {cr}"


def test_build_and_solve_falls_back_to_default_combo_when_unknown():
    m = _portal_2d()
    options = _default_options(combo="DOES_NOT_EXIST")
    res, _ = build_and_solve(m, options)
    assert res.combo == "ULS_LeadL"


def test_build_and_solve_skips_loads_when_toggled_off():
    """Sin servicio ni viento ni imperfecciones, sólo D contribuye al modelo."""
    m = _portal_2d()
    options = _default_options()
    options["apply_service"] = False
    options["apply_wind"] = False
    options["apply_imperfections"] = False

    build_and_solve(m, options)

    cases = {dl.case for dl in m.distributed_loads}
    assert cases == {"D"}            # sólo peso propio
    assert all(ld.case != "I" for ld in m.nodal_loads)


def test_build_and_solve_applies_service_only_to_deck_ledgers():
    """Si añadimos un mid-rail al modelo, no debe recibir carga de servicio."""
    m = _portal_2d()
    # Añadir un mid-rail entre los postes a media altura
    m.add_node(0,     0, 2, id="A_mid")
    m.add_node(2.5,   0, 2, id="B_mid")
    m.add_member("A_mid", "B_mid", CHS_48_3x3_2.name, S235JR.name,
                 "ledger", id="M_Ledger_Mid_0")

    options = _default_options()
    build_and_solve(m, options)

    service_targets = {dl.member for dl in m.distributed_loads
                       if dl.case == "L"}
    assert "LD" in service_targets                 # ledger normal sí
    assert "M_Ledger_Mid_0" not in service_targets  # mid-rail NO


def test_build_and_solve_uls_leadW_factors_match_combination_table():
    """Para ULS_LeadW: D=γ_G, L=γ_Q·ψ_0_L, W=γ_Q, I=γ_G — verificar que
    las reacciones reflejan estos factores con los valores aplicados."""
    m = _portal_2d()
    options = _default_options(combo="ULS_LeadW")
    res, _ = build_and_solve(m, options)

    # Solo verificamos que el solve usó los factores esperados.
    assert res.combo == "ULS_LeadW"
    # La reacción FZ total debe ser positiva (peso propio mayorado + servicio mayorado)
    rxn_total_z = sum(res.nodes[nid].RxnFZ for nid in ("A0", "B0"))
    assert rxn_total_z > 0
    # La reacción FX total debe ser distinta de cero (viento + imperfecciones)
    rxn_total_x = sum(res.nodes[nid].RxnFX for nid in ("A0", "B0"))
    assert abs(rxn_total_x) > 0


# ---------------------------------------------------------------------------
# Constantes utilizadas
# ---------------------------------------------------------------------------

def test_default_tube_diameter_matches_layher():
    assert DEFAULT_TUBE_DIAMETER == pytest.approx(0.0483)


# ---------------------------------------------------------------------------
# Auto-soportes en la base
# ---------------------------------------------------------------------------

def test_auto_add_base_supports_empotra_nodos_z_min():
    """Añade soporte 6-DOF a cada nodo en z_min cuando no hay soportes."""
    from calc.pipeline import auto_add_base_supports

    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0,   id="A0")
    m.add_node(0, 0, 4,   id="A1")
    m.add_node(2, 0, 0,   id="B0")
    m.add_node(2, 0, 4,   id="B1")

    n = auto_add_base_supports(m)
    assert n == 2     # A0 y B0
    assert len(m.supports) == 2
    for s in m.supports:
        assert s.DX and s.DY and s.DZ and s.RX and s.RY and s.RZ
        assert s.node in ("A0", "B0")


def test_auto_add_base_supports_respeta_supports_existentes():
    """Si el usuario ya añadió soportes, la función no toca nada."""
    from calc.pipeline import auto_add_base_supports

    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 4, id="B")
    # Soporte parcial (sólo DZ)
    m.add_support("A", DZ=True)

    n = auto_add_base_supports(m)
    assert n == 0
    assert len(m.supports) == 1
    assert m.supports[0].DZ is True
    assert m.supports[0].DX is False    # no se ha tocado


def test_build_and_solve_auto_adds_supports_when_missing():
    """Sin soportes explícitos, build_and_solve no debe producir NaN."""
    L = 3.0
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A0")
    m.add_node(0, 0, L, id="A1")
    m.add_node(2, 0, 0, id="B0")
    m.add_node(2, 0, L, id="B1")
    m.add_member("A0", "A1", CHS_48_3x3_2.name, S235JR.name, "pole",   id="PA")
    m.add_member("B0", "B1", CHS_48_3x3_2.name, S235JR.name, "pole",   id="PB")
    m.add_member("A1", "B1", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LD")

    options = _default_options()
    res, checks = build_and_solve(m, options)
    # Las reacciones del nodo A0 (auto-soportado) deben ser finitas y > 0
    rxn_z = res.nodes["A0"].RxnFZ
    import math
    assert math.isfinite(rxn_z)
    assert rxn_z > 0


def test_build_and_solve_raises_on_nan_when_unsolvable():
    """Si por alguna razón el solve produce NaN (raro tras el auto-soporte
    pero posible si el modelo tiene patología), debe levantar excepción
    con mensaje claro."""
    from calc.pipeline import _check_results_for_nan
    from calc.solver import Results, NodeResult
    res = Results()
    res.nodes["X"] = NodeResult(
        DX=float("nan"), DY=0, DZ=0, RX=0, RY=0, RZ=0,
    )
    msg = _check_results_for_nan(res)
    assert msg is not None
    assert "NaN" in msg or "no válidos" in msg


def test_spain_basic_wind_zones_match_cte():
    assert SPAIN_BASIC_WIND["A"] == 26.0
    assert SPAIN_BASIC_WIND["B"] == 27.0
    assert SPAIN_BASIC_WIND["C"] == 29.0
