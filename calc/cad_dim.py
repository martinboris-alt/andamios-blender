"""Acotación normativa para planos CAD según UNE-EN ISO 129-1.

Helpers puros (sin bpy ni SVG) que producen cadenas de cotas jerárquicas
listas para serializar:

    TOTAL    (cota global de la dimensión)
    A EJES   (cotas modulares entre montantes/plantas — usadas por el montador)
    PARCIAL  (sólo donde hay compensadores o piezas singulares)

Antes de generar las cadenas, las coordenadas de entrada se **consolidan**
(fusión por tolerancia) y se **snapean** al catálogo modular del fabricante
para evitar cotas espurias del tipo "1 973 mm" cuando lo correcto es
"2 070 mm − solape 97 mm".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# ---------------------------------------------------------------------------
# Catálogos modulares Layher Allround / Ringlock EU
# ---------------------------------------------------------------------------

# Longitudes nominales de larguero (m) — catálogo Layher Allround
LAYHER_BAY_LENGTHS_M: tuple[float, ...] = (
    0.73, 1.09, 1.40, 1.57, 2.07, 2.57, 3.07,
)

# Alturas habituales de planta (m)
LAYHER_FLOOR_HEIGHTS_M: tuple[float, ...] = (1.0, 1.5, 2.0)

# Longitudes nominales de poste (m)
LAYHER_POLE_LENGTHS_M: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)

# Tolerancia para considerar "el mismo montante" (mm reales)
DEFAULT_CONSOLIDATION_TOL_MM = 5.0

# Tolerancia para snap modular (mm reales)
DEFAULT_SNAP_TOL_MM = 10.0

# Escalas normalizadas (UNE-EN ISO 5455). El denominador (1:N).
NORMALIZED_SCALES: tuple[int, ...] = (20, 50, 100, 200, 500)


# ---------------------------------------------------------------------------
# Consolidación
# ---------------------------------------------------------------------------

def consolidate_coords(values_m: Sequence[float],
                       *, tol_mm: float = DEFAULT_CONSOLIDATION_TOL_MM,
                       round_step_mm: float = 5.0) -> list[float]:
    """Agrupa valores cercanos en un solo representante.

    Cualquier par de valores a distancia ≤ tol_mm se considera el mismo punto
    físico (montantes duplicados, ruido del modelador, etc.). Se devuelve
    el representante (media del cluster) redondeado a `round_step_mm`.

    Salida ordenada ascendentemente.
    """
    if not values_m:
        return []
    tol = tol_mm / 1000.0
    step = round_step_mm / 1000.0
    sorted_vals = sorted(values_m)
    clusters: list[list[float]] = [[sorted_vals[0]]]
    for v in sorted_vals[1:]:
        if v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    out: list[float] = []
    for cluster in clusters:
        avg = sum(cluster) / len(cluster)
        out.append(round(avg / step) * step)
    return out


# ---------------------------------------------------------------------------
# Snap modular
# ---------------------------------------------------------------------------

def snap_to_modular(length_m: float,
                    steps_m: Sequence[float] = LAYHER_BAY_LENGTHS_M,
                    *, tol_mm: float = DEFAULT_SNAP_TOL_MM) -> float | None:
    """Devuelve el step modular más próximo si la diferencia ≤ tol_mm.

    Si no hay step lo bastante cerca, devuelve None — la longitud se
    considera **compensador** (pieza singular, residuo de replanteo).
    """
    if not steps_m:
        return None
    best = min(steps_m, key=lambda s: abs(s - length_m))
    if abs(best - length_m) * 1000.0 <= tol_mm:
        return best
    return None


# ---------------------------------------------------------------------------
# Segmentos: cada par consecutivo de coords
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """Un tramo entre dos coordenadas consolidadas. Si es modular, `length_m`
    es el valor del catálogo; si no, es la medida real redondeada y se
    marca como compensador."""
    length_m: float
    label_mm: int           # cota como entero en mm
    modular: bool
    is_compensator: bool


@dataclass
class ChainGroup:
    """Grupo de segmentos modulares idénticos consecutivos. Si `n == 1`,
    el grupo equivale a un Segment individual."""
    n: int
    segment_label_mm: int
    total_label_mm: int
    is_compensator: bool

    def label(self) -> str:
        if self.n == 1 or self.is_compensator:
            return f"{self.segment_label_mm}"
        return f"{self.n} × {self.segment_label_mm} = {self.total_label_mm}"


def build_segments(consolidated_coords: Sequence[float],
                   *, modular_steps: Sequence[float] = LAYHER_BAY_LENGTHS_M,
                   tol_mm: float = DEFAULT_SNAP_TOL_MM) -> list[Segment]:
    """Convierte coordenadas consolidadas en lista de segmentos snapeados."""
    if len(consolidated_coords) < 2:
        return []
    sorted_c = sorted(consolidated_coords)
    out: list[Segment] = []
    for a, b in zip(sorted_c, sorted_c[1:]):
        L = b - a
        snap = snap_to_modular(L, modular_steps, tol_mm=tol_mm)
        if snap is not None:
            out.append(Segment(
                length_m=snap,
                label_mm=int(round(snap * 1000)),
                modular=True,
                is_compensator=False,
            ))
        else:
            # Redondear a 5 mm
            L_round = round(L * 200) / 200
            out.append(Segment(
                length_m=L_round,
                label_mm=int(round(L_round * 1000)),
                modular=False,
                is_compensator=True,
            ))
    return out


def group_chain(segments: Sequence[Segment]) -> list[ChainGroup]:
    """Agrupa segmentos modulares idénticos consecutivos para notación
    abreviada `N × L = T`. Los compensadores nunca se agrupan."""
    out: list[ChainGroup] = []
    i = 0
    while i < len(segments):
        s = segments[i]
        if s.is_compensator:
            out.append(ChainGroup(
                n=1, segment_label_mm=s.label_mm,
                total_label_mm=s.label_mm, is_compensator=True,
            ))
            i += 1
            continue
        # Buscar consecutivos iguales
        j = i
        while (j < len(segments)
               and not segments[j].is_compensator
               and segments[j].label_mm == s.label_mm):
            j += 1
        n = j - i
        out.append(ChainGroup(
            n=n,
            segment_label_mm=s.label_mm,
            total_label_mm=s.label_mm * n,
            is_compensator=False,
        ))
        i = j
    return out


def total_length_mm(segments: Sequence[Segment]) -> int:
    """Suma de las longitudes en mm enteros — la cota total."""
    return sum(s.label_mm for s in segments)


# ---------------------------------------------------------------------------
# Escala normalizada
# ---------------------------------------------------------------------------

def pick_normalized_scale(
    bbox_w_m: float, bbox_h_m: float,
    avail_w_mm: float, avail_h_mm: float,
    *, scales: Sequence[int] = NORMALIZED_SCALES,
) -> tuple[int, float]:
    """Elige la escala normalizada más fina (denominador menor) que aún
    permite que el bbox quepa en el rect disponible.

    Devuelve (scale_denom, mm_per_m). La cota se lee como `1:scale_denom`.
    Si nada cabe, devuelve la más permisiva.
    """
    for s in sorted(scales):
        mm_per_m = 1000.0 / s
        if bbox_w_m * mm_per_m <= avail_w_mm and bbox_h_m * mm_per_m <= avail_h_mm:
            return s, mm_per_m
    # Fallback
    s = max(scales)
    return s, 1000.0 / s


def pick_best_integer_scale(
    bbox_w_m: float, bbox_h_m: float,
    avail_w_mm: float, avail_h_mm: float,
    *, min_denom: int = 5, max_denom: int = 1000,
) -> tuple[int, float]:
    """Elige el denominador entero **óptimo** (no restringido a las
    escalas normalizadas) para que el bbox llene el rect lo máximo
    posible. Útil en hojas de detalle (tramos) donde el espacio
    importa más que el valor de la escala — el lector consulta cotas
    en mm, no mide con regla.

    Calcula `mm_per_m_max = min(avail_w/bw, avail_h/bh)` y devuelve
    `denom = ceil(1000/mm_per_m_max)` (ceil garantiza que el dibujo
    sigue cabiendo aunque haya redondeo). Clamp `[min_denom, max_denom]`.
    """
    import math
    if bbox_w_m <= 0 or bbox_h_m <= 0:
        return 100, 10.0
    mm_per_m_max = min(avail_w_mm / bbox_w_m, avail_h_mm / bbox_h_m)
    if mm_per_m_max <= 0:
        return max_denom, 1000.0 / max_denom
    denom = math.ceil(1000.0 / mm_per_m_max)
    denom = max(min_denom, min(max_denom, denom))
    return denom, 1000.0 / denom


# ---------------------------------------------------------------------------
# Asignación de etiquetas de eje (A/B/C/... y 1/2/3/...)
# ---------------------------------------------------------------------------

def axis_labels_alpha(n: int) -> list[str]:
    """Genera etiquetas A, B, C, ..., Z, AA, AB, ..."""
    out = []
    for i in range(n):
        if i < 26:
            out.append(chr(ord('A') + i))
        else:
            first = chr(ord('A') + (i // 26) - 1)
            second = chr(ord('A') + (i % 26))
            out.append(first + second)
    return out


def axis_labels_numeric(n: int) -> list[str]:
    return [str(i + 1) for i in range(n)]


# ---------------------------------------------------------------------------
# Producción de cadena estructurada lista para dibujo
# ---------------------------------------------------------------------------

@dataclass
class DimensionChainSpec:
    """Datos completos de una dimensión preparada para dibujo SVG.

    `coords_m`: posiciones consolidadas y ordenadas (m), lo que el dibujo
                debe pintar como puntos de referencia.
    `groups`:  cadenas agrupadas (notación N×L=T cuando hay repetición).
    `total_mm`: suma comprobación.
    """
    coords_m: list[float]
    segments: list[Segment]
    groups: list[ChainGroup]
    total_mm: int

    @property
    def has_compensators(self) -> bool:
        return any(s.is_compensator for s in self.segments)


def prepare_dimension_chain(
    raw_coords_m: Sequence[float],
    *,
    modular_steps: Sequence[float] = LAYHER_BAY_LENGTHS_M,
    consolidation_tol_mm: float = DEFAULT_CONSOLIDATION_TOL_MM,
    snap_tol_mm: float = DEFAULT_SNAP_TOL_MM,
) -> DimensionChainSpec:
    """Pipeline completo: consolida + snap + agrupa, todo en una sola
    llamada para los renderers SVG."""
    consolidated = consolidate_coords(raw_coords_m, tol_mm=consolidation_tol_mm)
    segments = build_segments(consolidated,
                              modular_steps=modular_steps,
                              tol_mm=snap_tol_mm)
    groups = group_chain(segments)
    total = total_length_mm(segments)
    return DimensionChainSpec(
        coords_m=consolidated,
        segments=segments,
        groups=groups,
        total_mm=total,
    )
