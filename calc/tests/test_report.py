"""Tests del informe HTML rediseñado (Fase F).

Verifica que el informe incluye todas las secciones del nuevo diseño:
resumen ejecutivo con semáforo, "cómo leer este informe", configuración,
métricas, tarjetas por fallo (con/sin imagen), tabla detallada y glosario.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.checks import run_all_checks
from calc.pipeline import compute_member_deflections
from calc.report import generate_html_report, write_html_report
from calc.solver import solve


def _build_simple_loaded_model() -> tuple[Model, object, dict]:
    """Voladizo deliberadamente sobrecargado para forzar fallos."""
    L = 3.0
    P = 50_000.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, L, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="POLE_X")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_nodal_load("B", "FZ", -P, case="D")
    res = solve(m, check_statics=False)
    return m, res, run_all_checks(m, res)


def _build_safe_model() -> tuple[Model, object, dict]:
    """Voladizo con carga ligera, no falla."""
    L = 3.0
    P = 5_000.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, L, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P_OK")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_nodal_load("B", "FZ", -P, case="D")
    res = solve(m, check_statics=False)
    return m, res, run_all_checks(m, res)


# ---------------------------------------------------------------------------
# Estructura del informe
# ---------------------------------------------------------------------------

def test_report_contains_executive_summary():
    """Resumen ejecutivo con semáforo + frase clara debe aparecer."""
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(model, res, checks)

    assert html.startswith("<!DOCTYPE html>")
    assert "Informe de cálculo estructural" in html
    assert "exec-summary" in html
    assert "exec-light" in html
    # Debe haber un encabezado del semáforo (ANDAMIO SEGURO / NO CUMPLE / ...)
    assert ("NO CUMPLE" in html or "MARGEN AJUSTADO" in html
            or "ANDAMIO SEGURO" in html)


def test_report_contains_help_section():
    """La sección 'Cómo leer este informe' debe aparecer."""
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(model, res, checks)
    assert "Cómo leer este informe" in html
    assert "utilización" in html.lower()


def test_report_contains_configuration_section():
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(
        model, res, checks,
        options={"apply_service": True, "service_class": "Q3",
                 "deck_width": 0.61, "apply_wind": True, "wind_zone": "A",
                 "wind_terrain": "II", "apply_imperfections": True,
                 "combo": "ULS_LeadW"},
    )
    assert "Configuración del cálculo" in html
    assert "Q3" in html
    assert "Resistencia con viento dominante" in html


def test_report_includes_metrics():
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(model, res, checks)
    # Las 4 cajas de métricas
    assert "Barras analizadas" in html
    assert "OK (holgadas)" in html
    assert "Cerca del límite" in html
    assert "Sobrepasadas" in html


def test_report_metrics_with_deflections():
    model, res, checks = _build_simple_loaded_model()
    deflections = compute_member_deflections(model, res)
    html = generate_html_report(model, res, checks, deflections=deflections)
    assert "Deformación máxima" in html
    assert "mm" in html


# ---------------------------------------------------------------------------
# Tarjetas de fallo
# ---------------------------------------------------------------------------

def test_failure_cards_render_with_diagnosis():
    """Cada barra fallida debe tener su tarjeta con why/fix."""
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(model, res, checks)

    # Hay al menos una tarjeta de fallo (no contar el CSS, sino el div real)
    assert "<div class='failure-card" in html
    # Con why/fix
    assert "¿Qué le pasa?" in html
    assert "¿Cómo corregir?" in html
    # Etiqueta de severidad
    assert ("Muy sobrepasado" in html or "Sobrepasado" in html
            or "Margen ajustado" in html)


def test_failure_card_includes_image_when_provided():
    """Si se pasa screenshots, el data-URL aparece en la tarjeta."""
    model, res, checks = _build_simple_loaded_model()
    fake_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
    html = generate_html_report(
        model, res, checks,
        screenshots={"POLE_X": fake_data_url},
    )
    assert fake_data_url in html
    assert "Imagen no disponible" not in html


def test_failure_card_has_no_image_when_not_provided():
    """Sin screenshots, las tarjetas indican que no hay imagen."""
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(model, res, checks)
    assert "Imagen no disponible" in html
    assert "data:image/png;base64" not in html


def test_safe_model_shows_no_failure_cards():
    """Un modelo sin fallos no muestra tarjetas, sí mensaje OK."""
    model, res, checks = _build_safe_model()
    html = generate_html_report(model, res, checks)
    assert "<div class='failure-card" not in html
    assert "Todas las barras están holgadas" in html


# ---------------------------------------------------------------------------
# Tabla detallada y glosario
# ---------------------------------------------------------------------------

def test_detail_table_rendered():
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(model, res, checks, top_n=10)
    assert "detail-table" in html
    assert "POLE_X" in html


def test_glossary_present():
    """El glosario al final debe aparecer con términos clave."""
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(model, res, checks)
    assert "<h2>Glosario</h2>" in html
    assert "Utilización" in html
    assert "Pandeo" in html
    assert "Compresión" in html
    assert "EN 12811" in html


# ---------------------------------------------------------------------------
# Ficheros y robustez
# ---------------------------------------------------------------------------

def test_write_html_report_creates_file():
    model, res, checks = _build_simple_loaded_model()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False,
    ) as f:
        path = f.name
    try:
        out = write_html_report(path, model, res, checks)
        assert out == os.path.abspath(path)
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert content.startswith("<!DOCTYPE html>")
        assert "Glosario" in content
    finally:
        os.unlink(path)


def test_report_escapes_html_in_member_names():
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 1, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P<X>")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_nodal_load("B", "FZ", -50_000.0)
    res = solve(m, check_statics=False)
    checks = run_all_checks(m, res)
    html = generate_html_report(m, res, checks)
    assert "P&lt;X&gt;" in html
    # No debe aparecer la versión sin escapar fuera del título escapado
    # (verificamos que no se cuela como tag HTML)
    assert "<P<X>>" not in html


def test_report_handles_top_n_larger_than_members():
    model, res, checks = _build_simple_loaded_model()
    # No debe lanzar excepción
    html = generate_html_report(model, res, checks, top_n=999)
    assert "<!DOCTYPE html>" in html


def test_report_handles_unknown_combo_gracefully():
    """Combo no reconocido aparece literal en lugar de explotar."""
    model, res, checks = _build_simple_loaded_model()
    html = generate_html_report(
        model, res, checks,
        options={"combo": "WEIRD_COMBO"},
    )
    assert "WEIRD_COMBO" in html
