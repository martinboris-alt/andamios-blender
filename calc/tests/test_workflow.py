"""Tests del estado del workflow guiado (Fase B).

Función pura `pipeline.compute_workflow_state` que dado los inputs de la
escena (nº de barras estructurales, último nivel de validación, contadores)
produce el resumen de las 3 etapas: Diseño, Validación, Informe.
"""

from __future__ import annotations

import pytest

from calc.pipeline import compute_workflow_state


# ---------------------------------------------------------------------------
# Etapa 1: Diseño
# ---------------------------------------------------------------------------

def test_design_empty_when_no_structural_objects():
    s = compute_workflow_state(n_structural=0, validation_level=None)
    assert s["design"]["state"] == "empty"
    assert s["design"]["count"] == 0


def test_design_ok_when_structural_objects_present():
    s = compute_workflow_state(n_structural=24, validation_level=None)
    assert s["design"]["state"] == "ok"
    assert s["design"]["count"] == 24


# ---------------------------------------------------------------------------
# Etapa 2: Validación
# ---------------------------------------------------------------------------

def test_validation_empty_when_level_none():
    s = compute_workflow_state(n_structural=10, validation_level=None)
    assert s["validation"]["state"] == "empty"


def test_validation_empty_when_level_unknown():
    """Niveles desconocidos se tratan como 'empty' en lugar de fallar."""
    s = compute_workflow_state(n_structural=10, validation_level="garbage")
    assert s["validation"]["state"] == "empty"


def test_validation_ok_passes_through_metrics():
    s = compute_workflow_state(
        n_structural=10, validation_level="ok",
        n_failed=0, n_warning=0, n_total=24, worst=0.62,
    )
    assert s["validation"]["state"] == "ok"
    assert s["validation"]["n_total"] == 24
    assert s["validation"]["worst"] == pytest.approx(0.62)


def test_validation_warning_counts():
    s = compute_workflow_state(
        n_structural=10, validation_level="warning",
        n_failed=0, n_warning=3, n_total=24, worst=0.93,
    )
    assert s["validation"]["state"] == "warning"
    assert s["validation"]["n_warning"] == 3


def test_validation_fail_counts():
    s = compute_workflow_state(
        n_structural=10, validation_level="fail",
        n_failed=2, n_warning=4, n_total=24, worst=1.42,
    )
    assert s["validation"]["state"] == "fail"
    assert s["validation"]["n_failed"] == 2


# ---------------------------------------------------------------------------
# Etapa 3: Informe
# ---------------------------------------------------------------------------

def test_report_blocked_until_validation_runs():
    s = compute_workflow_state(n_structural=10, validation_level=None)
    assert s["report"]["state"] == "blocked"


@pytest.mark.parametrize("level", ["ok", "warning", "fail"])
def test_report_available_after_any_validation(level):
    """Incluso si la validación falla, el informe debe poder exportarse
    para documentar el problema."""
    s = compute_workflow_state(
        n_structural=10, validation_level=level,
        n_failed=1, n_warning=0, n_total=10, worst=1.1,
    )
    assert s["report"]["state"] == "available"


# ---------------------------------------------------------------------------
# Iteración: tras corregir el diseño la validación queda obsoleta
# ---------------------------------------------------------------------------

def test_iteration_scenario_design_added_after_failed_validation():
    """Escenario realista: el usuario validó y obtuvo fallos. Tras editar
    geometría todavía existe el último nivel de validación (caduco).
    El estado refleja diseño OK + validación pasada (caducada por el usuario,
    pero la función no lo sabe — la heurística la considera vigente)."""
    s = compute_workflow_state(
        n_structural=10, validation_level="fail",
        n_failed=2, n_warning=0, n_total=10, worst=1.4,
    )
    # La función es pura: sigue el last_run aunque el modelo cambie.
    # Es responsabilidad de la UI invalidarlo (custom prop).
    assert s["validation"]["state"] == "fail"
    assert s["report"]["state"] == "available"
