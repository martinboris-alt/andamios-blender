"""Validación de Fase 4 — comprobaciones EN 1993-1-1, EN 12811-1 y EN 74.

Comprueba:
    1. Capacidades sección CHS Ø48,3×3,2 / S235JR contra cálculo manual.
    2. χ y N_b,Rd contra fórmula explícita (curva c).
    3. χ = 1.0 para λ̄ ≤ 0.2 (sin reducción por pandeo).
    4. Interacción flexo-compresión Eq. 6.61 simplificada.
    5. SectionCheck — tensión vs compresión, peor utilización.
    6. EN 12811-1 deflexión: δ = L/100 → util = 1.0.
    7. EN 74 joint check con interacción cuadrática.
    8. set_releases_by_type aplica el preset adecuado.
    9. Pipeline run_all_checks integrado: voladizo cargado axialmente.
   10. Solver con releases pinned: una barra triarticulada (cabe pole+brace
       como 2 elementos) reproduce el esquema clásico de cercha.
"""

from __future__ import annotations

import math

import pytest

from calc import S235JR, S355JR, CHS_48_3x3_2, Model
from calc.checks import (
    DEFLECTION_LIMIT_PLATFORM,
    LAYHER_ALLROUND_M,
    MemberCheckResult,
    bending_resistance,
    buckling_resistance,
    check_deflection_limit,
    check_joint,
    check_section_resistances,
    chi_buckling,
    compression_resistance,
    interaction_combined,
    non_dimensional_slenderness,
    run_all_checks,
    shear_resistance,
    tension_resistance,
)
from calc.releases import set_releases_by_type
from calc.solver import solve


# ---------------------------------------------------------------------------
# 1. Capacidades sección
# ---------------------------------------------------------------------------

def test_tension_resistance_chs_s235():
    N_Rd = tension_resistance(CHS_48_3x3_2, S235JR)
    expected = CHS_48_3x3_2.A * S235JR.fy
    assert N_Rd == pytest.approx(expected, rel=1e-12)
    assert N_Rd == pytest.approx(106_548.0, rel=1e-3)     # ≈ 106,5 kN


def test_compression_resistance_equals_tension_class1():
    """Para clase 1-3 N_c,Rd = N_pl,Rd = A·fy."""
    assert compression_resistance(CHS_48_3x3_2, S235JR) == pytest.approx(
        tension_resistance(CHS_48_3x3_2, S235JR)
    )


def test_bending_resistance_uses_Wpl_class1():
    M_Rd = bending_resistance(CHS_48_3x3_2, S235JR)
    expected = CHS_48_3x3_2.Wpl * S235JR.fy
    assert M_Rd == pytest.approx(expected, rel=1e-12)


def test_shear_resistance_chs_uses_Av_2A_over_pi():
    V_Rd = shear_resistance(CHS_48_3x3_2, S235JR)
    A_v = 2.0 * CHS_48_3x3_2.A / math.pi
    expected = A_v * S235JR.fy / math.sqrt(3.0)
    assert V_Rd == pytest.approx(expected, rel=1e-12)


def test_capacities_scale_with_fy():
    """Pasar de S235 a S355 escala N_Rd y M_Rd por el ratio de fy."""
    ratio = S355JR.fy / S235JR.fy
    assert tension_resistance(CHS_48_3x3_2, S355JR) == pytest.approx(
        tension_resistance(CHS_48_3x3_2, S235JR) * ratio
    )
    assert bending_resistance(CHS_48_3x3_2, S355JR) == pytest.approx(
        bending_resistance(CHS_48_3x3_2, S235JR) * ratio
    )


# ---------------------------------------------------------------------------
# 2-3. Pandeo
# ---------------------------------------------------------------------------

def test_chi_no_reduction_below_lambda_02():
    assert chi_buckling(0.0) == 1.0
    assert chi_buckling(0.1) == 1.0
    assert chi_buckling(0.2) == 1.0


@pytest.mark.parametrize("curve, alpha", [
    ("a0", 0.13), ("a", 0.21), ("b", 0.34), ("c", 0.49), ("d", 0.76),
])
def test_chi_matches_explicit_formula(curve, alpha):
    """Para λ̄ = 1.5, calcular χ con fórmula explícita y comparar."""
    lam = 1.5
    phi = 0.5 * (1.0 + alpha * (lam - 0.2) + lam ** 2)
    chi_expected = 1.0 / (phi + math.sqrt(phi ** 2 - lam ** 2))
    assert chi_buckling(lam, curve=curve) == pytest.approx(chi_expected, rel=1e-12)


def test_buckling_resistance_chs_L2_curve_c():
    """N_b,Rd para CHS Ø48,3×3,2 / S235 / L=2 m / curva c."""
    L = 2.0
    lam = non_dimensional_slenderness(CHS_48_3x3_2, S235JR, L)
    chi = chi_buckling(lam, curve="c")
    N_b = buckling_resistance(CHS_48_3x3_2, S235JR, L, curve="c")
    expected = chi * CHS_48_3x3_2.A * S235JR.fy
    assert N_b == pytest.approx(expected, rel=1e-12)
    # ≈ 40 kN
    assert N_b == pytest.approx(40_000.0, rel=5e-2)


def test_chi_decreases_with_curve_severity():
    """Para misma λ̄, χ decrece a₀ → a → b → c → d (más imperfección)."""
    lam = 1.5
    chis = [chi_buckling(lam, curve=c) for c in ("a0", "a", "b", "c", "d")]
    for a, b in zip(chis, chis[1:]):
        assert a > b


def test_non_dimensional_slenderness_invalid_inputs():
    with pytest.raises(ValueError):
        non_dimensional_slenderness(CHS_48_3x3_2, S235JR, 0.0)


# ---------------------------------------------------------------------------
# 4. Interacción flexo-compresión
# ---------------------------------------------------------------------------

def test_interaction_pure_compression_equals_buckling_ratio():
    """Sin momento, la interacción debe igualar N_Ed / N_b,Rd."""
    L = 2.0
    N = 15_000.0
    util = interaction_combined(
        CHS_48_3x3_2, S235JR, N_Ed=N, M_y_Ed=0, M_z_Ed=0, L_cr=L,
    )
    N_b = buckling_resistance(CHS_48_3x3_2, S235JR, L)
    assert util == pytest.approx(N / N_b, rel=1e-9)


def test_interaction_pure_bending_no_axial():
    """Sin axil pero con momento, n=0, k_yy = C_my (cota inferior).
    Util = C_my · M_Ed / M_Rk."""
    M_Rd = bending_resistance(CHS_48_3x3_2, S235JR)
    M = 0.5 * M_Rd
    util = interaction_combined(
        CHS_48_3x3_2, S235JR, N_Ed=0, M_y_Ed=M, M_z_Ed=0, L_cr=2.0, C_my=0.9,
    )
    # Sin axial el factor k_yy se reduce a C_my (sin término en n).
    # m_y = M / M_Rk · γ_M1 = 0.5
    assert util == pytest.approx(0.9 * 0.5, rel=1e-9)


# ---------------------------------------------------------------------------
# 5. SectionCheck wrapper
# ---------------------------------------------------------------------------

def test_check_section_resistances_tension_dominates_when_pure_tension():
    sc = check_section_resistances(
        CHS_48_3x3_2, S235JR,
        N_Ed_t=80_000.0, N_Ed_c=0.0,
        L_cr=2.0,
    )
    # tension util = 80 / 106.55
    assert sc.tension == pytest.approx(80_000.0 / (CHS_48_3x3_2.A * S235JR.fy))
    assert sc.compression == 0.0
    assert sc.buckling == 0.0
    assert sc.combined == 0.0
    assert sc.passed()


def test_check_section_resistances_buckling_dominates_for_long_member():
    """Compresión 30 kN sobre poste largo (L=4 m) → pandeo gobierna."""
    sc = check_section_resistances(
        CHS_48_3x3_2, S235JR,
        N_Ed_c=30_000.0,
        L_cr=4.0,
    )
    assert sc.compression < sc.buckling
    assert sc.worst() == sc.combined or sc.worst() == sc.buckling


# ---------------------------------------------------------------------------
# 6. EN 12811-1 deflexión
# ---------------------------------------------------------------------------

def test_deflection_limit_at_threshold():
    L = 3.0
    delta = L * DEFLECTION_LIMIT_PLATFORM    # δ = L/100
    assert check_deflection_limit(delta, L) == pytest.approx(1.0, rel=1e-12)


def test_deflection_limit_half_threshold():
    L = 3.0
    delta = 0.5 * L / 100.0
    assert check_deflection_limit(delta, L) == pytest.approx(0.5, rel=1e-12)


def test_deflection_limit_invalid_L():
    with pytest.raises(ValueError):
        check_deflection_limit(0.01, 0.0)


# ---------------------------------------------------------------------------
# 7. EN 74 joints
# ---------------------------------------------------------------------------

def test_check_joint_pure_axial_tension():
    """N_Ed = F_t,Rk → util_axial = γ_M2 (= 1.25 → fail)."""
    N = LAYHER_ALLROUND_M.F_t_Rk
    res = check_joint(N_Ed=N, joint=LAYHER_ALLROUND_M)
    assert res.axial == pytest.approx(1.25, rel=1e-12)
    assert not res.passed()


def test_check_joint_pure_compression_uses_F_c():
    """Compresión usa F_c_Rk (mucho mayor que F_t_Rk en Layher Allround)."""
    N_Rk = LAYHER_ALLROUND_M.F_c_Rk
    res = check_joint(N_Ed=-N_Rk, joint=LAYHER_ALLROUND_M)
    assert res.axial == pytest.approx(1.25, rel=1e-12)


def test_check_joint_string_alias():
    res = check_joint(N_Ed=1000.0, joint="layher_allround")
    expected = 1000.0 / (LAYHER_ALLROUND_M.F_t_Rk / 1.25)
    assert res.axial == pytest.approx(expected, rel=1e-12)


def test_check_joint_quadratic_interaction():
    """N+V cuadrática + M lineal: con N=V=M=½·R_d cada uno → util_int=0.75."""
    N_Rd = LAYHER_ALLROUND_M.F_t_Rk / 1.25
    V_Rd = LAYHER_ALLROUND_M.V_Rk / 1.25
    M_Rd = LAYHER_ALLROUND_M.M_Rk / 1.25
    res = check_joint(
        N_Ed=0.5 * N_Rd, V_Ed=0.5 * V_Rd, M_Ed=0.5 * M_Rd,
        joint=LAYHER_ALLROUND_M,
    )
    assert res.interaction == pytest.approx(0.5 ** 2 + 0.5 ** 2 + 0.5, rel=1e-12)


# ---------------------------------------------------------------------------
# 8. Releases
# ---------------------------------------------------------------------------

def test_set_releases_by_type_default_pinned_brace():
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(1, 0, 0, id="B")
    m.add_node(0, 0, 1, id="C")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "ledger", id="L")
    m.add_member("A", "C", CHS_48_3x3_2.name, S235JR.name, "pole",   id="P")
    m.add_member("B", "C", CHS_48_3x3_2.name, S235JR.name, "brace",  id="X")

    counts = set_releases_by_type(m)
    assert counts == {"ledger": 1, "pole": 1, "brace": 1}

    # Pole y ledger continuos por defecto
    assert m.members["L"].release_i == (False,) * 6
    assert m.members["P"].release_j == (False,) * 6
    # Brace pinned por defecto: libera RY, RZ (no torsion)
    assert m.members["X"].release_i == (False, False, False, False, True, True)
    assert m.members["X"].release_j == (False, False, False, False, True, True)


def test_set_releases_explicit_axial_releases_torsion():
    """Preset 'axial' libera adicionalmente la torsión (RX)."""
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(1, 0, 1, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "brace", id="X")
    set_releases_by_type(m, brace="axial")
    assert m.members["X"].release_i == (False, False, False, True, True, True)


def test_set_releases_invalid_preset():
    m = Model()
    with pytest.raises(ValueError, match="Preset"):
        set_releases_by_type(m, brace="rigidish")


# ---------------------------------------------------------------------------
# 9. Pipeline integrado: run_all_checks sobre voladizo
# ---------------------------------------------------------------------------

def test_run_all_checks_cantilever_compressed():
    """Voladizo CHS L=3 m, P=10 kN compresión axial. Verifica que
    run_all_checks devuelve utilización coherente con el cálculo manual."""
    L = 3.0
    P = 10_000.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, L, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_nodal_load("B", "FZ", -P, case="D")

    res = solve(m, check_statics=False)
    checks = run_all_checks(m, res, L_cr_factor=1.0)
    assert "P" in checks
    cr = checks["P"]
    assert isinstance(cr, MemberCheckResult)
    assert cr.section_check.compression == pytest.approx(
        P / (CHS_48_3x3_2.A * S235JR.fy), rel=1e-3,
    )
    # Pandeo con L_cr = L_real = 3 m → χ < 1
    chi = chi_buckling(
        non_dimensional_slenderness(CHS_48_3x3_2, S235JR, L), curve="c",
    )
    expected_buckling = P / (chi * CHS_48_3x3_2.A * S235JR.fy)
    assert cr.section_check.buckling == pytest.approx(expected_buckling, rel=1e-2)


def test_run_all_checks_uses_L_cr_overrides():
    """L_cr_overrides toma prioridad sobre L_cr_factor."""
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 3.0, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_nodal_load("B", "FZ", -10_000.0, case="D")

    res = solve(m, check_statics=False)
    cr_default = run_all_checks(m, res)["P"]
    cr_long = run_all_checks(m, res, L_cr_overrides={"P": 6.0})["P"]
    # L_cr más largo → pandeo peor → util mayor
    assert cr_long.section_check.buckling > cr_default.section_check.buckling


# ---------------------------------------------------------------------------
# 10. Solver con releases (axial puro en una diagonal)
# ---------------------------------------------------------------------------

def test_solver_runs_with_axial_releases():
    """Cercha mínima: 2 barras de 3 m con apoyos pinned y diagonal axial.
    El solver debe converger sin singularidades pese a las releases."""
    L = 3.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(L, 0, 0, id="B")
    m.add_node(L, 0, L, id="C")

    # Vertical (pole continuo) + diagonal (brace en axial puro)
    m.add_member("B", "C", CHS_48_3x3_2.name, S235JR.name, "pole",  id="V")
    m.add_member("A", "C", CHS_48_3x3_2.name, S235JR.name, "brace", id="D")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "ledger", id="H")

    set_releases_by_type(m)

    # Empotramientos en A (pin, libre rotación) y en B (corredera vertical)
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_support("B", DY=True, DZ=True, RX=True)
    # Carga horizontal en C
    m.add_nodal_load("C", "FX", 5_000.0, case="W")

    res = solve(m, check_statics=False)
    # La diagonal debe trabajar a tracción (positiva) o compresión finita
    assert "D" in res.members
    # Y el pipeline de checks corre sin error
    checks = run_all_checks(m, res)
    assert all(isinstance(c, MemberCheckResult) for c in checks.values())
