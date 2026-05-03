"""Tests de calc/cad_views.py — proyección isométrica + particionado por
tramos de polilínea para el plano CAD multi-hoja."""

from __future__ import annotations

from math import cos, isclose, pi, sin, sqrt

import pytest

from calc.cad_views import (
    SegmentFrame,
    iso_bbox,
    iso_project,
    line_midpoint,
    project_lines_to_segment,
    segment_frames,
    segment_label,
    split_lines_by_segments,
)


# ---------------------------------------------------------------------------
# iso_project
# ---------------------------------------------------------------------------

def test_iso_project_origin_maps_to_origin():
    assert iso_project((0.0, 0.0, 0.0)) == (0.0, 0.0)


def test_iso_project_z_axis_is_vertical():
    """El eje Z mundo se proyecta verticalmente (x'=0, y'=z)."""
    x, y = iso_project((0.0, 0.0, 5.0))
    assert isclose(x, 0.0)
    assert isclose(y, 5.0)


def test_iso_project_x_axis_goes_down_right():
    """+X mundo apunta abajo-derecha en la salida (x'>0, y'<0)."""
    x, y = iso_project((1.0, 0.0, 0.0))
    assert x > 0
    assert y < 0
    assert isclose(x, cos(pi/6))
    assert isclose(y, -sin(pi/6))


def test_iso_project_y_axis_goes_down_left():
    """+Y mundo apunta abajo-izquierda en la salida (x'<0, y'<0)."""
    x, y = iso_project((0.0, 1.0, 0.0))
    assert x < 0
    assert y < 0
    assert isclose(x, -cos(pi/6))
    assert isclose(y, -sin(pi/6))


def test_iso_project_diagonal_xy_collapses_horizontally():
    """Un punto en la diagonal X=Y proyecta sobre el eje Y' (x'=0)."""
    x, y = iso_project((2.0, 2.0, 0.0))
    assert isclose(x, 0.0)
    assert isclose(y, -2.0)  # 2·(-sin30) − 2·sin30 = −2


def test_iso_bbox_empty_returns_unit():
    assert iso_bbox([]) == ((0.0, 0.0), (1.0, 1.0))


def test_iso_bbox_cube():
    """Cubo 1×1×1 con esquinas en (0..1, 0..1, 0..1) tiene bbox conocido."""
    corners = [(x, y, z)
               for x in (0.0, 1.0)
               for y in (0.0, 1.0)
               for z in (0.0, 1.0)]
    bmin, bmax = iso_bbox(corners)
    # Ancho horizontal: de (1,0,0)=(cos30,-sin30) a (0,1,0)=(-cos30,-sin30)
    # → ancho = 2·cos30
    assert isclose(bmax[0] - bmin[0], 2 * cos(pi/6))
    # Alto vertical: de (1,1,0)=(0,-1) a (0,0,1)=(0,1) → alto = 2
    assert isclose(bmax[1] - bmin[1], 2.0)


# ---------------------------------------------------------------------------
# segment_frames
# ---------------------------------------------------------------------------

def test_segment_frames_single_horizontal():
    frames = segment_frames([(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)])
    assert len(frames) == 1
    f = frames[0]
    assert f.origin == (0.0, 0.0, 0.0)
    assert f.end == (5.0, 0.0, 0.0)
    assert isclose(f.length, 5.0)
    assert isclose(f.ex_xy[0], 1.0)
    assert isclose(f.ex_xy[1], 0.0)


def test_segment_frames_skips_zero_length_horizontal():
    """Tramos verticales (postes) no producen frame — no tienen alzado."""
    frames = segment_frames([(0.0, 0.0, 0.0), (0.0, 0.0, 3.0)])
    assert frames == []


def test_segment_frames_u_shape_three_segments():
    """U-shape con 4 puntos: 3 tramos no colineales."""
    pts = [(0.0, 0.0, 0.0),
           (5.0, 0.0, 0.0),
           (5.0, 3.0, 0.0),
           (0.0, 3.0, 0.0)]
    frames = segment_frames(pts)
    assert len(frames) == 3
    # Tramo 0: dirección +X
    assert isclose(frames[0].ex_xy[0], 1.0) and isclose(frames[0].ex_xy[1], 0.0)
    # Tramo 1: dirección +Y
    assert isclose(frames[1].ex_xy[0], 0.0) and isclose(frames[1].ex_xy[1], 1.0)
    # Tramo 2: dirección −X
    assert isclose(frames[2].ex_xy[0], -1.0) and isclose(frames[2].ex_xy[1], 0.0)
    # Índices secuenciales
    assert [f.index for f in frames] == [0, 1, 2]


def test_segment_frames_diagonal_normalized():
    """Tramo a 45° tiene ex_xy = (√2/2, √2/2)."""
    frames = segment_frames([(0.0, 0.0, 0.0), (3.0, 3.0, 0.0)])
    assert len(frames) == 1
    f = frames[0]
    assert isclose(f.length, 3.0 * sqrt(2.0))
    assert isclose(f.ex_xy[0], sqrt(2.0) / 2)
    assert isclose(f.ex_xy[1], sqrt(2.0) / 2)


def test_segment_frames_one_or_zero_points():
    assert segment_frames([]) == []
    assert segment_frames([(0.0, 0.0, 0.0)]) == []


# ---------------------------------------------------------------------------
# SegmentFrame.project
# ---------------------------------------------------------------------------

def test_project_point_on_axis_gives_arc_length():
    """Un punto sobre el eje del tramo proyecta a (u=arc, v=z)."""
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    u, v = f.project((3.0, 0.0, 2.5))
    assert isclose(u, 3.0)
    assert isclose(v, 2.5)


def test_project_drops_perpendicular_component():
    """La proyección sobre ex_xy ignora la separación perpendicular."""
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    u, _ = f.project((3.0, 1.5, 0.0))   # 1.5 m de separación lateral
    assert isclose(u, 3.0)


def test_project_keeps_z_as_vertical():
    f = SegmentFrame(0, (0, 0, 0), (10, 0, 0), (1, 0), 10.0)
    _, v = f.project((1.0, 0.0, 7.5))
    assert isclose(v, 7.5)


def test_project_origin_offset():
    """Si el origen no es (0,0,0), las u son relativas al origen."""
    f = SegmentFrame(0, (10, 5, 0), (15, 5, 0), (1, 0), 5.0)
    u, v = f.project((12.0, 5.0, 1.5))
    assert isclose(u, 2.0)
    assert isclose(v, 1.5)


# ---------------------------------------------------------------------------
# SegmentFrame.perp_distance_xy
# ---------------------------------------------------------------------------

def test_perp_distance_zero_on_axis():
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    assert isclose(f.perp_distance_xy((2.5, 0.0, 4.0)), 0.0)


def test_perp_distance_uses_xy_only():
    """Z no afecta — un punto a 100 m de altura sigue a 0 m del eje XY."""
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    assert isclose(f.perp_distance_xy((2.5, 0.0, 100.0)), 0.0)


def test_perp_distance_perpendicular_offset():
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    assert isclose(f.perp_distance_xy((2.5, 1.5, 0.0)), 1.5)


def test_perp_distance_outside_interval_penalized():
    """Puntos antes del origen o después del fin reciben penalización
    de la distancia al extremo más próximo."""
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    # 3 m antes del origen, sobre el eje
    d = f.perp_distance_xy((-3.0, 0.0, 0.0))
    assert isclose(d, 3.0)
    # 4 m después del fin, sobre el eje
    d = f.perp_distance_xy((9.0, 0.0, 0.0))
    assert isclose(d, 4.0)


# ---------------------------------------------------------------------------
# line_midpoint y split_lines_by_segments
# ---------------------------------------------------------------------------

def test_line_midpoint_basic():
    ln = {"p1": (0, 0, 0), "p2": (4, 2, 6)}
    assert line_midpoint(ln) == (2, 1, 3)


def test_split_lines_empty_path_returns_single_bucket():
    lines = [{"p1": (0, 0, 0), "p2": (1, 0, 1), "category": "pole"}]
    buckets = split_lines_by_segments(lines, [(0, 0, 0)])
    assert len(buckets) == 1
    assert buckets[0] == lines


def test_split_lines_l_shape_assigns_correctly():
    """L-shape: 3 puntos → 2 tramos. Líneas claramente sobre cada tramo
    deben caer en el bucket correcto."""
    pts = [(0, 0, 0), (5, 0, 0), (5, 3, 0)]   # tramo 0 a lo largo de +X,
    #                                            tramo 1 a lo largo de +Y
    lines = [
        # Sobre tramo 0 (eje +X, y=0)
        {"name": "t0_a", "p1": (1, 0, 0), "p2": (1, 0, 2), "category": "pole"},
        {"name": "t0_b", "p1": (3, 0, 0), "p2": (3, 0, 2), "category": "pole"},
        # Sobre tramo 1 (eje +Y a partir de x=5)
        {"name": "t1_a", "p1": (5, 1, 0), "p2": (5, 1, 2), "category": "pole"},
        {"name": "t1_b", "p1": (5, 2, 0), "p2": (5, 2, 2), "category": "pole"},
    ]
    buckets = split_lines_by_segments(lines, pts)
    assert len(buckets) == 2
    names_0 = {ln["name"] for ln in buckets[0]}
    names_1 = {ln["name"] for ln in buckets[1]}
    assert names_0 == {"t0_a", "t0_b"}
    assert names_1 == {"t1_a", "t1_b"}


def test_split_lines_corner_tube_assigned_to_one_segment():
    """Un poste exactamente en el codo (5, 0, _) está a igual distancia
    de ambos tramos. Debe asignarse al primero (estable: argmin con `<`)."""
    pts = [(0, 0, 0), (5, 0, 0), (5, 3, 0)]
    lines = [{"name": "corner", "p1": (5, 0, 0), "p2": (5, 0, 2),
              "category": "pole"}]
    buckets = split_lines_by_segments(lines, pts)
    # cae en uno de los dos buckets (no se duplica)
    n_total = sum(len(b) for b in buckets)
    assert n_total == 1


def test_split_lines_preserves_count():
    """No se pierden ni duplican líneas — la suma de buckets = total."""
    pts = [(0, 0, 0), (5, 0, 0), (5, 3, 0), (0, 3, 0)]   # U-shape
    lines = []
    for x in (0.5, 1.5, 2.5, 3.5, 4.5):
        lines.append({"p1": (x, 0, 0), "p2": (x, 0, 2), "category": "pole"})
    for y in (0.5, 1.5, 2.5):
        lines.append({"p1": (5, y, 0), "p2": (5, y, 2), "category": "pole"})
    for x in (0.5, 1.5, 2.5, 3.5, 4.5):
        lines.append({"p1": (x, 3, 0), "p2": (x, 3, 2), "category": "pole"})
    buckets = split_lines_by_segments(lines, pts)
    assert sum(len(b) for b in buckets) == len(lines)


# ---------------------------------------------------------------------------
# project_lines_to_segment
# ---------------------------------------------------------------------------

def test_project_lines_to_segment_returns_tuple_format():
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    lines = [
        {"p1": (1, 0, 0), "p2": (1, 0, 2), "category": "pole"},
        {"p1": (3, 0, 0), "p2": (3, 0, 2), "category": "pole"},
    ]
    out = project_lines_to_segment(lines, f)
    assert len(out) == 2
    # Cada elemento es (p1_2d, p2_2d, category)
    p1, p2, cat = out[0]
    assert isclose(p1[0], 1.0) and isclose(p1[1], 0.0)
    assert isclose(p2[0], 1.0) and isclose(p2[1], 2.0)
    assert cat == "pole"


def test_project_lines_to_segment_default_category_when_missing():
    f = SegmentFrame(0, (0, 0, 0), (5, 0, 0), (1, 0), 5.0)
    lines = [{"p1": (1, 0, 0), "p2": (1, 0, 2)}]   # sin category
    out = project_lines_to_segment(lines, f)
    assert out[0][2] == "pole"


def test_project_lines_to_segment_y_segment():
    """Tramo en dirección +Y: u sigue la coordenada Y."""
    f = SegmentFrame(0, (0, 0, 0), (0, 5, 0), (0, 1), 5.0)
    lines = [{"p1": (0, 2, 0), "p2": (0, 2, 3), "category": "pole"}]
    out = project_lines_to_segment(lines, f)
    p1, p2, _ = out[0]
    assert isclose(p1[0], 2.0) and isclose(p1[1], 0.0)
    assert isclose(p2[0], 2.0) and isclose(p2[1], 3.0)


# ---------------------------------------------------------------------------
# segment_label
# ---------------------------------------------------------------------------

def test_segment_label_basic():
    assert segment_label(0, 3) == "A-B"
    assert segment_label(1, 3) == "B-C"
    assert segment_label(2, 3) == "C-D"


def test_segment_label_zero_segments():
    assert segment_label(0, 0) == ""
