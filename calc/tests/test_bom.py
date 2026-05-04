"""Tests del módulo BOM (Bill of Materials).

Helpers puros de categorización y agregación, validados sin bpy.
"""

from __future__ import annotations

import pytest

from calc.bom import (
    CATEGORY_LABELS,
    CHS_AREA,
    STEEL_RHO,
    TUBE_WEIGHT_PER_M,
    aggregate_bom,
    category_for_name,
    is_structural_object_name,
    summarize_bom,
    tube_weight_kg,
)


# ---------------------------------------------------------------------------
# Categorización por nombre
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    # Postes
    ("Pole_F__001", "pole"),
    ("Pole_BC_002", "pole"),
    ("Pole_FC_003", "pole"),
    # Travesaños de planta (todos Ledger_*)
    ("Ledger_F_F1_000", "ledger_floor"),
    ("Ledger_B_F1_000", "ledger_floor"),
    ("Ledger_T_F1_000", "ledger_floor"),
    ("Ledger_TC_F1_002", "ledger_floor"),
    # Barandillas (Rail_*)
    ("Rail_F_mid_F1_000", "ledger_rail"),
    ("Rail_B_top_F1_000", "ledger_rail"),
    ("Rail_C_mid_F1_002_F", "ledger_rail"),
    ("Rail_E_mid_F1_000", "ledger_rail"),
    # Rodapiés
    ("Toe_F_F1_000", "toe"),
    ("Toe_B_F1_000", "toe"),
    ("Toe_E_F1_000", "toe"),
    ("Toe_C_F1_002", "toe"),
    # Cruces
    ("Brace_F0_002_F", "brace"),
    ("Brace_F1_001_F", "brace"),
    # Plataformas
    ("Deck_F1_000_p1a", "plank"),
    ("Corner_Plank_F1_002", "plank"),
    # Trampillas
    ("Lid_F1_000", "trapdoor"),
    # Escaleras: solo el representativo cuenta
    ("Ladder_000_F0_rail_a", "ladder"),
    ("Ladder_003_F0_rail_a", "ladder"),
])
def test_category_for_name(name, expected):
    assert category_for_name(name) == expected


@pytest.mark.parametrize("name", [
    "Hinge_F1_000_L",            # bisagras de trampilla (integradas en lid)
    "LidHandle_F1_000_l",        # asas
    "Ladder_000_F0_rail_b",      # sub-pieza de escalera (no representativa)
    "Ladder_000_F0_step_3",
    "Ladder_000_F0_handrail",        # pasamanos lateral (v0.7.15)
    "Ladder_000_F0_handrail_post_bot",
    "Ladder_000_F0_handrail_post_top",
])
def test_non_bom_objects_filtered_out(name):
    assert category_for_name(name) is None


@pytest.mark.parametrize("name", [
    "Rose_F_Z0000_000",          # rosetas: SÍ se contabilizan en el BOM
    "Rose_B_Z0150_001",
])
def test_rosettes_included_in_bom(name):
    """Las rosetas son piezas independientes del catálogo, deben
    contabilizarse para los pedidos al fabricante."""
    assert category_for_name(name) == "rosette"


def test_category_for_unknown_returns_none():
    assert category_for_name("FooBar_random") is None
    assert category_for_name("") is None


def test_non_structural_objects_excluded():
    assert is_structural_object_name("Pole_F0_3_sleeve") is False
    assert is_structural_object_name("Pole_F0_3_capA") is False
    assert is_structural_object_name("Brace_F0_2_head") is False
    assert is_structural_object_name("Pole_F0_3") is True


def test_category_for_decorative_pieces_returns_none():
    assert category_for_name("Pole_F0_3_sleeve") is None
    assert category_for_name("Brace_F0_2_capA") is None


# ---------------------------------------------------------------------------
# Pesos
# ---------------------------------------------------------------------------

def test_tube_weight_per_meter_matches_chs_48_3x3_2_s235():
    """≈ 3,56 kg/m para CHS Ø48,3×3,2 en S235JR (valor catálogo Layher)."""
    assert TUBE_WEIGHT_PER_M == pytest.approx(STEEL_RHO * CHS_AREA, rel=1e-9)
    assert TUBE_WEIGHT_PER_M == pytest.approx(3.56, rel=1e-2)


def test_tube_weight_kg_scales_linearly():
    assert tube_weight_kg(1.0) == pytest.approx(TUBE_WEIGHT_PER_M)
    assert tube_weight_kg(2.5) == pytest.approx(TUBE_WEIGHT_PER_M * 2.5)
    assert tube_weight_kg(0.0) == 0.0
    assert tube_weight_kg(-1.0) == 0.0


# ---------------------------------------------------------------------------
# Agregación
# ---------------------------------------------------------------------------

def _tube_item(cat, length_m):
    return {
        "name": f"{cat}_xx",
        "category": cat,
        "is_tube": True,
        "length_m": length_m,
        "weight_kg": tube_weight_kg(length_m),
    }


def test_aggregate_bom_groups_by_category_and_length():
    items = [
        _tube_item("pole", 2.0),
        _tube_item("pole", 2.0),
        _tube_item("pole", 2.0),
        _tube_item("pole", 1.0),
        _tube_item("ledger_floor", 2.5),
    ]
    groups = aggregate_bom(items)
    # 3 grupos esperados
    assert len(groups) == 3
    # Encontrar el grupo de postes 2 m
    pole_2m = next((g for g in groups
                    if g["category"] == "pole" and g["length_m"] == 2.0), None)
    assert pole_2m is not None
    assert pole_2m["count"] == 3
    assert pole_2m["total_weight_kg"] == pytest.approx(3 * tube_weight_kg(2.0))


def test_aggregate_rounds_close_lengths_into_same_bucket():
    """Longitudes a 0,01 m de diferencia que redondean al mismo múltiplo
    de length_round_m caen en el mismo bucket."""
    items = [
        _tube_item("pole", 2.00),
        _tube_item("pole", 2.01),
        _tube_item("pole", 2.02),
    ]
    groups = aggregate_bom(items, length_round_m=0.05)
    assert len(groups) == 1
    assert groups[0]["count"] == 3


def test_aggregate_distinguishes_distant_lengths():
    items = [
        _tube_item("pole", 2.0),
        _tube_item("pole", 2.5),
    ]
    groups = aggregate_bom(items)
    assert len(groups) == 2


def test_aggregate_handles_decks():
    items = [
        {"name": "P1", "category": "plank", "is_tube": False,
         "deck_id": "STEEL_2.57x0.32_C", "weight_kg": 13.5},
        {"name": "P2", "category": "plank", "is_tube": False,
         "deck_id": "STEEL_2.57x0.32_C", "weight_kg": 13.5},
        {"name": "P3", "category": "plank", "is_tube": False,
         "deck_id": "ALU_LVL_1.57x0.61_C", "weight_kg": 9.2},
    ]
    groups = aggregate_bom(items)
    assert len(groups) == 2  # 2 deck_ids distintos
    by_id = {g["deck_id"]: g for g in groups}
    assert by_id["STEEL_2.57x0.32_C"]["count"] == 2
    assert by_id["ALU_LVL_1.57x0.61_C"]["count"] == 1


# ---------------------------------------------------------------------------
# Resumen agregado
# ---------------------------------------------------------------------------

def test_summarize_returns_total_weight_and_pieces():
    items = [
        _tube_item("pole", 2.0),
        _tube_item("pole", 2.0),
        _tube_item("ledger_floor", 2.5),
    ]
    groups = aggregate_bom(items)
    summary = summarize_bom(groups)

    expected_weight = 2 * tube_weight_kg(2.0) + tube_weight_kg(2.5)
    assert summary["total_weight_kg"] == pytest.approx(expected_weight, rel=1e-9)
    assert summary["total_pieces"] == 3
    assert summary["total_tube_length_m"] == pytest.approx(2*2.0 + 2.5)


def test_summarize_orders_by_category():
    items = [
        _tube_item("plank" if False else "ledger_floor", 2.0),
        _tube_item("pole", 2.0),
    ]
    groups = aggregate_bom(items)
    summary = summarize_bom(groups)
    cats = [c["category"] for c in summary["by_category"]]
    assert cats == ["pole", "ledger_floor"]   # postes antes que ledgers


def test_summarize_breakdown_includes_tube_length():
    items = [
        _tube_item("pole", 2.0),
        _tube_item("pole", 2.0),
        _tube_item("ledger_floor", 2.5),
    ]
    groups = aggregate_bom(items)
    summary = summarize_bom(groups)
    pole_entry = next(c for c in summary["by_category"] if c["category"] == "pole")
    assert pole_entry["tube_length_m"] == pytest.approx(4.0)
    assert pole_entry["count"] == 2
