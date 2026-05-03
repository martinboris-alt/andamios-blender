"""Tests de conectividad del modelo FEM (welding de nodos próximos +
splits a media barra).

Garantizan que el pipeline captura todas las uniones físicas del andamio
incluso cuando hay ruido geométrico (esquinas con bisectriz) o uniones
que no caen en los extremos teóricos de los miembros (un tie atando un
poste en una Z intermedia).
"""

from __future__ import annotations

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.pipeline import (
    NODE_MERGE_TOL,
    auto_add_base_supports,
    build_and_solve,
    weld_close_nodes,
    weld_mid_span_attachments,
)


def _default_options(combo: str = "ULS_LeadL") -> dict:
    return {
        "apply_service": False,
        "apply_wind": False,
        "apply_imperfections": False,
        "combo": combo,
    }


# ---------------------------------------------------------------------------
# weld_close_nodes
# ---------------------------------------------------------------------------

def test_weld_close_nodes_merges_pair_within_tolerance():
    """Dos nodos a 2 mm uno del otro se fusionan en uno solo."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0,     0, 0,     id="A")
    m.add_node(0.002, 0, 0,     id="B")    # 2 mm de A
    m.add_node(3,     0, 0,     id="C")
    m.add_member("A", "C", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LA")
    m.add_member("B", "C", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LB")

    n_removed = weld_close_nodes(m)
    assert n_removed == 1                    # uno de A/B desaparece
    assert len(m.nodes) == 2
    # Los dos miembros siguen apuntando al mismo extremo izquierdo
    nodes_used = {m.members["LA"].i_node, m.members["LB"].i_node}
    assert len(nodes_used) == 1


def test_weld_close_nodes_keeps_far_nodes_separate():
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(1, 0, 0, id="B")   # bien lejos
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "ledger", id="L")

    n = weld_close_nodes(m)
    assert n == 0
    assert len(m.nodes) == 2


def test_weld_close_nodes_removes_degenerate_member_after_merge():
    """Si tras fusionar quedan dos extremos iguales, el miembro se elimina."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0.002, 0, 0, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LDeg")

    n = weld_close_nodes(m)
    assert n == 1
    assert "LDeg" not in m.members


def test_weld_close_nodes_redirects_supports_and_loads():
    """Soportes y cargas nodales también deben actualizarse."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0.001, 0, 0, id="B")
    m.add_node(2, 0, 0, id="C")
    m.add_member("A", "C", CHS_48_3x3_2.name, S235JR.name, "ledger", id="L")
    m.add_support("B", DX=True)
    m.add_nodal_load("B", "FZ", -100.0)

    weld_close_nodes(m)
    # El soporte y la carga ahora apuntan al nodo superviviente
    surviving = next(iter(m.nodes))
    assert m.supports[0].node == surviving
    assert m.nodal_loads[0].node == surviving


def test_weld_close_nodes_no_op_on_empty_model():
    m = Model()
    assert weld_close_nodes(m) == 0


# ---------------------------------------------------------------------------
# weld_mid_span_attachments
# ---------------------------------------------------------------------------

def test_weld_mid_span_splits_member_when_node_lies_on_centerline():
    """Un poste vertical de 4 m con un anclaje atando en z=2 debe
    descomponerse en dos sub-postes."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 4, id="B")
    m.add_node(0, 0, 2, id="MID")    # cae a media altura del poste
    # Otro miembro acabando en MID (un tie horizontal, p. ej.)
    m.add_node(1, 0, 2, id="WALL")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="POLE")
    m.add_member("WALL", "MID", CHS_48_3x3_2.name, S235JR.name, "tie", id="TIE")

    n = weld_mid_span_attachments(m)
    assert n == 1
    # POLE original ya no existe; se han creado dos sub-piezas
    assert "POLE" not in m.members
    new_ids = [k for k in m.members if k.startswith("POLE_")]
    assert len(new_ids) == 2
    # Las dos sub-barras pasan por MID
    used_nodes = set()
    for nid in new_ids:
        used_nodes.add(m.members[nid].i_node)
        used_nodes.add(m.members[nid].j_node)
    assert "MID" in used_nodes


def test_weld_mid_span_does_nothing_when_no_intermediate_attachment():
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 3, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")

    n = weld_mid_span_attachments(m)
    assert n == 0
    assert "P" in m.members


def test_weld_mid_span_ignores_endpoints_within_margin():
    """Un nodo a 2 % de la longitud (dentro del margen) no debe
    considerarse a media barra."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 4, id="B")
    m.add_node(0, 0, 0.05, id="NEAR_A")   # 1.25 % de la longitud
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")

    n = weld_mid_span_attachments(m, margin=0.05)
    assert n == 0
    assert "P" in m.members


def test_weld_mid_span_handles_iterative_splits():
    """Un poste de 6 m con 2 anclajes a media altura debe partirse 2 veces."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 6, id="B")
    m.add_node(0, 0, 2, id="M1")
    m.add_node(0, 0, 4, id="M2")
    m.add_node(1, 0, 2, id="W1"); m.add_node(1, 0, 4, id="W2")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")
    m.add_member("W1", "M1", CHS_48_3x3_2.name, S235JR.name, "tie", id="T1")
    m.add_member("W2", "M2", CHS_48_3x3_2.name, S235JR.name, "tie", id="T2")

    n = weld_mid_span_attachments(m)
    assert n == 2
    # 3 sub-piezas del poste original + 2 ties = 5 miembros
    assert len(m.members) == 5


def test_weld_mid_span_preserves_external_releases():
    """Si el miembro original tenía releases en el extremo j, sólo el
    sub-miembro b (el que toca el extremo j original) las hereda."""
    from calc.releases import set_releases_by_type
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 4, id="B")
    m.add_node(0, 0, 2, id="MID")
    m.add_node(1, 0, 2, id="W")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "brace", id="X")
    m.add_member("W", "MID", CHS_48_3x3_2.name, S235JR.name, "tie", id="T")
    set_releases_by_type(m)             # brace -> RY/RZ released; tie idem

    weld_mid_span_attachments(m)
    new_ids = sorted(k for k in m.members if k.startswith("X_"))
    assert len(new_ids) == 2
    a = m.members[new_ids[0]]   # extremo original "A" (i)
    b = m.members[new_ids[1]]   # extremo original "B" (j)
    # A hereda release_i del original (brace pinned), B hereda release_j
    assert a.release_i == (False, False, False, False, True, True)
    assert a.release_j == (False,) * 6              # interior continuo
    assert b.release_i == (False,) * 6              # interior continuo
    assert b.release_j == (False, False, False, False, True, True)


# ---------------------------------------------------------------------------
# Integración: build_and_solve los aplica automáticamente
# ---------------------------------------------------------------------------

def test_build_and_solve_welds_close_nodes_automatically():
    """Si el modelo extraído tiene un par de nodos a 2 mm, build_and_solve
    los fusiona antes de resolver."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0,     0, 0, id="A0")
    m.add_node(0.002, 0, 0, id="A0_dup")  # casi-duplicado
    m.add_node(0,     0, 4, id="A1")
    m.add_node(2,     0, 0, id="B0")
    m.add_node(2,     0, 4, id="B1")
    m.add_member("A0",     "A1", CHS_48_3x3_2.name, S235JR.name, "pole", id="PA")
    m.add_member("A0_dup", "B0", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LB")
    m.add_member("A1",     "B1", CHS_48_3x3_2.name, S235JR.name, "ledger", id="LT")
    m.add_member("B0",     "B1", CHS_48_3x3_2.name, S235JR.name, "pole", id="PB")

    initial_nodes = len(m.nodes)
    build_and_solve(m, _default_options())
    # El nodo A0_dup se fusionó con A0
    assert len(m.nodes) == initial_nodes - 1


def test_build_and_solve_welds_mid_span_automatically():
    """Si hay un anclaje a media altura, build_and_solve detecta la unión
    y parte el poste antes de resolver."""
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 4, id="B")
    m.add_node(0, 0, 2, id="MID")
    m.add_node(1, 0, 2, id="W")
    m.add_member("A", "B",   CHS_48_3x3_2.name, S235JR.name, "pole", id="POLE")
    m.add_member("W", "MID", CHS_48_3x3_2.name, S235JR.name, "tie",  id="TIE")
    # Soportes manuales en A y W para no colapsar el sistema
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_support("W", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)

    build_and_solve(m, _default_options())
    # El poste original debe haberse partido
    assert "POLE" not in m.members
    pole_parts = [k for k in m.members if k.startswith("POLE_")]
    assert len(pole_parts) == 2
