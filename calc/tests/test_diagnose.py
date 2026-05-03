"""Tests del diagnóstico narrativo de fallos (Fase E).

`pipeline.diagnose_failure(check, member_type)` produce explicación en
plano y recomendación de corrección, según el tipo de fallo dominante y
el tipo de miembro.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from calc.checks import SectionCheck
from calc.pipeline import diagnose_failure


@dataclass
class _FakeCheck:
    section_check: SectionCheck

    @property
    def utilization(self):
        return self.section_check.worst()


def _make(util_field: str, util: float, **extra) -> _FakeCheck:
    sc = SectionCheck()
    setattr(sc, util_field, util)
    for k, v in extra.items():
        setattr(sc, k, v)
    return _FakeCheck(section_check=sc)


# ---------------------------------------------------------------------------
# Severidad
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("util, expected", [
    (0.5,  "ok"),
    (0.84, "ok"),
    (0.85, "minor"),
    (0.99, "minor"),
    (1.0,  "serious"),
    (1.29, "serious"),
    (1.3,  "critical"),
    (2.5,  "critical"),
])
def test_severity_thresholds(util, expected):
    chk = _make("compression", util)
    d = diagnose_failure(chk)
    assert d["severity"] == expected


def test_severity_label_is_translated():
    chk = _make("compression", 1.5)
    d = diagnose_failure(chk)
    assert d["severity_label"] == "Muy sobrepasado"


# ---------------------------------------------------------------------------
# Texto específico por (tipo, member_type)
# ---------------------------------------------------------------------------

def test_pandeo_pole_mentions_altura_libre_and_perfil_reforzado():
    chk = _make("buckling", 1.4)
    d = diagnose_failure(chk, member_type="pole")
    assert d["type"] == "pandeo"
    assert "poste" in d["why"].lower() or "estabilidad" in d["why"].lower()
    assert "altura" in d["fix"].lower() or "Ø60" in d["fix"]


def test_pandeo_brace_mentions_diagonal():
    chk = _make("buckling", 1.4)
    d = diagnose_failure(chk, member_type="brace")
    assert "diagonal" in d["why"].lower()


def test_flexion_ledger_mentions_travesaño_and_vano():
    chk = _make("bending_y", 1.5)
    d = diagnose_failure(chk, member_type="ledger")
    assert d["type"] == "flexión"
    assert "travesaño" in d["why"].lower() or "plataforma" in d["why"].lower()
    assert "vano" in d["fix"].lower() or "luz" in d["fix"].lower()


def test_traccion_tie_mentions_anclaje():
    chk = _make("tension", 1.1)
    d = diagnose_failure(chk, member_type="tie")
    assert "anclaje" in d["why"].lower()
    assert "anclaje" in d["fix"].lower() or "fachada" in d["fix"].lower()


def test_combinada_pole_specifics():
    sc = SectionCheck()
    sc.compression = 0.5; sc.bending_y = 0.4; sc.combined = 1.6
    chk = _FakeCheck(section_check=sc)
    d = diagnose_failure(chk, member_type="pole")
    assert d["type"] == "combinada"
    assert "axil" in d["why"].lower() or "compresión" in d["why"].lower()
    assert "flex" in d["why"].lower()


def test_compresion_pure_in_pole_mentions_axial_capacity():
    chk = _make("compression", 1.2)
    d = diagnose_failure(chk, member_type="pole")
    assert d["type"] == "compresión"
    assert "axial" in d["why"].lower() or "vertical" in d["why"].lower()


# ---------------------------------------------------------------------------
# Fallback genérico
# ---------------------------------------------------------------------------

def test_unknown_member_type_falls_back_to_default_text():
    """Tipo de miembro desconocido debe usar el _default del tipo de fallo."""
    chk = _make("buckling", 1.2)
    d = diagnose_failure(chk, member_type="unknown_xyz")
    # El _default de pandeo no menciona "poste" ni "diagonal"
    assert d["type"] == "pandeo"
    assert "poste" not in d["why"].lower()
    assert "diagonal" not in d["why"].lower()
    # Pero sí debe tener texto útil
    assert d["why"]
    assert d["fix"]


def test_no_member_type_uses_default():
    chk = _make("buckling", 1.2)
    d = diagnose_failure(chk, member_type=None)
    assert d["why"]
    assert d["fix"]


def test_dash_type_for_zero_utilization_member():
    """Si todas las utilizaciones son 0 (no debería pasar pero por robustez)."""
    chk = _FakeCheck(section_check=SectionCheck())
    d = diagnose_failure(chk)
    assert d["type"] == "—"
    assert d["why"]
    assert d["fix"]


# ---------------------------------------------------------------------------
# Estructura del dict devuelto
# ---------------------------------------------------------------------------

def test_diagnose_returns_complete_dict():
    chk = _make("buckling", 1.5)
    d = diagnose_failure(chk, member_type="pole")
    for key in ("type", "severity", "severity_label", "why", "fix"):
        assert key in d, f"Falta clave {key}"
        assert d[key] != "" or key == "type"   # type puede ser "—"
