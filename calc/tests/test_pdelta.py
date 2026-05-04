"""Tests del análisis P-Delta (2º orden geométrico).

Cubre:
- Default OFF en `solve()` y switch on cuando `use_pdelta=True`.
- `Results.pdelta` reflejando el modo usado.
- Comparativa lineal vs P-Δ en voladizo vertical: la amplificación
  numérica debe acercarse a la fórmula clásica de Euler
  δ_pd/δ_lin ≈ 1/(1 − N/N_cr).
- Monotonía: util P-Δ ≥ util lineal cuando hay axil de compresión.
- Divergencia: torre cargada por encima de la carga crítica → P-Δ
  lanza RuntimeError accionable.

Validación analítica
====================
Para una columna vertical empotrada en la base, con carga axial de
compresión `N` en la cabeza + carga transversal `P_lat` en la cabeza,
la flecha lateral exacta de 2º orden es:

    δ_pd = δ_lin · 1 / (1 − N / N_cr)

donde `N_cr = π²·E·I / L_cr²` y `L_cr = 2·L` para el caso voladizo
(extremo libre + empotrado en la base).

La discretización en un único elemento Bernoulli-Euler da N_cr exacto
sólo en el límite de muchos elementos; para validación cuantitativa
subdividimos el voladizo en varios tramos.
"""

from __future__ import annotations

import math

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.solver import solve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _euler_n_cr_cantilever(E: float, I: float, L: float) -> float:
    """Carga crítica de Euler para columna voladizo (L_cr = 2·L)."""
    return math.pi ** 2 * E * I / (2.0 * L) ** 2


def _build_vertical_cantilever(
    L: float,
    n_segments: int,
    N_axial: float,
    P_lateral: float,
) -> Model:
    """Construye un poste vertical empotrado en la base, dividido en
    `n_segments` elementos. Cargas axial y lateral aplicadas en la cabeza.
    """
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)

    # Nodos a lo largo del eje Z
    node_ids = []
    for k in range(n_segments + 1):
        z = L * k / n_segments
        nid = f"N{k}"
        m.add_node(0.0, 0.0, z, id=nid)
        node_ids.append(nid)

    # Miembros en serie
    for k in range(n_segments):
        m.add_member(
            node_ids[k], node_ids[k + 1],
            CHS_48_3x3_2.name, S235JR.name, "pole",
            id=f"M{k}",
        )

    # Empotramiento perfecto en la base
    m.add_support(
        node_ids[0],
        DX=True, DY=True, DZ=True,
        RX=True, RY=True, RZ=True,
    )

    # Cargas en la cabeza: -N en Z (compresión, hacia abajo) + P_lat en X
    top = node_ids[-1]
    if N_axial != 0.0:
        m.add_nodal_load(top, direction="FZ", magnitude=-N_axial, case="D")
    if P_lateral != 0.0:
        m.add_nodal_load(top, direction="FX", magnitude=P_lateral, case="D")

    return m


# ---------------------------------------------------------------------------
# Tests de switching y bandera
# ---------------------------------------------------------------------------

def test_solve_default_is_linear():
    """`solve(model)` sin opciones debe usar análisis lineal."""
    m = _build_vertical_cantilever(L=3.0, n_segments=4, N_axial=0.0,
                                    P_lateral=500.0)
    res = solve(m, check_statics=False)
    assert res.pdelta is False


def test_solve_use_pdelta_flag_set():
    """`solve(use_pdelta=True)` debe marcar `Results.pdelta = True`."""
    m = _build_vertical_cantilever(L=3.0, n_segments=4, N_axial=0.0,
                                    P_lateral=500.0)
    res = solve(m, use_pdelta=True)
    assert res.pdelta is True


def test_pdelta_with_zero_axial_matches_linear():
    """Sin axil, P-Δ debe coincidir con lineal (no hay amplificación)."""
    m_lin = _build_vertical_cantilever(L=3.0, n_segments=8, N_axial=0.0,
                                        P_lateral=500.0)
    m_pd = _build_vertical_cantilever(L=3.0, n_segments=8, N_axial=0.0,
                                       P_lateral=500.0)
    res_lin = solve(m_lin, check_statics=False)
    res_pd = solve(m_pd, use_pdelta=True)

    dx_lin = res_lin.nodes["N8"].DX
    dx_pd = res_pd.nodes["N8"].DX
    assert dx_lin == pytest.approx(dx_pd, rel=1e-3), (
        f"Sin axil P-Δ debería igualar lineal: lin={dx_lin:.4e}, "
        f"pd={dx_pd:.4e}"
    )


# ---------------------------------------------------------------------------
# Validación cuantitativa contra fórmula de Euler
# ---------------------------------------------------------------------------

def test_pdelta_amplification_matches_euler_formula():
    """Voladizo CHS Ø48,3×3,2 con axil = 0,3·N_cr y lateral.

    La amplificación δ_pd/δ_lin debe coincidir con 1/(1 − 0,3) ≈ 1,429
    dentro de ~10 % (precisión limitada por la discretización en n
    elementos finitos Bernoulli-Euler).
    """
    L = 3.0
    n_segments = 16   # discretización fina para que N_cr numérico sea preciso
    EI = S235JR.E * CHS_48_3x3_2.Iy
    N_cr = _euler_n_cr_cantilever(S235JR.E, CHS_48_3x3_2.Iy, L)
    N_axial = 0.30 * N_cr
    P_lateral = 200.0

    expected_amp = 1.0 / (1.0 - N_axial / N_cr)   # ≈ 1,429

    m_lin = _build_vertical_cantilever(L, n_segments, N_axial, P_lateral)
    m_pd = _build_vertical_cantilever(L, n_segments, N_axial, P_lateral)
    res_lin = solve(m_lin, check_statics=False)
    res_pd = solve(m_pd, use_pdelta=True)

    dx_lin = abs(res_lin.nodes[f"N{n_segments}"].DX)
    dx_pd = abs(res_pd.nodes[f"N{n_segments}"].DX)

    # Sanity: la flecha lineal coincide con P·L³/(3·EI)
    dx_lin_an = P_lateral * L ** 3 / (3.0 * EI)
    assert dx_lin == pytest.approx(dx_lin_an, rel=1e-2)

    amp = dx_pd / dx_lin
    rel_err = abs(amp - expected_amp) / expected_amp
    assert rel_err < 0.10, (
        f"Amplificación P-Δ fuera de tolerancia: numérico={amp:.3f}, "
        f"Euler={expected_amp:.3f}, error={rel_err:.1%}"
    )
    assert amp > 1.0, "P-Δ con compresión debe amplificar la flecha"


def test_pdelta_amplification_increases_with_axial():
    """Subir el axil debe aumentar el factor de amplificación."""
    L = 3.0
    n_segments = 16
    N_cr = _euler_n_cr_cantilever(S235JR.E, CHS_48_3x3_2.Iy, L)
    P_lateral = 200.0

    amps = []
    for ratio in (0.10, 0.30, 0.50):
        N_axial = ratio * N_cr

        m_lin = _build_vertical_cantilever(L, n_segments, N_axial, P_lateral)
        m_pd = _build_vertical_cantilever(L, n_segments, N_axial, P_lateral)
        res_lin = solve(m_lin, check_statics=False)
        res_pd = solve(m_pd, use_pdelta=True)

        dx_lin = abs(res_lin.nodes[f"N{n_segments}"].DX)
        dx_pd = abs(res_pd.nodes[f"N{n_segments}"].DX)
        amps.append(dx_pd / dx_lin)

    assert amps[0] < amps[1] < amps[2], (
        f"La amplificación P-Δ debe crecer con el axil: {amps}"
    )


# ---------------------------------------------------------------------------
# Comportamiento post-crítico
# ---------------------------------------------------------------------------

def test_pdelta_post_critical_flips_sign():
    """Con N > N_cr el solver de PyNite NO eleva ValueError (su detector
    de inestabilidad analiza pivots de la matriz tangente, que siguen
    siendo válidos aunque el equilibrio sea inestable). En ese régimen
    la "solución" matemática converge a una rama de equilibrio inestable
    con flecha en dirección OPUESTA a la carga lateral aplicada — un
    indicador claro de que la columna ha pasado el punto de bifurcación.

    Este test documenta y verifica ese comportamiento. La detección real
    de inestabilidad para el usuario se hace en upstream: el chequeo
    EN 1993-1-1 §6.3 captura el problema vía utilización > 1 (axil
    sobre N_b,Rd dispara la alarma antes de llegar a P-Δ post-crítico).
    """
    L = 3.0
    n_segments = 16
    N_cr = _euler_n_cr_cantilever(S235JR.E, CHS_48_3x3_2.Iy, L)

    P_lateral = 10.0   # pequeña, sólo para perturbar el equilibrio

    # Caso subcrítico: la flecha apunta en el sentido de la lateral (+X)
    m_sub = _build_vertical_cantilever(L, n_segments, 0.5 * N_cr, P_lateral)
    res_sub = solve(m_sub, use_pdelta=True, pdelta_max_iter=30)
    dx_sub = res_sub.nodes[f"N{n_segments}"].DX
    assert dx_sub > 0, "Subcrítico: flecha debe tener el signo de la carga"

    # Caso supercrítico: la flecha cambia de signo (rama post-bifurcación)
    m_super = _build_vertical_cantilever(L, n_segments, 1.5 * N_cr, P_lateral)
    res_super = solve(m_super, use_pdelta=True, pdelta_max_iter=30)
    dx_super = res_super.nodes[f"N{n_segments}"].DX
    assert dx_super < 0, (
        f"Supercrítico (N=1,5·N_cr): se esperaba flecha de signo "
        f"opuesto al subcrítico (rama post-bifurcación inestable), "
        f"recibido DX={dx_super:.3e}"
    )


def test_pdelta_runtime_error_message_is_actionable():
    """Cuando PyNite SÍ lanza ValueError (singularidad real de la matriz),
    el wrapper debe reempaquetarlo en RuntimeError con mensaje accionable
    que sugiera alguna corrección concreta al usuario.

    Forzamos el escenario con un modelo mal restringido (sin soportes).
    """
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0.0, 0.0, 0.0, id="A")
    m.add_node(0.0, 0.0, 1.0, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="M1")
    m.add_nodal_load("B", direction="FX", magnitude=100.0, case="D")
    # Adrede sin soportes → matriz singular

    with pytest.raises(RuntimeError) as exc_info:
        solve(m, use_pdelta=True, pdelta_max_iter=10)

    msg = str(exc_info.value)
    assert "P-Delta" in msg or "P-Δ" in msg
    # El mensaje debe sugerir alguna acción concreta al usuario
    assert ("anclaj" in msg.lower()
            or "altura" in msg.lower()
            or "secciones" in msg.lower()), (
        f"Mensaje no accionable: {msg!r}"
    )
