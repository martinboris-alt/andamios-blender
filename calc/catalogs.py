"""Catálogos dimensionales multi-fabricante de sistemas ringlock (Fase I).

Fuente única de las longitudes nominales de pieza por fabricante. El addon
(`andamios_addon.py`) consume estos datos para subdividir tramos horizontales
(vanos) y postes verticales en piezas reales de catálogo; `cad_dim`/`cad_plan`
los usan para snapear cotas a longitudes modulares.

NO importa bpy — testeable fuera de Blender (ver tests/test_catalogs.py).

Datos verificados contra documentación pública de fabricante (junio 2026):

- **LAYHER** — Layher Allround. Integrado desde v0.2.x (catálogo histórico
  del addon). Largueros 0,73–3,07 m; verticales 0,5–4,0 m; rosetas cada 0,5 m.
- **PERI** — PERI UP Rosett Flex. Brochure técnica PERI (tablas "Ledgers UH
  Plus", "Standards UVR", "Steel Decks UDG"). Retícula métrica de 25/50 cm;
  rosetas cada 0,5 m; bandejas de 25 y 37,5 cm de ancho.
- **ULMA** — ULMA BRIO. Catálogo oficial ULMA Construction (CAT_BRIO_ES,
  tablas "Brazos", "Pies", "Plataformas"). Discos cada 0,5 m.
- **DOKA** — Doka Ringlock S. shop.doka.com (ficha "Ledger") y brochure
  Ringlock: largueros 0,39–3,07 m; verticales 0,5–3,0 m en pasos de 0,5 m.

Los pesos por pieza (kg) son los publicados por el fabricante y alimentan el
BOM cuando existen; si un sistema no los declara se usan las estimaciones
genéricas de `bom.py`. Las propiedades estructurales (sección, fy) NO viven
aquí: todos estos sistemas usan tubo CHS Ø48,3 según EN 39 / EN 12810 y el
FEM aplica la sección común definida en el addon. Marcado CE y valores de
DoP deben verificarse con el certificado del fabricante para uso real.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScaffoldSystem:
    """Catálogo dimensional de un sistema de andamio multidireccional."""
    key: str                              # clave estable usada en enums/props
    display_name: str
    bay_lengths_m: tuple[float, ...]      # largueros / vanos horizontales
    pole_lengths_m: tuple[float, ...]     # verticales (piezas de poste)
    standard_widths_m: tuple[float, ...]  # profundidades típicas del andamio
    deck_widths_m: tuple[float, ...]      # anchos de bandeja de catálogo
    rosette_pitch_m: float = 0.5
    # Pesos de catálogo por longitud nominal (m -> kg). Vacío = sin datos
    # publicados integrados; el BOM usa entonces su estimación genérica.
    ledger_weights_kg: dict[float, float] = field(default_factory=dict)
    pole_weights_kg: dict[float, float] = field(default_factory=dict)
    deck_weights_kg: dict[float, float] = field(default_factory=dict)
    source: str = ""


SYSTEMS: dict[str, ScaffoldSystem] = {
    "GENERIC": ScaffoldSystem(
        key="GENERIC",
        display_name="Genérico múltiplos 0,5 m",
        bay_lengths_m=(1.0, 1.5, 2.0, 2.5, 3.0),
        pole_lengths_m=(0.5, 1.0, 1.5, 2.0, 2.5, 3.0),
        standard_widths_m=(0.64, 1.0),
        deck_widths_m=(0.32, 0.61),
        source="Convención del addon (planificación en múltiplos de 0,5 m)",
    ),
    "LAYHER": ScaffoldSystem(
        key="LAYHER",
        display_name="Layher Allround",
        bay_lengths_m=(0.73, 1.09, 1.40, 1.57, 1.73, 2.07, 2.57, 3.07),
        pole_lengths_m=(0.5, 1.0, 1.5, 2.0, 3.0, 4.0),
        standard_widths_m=(0.732, 1.09),
        deck_widths_m=(0.19, 0.32, 0.61),
        source="Catálogo Layher Allround (integrado desde v0.2.x)",
    ),
    "PERI": ScaffoldSystem(
        key="PERI",
        display_name="PERI UP Rosett Flex",
        # Tabla "Ledgers UH Plus": 25/37,5/50/75/100/125/150/175/200/225/250/300 cm
        bay_lengths_m=(0.25, 0.375, 0.5, 0.75, 1.0, 1.25, 1.5,
                       1.75, 2.0, 2.25, 2.5, 3.0),
        # Tabla "Standards UVR": 50/100/150/200/300/400 cm
        pole_lengths_m=(0.5, 1.0, 1.5, 2.0, 3.0, 4.0),
        standard_widths_m=(0.75, 1.0),
        # Bandejas UDG de 25 y 37,5 cm de ancho
        deck_widths_m=(0.25, 0.375),
        ledger_weights_kg={
            # Pesos verbatim de la tabla UH Plus. El salto 1,25 m (4,46→5,43)
            # vs 1,50 m (4,71) es así en el catálogo (cambio de perfil).
            0.25: 1.42, 0.375: 1.77, 0.5: 2.07, 0.75: 2.73, 1.0: 4.46,
            1.25: 5.43, 1.5: 4.71, 1.75: 5.38, 2.0: 6.04, 2.25: 6.70,
            2.5: 7.36, 3.0: 8.68,
        },
        pole_weights_kg={
            0.5: 3.08, 1.0: 5.38, 1.5: 7.69, 2.0: 9.99, 3.0: 14.70, 4.0: 19.20,
        },
        deck_weights_kg={
            # Steel Deck UDG 25 (ancho 0,25 m) por longitud
            0.5: 3.81, 0.75: 5.18, 1.0: 6.55, 1.25: 7.94, 1.5: 9.33,
            2.0: 12.20, 2.5: 14.90, 3.0: 17.70,
        },
        source="Brochure técnica PERI UP Rosett Flex (UH Plus / UVR / UDG)",
    ),
    "ULMA": ScaffoldSystem(
        key="ULMA",
        display_name="ULMA BRIO",
        # Tabla "Brazos" (elementos horizontales)
        bay_lengths_m=(0.35, 0.7, 1.02, 1.5, 2.0, 2.5, 3.0),
        # Tabla "Pies" (verticales con disco cada 0,5 m)
        pole_lengths_m=(1.0, 1.5, 2.0, 3.0, 4.0),
        standard_widths_m=(0.7, 1.02),
        deck_widths_m=(0.32,),
        ledger_weights_kg={
            0.35: 1.8, 0.7: 2.9, 1.02: 4.0, 1.5: 5.5, 2.0: 7.2,
            2.5: 8.8, 3.0: 10.4,
        },
        pole_weights_kg={1.0: 4.6, 1.5: 7.4, 2.0: 9.0, 3.0: 13.6, 4.0: 17.8},
        deck_weights_kg={
            # "Plataforma" acero galvanizado por longitud
            0.7: 6.6, 1.02: 9.0, 1.5: 12.4, 2.0: 17.0, 2.5: 20.2, 3.0: 22.2,
        },
        source="Catálogo ULMA BRIO (CAT_BRIO_ES, tablas Brazos/Pies/Plataformas)",
    ),
    "DOKA": ScaffoldSystem(
        key="DOKA",
        display_name="Doka Ringlock S",
        # Ficha "Ledger" Ringlock S (shop.doka.com)
        bay_lengths_m=(0.39, 0.73, 1.04, 1.09, 1.40, 1.57, 2.07, 2.57, 3.07),
        # Verticales 0,5–3,0 m en pasos de 0,5 m; rosetas cada 0,5 m
        pole_lengths_m=(0.5, 1.0, 1.5, 2.0, 2.5, 3.0),
        standard_widths_m=(0.73, 1.09),
        deck_widths_m=(0.32,),
        source="Doka Ringlock S (shop.doka.com / brochure Ringlock)",
    ),
}


def systems() -> tuple[str, ...]:
    """Claves de sistema disponibles, en orden estable de declaración."""
    return tuple(SYSTEMS.keys())


def get(key: str) -> ScaffoldSystem | None:
    return SYSTEMS.get(key)


def bay_lengths(key: str, fallback: str | None = None) -> tuple[float, ...] | None:
    """Largueros de catálogo del sistema `key`, o los del `fallback`, o None
    (p.ej. para el modo UNIFORM, que no es un catálogo)."""
    sys_ = SYSTEMS.get(key) or (SYSTEMS.get(fallback) if fallback else None)
    return sys_.bay_lengths_m if sys_ else None


def pole_lengths(key: str, fallback: str | None = None) -> tuple[float, ...] | None:
    sys_ = SYSTEMS.get(key) or (SYSTEMS.get(fallback) if fallback else None)
    return sys_.pole_lengths_m if sys_ else None
