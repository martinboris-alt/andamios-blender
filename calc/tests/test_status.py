"""Tests del helper format_status_message — resumen del cálculo en lenguaje
no-experto que alimenta el panel y el informe HTML.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from calc.checks import SectionCheck
from calc.pipeline import (
    SERVICE_DESCRIPTION,
    WIND_DESCRIPTION,
    format_status_message,
)


@dataclass
class _FakeCheck:
    """Stub mínimo de MemberCheckResult para los tests."""
    member: str
    section: str
    material: str
    L: float
    L_cr: float
    section_check: SectionCheck

    @property
    def utilization(self) -> float:
        return self.section_check.worst()

    @property
    def passed(self) -> bool:
        return self.section_check.passed()


def _make_checks(utils: list[float]) -> dict[str, _FakeCheck]:
    """Construye un dict de checks con las utilizaciones dadas (en compresión)."""
    out: dict[str, _FakeCheck] = {}
    for i, u in enumerate(utils):
        sc = SectionCheck()
        sc.compression = u
        out[f"M{i}"] = _FakeCheck(
            member=f"M{i}", section="CHS", material="S235",
            L=2.0, L_cr=2.0, section_check=sc,
        )
    return out


# ---------------------------------------------------------------------------
# Niveles
# ---------------------------------------------------------------------------

def test_status_level_ok_when_all_below_085():
    checks = _make_checks([0.1, 0.4, 0.7, 0.84])
    s = format_status_message(checks)
    assert s["level"] == "ok"
    assert "seguro" in s["title"].lower()
    assert s["n_failed"] == 0
    assert s["n_warning"] == 0


def test_status_level_warning_when_some_near_limit():
    checks = _make_checks([0.5, 0.86, 0.95, 0.99])
    s = format_status_message(checks)
    assert s["level"] == "warning"
    assert s["n_failed"] == 0
    assert s["n_warning"] == 3


def test_status_level_fail_when_any_over_one():
    checks = _make_checks([0.4, 0.7, 1.05, 1.5])
    s = format_status_message(checks)
    assert s["level"] == "fail"
    assert s["n_failed"] == 2
    assert "2" in s["title"]
    assert "sobrepasados" in s["title"].lower()


def test_status_level_fail_singular_for_one_failure():
    checks = _make_checks([0.5, 1.2])
    s = format_status_message(checks)
    assert s["level"] == "fail"
    assert s["n_failed"] == 1
    assert "1" in s["title"]
    assert "sobrepasado" in s["title"].lower()


def test_status_level_handles_empty_model():
    s = format_status_message({})
    assert s["level"] == "warning"
    assert s["n_total"] == 0


# ---------------------------------------------------------------------------
# Subtítulo (frase descriptiva)
# ---------------------------------------------------------------------------

def test_subtitle_includes_service_description_when_enabled():
    checks = _make_checks([0.2])
    s = format_status_message(checks, options={
        "apply_service": True, "service_class": "Q3",
        "apply_wind": False, "apply_imperfections": False,
        "combo": "ULS_LeadL",
    })
    assert SERVICE_DESCRIPTION["Q3"] in s["subtitle"]


def test_subtitle_says_no_service_when_disabled():
    checks = _make_checks([0.2])
    s = format_status_message(checks, options={
        "apply_service": False,
        "apply_wind": False, "apply_imperfections": False,
        "combo": "ULS_LeadL",
    })
    assert "sin carga de servicio" in s["subtitle"]


def test_subtitle_includes_wind_description():
    checks = _make_checks([0.2])
    s = format_status_message(checks, options={
        "apply_service": False,
        "apply_wind": True, "wind_zone": "C",
        "apply_imperfections": False,
        "combo": "ULS_LeadW",
    })
    assert WIND_DESCRIPTION["C"] in s["subtitle"]
    assert "viento dominante" in s["subtitle"]


def test_subtitle_falls_back_when_combo_unknown():
    checks = _make_checks([0.2])
    s = format_status_message(checks, options={"combo": "NOPE"})
    # No debe lanzar excepción; el combo aparece literal si no hay traducción
    assert "NOPE" in s["subtitle"]


def test_status_worst_is_max_utilization():
    checks = _make_checks([0.3, 0.9, 1.5, 0.4])
    s = format_status_message(checks)
    assert s["worst"] == pytest.approx(1.5)
