"""Tests del auto-fix iterativo (Fase G).

`autofix.decide_next_fix` es función pura: dados el estado actual de las
props y la lista de fallos, decide la siguiente acción correctiva.
"""

from __future__ import annotations

import pytest

from calc.autofix import (
    BAY_STEPS,
    POLE_SEG_STEPS,
    decide_next_fix,
    next_lower_step,
)


def _failure(member_id="M1", util=1.5, ftype="combinada", mtype="pole"):
    return {
        "member_id": member_id,
        "utilization": util,
        "failure_type": ftype,
        "member_type": mtype,
    }


def _state(**overrides):
    """Estado por defecto: ya tiene todas las cruces, vano grande, segmento grande."""
    base = {
        "add_braces": True,
        "add_horizontal_braces": True,
        "bay_length_catalog": "UNIFORM",
        "bay_length": 3.0,
        "pole_segment_length": 4.0,
        "pole_length_catalog": "UNIFORM",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# next_lower_step
# ---------------------------------------------------------------------------

def test_next_lower_step_returns_immediate_smaller():
    assert next_lower_step(2.5, BAY_STEPS) == pytest.approx(2.07)


def test_next_lower_step_returns_none_below_minimum():
    assert next_lower_step(0.5, BAY_STEPS) is None


def test_next_lower_step_handles_exact_match():
    """Si value == step, devuelve el step inmediatamente menor."""
    assert next_lower_step(2.07, BAY_STEPS) == pytest.approx(1.57)


def test_next_lower_step_pole_seg():
    assert next_lower_step(3.0, POLE_SEG_STEPS) == pytest.approx(2.0)
    assert next_lower_step(0.5, POLE_SEG_STEPS) is None


# ---------------------------------------------------------------------------
# Estrategia priorizada
# ---------------------------------------------------------------------------

def test_priority_a_activate_braces_when_off():
    state = _state(add_braces=False)
    fix = decide_next_fix(state, [_failure()])
    assert fix is not None
    assert fix["prop"] == "add_braces"
    assert fix["after"] is True


def test_priority_b_activate_horizontal_braces_when_braces_already_on():
    state = _state(add_braces=True, add_horizontal_braces=False)
    fix = decide_next_fix(state, [_failure()])
    assert fix["prop"] == "add_horizontal_braces"


def test_pandeo_in_pole_reduces_pole_segment():
    state = _state()
    failures = [_failure(util=1.5, ftype="pandeo", mtype="pole")]
    fix = decide_next_fix(state, failures)
    assert fix is not None
    assert fix["prop"] == "pole_segment_length"
    assert fix["after"] < fix["before"]


def test_flexion_in_ledger_reduces_bay_length():
    state = _state()
    failures = [_failure(util=1.4, ftype="flexión", mtype="ledger")]
    fix = decide_next_fix(state, failures)
    assert fix is not None
    assert fix["prop"] == "bay_length"
    assert fix["after"] < fix["before"]


def test_non_uniform_catalog_first_forced_to_uniform_before_reducing_bay():
    """Si bay_length_catalog está en LAYHER, debe pasar primero a UNIFORM."""
    state = _state(bay_length_catalog="LAYHER")
    failures = [_failure(ftype="flexión", mtype="ledger")]
    fix = decide_next_fix(state, failures)
    assert fix["prop"] == "bay_length_catalog"
    assert fix["after"] == "UNIFORM"


def test_combinada_in_pole_prefers_pole_seg():
    """Combinada en poste con pandeo dominante → reduce segmento."""
    state = _state()
    failures = [_failure(ftype="combinada", mtype="pole"),
                _failure(ftype="pandeo", mtype="pole")]
    fix = decide_next_fix(state, failures)
    # Pandeo presente → prefer pole_seg
    assert fix["prop"] == "pole_segment_length"


def test_combinada_majority_in_ledgers_reduces_bay():
    """Cuando los fallos vienen mayoritariamente de ledgers → reducir vano."""
    state = _state()
    failures = [
        _failure(member_id=f"L{i}", ftype="flexión", mtype="ledger")
        for i in range(5)
    ] + [_failure(ftype="combinada", mtype="pole")]
    fix = decide_next_fix(state, failures)
    assert fix["prop"] == "bay_length"


# ---------------------------------------------------------------------------
# Sin más opciones disponibles
# ---------------------------------------------------------------------------

def test_returns_none_when_at_minimum_design():
    """Bay_length y pole_segment ya en mínimos, cruces activas → no hay más."""
    state = _state(
        bay_length=BAY_STEPS[-1],
        pole_segment_length=POLE_SEG_STEPS[-1],
    )
    fix = decide_next_fix(state, [_failure(util=1.5)])
    assert fix is None


def test_returns_none_when_no_failures():
    """Sin fallos y todo activo, no hay nada que hacer."""
    state = _state()
    fix = decide_next_fix(state, [])
    assert fix is None


def test_iterative_convergence_simulation():
    """Simulación sencilla: si llamamos a decide repetidamente y aplicamos
    los cambios, eventualmente converge a None."""
    state = _state(add_braces=False, add_horizontal_braces=False)
    failures = [_failure(ftype="flexión", mtype="ledger")]

    history = []
    for _ in range(20):
        fix = decide_next_fix(state, failures)
        if fix is None:
            break
        history.append(fix)
        state[fix["prop"]] = fix["after"]
    # Debe haber aplicado al menos:
    # 1) add_braces
    # 2) add_horizontal_braces
    # 3..) reducir bay_length step a step
    actions = [f["prop"] for f in history]
    assert "add_braces" in actions
    assert "add_horizontal_braces" in actions
    assert actions.count("bay_length") >= 1
    # Eventualmente debe terminar en None
    assert fix is None


# ---------------------------------------------------------------------------
# Snapshot / restore (sin bpy real — usamos dict-like)
# ---------------------------------------------------------------------------

class _PropsLike:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_snapshot_captures_named_props():
    from calc.autofix import snapshot_props, SNAPSHOT_PROPS
    p = _PropsLike(
        add_braces=True, add_horizontal_braces=False,
        bay_length_catalog="UNIFORM", bay_length=2.5,
        pole_segment_length=2.0, pole_length_catalog="LAYHER",
        irrelevant_prop=42,
    )
    snap = snapshot_props(p)
    for k in SNAPSHOT_PROPS:
        assert k in snap
    assert "irrelevant_prop" not in snap
    assert snap["bay_length"] == 2.5


def test_restore_writes_back_snapshot():
    from calc.autofix import restore_props
    p = _PropsLike(bay_length=1.0, pole_segment_length=0.5)
    snap = {"bay_length": 3.0, "pole_segment_length": 4.0}
    n = restore_props(p, snap)
    assert n == 2
    assert p.bay_length == 3.0
    assert p.pole_segment_length == 4.0
