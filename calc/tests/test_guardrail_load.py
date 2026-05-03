"""Tests de calc/loads/guardrail.py — carga horizontal EN 12811-1 §7.2.1
en barandillas (0,3 kN puntual)."""

from __future__ import annotations

import pytest

from calc.loads.guardrail import (
    GUARDRAIL_F_NEWTONS,
    apply_guardrail_horizontal_load,
)
from calc.materials import MATERIALS
from calc.model import Model
from calc.sections import make_chs_section


def _build_simple_scaffold() -> Model:
    """Modelo mínimo: 4 postes en cuadrícula 2×1 bay × 2 plantas.

    Layout (en planta, +X = longitudinal, +Y = transversal):
        N0 ----- N1     (z=0)
        |        |
        |        |     bay 2,07 m × depth 1 m
        |        |
        N2 ----- N3     (z=0)

    Postes verticales N0→N0t, N1→N1t, N2→N2t, N3→N3t (cada uno 2 m).
    """
    m = Model()
    sec = make_chs_section("CHS", D=0.0483, t=0.0032, fy=235e6)
    m.add_material(MATERIALS["S235JR"])
    m.add_section(sec)
    # Base
    m.add_node(0.0, 0.0, 0.0, id="N0")
    m.add_node(2.07, 0.0, 0.0, id="N1")
    m.add_node(0.0, 1.0, 0.0, id="N2")
    m.add_node(2.07, 1.0, 0.0, id="N3")
    # Top (z = 2 m)
    m.add_node(0.0, 0.0, 2.0, id="N0t")
    m.add_node(2.07, 0.0, 2.0, id="N1t")
    m.add_node(0.0, 1.0, 2.0, id="N2t")
    m.add_node(2.07, 1.0, 2.0, id="N3t")
    for nid_bot, nid_top in [("N0","N0t"),("N1","N1t"),
                              ("N2","N2t"),("N3","N3t")]:
        m.add_member(id=f"P_{nid_bot}", i_node=nid_bot, j_node=nid_top,
                     section="CHS", material="S235JR", member_type="pole")
    return m


# ---------------------------------------------------------------------------
# Caso básico: 4 nodos top reciben 0,3 kN cada uno
# ---------------------------------------------------------------------------

def test_applies_load_to_each_top_pole_node():
    m = _build_simple_scaffold()
    n_loads = apply_guardrail_horizontal_load(m)
    assert n_loads == 4    # 4 postes → 4 nodos top


def test_load_magnitude_default_is_300_N():
    m = _build_simple_scaffold()
    apply_guardrail_horizontal_load(m)
    # Verificar que la magnitud sea 300 N (valor absoluto) en los 4 ld
    mags = [abs(ld.magnitude) for ld in m.nodal_loads]
    assert all(mag == GUARDRAIL_F_NEWTONS for mag in mags)
    assert GUARDRAIL_F_NEWTONS == 300.0


def test_loads_are_horizontal():
    """La carga debe ser FX o FY (nunca FZ ni momento)."""
    m = _build_simple_scaffold()
    apply_guardrail_horizontal_load(m)
    for ld in m.nodal_loads:
        assert ld.direction in ("FX", "FY")


def test_loads_target_top_nodes_only():
    """Solo nodos top reciben la carga; los nodos base (z=0) no."""
    m = _build_simple_scaffold()
    apply_guardrail_horizontal_load(m)
    base_nodes = {"N0", "N1", "N2", "N3"}
    loaded = {ld.node for ld in m.nodal_loads}
    assert loaded.isdisjoint(base_nodes)
    assert loaded == {"N0t", "N1t", "N2t", "N3t"}


# ---------------------------------------------------------------------------
# Auto-detección del eje perpendicular
# ---------------------------------------------------------------------------

def test_auto_detects_perpendicular_for_x_aligned_scaffold():
    """Andamio largo en X (longitud > depth) → carga en FY."""
    m = _build_simple_scaffold()
    # X: 0..2.07 → range 2.07. Y: 0..1 → range 1.0. X manda → carga ⊥ Y.
    apply_guardrail_horizontal_load(m, direction="AUTO")
    axes = {ld.direction for ld in m.nodal_loads}
    assert axes == {"FY"}


def test_auto_detects_perpendicular_for_y_aligned_scaffold():
    """Andamio largo en Y (depth ≪ longitud-Y) → carga en FX."""
    m = Model()
    sec = make_chs_section("CHS", D=0.0483, t=0.0032, fy=235e6)
    m.add_material(MATERIALS["S235JR"])
    m.add_section(sec)
    m.add_node(0.0, 0.0, 0.0, id="A")
    m.add_node(0.0, 5.0, 0.0, id="B")
    m.add_node(0.5, 0.0, 0.0, id="C")
    m.add_node(0.5, 5.0, 0.0, id="D")
    m.add_node(0.0, 0.0, 2.0, id="At")
    m.add_node(0.0, 5.0, 2.0, id="Bt")
    m.add_node(0.5, 0.0, 2.0, id="Ct")
    m.add_node(0.5, 5.0, 2.0, id="Dt")
    for bot, top in [("A","At"),("B","Bt"),("C","Ct"),("D","Dt")]:
        m.add_member(id=f"P_{bot}", i_node=bot, j_node=top,
                     section="CHS", material="S235JR", member_type="pole")
    apply_guardrail_horizontal_load(m, direction="AUTO")
    axes = {ld.direction for ld in m.nodal_loads}
    assert axes == {"FX"}


# ---------------------------------------------------------------------------
# Direcciones explícitas
# ---------------------------------------------------------------------------

def test_explicit_positive_x_direction():
    m = _build_simple_scaffold()
    apply_guardrail_horizontal_load(m, direction="+X")
    assert all(ld.direction == "FX" and ld.magnitude > 0
               for ld in m.nodal_loads)


def test_explicit_negative_y_direction():
    m = _build_simple_scaffold()
    apply_guardrail_horizontal_load(m, direction="-Y")
    assert all(ld.direction == "FY" and ld.magnitude < 0
               for ld in m.nodal_loads)


def test_invalid_direction_raises():
    m = _build_simple_scaffold()
    with pytest.raises(ValueError, match="direction"):
        apply_guardrail_horizontal_load(m, direction="UP")


# ---------------------------------------------------------------------------
# Casos límite
# ---------------------------------------------------------------------------

def test_zero_magnitude_no_op():
    m = _build_simple_scaffold()
    n = apply_guardrail_horizontal_load(m, F=0.0)
    assert n == 0
    assert m.nodal_loads == []


def test_no_poles_no_loads():
    """Modelo sin postes (solo ledgers, etc) → cero cargas."""
    m = Model()
    sec = make_chs_section("CHS", D=0.0483, t=0.0032, fy=235e6)
    m.add_material(MATERIALS["S235JR"])
    m.add_section(sec)
    m.add_node(0.0, 0.0, 2.0, id="A")
    m.add_node(2.0, 0.0, 2.0, id="B")
    m.add_member(id="L", i_node="A", j_node="B",
                 section="CHS", material="S235JR", member_type="ledger")
    n = apply_guardrail_horizontal_load(m)
    assert n == 0


def test_excludes_intermediate_pole_nodes():
    """En un poste segmentado (P1 z=0→1, P2 z=1→2), el nodo intermedio
    NO recibe carga: solo el verdadero top (z=2)."""
    m = Model()
    sec = make_chs_section("CHS", D=0.0483, t=0.0032, fy=235e6)
    m.add_material(MATERIALS["S235JR"])
    m.add_section(sec)
    m.add_node(0.0, 0.0, 0.0, id="bot")
    m.add_node(0.0, 0.0, 1.0, id="mid")
    m.add_node(0.0, 0.0, 2.0, id="top")
    m.add_member(id="P1", i_node="bot", j_node="mid",
                 section="CHS", material="S235JR", member_type="pole")
    m.add_member(id="P2", i_node="mid", j_node="top",
                 section="CHS", material="S235JR", member_type="pole")
    apply_guardrail_horizontal_load(m)
    loaded = {ld.node for ld in m.nodal_loads}
    assert loaded == {"top"}     # mid no aparece (es bottom de P2)


# ---------------------------------------------------------------------------
# Custom case label
# ---------------------------------------------------------------------------

def test_custom_case_label():
    m = _build_simple_scaffold()
    apply_guardrail_horizontal_load(m, case="Q_GUARDRAIL")
    assert all(ld.case == "Q_GUARDRAIL" for ld in m.nodal_loads)
