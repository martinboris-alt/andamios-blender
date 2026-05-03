"""Tests del validador del modelo (calc/validator.py).

Tests puros: validate_model + summarize_issues. validate_scene requiere
bpy y se prueba via smoke test en Blender headless.
"""

from __future__ import annotations

import pytest

from calc.materials import MATERIALS
from calc.model import Model, Support
from calc.sections import make_chs_section
from calc.validator import (
    ValidationIssue,
    summarize_issues,
    validate_model,
)


def _build_minimal_scaffold(n_poles: int = 4,
                            with_supports: bool = True,
                            with_braces: bool = True) -> Model:
    """Construye un modelo de andamio mínimo válido."""
    m = Model()
    sec = make_chs_section("CHS", D=0.0483, t=0.0032, fy=235e6)
    m.add_material(MATERIALS["S235JR"])
    m.add_section(sec)
    nodes_per_row = max(1, n_poles // 2)
    # Postes
    pole_ids: list[str] = []
    for row in range(2):
        y = row * 1.0
        for i in range(nodes_per_row):
            x = i * 2.0
            bot_id = f"N{row}_{i}_b"
            top_id = f"N{row}_{i}_t"
            m.add_node(x, y, 0.0, id=bot_id)
            m.add_node(x, y, 2.0, id=top_id)
            pid = f"P_{row}_{i}"
            m.add_member(id=pid, i_node=bot_id, j_node=top_id,
                         section="CHS", material="S235JR",
                         member_type="pole")
            pole_ids.append(pid)
            if with_supports:
                m.supports.append(Support(node=bot_id,
                                           DX=True, DY=True, DZ=True,
                                           RX=False, RY=False, RZ=False))
    # Ledgers (top): conectan postes en cada fila
    for row in range(2):
        for i in range(nodes_per_row - 1):
            i_node = f"N{row}_{i}_t"
            j_node = f"N{row}_{i+1}_t"
            m.add_member(id=f"L_{row}_{i}",
                         i_node=i_node, j_node=j_node,
                         section="CHS", material="S235JR",
                         member_type="ledger")
    if with_braces and nodes_per_row >= 2:
        m.add_member(id="B0", i_node="N0_0_b", j_node="N0_1_t",
                     section="CHS", material="S235JR",
                     member_type="brace")
    return m


# ---------------------------------------------------------------------------
# Casos felices
# ---------------------------------------------------------------------------

def test_minimal_valid_scaffold_only_info():
    m = _build_minimal_scaffold(n_poles=4)
    issues = validate_model(m)
    levels = [i.level for i in issues]
    assert "ERROR" not in levels
    assert "WARNING" not in levels
    assert "INFO" in levels   # I1 con resumen


def test_info_message_has_member_count():
    m = _build_minimal_scaffold(n_poles=4)
    issues = validate_model(m)
    info = next(i for i in issues if i.code == "I1")
    assert "P" in info.message
    assert "L" in info.message
    assert "D" in info.message


# ---------------------------------------------------------------------------
# Errores que bloquean el cálculo (E1, E2, E3)
# ---------------------------------------------------------------------------

def test_empty_model_returns_E1_only():
    m = Model()
    issues = validate_model(m)
    assert len(issues) == 1
    assert issues[0].code == "E1"
    assert issues[0].level == "ERROR"
    assert issues[0].is_blocking


def test_missing_node_reference_E3():
    m = _build_minimal_scaffold(n_poles=4)
    # Romper una referencia manualmente
    next(iter(m.members.values())).i_node = "Nx_inexistente"
    issues = validate_model(m)
    err = next(i for i in issues if i.code == "E3")
    assert err.level == "ERROR"
    assert "inexistentes" in err.message


# ---------------------------------------------------------------------------
# Warnings (W1-W4)
# ---------------------------------------------------------------------------

def test_too_few_poles_W1():
    m = _build_minimal_scaffold(n_poles=2)   # solo 2 postes
    issues = validate_model(m)
    warn = next(i for i in issues if i.code == "W1")
    assert warn.level == "WARNING"
    assert "2 postes" in warn.message


def test_zero_length_member_W2():
    m = _build_minimal_scaffold(n_poles=4)
    # Crear un nodo duplicado pegado a otro y un miembro entre ambos
    m.add_node(0.0, 0.0, 2.0001, id="dup")   # casi-coincidente con N0_0_t
    m.add_member(id="L_dup", i_node="N0_0_t", j_node="dup",
                 section="CHS", material="S235JR", member_type="ledger")
    issues = validate_model(m)
    warn = next((i for i in issues if i.code == "W2"), None)
    assert warn is not None
    assert "1 mm" in warn.message


def test_no_supports_W3():
    m = _build_minimal_scaffold(n_poles=4, with_supports=False)
    issues = validate_model(m)
    warn = next(i for i in issues if i.code == "W3")
    assert warn.level == "WARNING"
    assert "soportes" in warn.message.lower()


def test_orphan_pole_W4():
    """Crea un poste 'flotante' que no comparte nodo con nadie."""
    m = _build_minimal_scaffold(n_poles=4)
    m.add_node(99.0, 99.0, 0.0, id="orph_b")
    m.add_node(99.0, 99.0, 2.0, id="orph_t")
    m.add_member(id="P_orphan", i_node="orph_b", j_node="orph_t",
                 section="CHS", material="S235JR",
                 member_type="pole")
    issues = validate_model(m)
    warn = next(i for i in issues if i.code == "W4")
    assert warn.level == "WARNING"
    assert "P_orphan" in warn.message


def test_well_connected_poles_no_W4():
    """Postes conectados via ledger no deben dar W4."""
    m = _build_minimal_scaffold(n_poles=4)   # ya tiene ledgers
    issues = validate_model(m)
    assert all(i.code != "W4" for i in issues)


# ---------------------------------------------------------------------------
# summarize_issues
# ---------------------------------------------------------------------------

def test_summarize_empty():
    n_e, n_w, n_i, status = summarize_issues([])
    assert (n_e, n_w, n_i) == (0, 0, 0)
    assert status == "ok"


def test_summarize_only_info():
    issues = [ValidationIssue(level="INFO", code="I1", message="hola")]
    _, _, _, status = summarize_issues(issues)
    assert status == "ok"


def test_summarize_with_warning():
    issues = [
        ValidationIssue(level="WARNING", code="W1", message="x"),
        ValidationIssue(level="INFO",    code="I1", message="y"),
    ]
    _, _, _, status = summarize_issues(issues)
    assert status == "warning"


def test_summarize_with_error_blocks_even_with_warnings():
    issues = [
        ValidationIssue(level="WARNING", code="W1", message="x"),
        ValidationIssue(level="ERROR",   code="E1", message="y"),
    ]
    n_e, n_w, _, status = summarize_issues(issues)
    assert n_e == 1
    assert n_w == 1
    assert status == "blocked"


# ---------------------------------------------------------------------------
# is_blocking property
# ---------------------------------------------------------------------------

def test_is_blocking_only_for_errors():
    assert ValidationIssue("ERROR", "E1", "x").is_blocking is True
    assert ValidationIssue("WARNING", "W1", "x").is_blocking is False
    assert ValidationIssue("INFO", "I1", "x").is_blocking is False
