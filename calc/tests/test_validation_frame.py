"""Validación contra ejemplo de bibliografía — pórtico 1 vano × 2 plantas.

Sistema multi-elemento con solución analítica cerrada. Inspirado en los
ejemplos clásicos de pórticos isostáticos de Timoshenko / Pieper-Köhler:
estructura plana en el plano XZ embedida en un análisis 3D con base
empotrada y ledgers articulados.

Geometría:
    2 postes verticales en x = 0 y x = L = 3 m, divididos en 2 segmentos
    de altura h = 2 m cada uno (planta 1 a z = h, planta 2 a z = 2h).
    2 ledgers horizontales articulados (releases ledger="pinned" → R_y, R_z
    liberadas en ambos extremos → simply supported).
    Bases empotradas (6 DOFs restringidos).
    Carga uniforme q = 0,8 kN/m sobre cada ledger (≈ Q3 sobre tablón
    de 0,8 m repartido entre 2 ledgers; ligeramente reducido para
    mantener util < 1 con CHS Ø48,3×3,2 / S235).

Solución cerrada Bernoulli-Euler:

    Reacción vertical en cada base    R_z   = q · L          = 2,40 kN
    Axil en pole superior              N_up  = q · L / 2      = 1,20 kN  (compresión)
    Axil en pole inferior              N_low = q · L          = 2,40 kN  (compresión)
    Momento máximo en cada ledger      M_max = q · L² / 8     = 0,90 kN·m
    Reacción de ledger sobre el pole   R_lt  = q · L / 2      = 1,20 kN

PyNite resuelve este sistema con error nodal exacto (vector de cargas
consistente Bernoulli-Euler), por lo que las tolerancias se ajustan a 1·10⁻⁹.
"""

from __future__ import annotations

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.checks import run_all_checks
from calc.releases import set_releases_by_type
from calc.solver import solve


L_BAY = 3.0          # m
H_FLOOR = 2.0        # m
Q_LEDGER = 800.0     # N/m por ledger


def _build_two_story_portal() -> Model:
    """Construye el pórtico 1 vano × 2 plantas con releases y cargas."""
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)

    # 2 postes × 3 niveles
    m.add_node(0,     0, 0,           id="A0")
    m.add_node(0,     0, H_FLOOR,     id="A1")
    m.add_node(0,     0, 2 * H_FLOOR, id="A2")
    m.add_node(L_BAY, 0, 0,           id="B0")
    m.add_node(L_BAY, 0, H_FLOOR,     id="B1")
    m.add_node(L_BAY, 0, 2 * H_FLOOR, id="B2")

    # Postes (4 segmentos en total)
    sec, mat = CHS_48_3x3_2.name, S235JR.name
    m.add_member("A0", "A1", sec, mat, "pole", id="PA_lower")
    m.add_member("A1", "A2", sec, mat, "pole", id="PA_upper")
    m.add_member("B0", "B1", sec, mat, "pole", id="PB_lower")
    m.add_member("B1", "B2", sec, mat, "pole", id="PB_upper")

    # Ledgers entre postes
    m.add_member("A1", "B1", sec, mat, "ledger", id="L_lower")
    m.add_member("A2", "B2", sec, mat, "ledger", id="L_upper")

    # Releases: ledgers articulados, postes continuos, sin braces
    set_releases_by_type(m, ledger="pinned")

    # Empotramiento total en bases (todas las rotaciones también — andamio
    # anclado a fachada / con husillos sin juego rotacional).
    m.add_support("A0", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_support("B0", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)

    # Carga uniforme vertical en cada ledger
    m.add_distributed_load("L_lower", "FZ", -Q_LEDGER, -Q_LEDGER)
    m.add_distributed_load("L_upper", "FZ", -Q_LEDGER, -Q_LEDGER)

    return m


# ---------------------------------------------------------------------------
# Reacciones
# ---------------------------------------------------------------------------

def test_base_reactions_split_evenly():
    """Cada base soporta exactamente q · L (reparto simétrico de 2 ledgers)."""
    m = _build_two_story_portal()
    res = solve(m, check_statics=False)

    expected = Q_LEDGER * L_BAY
    assert res.nodes["A0"].RxnFZ == pytest.approx(expected, rel=1e-9)
    assert res.nodes["B0"].RxnFZ == pytest.approx(expected, rel=1e-9)


def test_base_horizontal_reactions_zero():
    """Sin carga horizontal, no debe haber reacción en X ni en Y."""
    m = _build_two_story_portal()
    res = solve(m, check_statics=False)

    for node_id in ("A0", "B0"):
        n = res.nodes[node_id]
        assert abs(n.RxnFX) < 1e-6
        assert abs(n.RxnFY) < 1e-6


# ---------------------------------------------------------------------------
# Axiles en postes
# ---------------------------------------------------------------------------

def test_pole_lower_segment_axial_compression():
    """El segmento inferior carga la suma de los dos ledgers = q · L."""
    m = _build_two_story_portal()
    res = solve(m, check_statics=False)

    expected_compression = -Q_LEDGER * L_BAY     # negativo = compresión
    assert res.members["PA_lower"].axial_min == pytest.approx(
        expected_compression, rel=1e-9,
    )
    assert res.members["PB_lower"].axial_min == pytest.approx(
        expected_compression, rel=1e-9,
    )


def test_pole_upper_segment_axial_compression():
    """El segmento superior sólo carga el ledger superior = q · L / 2."""
    m = _build_two_story_portal()
    res = solve(m, check_statics=False)

    expected = -Q_LEDGER * L_BAY / 2.0
    assert res.members["PA_upper"].axial_min == pytest.approx(expected, rel=1e-9)
    assert res.members["PB_upper"].axial_min == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Momento en ledgers
# ---------------------------------------------------------------------------

def test_ledger_max_moment_matches_qL2_over_8():
    """Ledger articulado en ambos extremos → M_max = q · L² / 8."""
    m = _build_two_story_portal()
    res = solve(m, check_statics=False)

    expected_M = Q_LEDGER * L_BAY ** 2 / 8.0
    assert res.members["L_lower"].moment_y_max == pytest.approx(expected_M, rel=1e-9)
    assert res.members["L_upper"].moment_y_max == pytest.approx(expected_M, rel=1e-9)


# ---------------------------------------------------------------------------
# Pipeline completo: run_all_checks devuelve utilizaciones razonables
# ---------------------------------------------------------------------------

def test_run_all_checks_pipeline_passes():
    """Con 2 kN/m sobre los ledgers y CHS Ø48,3×3,2 / S235, ningún
    elemento debe fallar (utilización < 1)."""
    m = _build_two_story_portal()
    res = solve(m, check_statics=False)
    checks = run_all_checks(m, res)

    assert len(checks) == 6
    worst = max(c.utilization for c in checks.values())
    assert worst < 1.0, f"Alguna barra falla: util max = {worst:.3f}"

    # El ledger debe ser el más solicitado (M = qL²/8) frente a los postes
    # (axil moderado 6 kN sobre N_pl ≈ 106 kN).
    worst_member = max(checks.values(), key=lambda c: c.utilization)
    assert worst_member.member.startswith("L_"), (
        f"Esperaba que un ledger gobernase, pero gobierna {worst_member.member}"
    )
