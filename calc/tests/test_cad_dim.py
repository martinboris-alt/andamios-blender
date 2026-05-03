"""Tests de la acotación normativa UNE-EN ISO 129-1 (calc/cad_dim.py).

Cubren consolidación + snap modular + agrupación abreviada + escala
normalizada + producción de DimensionChainSpec listas para dibujo.
"""

from __future__ import annotations

import pytest

from calc.cad_dim import (
    LAYHER_BAY_LENGTHS_M,
    LAYHER_FLOOR_HEIGHTS_M,
    NORMALIZED_SCALES,
    axis_labels_alpha,
    axis_labels_numeric,
    build_segments,
    consolidate_coords,
    group_chain,
    pick_best_integer_scale,
    pick_normalized_scale,
    prepare_dimension_chain,
    snap_to_modular,
    total_length_mm,
)


# ---------------------------------------------------------------------------
# Consolidación
# ---------------------------------------------------------------------------

def test_consolidate_groups_close_values():
    """Dos coordenadas a 0,4 mm y a 41,6 mm de otra son el mismo montante
    duplicado — deben fusionarse."""
    raw = [0.0, 0.0004, 2.07, 2.0696, 4.14]
    out = consolidate_coords(raw, tol_mm=5.0)
    assert len(out) == 3
    # Cada cluster representado por su media
    assert out[0] == pytest.approx(0.0, abs=1e-3)
    assert out[1] == pytest.approx(2.07, abs=5e-3)
    assert out[2] == pytest.approx(4.14, abs=5e-3)


def test_consolidate_keeps_distant_values():
    """Coordenadas a > tol_mm permanecen separadas."""
    raw = [0.0, 1.0, 2.0]
    out = consolidate_coords(raw, tol_mm=5.0)
    assert out == [0.0, 1.0, 2.0]


def test_consolidate_rounds_to_5mm():
    """El representante se redondea a múltiplos de 5 mm."""
    out = consolidate_coords([2.0673], tol_mm=5.0, round_step_mm=5.0)
    assert out == [2.065]   # 2.0673 → 2065 mm


def test_consolidate_handles_empty():
    assert consolidate_coords([]) == []


# ---------------------------------------------------------------------------
# Snap modular
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("length_m, expected", [
    (0.730,    0.73),     # exacto
    (0.735,    0.73),     # +5 mm dentro de tolerancia
    (0.745,    None),     # +15 mm fuera de tolerancia (>10mm)
    (1.092,    1.09),
    (1.405,    1.40),
    (2.073,    2.07),
    (3.069,    3.07),
])
def test_snap_to_modular_layher(length_m, expected):
    result = snap_to_modular(length_m, LAYHER_BAY_LENGTHS_M, tol_mm=10.0)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_snap_returns_none_for_compensator():
    """1,752 m no es modular Layher (compensador → None)."""
    assert snap_to_modular(1.752, LAYHER_BAY_LENGTHS_M, tol_mm=10.0) is None


# ---------------------------------------------------------------------------
# Construcción de segmentos
# ---------------------------------------------------------------------------

def test_build_segments_marks_modular_and_compensators():
    """Coordenadas con tramos modulares y un residuo final."""
    coords = [0.0, 2.07, 4.14, 6.21, 7.20]   # 3 × 2070 + compensador 990
    segments = build_segments(coords, modular_steps=LAYHER_BAY_LENGTHS_M)

    assert len(segments) == 4
    # Los 3 primeros son 2070 mm modulares
    for i in range(3):
        assert segments[i].label_mm == 2070
        assert segments[i].modular is True
        assert segments[i].is_compensator is False
    # El último (990 mm) NO encaja en el catálogo → compensador
    assert segments[3].is_compensator is True
    assert segments[3].modular is False
    assert segments[3].label_mm == 990


def test_build_segments_handles_two_only():
    """Una sola crujía."""
    segments = build_segments([0.0, 2.07])
    assert len(segments) == 1
    assert segments[0].label_mm == 2070


def test_total_length_sums_segments():
    coords = [0.0, 2.07, 4.14, 6.21]
    segments = build_segments(coords)
    assert total_length_mm(segments) == 6210


# ---------------------------------------------------------------------------
# Agrupación abreviada N × L = T
# ---------------------------------------------------------------------------

def test_group_chain_collapses_repeated_modular():
    """5 crujías de 2 070 mm → un solo grupo '5 × 2070 = 10350'."""
    segments = build_segments([0.0, 2.07, 4.14, 6.21, 8.28, 10.35])
    groups = group_chain(segments)

    assert len(groups) == 1
    g = groups[0]
    assert g.n == 5
    assert g.segment_label_mm == 2070
    assert g.total_label_mm == 10350
    assert g.label() == "5 × 2070 = 10350"


def test_group_chain_keeps_compensators_individual():
    """Compensadores nunca se agrupan."""
    coords = [0.0, 2.07, 4.14, 5.13]   # 2×2070 + compensador 990
    segments = build_segments(coords)
    groups = group_chain(segments)

    assert len(groups) == 2
    assert groups[0].n == 2
    assert groups[0].label() == "2 × 2070 = 4140"
    assert groups[1].is_compensator is True
    assert groups[1].label() == "990"


def test_group_chain_does_not_collapse_different_modular_lengths():
    """2070 + 1570 + 2070 = 3 grupos distintos."""
    coords = [0.0, 2.07, 3.64, 5.71]
    segments = build_segments(coords)
    groups = group_chain(segments)
    # 3 grupos, todos n=1
    assert [g.segment_label_mm for g in groups] == [2070, 1570, 2070]
    assert all(g.n == 1 for g in groups)


def test_group_chain_label_for_single_segment():
    """Un grupo con n=1 no usa la notación N × L = T."""
    segments = build_segments([0.0, 2.07])
    groups = group_chain(segments)
    assert groups[0].label() == "2070"


# ---------------------------------------------------------------------------
# Escala normalizada
# ---------------------------------------------------------------------------

def test_pick_normalized_scale_picks_finest_that_fits():
    """Andamio 15 m × 7 m en A3 (380 × 200 mm) → 1:50 cabe (300 × 140 mm)."""
    scale, mm_per_m = pick_normalized_scale(15.0, 7.0, 380, 200)
    assert scale == 50
    assert mm_per_m == pytest.approx(20.0)


def test_pick_normalized_scale_falls_back_to_coarser():
    """Andamio 15 m × 7 m en rect 200 × 100 mm → 1:100 (150 × 70 mm)."""
    scale, mm_per_m = pick_normalized_scale(15.0, 7.0, 200, 100)
    assert scale == 100


def test_pick_normalized_scale_uses_largest_when_too_big():
    """Si ni la escala más grande basta, usar la más permisiva."""
    scale, mm_per_m = pick_normalized_scale(100.0, 50.0, 100, 50)
    assert scale == max(NORMALIZED_SCALES)


# ---------------------------------------------------------------------------
# Etiquetas de eje
# ---------------------------------------------------------------------------

def test_axis_labels_alpha_basic():
    assert axis_labels_alpha(3) == ["A", "B", "C"]


def test_axis_labels_alpha_overflow():
    labels = axis_labels_alpha(28)
    assert labels[25] == "Z"
    assert labels[26] == "AA"
    assert labels[27] == "AB"


def test_axis_labels_numeric():
    assert axis_labels_numeric(4) == ["1", "2", "3", "4"]


# ---------------------------------------------------------------------------
# Pipeline completo
# ---------------------------------------------------------------------------

def test_prepare_dimension_chain_full_pipeline():
    """Ejemplo del prompt: 5 crujías de 2 070 + compensador.

    Caso real: postes en x = [0, 2.0696, 4.1392, 6.2088, 8.2784, 10.348, 10.628]
    Los primeros 5 segmentos son 2,07 m (con ruido) y el último es un
    compensador de 280 mm.
    """
    raw = [0.0, 2.0696, 4.1392, 6.2088, 8.2784, 10.348, 10.628]
    spec = prepare_dimension_chain(raw)

    # Total = 5 × 2070 + 280 = 10630 mm
    assert spec.total_mm == 10630
    # Una entrada agrupada de 5 + un compensador
    assert len(spec.groups) == 2
    assert spec.groups[0].n == 5
    assert spec.groups[0].segment_label_mm == 2070
    assert spec.groups[0].total_label_mm == 10350
    assert spec.groups[1].is_compensator is True
    assert spec.groups[1].segment_label_mm == 280
    assert spec.has_compensators is True


def test_prepare_dimension_chain_handles_duplicate_montantes():
    """Coordenadas con duplicados a < 5 mm se fusionan en un solo punto."""
    # x = 0, 0.0004 (duplicado), 2.07, 2.0696 (duplicado), 4.14
    raw = [0.0, 0.0004, 2.07, 2.0696, 4.14]
    spec = prepare_dimension_chain(raw)
    assert len(spec.coords_m) == 3
    assert spec.total_mm == 4140
    assert len(spec.segments) == 2
    assert all(s.label_mm == 2070 for s in spec.segments)


# ---------------------------------------------------------------------------
# pick_best_integer_scale (modo fit-to-canvas, sin restricción ISO 5455)
# ---------------------------------------------------------------------------

def test_pick_best_integer_scale_height_limited():
    """Tramo 6×4 m sobre área 372×185 mm: el alto manda.
    mm_per_m_max = 185/4 = 46,25 → denom = ceil(1000/46.25) = 22.
    """
    denom, mm_per_m = pick_best_integer_scale(6.0, 4.0, 372.0, 185.0)
    assert denom == 22
    # mm_per_m ≈ 45,45 → drawing 6m × 4m ocupa ~273×182 mm
    assert 6.0 * mm_per_m <= 372.0
    assert 4.0 * mm_per_m <= 185.0


def test_pick_best_integer_scale_width_limited():
    """Tramo 10×2 m sobre área 372×185 mm: el ancho manda.
    mm_per_m_max = 372/10 = 37,2 → denom = ceil(1000/37.2) = 27.
    """
    denom, mm_per_m = pick_best_integer_scale(10.0, 2.0, 372.0, 185.0)
    assert denom == 27
    assert 10.0 * mm_per_m <= 372.0


def test_pick_best_integer_scale_clamps_min_denom():
    """bbox tan pequeño que la escala saldría < 5 → clamp a min_denom=5."""
    denom, _ = pick_best_integer_scale(0.05, 0.05, 372.0, 185.0,
                                        min_denom=5)
    assert denom == 5


def test_pick_best_integer_scale_zero_bbox_safe():
    """bbox degenerado (ancho o alto = 0) no rompe."""
    denom, mm_per_m = pick_best_integer_scale(0.0, 4.0, 372.0, 185.0)
    assert denom == 100
    assert mm_per_m == 10.0


def test_pick_best_beats_normalized_in_canvas_fill():
    """Para 6×4 m en 372×185 mm, best_integer (1:22) llena más canvas
    que normalized (1:50)."""
    bw, bh, aw, ah = 6.0, 4.0, 372.0, 185.0
    norm_denom, norm_mpm = pick_normalized_scale(bw, bh, aw, ah)
    best_denom, best_mpm = pick_best_integer_scale(bw, bh, aw, ah)
    assert best_denom < norm_denom    # más fina
    # Área usada por mejor escala > área usada por normalizada
    norm_area = (bw * norm_mpm) * (bh * norm_mpm)
    best_area = (bw * best_mpm) * (bh * best_mpm)
    assert best_area > norm_area * 4   # >>4× más cobertura
