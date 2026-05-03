"""Validación de Fase 3 — viento EN 1991-1-4, imperfecciones EN 1993-1-1
y combinaciones EN 1990.

Comprobamos:
    1. Roughness factor c_r y turbulence intensity I_v contra fórmula explícita.
    2. q_p(z) contra cálculo manual.
    3. Clamp z < z_min de cat II.
    4. α_h con clamps inferior (h > 9 m) y superior (h < 4 m).
    5. α_m valores conocidos (m=1 → 1.0, m=2 → √0.75, m=4 → √0.625).
    6. apply_horizontal_imperfection: H_i = φ · V_i en cada nodo.
    7. apply_wind_load: w = c_f · q_p(z_mid) · D en una barra vertical.
    8. Combinaciones ULS Eq. 6.10 con factores correctos.
    9. Combinaciones SLS frecuente / casi-permanente con ψ correctos.
"""

from __future__ import annotations

import math

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.combinations import (
    GAMMA_G,
    GAMMA_Q,
    PSI_0,
    PSI_1,
    PSI_2,
    sls_characteristic,
    sls_frequent,
    sls_quasi_permanent,
    standard_combos,
    uls_eq_6_10,
)
from calc.loads.imperfections import (
    PHI_0,
    alpha_h,
    alpha_m,
    apply_horizontal_imperfection,
    imperfection_angle,
)
from calc.loads.wind import (
    RHO_AIR,
    SPAIN_BASIC_WIND,
    apply_wind_load,
    basic_velocity_pressure,
    peak_velocity_pressure,
    roughness_factor,
    turbulence_intensity,
)


# ---------------------------------------------------------------------------
# 1-3. Viento — magnitudes
# ---------------------------------------------------------------------------

def test_basic_velocity_pressure_spain_zone_a():
    q_b = basic_velocity_pressure(SPAIN_BASIC_WIND["A"])
    expected = 0.5 * RHO_AIR * 26.0 ** 2
    assert q_b == pytest.approx(expected)
    assert q_b == pytest.approx(422.5, rel=1e-9)


def test_roughness_and_turbulence_terrain_II_z10():
    """k_r = 0.19 (cat II = referencia), c_r(10) = 0.19·ln(200)."""
    z = 10.0
    c_r = roughness_factor(z, "II")
    expected = 0.19 * math.log(200.0)
    assert c_r == pytest.approx(expected, rel=1e-9)

    I_v = turbulence_intensity(z, "II")
    assert I_v == pytest.approx(1.0 / math.log(200.0), rel=1e-9)


def test_peak_velocity_pressure_terrain_II_z10_vb26():
    """q_p calculado a mano:
        c_r = 0.19·ln(200) ≈ 1.00668
        v_m = c_r · 26 ≈ 26.174
        I_v = 1/ln(200) ≈ 0.18874
        q_p = (1 + 7·I_v) · 0.5·1.25·v_m² ≈ 993.84 Pa
    """
    q_p = peak_velocity_pressure(10.0, terrain="II", v_b=26.0)
    c_r_e = 0.19 * math.log(200.0)
    v_m = c_r_e * 26.0
    I_v = 1.0 / math.log(200.0)
    expected = (1.0 + 7.0 * I_v) * 0.5 * RHO_AIR * v_m ** 2
    assert q_p == pytest.approx(expected, rel=1e-9)


def test_peak_velocity_pressure_clamps_below_zmin():
    """Cat II tiene z_min = 2 m: q_p(0.5) debe igualar q_p(2.0)."""
    q_low = peak_velocity_pressure(0.5, terrain="II", v_b=26.0)
    q_zmin = peak_velocity_pressure(2.0, terrain="II", v_b=26.0)
    assert q_low == pytest.approx(q_zmin, rel=1e-12)


def test_peak_velocity_pressure_unknown_terrain():
    with pytest.raises(ValueError, match="Terreno"):
        peak_velocity_pressure(10.0, terrain="V")


# ---------------------------------------------------------------------------
# 4-5. Imperfecciones — α_h, α_m
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("h, expected", [
    (4.0, 1.0),                # 2/√4 = 1.0 → clamp superior
    (9.0, 2.0 / 3.0),          # 2/√9 = 2/3 (justo en el límite)
    (10.0, 2.0 / 3.0),         # 2/√10 < 2/3 → clamp inferior
    (16.0, 2.0 / 3.0),         # 2/√16 = 0.5 < 2/3 → clamp inferior
    (5.0, 2.0 / math.sqrt(5)),  # entre límites
])
def test_alpha_h(h, expected):
    assert alpha_h(h) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("m, expected", [
    (1, 1.0),
    (2, math.sqrt(0.75)),
    (4, math.sqrt(0.625)),
    (10, math.sqrt(0.55)),
])
def test_alpha_m(m, expected):
    assert alpha_m(m) == pytest.approx(expected, rel=1e-12)


def test_imperfection_angle_combines_phi0_alpha_h_alpha_m():
    h, m = 10.0, 4
    phi = imperfection_angle(h, m)
    expected = PHI_0 * (2.0 / 3.0) * math.sqrt(0.625)
    assert phi == pytest.approx(expected, rel=1e-12)


def test_alpha_h_invalid_h():
    with pytest.raises(ValueError):
        alpha_h(0.0)
    with pytest.raises(ValueError):
        alpha_h(-3.0)


# ---------------------------------------------------------------------------
# 6. apply_horizontal_imperfection
# ---------------------------------------------------------------------------

def test_apply_horizontal_imperfection_adds_nodal_loads():
    """H_i = φ · V_i por cada nodo; nodal_load horizontal en el caso 'I'."""
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0.0, 0.0, 0.0, id="N1")
    m.add_node(1.0, 0.0, 0.0, id="N2")

    V1, V2 = 5000.0, 3000.0
    n, phi = apply_horizontal_imperfection(
        m, {"N1": V1, "N2": V2}, h=10.0, m=4, direction="FX",
    )
    assert n == 2
    assert phi == pytest.approx(PHI_0 * (2.0 / 3.0) * math.sqrt(0.625))
    assert len(m.nodal_loads) == 2

    by_node = {ld.node: ld for ld in m.nodal_loads}
    assert by_node["N1"].magnitude == pytest.approx(phi * V1)
    assert by_node["N2"].magnitude == pytest.approx(phi * V2)
    for ld in m.nodal_loads:
        assert ld.direction == "FX"
        assert ld.case == "I"


def test_apply_horizontal_imperfection_invalid_direction():
    m = Model()
    m.add_node(0, 0, 0, id="N")
    with pytest.raises(ValueError, match="direction"):
        apply_horizontal_imperfection(m, {"N": 1.0}, h=5.0, direction="FZ")


# ---------------------------------------------------------------------------
# 7. apply_wind_load — viga vertical
# ---------------------------------------------------------------------------

def test_apply_wind_load_uses_midpoint_z():
    """Una barra vertical de A=(0,0,0) a B=(0,0,4) debe recibir
    w = c_f · q_p(z_mid=2) · D."""
    D = 0.0483
    c_f = 1.3
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 4, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")

    n = apply_wind_load(
        m, ["P"], diameter=D, c_f=c_f, terrain="II", v_b=26.0,
    )
    assert n == 1
    assert len(m.distributed_loads) == 1
    dl = m.distributed_loads[0]
    q_mid = peak_velocity_pressure(2.0, terrain="II", v_b=26.0)
    expected_w = c_f * q_mid * D
    assert dl.w1 == pytest.approx(expected_w, rel=1e-9)
    assert dl.w2 == pytest.approx(expected_w, rel=1e-9)
    assert dl.direction == "FX"
    assert dl.case == "W"


def test_apply_wind_load_invalid_member():
    m = Model()
    with pytest.raises(ValueError, match="no existe"):
        apply_wind_load(m, ["XXX"], diameter=0.05)


def test_apply_wind_load_invalid_diameter():
    m = Model()
    with pytest.raises(ValueError, match="diameter"):
        apply_wind_load(m, [], diameter=0.0)


# ---------------------------------------------------------------------------
# 8-9. Combinaciones EN 1990
# ---------------------------------------------------------------------------

def test_uls_eq_6_10_default_factors():
    combos = uls_eq_6_10()
    assert set(combos) == {"ULS_LeadL", "ULS_LeadW", "ULS_Uplift"}

    leadL = combos["ULS_LeadL"]
    assert leadL["D"] == pytest.approx(GAMMA_G)
    assert leadL["L"] == pytest.approx(GAMMA_Q)
    assert leadL["W"] == pytest.approx(GAMMA_Q * PSI_0["W"])
    assert leadL["I"] == pytest.approx(GAMMA_G)

    leadW = combos["ULS_LeadW"]
    assert leadW["D"] == pytest.approx(GAMMA_G)
    assert leadW["L"] == pytest.approx(GAMMA_Q * PSI_0["L"])
    assert leadW["W"] == pytest.approx(GAMMA_Q)

    uplift = combos["ULS_Uplift"]
    assert uplift["D"] == pytest.approx(1.0)
    assert uplift["W"] == pytest.approx(GAMMA_Q)
    assert "L" not in uplift           # no contributes when uplift checks


def test_sls_characteristic_lead_L():
    combo = sls_characteristic(leading="L")["SLS_char_L"]
    assert combo == {"D": 1.0, "I": 1.0, "L": 1.0, "W": PSI_0["W"]}


def test_sls_frequent_lead_L():
    combo = sls_frequent(leading="L")["SLS_freq_L"]
    assert combo["D"] == 1.0
    assert combo["L"] == pytest.approx(PSI_1["L"])
    assert combo["W"] == pytest.approx(PSI_2["W"])


def test_sls_quasi_permanent():
    combo = sls_quasi_permanent()["SLS_quasi"]
    assert combo["D"] == 1.0
    assert combo["L"] == pytest.approx(PSI_2["L"])
    assert combo["W"] == pytest.approx(PSI_2["W"])


def test_standard_combos_includes_uls_and_sls():
    combos = standard_combos()
    expected = {
        "ULS_LeadL", "ULS_LeadW", "ULS_Uplift",
        "SLS_char_L", "SLS_freq_L", "SLS_quasi",
    }
    assert set(combos) == expected


# ---------------------------------------------------------------------------
# Integración: solver con combinación viento + imperfecciones
# ---------------------------------------------------------------------------

def test_solve_with_wind_imperfections_combo():
    """Test integración: poste empotrado en A, libre en B, con viento +
    imperfecciones. Verificar que la combinación ULS_LeadW factoriza
    correctamente cargas D (peso propio), W (viento) y I (imperfecciones).
    """
    from calc.loads import apply_self_weight, apply_wind_load
    from calc.solver import solve

    L = 4.0
    D = 0.0483

    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, L, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)

    apply_self_weight(m)                                               # case "D"
    apply_wind_load(m, ["P"], diameter=D, terrain="II", v_b=26.0)      # case "W"
    apply_horizontal_imperfection(m, {"B": 1000.0}, h=L)               # case "I"

    combos = uls_eq_6_10()
    res = solve(m, combos=combos, combo="ULS_LeadW", check_statics=False)

    # La reacción vertical debe ser γ_G · q_self · L (con γ_G=1.35)
    q_self = S235JR.rho * CHS_48_3x3_2.A * 9.81
    rxn_z = res.nodes["A"].RxnFZ
    expected_rxn = GAMMA_G * q_self * L      # peso propio mayorado
    assert rxn_z == pytest.approx(expected_rxn, rel=1e-3)

    # La reacción horizontal en X debe igualar γ_Q · w_wind · L + γ_G · H_imperf
    q_mid = peak_velocity_pressure(L / 2.0, terrain="II", v_b=26.0)
    w_wind = 1.3 * q_mid * D
    phi = imperfection_angle(L)
    H_imp = phi * 1000.0
    expected_h = GAMMA_Q * w_wind * L + GAMMA_G * H_imp
    rxn_x = res.nodes["A"].RxnFX
    # Convención: la reacción se opone a la carga aplicada (signo negativo
    # respecto al sentido del viento) — comparamos magnitudes.
    assert abs(rxn_x) == pytest.approx(expected_h, rel=5e-3)
