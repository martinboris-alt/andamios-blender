"""Tests del K_φ semi-rígido (calc/releases.py).

- effective_buckling_factor_K: fórmula EN 1993-1-1 Anexo E para pórtico
  arriostrado, casos límite y caso Layher real.
- compute_pole_lcr_overrides: dict de L_cr por miembro tipo poste a partir
  del K_φ del catálogo, ignorando ledgers/braces/ties.
"""

from __future__ import annotations

from math import isclose

import pytest

from calc.materials import MATERIALS
from calc.model import Model, Node
from calc.releases import (
    compute_pole_lcr_overrides,
    effective_buckling_factor_K,
)
from calc.sections import make_chs_section


# ---------------------------------------------------------------------------
# effective_buckling_factor_K — casos límite y caso real
# ---------------------------------------------------------------------------

def test_K_phi_infinite_gives_K_one_half():
    """Empotramiento perfecto en ambos extremos → K = 0,5 (caso ideal)."""
    K = effective_buckling_factor_K(L=2.0, EI=24_000.0,
                                    K_phi_top=1e15, K_phi_bot=1e15)
    assert isclose(K, 0.5, abs_tol=1e-3)


def test_K_phi_zero_gives_K_one_pinned():
    """Rótulas perfectas en ambos extremos → K = 1,0 (caso conservador)."""
    K = effective_buckling_factor_K(L=2.0, EI=24_000.0,
                                    K_phi_top=0.0, K_phi_bot=0.0)
    assert isclose(K, 1.0, abs_tol=1e-3)


def test_K_phi_layher_gives_intermediate_factor():
    """Caso real: poste CHS Ø48,3×3,2 (E·I≈24,3 kN·m²) de L=2 m con
    rosetas Layher (K_φ=80 kN·m/rad). Esperado K ≈ 0,54 (entre 0,5
    y 1,0, mucho más cerca de rígido que de pinned)."""
    K = effective_buckling_factor_K(L=2.0, EI=24_300.0,
                                    K_phi_top=80_000.0, K_phi_bot=80_000.0)
    assert 0.50 < K < 0.60
    assert isclose(K, 0.544, abs_tol=0.02)


def test_K_phi_clamps_to_pinned_range():
    """Para K_φ muy bajos respecto a la rigidez de la columna, K → 1,0."""
    # K_C = EI/L = 24_000/4 = 6_000 kN·m/rad. K_phi=1 → η ≈ 1.
    K = effective_buckling_factor_K(L=4.0, EI=24_000.0,
                                    K_phi_top=1.0, K_phi_bot=1.0)
    assert 0.99 <= K <= 1.0


def test_K_phi_degenerate_inputs_safe():
    """L=0 o EI=0 devuelven 1,0 (asumen pinned conservador)."""
    assert effective_buckling_factor_K(0.0, 24_000.0, 80_000.0, 80_000.0) == 1.0
    assert effective_buckling_factor_K(2.0, 0.0,    80_000.0, 80_000.0) == 1.0


def test_K_phi_asymmetric_top_pinned_bot_rigid():
    """Top pinned (K_phi_top=0) + bot fully rigid → K entre 0,7 y 0,8
    (caso típico de poste con rosa fija y sin restricción arriba)."""
    K = effective_buckling_factor_K(L=2.0, EI=24_300.0,
                                    K_phi_top=0.0, K_phi_bot=1e15)
    assert 0.65 < K < 0.85


# ---------------------------------------------------------------------------
# compute_pole_lcr_overrides — dict por poste, ignora otros tipos
# ---------------------------------------------------------------------------

def _build_test_model() -> Model:
    """Modelo mínimo con 1 poste (L=2 m) + 1 ledger + 1 brace."""
    m = Model()
    sec = make_chs_section("CHS_test", D=0.0483, t=0.0032, fy=235e6)
    m.add_material(MATERIALS["S235JR"])
    m.add_section(sec)
    m.add_node(0.0, 0.0, 0.0, id="n0")
    m.add_node(0.0, 0.0, 2.0, id="n1")
    m.add_node(1.5, 0.0, 0.0, id="n2")
    m.add_node(1.5, 0.0, 2.0, id="n3")
    m.add_member(id="P1", i_node="n0", j_node="n1",
                 section="CHS_test", material="S235JR", member_type="pole")
    m.add_member(id="L1", i_node="n1", j_node="n3",
                 section="CHS_test", material="S235JR", member_type="ledger")
    m.add_member(id="B1", i_node="n0", j_node="n3",
                 section="CHS_test", material="S235JR", member_type="brace")
    return m


def test_compute_pole_lcr_returns_only_poles():
    """Sólo los miembros tipo 'pole' aparecen en el dict; ledgers,
    braces, ties se ignoran."""
    m = _build_test_model()
    overrides = compute_pole_lcr_overrides(m, K_phi=80_000.0)
    assert set(overrides.keys()) == {"P1"}
    assert "L1" not in overrides
    assert "B1" not in overrides


def test_compute_pole_lcr_returns_empty_for_zero_kphi():
    """K_phi ≤ 0 → dict vacío; el caller usa el default L_cr_factor=1,0."""
    m = _build_test_model()
    assert compute_pole_lcr_overrides(m, K_phi=0.0) == {}
    assert compute_pole_lcr_overrides(m, K_phi=-5.0) == {}


def test_compute_pole_lcr_uses_geometric_length():
    """Para un poste de 2 m con K_φ Layher, L_cr debe ser ~ 0,54·2 = 1,09 m."""
    m = _build_test_model()
    overrides = compute_pole_lcr_overrides(m, K_phi=80_000.0)
    L_cr = overrides["P1"]
    assert 0.95 < L_cr < 1.20   # ~1,09 m


def test_compute_pole_lcr_higher_kphi_gives_shorter_lcr():
    """Más K_φ → más restricción → L_cr más corto (más capacidad a pandeo)."""
    m = _build_test_model()
    o_normal = compute_pole_lcr_overrides(m, K_phi=80_000.0)
    o_heavy  = compute_pole_lcr_overrides(m, K_phi=100_000.0)
    assert o_heavy["P1"] < o_normal["P1"]
