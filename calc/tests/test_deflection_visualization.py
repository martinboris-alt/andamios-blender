"""Tests de la visualización de deformaciones (Fase C).

Cubre los helpers puros de pipeline:
    deflection_ratio_to_bucket — clasificación por ratio δ/L
    compute_member_deflections — recorre miembros y empareja con results
    find_max_deflection_node   — localiza el nodo más desplazado
    deflection_summary         — resumen para el panel

La integración bpy (apply_deflection_colors / operador localizar) se valida
por inspección manual en Blender; aquí nos concentramos en la lógica.
"""

from __future__ import annotations

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.loads import apply_self_weight
from calc.pipeline import (
    DEFLECTION_BUCKET_LABELS,
    DEFLECTION_RATIO_THRESHOLDS,
    compute_member_deflections,
    deflection_ratio_to_bucket,
    deflection_summary,
    find_max_deflection_node,
)
from calc.solver import solve


# ---------------------------------------------------------------------------
# Buckets por ratio δ/L
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ratio, expected_bucket", [
    (0.0,         0),     # sin movimiento
    (0.0005,      0),     # < 1/1000
    (0.0015,      1),     # entre 1/1000 y 1/500
    (0.0025,      2),     # entre 1/500 y 1/300
    (0.004,       3),     # entre 1/300 y 1/200
    (0.0075,      4),     # entre 1/200 y 1/100
    (0.02,        5),     # > 1/100
])
def test_deflection_ratio_to_bucket(ratio, expected_bucket):
    assert deflection_ratio_to_bucket(ratio) == expected_bucket


def test_deflection_thresholds_match_en12811_limits():
    """Los umbrales deben incluir L/200 (postes) y L/100 (plataformas)."""
    assert 1 / 200 in DEFLECTION_RATIO_THRESHOLDS
    assert 1 / 100 in DEFLECTION_RATIO_THRESHOLDS


def test_deflection_bucket_labels_count_matches_buckets():
    # Hay un bucket más que umbrales (los rangos abiertos a izquierda y derecha)
    assert len(DEFLECTION_BUCKET_LABELS) == len(DEFLECTION_RATIO_THRESHOLDS) + 1


# ---------------------------------------------------------------------------
# compute_member_deflections — voladizo conocido
# ---------------------------------------------------------------------------

def test_compute_member_deflections_cantilever():
    """Voladizo CHS L=3 m con P=1 kN en la punta tiene δ_z analítica =
    P·L³/(3·E·I); debemos recuperarla nodo a nodo."""
    L = 3.0
    P = 1000.0

    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, L, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P1")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    # Carga lateral en la punta: induce flexión clara
    m.add_nodal_load("B", "FX", P, case="D")

    res = solve(m, check_statics=False)
    deflections = compute_member_deflections(m, res)
    assert "P1" in deflections

    # δ analítica de un voladizo: δ = P·L³/(3·E·I)
    EI = S235JR.E * CHS_48_3x3_2.Iy
    delta_an = P * L ** 3 / (3.0 * EI)
    info = deflections["P1"]
    assert info["max_disp_m"] == pytest.approx(delta_an, rel=5e-3)
    assert info["L"] == pytest.approx(L, rel=1e-9)
    assert info["worst_node"] == "B"   # nodo libre del voladizo
    # La etiqueta debe coincidir con el bucket
    assert info["label"] == DEFLECTION_BUCKET_LABELS[info["bucket"]]


def test_compute_member_deflections_skips_zero_length_or_missing():
    """Barras con datos incompletos en `results` no deben aparecer."""
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, 1, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_nodal_load("B", "FX", 100.0)
    res = solve(m, check_statics=False)
    deflections = compute_member_deflections(m, res)
    # 1 barra computada
    assert len(deflections) == 1


# ---------------------------------------------------------------------------
# find_max_deflection_node
# ---------------------------------------------------------------------------

def test_find_max_deflection_node_returns_free_end_of_cantilever():
    L = 3.0
    m = Model()
    m.add_material(S235JR)
    m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, L, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole", id="P1")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    apply_self_weight(m)
    m.add_nodal_load("B", "FX", 500.0)
    res = solve(m, check_statics=False)

    node_id, mag = find_max_deflection_node(res)
    assert node_id == "B"
    assert mag > 0


def test_find_max_deflection_handles_empty_results():
    from calc.solver import Results
    res = Results()  # sin nodos
    nid, mag = find_max_deflection_node(res)
    assert nid is None
    assert mag == 0.0


# ---------------------------------------------------------------------------
# deflection_summary
# ---------------------------------------------------------------------------

def test_deflection_summary_aggregates_buckets():
    fake = {
        "M1": {"max_disp_m": 0.001, "L": 2.0, "ratio": 0.0005,
               "worst_node": "N1", "bucket": 0, "label": "muy rígido"},
        "M2": {"max_disp_m": 0.005, "L": 2.0, "ratio": 0.0025,
               "worst_node": "N2", "bucket": 2, "label": "deformación moderada"},
        "M3": {"max_disp_m": 0.025, "L": 2.0, "ratio": 0.0125,
               "worst_node": "N3", "bucket": 5, "label": "deformación excesiva"},
        "M4": {"max_disp_m": 0.014, "L": 2.0, "ratio": 0.007,
               "worst_node": "N4", "bucket": 4, "label": "cerca del límite plataforma (L/100)"},
    }
    s = deflection_summary(fake)
    assert s["n_excessive"] == 1     # bucket >= 5
    assert s["n_warning"] == 2       # bucket >= 3 (M3 + M4)
    # La peor por ratio es M3 (0.0125)
    assert s["worst_member"] == "M3"
    assert s["worst_ratio"] == pytest.approx(0.0125)
    assert s["worst_disp_m"] == pytest.approx(0.025)


def test_deflection_summary_handles_empty_dict():
    s = deflection_summary({})
    assert s["worst_member"] is None
    assert s["worst_disp_m"] == 0.0
    assert s["n_excessive"] == 0
