"""Tests de la clasificación básica de fallos por componente dominante.

Función pura `pipeline.classify_failure_basic(check)` que detecta cuál
sub-utilización (compresión / pandeo / flexión / etc.) gobierna el fallo
de un miembro, para mostrarlo en la lista clicable del panel y en el
informe HTML.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from calc.checks import SectionCheck
from calc.pipeline import classify_failure_basic


@dataclass
class _FakeCheck:
    section_check: SectionCheck


def _make_check(**kw) -> _FakeCheck:
    sc = SectionCheck()
    for k, v in kw.items():
        setattr(sc, k, v)
    return _FakeCheck(section_check=sc)


# ---------------------------------------------------------------------------
# Casos individuales
# ---------------------------------------------------------------------------

def test_no_components_returns_dash():
    assert classify_failure_basic(_make_check()) == "—"


def test_pure_tension():
    assert classify_failure_basic(_make_check(tension=0.6)) == "tracción"


def test_pure_compression():
    assert classify_failure_basic(_make_check(compression=0.7)) == "compresión"


def test_pure_buckling():
    assert classify_failure_basic(_make_check(buckling=0.8)) == "pandeo"


def test_pure_bending_y():
    assert classify_failure_basic(_make_check(bending_y=0.5)) == "flexión"


def test_pure_bending_z():
    assert classify_failure_basic(_make_check(bending_z=0.55)) == "flexión"


def test_pure_shear():
    assert classify_failure_basic(_make_check(shear_y=0.4)) == "cortante"


# ---------------------------------------------------------------------------
# Combinada
# ---------------------------------------------------------------------------

def test_combined_dominates_when_high_enough():
    """Si la utilización combinada supera el resto, gana ella."""
    chk = _make_check(compression=0.5, bending_y=0.6, combined=1.2)
    assert classify_failure_basic(chk) == "combinada"


def test_combined_above_one_dominates_even_if_others_higher_individually():
    """Si combinada >= 1.0 y otra componente está por debajo de 1, sigue
    ganando combinada porque ése es el chequeo gobernante real."""
    chk = _make_check(compression=0.4, buckling=0.8, combined=1.05)
    assert classify_failure_basic(chk) == "combinada"


def test_combined_loses_when_smaller_than_individual_components():
    """Si combinada es menor que las componentes (raro en la práctica),
    gana la peor componente individual."""
    chk = _make_check(buckling=0.95, combined=0.3)
    assert classify_failure_basic(chk) == "pandeo"


# ---------------------------------------------------------------------------
# Empates — orden de prioridad
# ---------------------------------------------------------------------------

def test_tie_buckling_beats_compression():
    """Si pandeo == compresión, la heurística favorece pandeo (típicamente
    es el chequeo más restrictivo en postes)."""
    chk = _make_check(compression=0.7, buckling=0.7)
    assert classify_failure_basic(chk) == "pandeo"


def test_tie_bending_beats_compression():
    chk = _make_check(compression=0.5, bending_y=0.5)
    assert classify_failure_basic(chk) == "flexión"


# ---------------------------------------------------------------------------
# Caso realista
# ---------------------------------------------------------------------------

def test_typical_failed_pole_with_buckling():
    """Poste con compresión moderada y pandeo dominante (caso típico)."""
    chk = _make_check(compression=0.5, buckling=1.3, combined=0.9)
    # combined < buckling → debe ganar pandeo
    assert classify_failure_basic(chk) == "pandeo"


def test_typical_failed_ledger_with_bending():
    """Travesaño con flexión dominante."""
    chk = _make_check(bending_y=1.4, shear_y=0.3, compression=0.05)
    assert classify_failure_basic(chk) == "flexión"
