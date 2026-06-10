"""Tests de calc/catalogs.py — catálogos multi-fabricante (Fase I).

Validan integridad de los datos dimensionales y que los valores clave
coinciden con los catálogos públicos de fabricante de los que se
transcribieron (ver docstring de calc/catalogs.py para las fuentes).
"""

from __future__ import annotations

import pytest

from calc import catalogs
from calc.catalogs import SYSTEMS, ScaffoldSystem, bay_lengths, get, pole_lengths


# ---------------------------------------------------------------------------
# Presencia y forma
# ---------------------------------------------------------------------------

def test_all_expected_systems_present():
    assert set(catalogs.systems()) == {"GENERIC", "LAYHER", "PERI", "ULMA", "DOKA"}


@pytest.mark.parametrize("key", list(SYSTEMS))
def test_system_wellformed(key):
    sys_ = get(key)
    assert isinstance(sys_, ScaffoldSystem)
    assert sys_.key == key
    assert sys_.display_name
    assert sys_.source
    for seq in (sys_.bay_lengths_m, sys_.pole_lengths_m,
                sys_.standard_widths_m, sys_.deck_widths_m):
        assert len(seq) > 0
        assert all(L > 0 for L in seq)
        assert list(seq) == sorted(seq), "longitudes ordenadas ascendente"
        assert len(set(seq)) == len(seq), "sin duplicados"


@pytest.mark.parametrize("key", list(SYSTEMS))
def test_dimensional_plausibility(key):
    """Rangos físicos de sistemas ringlock EN 12810/12811."""
    sys_ = get(key)
    assert max(sys_.bay_lengths_m) <= 3.07      # vano máximo comercial
    assert min(sys_.bay_lengths_m) >= 0.25
    assert max(sys_.pole_lengths_m) <= 4.0
    assert 0.15 <= min(sys_.deck_widths_m) <= max(sys_.deck_widths_m) <= 0.7
    assert 0.6 <= min(sys_.standard_widths_m) <= max(sys_.standard_widths_m) <= 1.2


def test_rosette_pitch_is_half_metre_everywhere():
    # Todos los sistemas ringlock integrados llevan roseta/disco cada 0,5 m.
    assert all(s.rosette_pitch_m == 0.5 for s in SYSTEMS.values())


# ---------------------------------------------------------------------------
# Valores transcritos de catálogo (spot-checks contra la fuente)
# ---------------------------------------------------------------------------

def test_layher_matches_addon_historic_catalog():
    assert SYSTEMS["LAYHER"].bay_lengths_m == (
        0.73, 1.09, 1.40, 1.57, 1.73, 2.07, 2.57, 3.07)
    assert SYSTEMS["LAYHER"].pole_lengths_m == (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)


def test_peri_metric_grid():
    """PERI UP Rosett Flex: retícula métrica de 25 cm (más la pieza de 37,5)."""
    peri = SYSTEMS["PERI"]
    assert 0.25 in peri.bay_lengths_m and 3.0 in peri.bay_lengths_m
    for L in peri.bay_lengths_m:
        # todas las longitudes UH Plus son múltiplos de 12,5 cm
        assert round(L / 0.125, 6) == round(L / 0.125), L
    assert peri.pole_lengths_m == (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)  # tabla UVR
    assert peri.deck_widths_m == (0.25, 0.375)                     # decks UDG


def test_ulma_brio_brazos_y_pies():
    ulma = SYSTEMS["ULMA"]
    assert ulma.bay_lengths_m == (0.35, 0.7, 1.02, 1.5, 2.0, 2.5, 3.0)
    assert ulma.pole_lengths_m == (1.0, 1.5, 2.0, 3.0, 4.0)
    # 1,02 m es la longitud característica BRIO (≠ 1,09 Layher)
    assert 1.02 in ulma.bay_lengths_m and 1.09 not in ulma.bay_lengths_m


def test_doka_ringlock_ledgers():
    doka = SYSTEMS["DOKA"]
    assert doka.bay_lengths_m == (
        0.39, 0.73, 1.04, 1.09, 1.40, 1.57, 2.07, 2.57, 3.07)
    # verticales 0,5–3,0 en pasos de 0,5
    assert doka.pole_lengths_m == (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)


# ---------------------------------------------------------------------------
# Pesos de catálogo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(SYSTEMS))
def test_weights_keyed_to_catalog_lengths(key):
    """Cada peso publicado referencia una longitud que existe en el catálogo."""
    sys_ = get(key)
    assert set(sys_.ledger_weights_kg) <= set(sys_.bay_lengths_m)
    assert set(sys_.pole_weights_kg) <= set(sys_.pole_lengths_m)
    # las plataformas comparten la modulación longitudinal de los vanos
    assert set(sys_.deck_weights_kg) <= set(sys_.bay_lengths_m)
    for d in (sys_.ledger_weights_kg, sys_.pole_weights_kg, sys_.deck_weights_kg):
        assert all(kg > 0 for kg in d.values())


def test_pole_weights_monotonic_with_length():
    """A más largo, más pesado (sanidad de transcripción de verticales)."""
    for sys_ in SYSTEMS.values():
        if not sys_.pole_weights_kg:
            continue
        items = sorted(sys_.pole_weights_kg.items())
        kgs = [kg for _, kg in items]
        assert kgs == sorted(kgs), sys_.key


def test_ulma_spot_weights():
    ulma = SYSTEMS["ULMA"]
    assert ulma.ledger_weights_kg[1.02] == 4.0    # Brazo 1,02
    assert ulma.pole_weights_kg[3.0] == 13.6      # Pie 3
    assert ulma.deck_weights_kg[3.0] == 22.2      # Plataforma 3


def test_peri_spot_weights():
    peri = SYSTEMS["PERI"]
    assert peri.ledger_weights_kg[3.0] == 8.68    # Ledger UH 300 Plus
    assert peri.pole_weights_kg[4.0] == 19.2      # Standard UVR 400


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_bay_lengths_helper():
    assert bay_lengths("ULMA") == SYSTEMS["ULMA"].bay_lengths_m
    assert bay_lengths("UNIFORM") is None             # no es un catálogo
    assert bay_lengths("UNIFORM", fallback="LAYHER") == \
        SYSTEMS["LAYHER"].bay_lengths_m


def test_pole_lengths_helper():
    assert pole_lengths("DOKA") == SYSTEMS["DOKA"].pole_lengths_m
    assert pole_lengths("NOPE") is None
    assert pole_lengths("NOPE", fallback="GENERIC") == \
        SYSTEMS["GENERIC"].pole_lengths_m
