"""Tests de los overlays funcionales en planta del plano CAD:
- kind_for_object_name (clasificación por prefijo de nombre)
- _draw_top_markers (genera SVG correcto por kind)
- _draw_north (flecha de norte en esquina del rect)
"""

from __future__ import annotations

import pytest

from calc.cad_plan import (
    _MARKER_STYLE,
    _draw_north,
    _draw_top_markers,
    _draw_top_overlays,
    kind_for_object_name,
)


# ---------------------------------------------------------------------------
# kind_for_object_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    # Plataformas — distintos prefijos
    ("Deck_F1_001",            "plank"),
    ("Plank_F2_03",            "plank"),
    ("Corner_Plank_F0_01",     "plank"),
    # Trampillas
    ("Lid_F1_02",              "trapdoor"),
    ("Trapdoor_F0_01",         "trapdoor"),
    # Escaleras: SOLO el _rail_a cuenta (igual que en BOM)
    ("Ladder_F1_02_rail_a",    "ladder"),
    # Anclajes a fachada
    ("Tie_F2_03",              "tie"),
])
def test_kind_for_known_prefixes(name, expected):
    assert kind_for_object_name(name) == expected


@pytest.mark.parametrize("name", [
    # No-marker: postes/ledgers/rails/braces/husillos/rosetas
    "Pole_FC_000",
    "Pole_F__001",
    "Ledger_F1_F_002",
    "Rail_T_F2_005",
    "Rail_M_F1_010",
    "Toe_F0_F_003",
    "Brace_F1_001",
    "HBrace_F2_007",
    "Husillo_FC_000",
    "Rose_F1_005",
    # Sub-piezas duplicadas de escalera (sólo rail_a cuenta)
    "Ladder_F1_02_rail_b",
    "Ladder_F1_02_step_03",
    # Pasamanos lateral de escalera (v0.7.15) — sub-pieza, no marker propio
    "Ladder_F1_02_handrail",
    "Ladder_F1_02_handrail_post_bot",
    "Ladder_F1_02_handrail_post_top",
    # Decorativos del lid (la trampilla cuenta como Lid_, no estos)
    "Hinge_F1_02",
    "LidHandle_F1_02",
])
def test_kind_skipped_for_non_functional(name):
    assert kind_for_object_name(name) is None


def test_kind_unknown_prefix_returns_none():
    assert kind_for_object_name("Random_Object") is None
    assert kind_for_object_name("") is None


def test_plank_classified_but_skipped_in_marker_style():
    """Regresión v0.7.7: las bandejas se clasifican como 'plank' pero
    al haber removido 'plank' de _MARKER_STYLE, los consumers deben
    omitirlas en lugar de hacer KeyError."""
    assert kind_for_object_name("Deck_F1_001") == "plank"
    assert "plank" not in _MARKER_STYLE   # confirmado: sin marker
    # Cualquier consumer que use _MARKER_STYLE[kind] con kind="plank"
    # debería filtrar antes (in operator).
    elements = [{"kind": "plank", "x": 1, "y": 2, "z": 0, "label": ""}]
    svg = _draw_top_markers(_identity_transform(), elements)
    assert svg == ""


# ---------------------------------------------------------------------------
# _draw_top_markers
# ---------------------------------------------------------------------------

def _identity_transform():
    """Transform que mapea x_world → 0 + x*1 = x, y_world → 100 - y*1.
    Útil para verificar que los markers caen donde esperamos.
    """
    return (0.0, 100.0, 1.0)


def test_draw_top_markers_returns_empty_when_no_transform():
    elements = [{"kind": "plank", "x": 1, "y": 2, "z": 0, "label": ""}]
    assert _draw_top_markers(None, elements) == ""


def test_draw_top_markers_returns_empty_when_no_elements():
    assert _draw_top_markers(_identity_transform(), []) == ""


def test_draw_top_markers_plank_is_not_drawn_as_marker():
    """Las bandejas (planks) ya se dibujan como línea discontinua marrón
    vía extract_scaffold_lines_3d, así que no necesitan marker en planta
    (sería redundante). Solo trampillas / escaleras / anclajes llevan
    marker."""
    elements = [{"kind": "plank", "x": 5, "y": 3, "z": 0, "label": ""}]
    svg = _draw_top_markers(_identity_transform(), elements)
    # No emite ni rect ni texto para plank
    assert svg == "" or ("<rect" not in svg and "<text" not in svg)


def test_draw_top_markers_trapdoor_includes_T_label():
    elements = [{"kind": "trapdoor", "x": 0, "y": 0, "z": 0, "label": "T"}]
    svg = _draw_top_markers(_identity_transform(), elements)
    assert "<rect" in svg
    # Numeración secuencial por tipo: primer trapdoor → T1
    assert ">T1<" in svg
    assert _MARKER_STYLE["trapdoor"][0] in svg


def test_draw_top_markers_ladder_includes_E_label():
    elements = [{"kind": "ladder", "x": 0, "y": 0, "z": 0, "label": "E"}]
    svg = _draw_top_markers(_identity_transform(), elements)
    # Numeración secuencial por tipo: primera escalera → E1
    assert ">E1<" in svg
    assert _MARKER_STYLE["ladder"][0] in svg


def test_draw_top_markers_tie_renders_triangle():
    elements = [{"kind": "tie", "x": 0, "y": 0, "z": 0, "label": ""}]
    svg = _draw_top_markers(_identity_transform(), elements)
    assert "<polygon" in svg
    assert _MARKER_STYLE["tie"][0] in svg


def test_draw_top_markers_unknown_kind_skipped_safely():
    elements = [{"kind": "unknown", "x": 1, "y": 2, "z": 3, "label": ""}]
    svg = _draw_top_markers(_identity_transform(), elements)
    # No genera ningún rect/polygon, pero tampoco rompe
    assert "<rect" not in svg
    assert "<polygon" not in svg


def test_draw_top_markers_multiple_elements():
    elements = [
        {"kind": "plank",    "x": 1, "y": 1, "z": 0, "label": ""},
        {"kind": "trapdoor", "x": 2, "y": 2, "z": 0, "label": "T"},
        {"kind": "ladder",   "x": 3, "y": 3, "z": 0, "label": "E"},
        {"kind": "tie",      "x": 4, "y": 4, "z": 0, "label": ""},
    ]
    svg = _draw_top_markers(_identity_transform(), elements)
    # Plank no se dibuja como marker (es línea discontinua).
    # trapdoor + ladder = 2 rects; tie = 1 polygon.
    # Textos: T1 (trapdoor), E1 (ladder), A1 (tie ahora etiquetado) = 3 textos
    assert svg.count("<rect") == 2
    assert svg.count("<polygon") == 1
    assert svg.count("<text") == 3


def test_draw_top_markers_position_uses_transform():
    """Una elemento en (10, 5) con transform (x_off=2, y_off=100, scale=3)
    se centra en svg(2 + 10*3, 100 - 5*3) = (32, 85). El triángulo del
    `tie` tiene vértice en cy-1.8 = 83.2 y base en cy+1.0 = 86."""
    elements = [{"kind": "tie", "x": 10, "y": 5, "z": 0, "label": ""}]
    svg = _draw_top_markers((2.0, 100.0, 3.0), elements)
    # cx = 32 aparece tres veces (vértice + offsets ±1.6)
    assert "32.00" in svg
    # Las dos coordenadas Y del triángulo son cy±offsets
    assert "83.20" in svg
    assert "86.00" in svg


# ---------------------------------------------------------------------------
# _draw_north
# ---------------------------------------------------------------------------

def test_draw_north_includes_circle_and_label():
    svg = _draw_north((0, 0, 100, 80))
    assert "<circle" in svg
    assert ">N<" in svg
    assert "<polygon" in svg


@pytest.mark.parametrize("position", [
    "bottom-right", "bottom-left", "top-right", "top-left",
])
def test_draw_north_supports_four_corners(position):
    """El símbolo se posiciona en cualquier esquina sin lanzar."""
    svg = _draw_north((10, 20, 100, 80), position=position)
    assert "<circle" in svg
    assert ">N<" in svg


def test_draw_north_in_bottom_right_is_inside_rect():
    """El círculo+flecha debe estar contenido dentro del rect."""
    rect = (0.0, 0.0, 100.0, 100.0)
    svg = _draw_north(rect, position="bottom-right", radius_mm=5.0)
    # Aproximación: el cx ronda x + w - margin - r = 100 - 6 - 5 = 89
    # No es necesario test exhaustivo, sólo que aparece un cx alto
    import re
    m = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)
    assert m is not None
    cx, cy = float(m.group(1)), float(m.group(2))
    assert 80 < cx < 100
    assert 80 < cy < 100


# ---------------------------------------------------------------------------
# _draw_top_overlays (combo)
# ---------------------------------------------------------------------------

def test_draw_top_overlays_combines_markers_and_north():
    rect = (0, 0, 100, 80)
    elements = [{"kind": "tie", "x": 1, "y": 2, "z": 0, "label": ""}]
    svg = _draw_top_overlays(rect, _identity_transform(), elements)
    # Norte presente
    assert ">N<" in svg
    # Tie presente (al menos un polygon)
    assert "<polygon" in svg


def test_draw_top_overlays_norte_even_without_elements():
    """La flecha de Norte se pinta aunque no haya markers funcionales."""
    rect = (0, 0, 100, 80)
    svg = _draw_top_overlays(rect, _identity_transform(), [])
    assert ">N<" in svg


def test_draw_top_overlays_norte_even_without_transform():
    """Si _draw_view no produjo transform (vista vacía), Norte sigue
    pintándose (no depende del transform)."""
    rect = (0, 0, 100, 80)
    svg = _draw_top_overlays(rect, None, [])
    assert ">N<" in svg


# ---------------------------------------------------------------------------
# _draw_tramo_labels (etiquetas TRAMO A-B en la planta general)
# ---------------------------------------------------------------------------

def test_draw_tramo_labels_renders_labels_for_each_frame():
    """U-shape con 3 tramos produce TRAMO A-B / B-C / C-D centrados en
    sus midpoints respectivos."""
    from calc.cad_plan import _draw_tramo_labels
    from calc.cad_views import segment_frames

    frames = segment_frames([(0, 0, 0), (5, 0, 0), (5, 3, 0), (0, 3, 0)])
    svg = _draw_tramo_labels(_identity_transform(), frames)
    assert "TRAMO A-B" in svg
    assert "TRAMO B-C" in svg
    assert "TRAMO C-D" in svg


def test_draw_tramo_labels_returns_empty_when_no_frames():
    from calc.cad_plan import _draw_tramo_labels
    assert _draw_tramo_labels(_identity_transform(), []) == ""


def test_draw_tramo_labels_returns_empty_when_no_transform():
    """Sin transform (vista vacía) no se pintan las etiquetas."""
    from calc.cad_plan import _draw_tramo_labels
    from calc.cad_views import segment_frames

    frames = segment_frames([(0, 0, 0), (5, 0, 0)])
    assert _draw_tramo_labels(None, frames) == ""


def test_draw_tramo_labels_centers_on_midpoint():
    """El tramo (0,0)→(10,0) tiene midpoint en (5,0). Con identity
    transform el cx del rect blanco va con offset −7 → x=−2."""
    from calc.cad_plan import _draw_tramo_labels
    from calc.cad_views import segment_frames

    frames = segment_frames([(0, 0, 0), (10, 0, 0)])
    svg = _draw_tramo_labels(_identity_transform(), frames)
    # midpoint x_svg = 0 + 5*1 = 5; el rect cx-7 = -2
    # midpoint y_svg = 100 - 0*1 = 100; el rect cy-2.4 = 97.6
    assert "-2.00" in svg or '"-2.00"' in svg
    assert "97.60" in svg


def test_draw_top_overlays_includes_tramo_labels_when_frames_passed():
    from calc.cad_plan import _draw_top_overlays
    from calc.cad_views import segment_frames

    frames = segment_frames([(0, 0, 0), (5, 0, 0), (5, 3, 0)])
    rect = (0, 0, 100, 80)
    svg = _draw_top_overlays(
        rect, _identity_transform(), [], frames=frames,
    )
    assert "TRAMO A-B" in svg
    assert "TRAMO B-C" in svg
    # Norte sigue presente
    assert ">N<" in svg


def test_draw_top_overlays_omits_tramo_labels_when_no_frames():
    """En la hoja única (1 tramo o sin polilínea) no se pintan las
    etiquetas — el frames param es opcional."""
    from calc.cad_plan import _draw_top_overlays
    rect = (0, 0, 100, 80)
    svg = _draw_top_overlays(rect, _identity_transform(), [])
    assert "TRAMO" not in svg
