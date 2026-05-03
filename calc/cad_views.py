"""Vistas adicionales para el plano CAD: isometría axonométrica y
particionado por tramos de la polilínea de generación.

El alzado frontal global de un andamio en U/L (varios tramos) se aplasta
porque mezcla todas las direcciones en el mismo eje X. Buenas prácticas
de delineación dictan dibujar **un alzado por tramo recto** (Sección
A-B, B-C, ...) cada uno proyectado sobre su plano local. Este módulo
provee:

- `iso_project` — proyección axonométrica clásica (cos30°, sin30°) con
  +Z hacia arriba, lista para serializar a SVG.
- `SegmentFrame` — sistema local 2D de un tramo recto de la polilínea
  (origen + dirección horizontal unitaria + altura = +Z).
- `segment_frames(path_points)` — construye un frame por tramo recto.
- `split_lines_by_segments(lines_3d, path_points)` — reparte cada
  línea al tramo cuyo eje pasa más cerca del midpoint en XY.
- `project_lines_to_segment(lines_3d, frame)` — proyecta a 2D local.

Helpers puros, sin bpy ni SVG. Las distancias permanecen en metros.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, pi, sin
from typing import Sequence


# ---------------------------------------------------------------------------
# Proyección isométrica
# ---------------------------------------------------------------------------

# Ángulos clásicos 30°/30° de la isometría 3/4. cos30 ≈ 0.8660, sin30 = 0.5
_ISO_COS = cos(pi / 6.0)
_ISO_SIN = sin(pi / 6.0)


def iso_project(p3d: tuple[float, float, float]) -> tuple[float, float]:
    """Proyección isométrica clásica con +Z hacia arriba.

    Convención matemática (no SVG): +y' crece hacia arriba en la salida.
    Los renderers SVG deben invertir Y al dibujar.

        x' = (x - y) · cos(30°)
        y' = z - (x + y) · sin(30°)

    Origen → (0, 0). El eje +X (mundo) apunta abajo-derecha en la salida,
    el eje +Y mundo abajo-izquierda, el eje +Z arriba.
    """
    x, y, z = p3d
    return (
        (x - y) * _ISO_COS,
        z - (x + y) * _ISO_SIN,
    )


def iso_bbox(points_3d: Sequence[tuple[float, float, float]]
             ) -> tuple[tuple[float, float], tuple[float, float]]:
    """Bounding box 2D (x', y') tras proyectar todos los puntos.

    Devuelve ((min_x, min_y), (max_x, max_y)). Si la lista está vacía,
    devuelve un bbox unitario (cero division-safe)."""
    if not points_3d:
        return ((0.0, 0.0), (1.0, 1.0))
    xs: list[float] = []
    ys: list[float] = []
    for p in points_3d:
        a, b = iso_project(p)
        xs.append(a)
        ys.append(b)
    return ((min(xs), min(ys)), (max(xs), max(ys)))


# ---------------------------------------------------------------------------
# Frames locales por tramo de polilínea
# ---------------------------------------------------------------------------

@dataclass
class SegmentFrame:
    """Sistema local 2D de un tramo recto de polilínea.

    `origin` es el punto inicial 3D del tramo. `ex_xy` es la dirección
    horizontal unitaria (vector 2D, z=0). `length` es la longitud
    horizontal del tramo. El plano local es (ex_xy, +Z), de modo que la
    proyección produce un alzado frontal local del tramo:

        u = (P - origin) · ex_xy   (longitudinal sobre el tramo)
        v = P.z                    (altura)
    """
    index: int
    origin: tuple[float, float, float]
    end: tuple[float, float, float]
    ex_xy: tuple[float, float]
    length: float

    def project(self, p3d: tuple[float, float, float]
                ) -> tuple[float, float]:
        """Proyecta P al plano local (u, v)."""
        dx = p3d[0] - self.origin[0]
        dy = p3d[1] - self.origin[1]
        u = dx * self.ex_xy[0] + dy * self.ex_xy[1]
        return (u, p3d[2])

    def perp_distance_xy(self, p3d: tuple[float, float, float]) -> float:
        """Distancia perpendicular en XY al eje del tramo, penalizando
        puntos fuera del intervalo [0, length] (les sumamos la distancia
        al extremo más cercano).

        Esto hace que `argmin(perp_distance_xy)` sobre los frames elija
        el tramo cuyo eje pasa cerca del punto en su intervalo, no un
        eje paralelo lejano.
        """
        dx = p3d[0] - self.origin[0]
        dy = p3d[1] - self.origin[1]
        u = dx * self.ex_xy[0] + dy * self.ex_xy[1]
        perp_x = dx - u * self.ex_xy[0]
        perp_y = dy - u * self.ex_xy[1]
        perp = hypot(perp_x, perp_y)
        if u < 0:
            return hypot(perp, -u)
        if u > self.length:
            return hypot(perp, u - self.length)
        return perp


def segment_frames(
    path_points: Sequence[tuple[float, float, float]],
) -> list[SegmentFrame]:
    """Construye un SegmentFrame por cada par consecutivo de path_points.

    Tramos de longitud horizontal nula (postes verticales) se descartan.
    """
    out: list[SegmentFrame] = []
    for i in range(len(path_points) - 1):
        p0 = tuple(path_points[i])
        p1 = tuple(path_points[i + 1])
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        L = hypot(dx, dy)
        if L < 1e-6:
            continue
        ex = (dx / L, dy / L)
        out.append(SegmentFrame(
            index=len(out),
            origin=p0,
            end=p1,
            ex_xy=ex,
            length=L,
        ))
    return out


# ---------------------------------------------------------------------------
# Particionado de líneas por tramo
# ---------------------------------------------------------------------------

def line_midpoint(line: dict) -> tuple[float, float, float]:
    """Midpoint 3D de una línea con campos p1, p2."""
    p1, p2 = line["p1"], line["p2"]
    return (
        0.5 * (p1[0] + p2[0]),
        0.5 * (p1[1] + p2[1]),
        0.5 * (p1[2] + p2[2]),
    )


def split_lines_by_segments(
    lines_3d: Sequence[dict],
    path_points: Sequence[tuple[float, float, float]],
) -> list[list[dict]]:
    """Reparte cada línea al tramo de la polilínea más cercano por
    distancia horizontal del midpoint al eje del tramo.

    Devuelve `len(segment_frames(path_points))` buckets. Si la polilínea
    no define tramos (≤ 1 punto o todos colineales con dz=0 horizontal=0),
    devuelve `[list(lines_3d)]` — todo en un único bucket.
    """
    frames = segment_frames(path_points)
    if not frames:
        return [list(lines_3d)]

    buckets: list[list[dict]] = [[] for _ in frames]
    for ln in lines_3d:
        mp = line_midpoint(ln)
        best_idx = 0
        best_d = frames[0].perp_distance_xy(mp)
        for i in range(1, len(frames)):
            d = frames[i].perp_distance_xy(mp)
            if d < best_d:
                best_d = d
                best_idx = i
        buckets[best_idx].append(ln)
    return buckets


def project_lines_to_segment(
    lines_3d: Sequence[dict],
    frame: SegmentFrame,
) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
    """Proyecta líneas 3D al alzado frontal local del tramo.

    Devuelve la misma estructura tuple-based que consume `_draw_view` en
    `cad_plan.py`: `[(p1_2d, p2_2d, category), ...]`.
    """
    out: list[tuple[tuple[float, float], tuple[float, float], str]] = []
    for ln in lines_3d:
        a = frame.project(ln["p1"])
        b = frame.project(ln["p2"])
        out.append((a, b, ln.get("category", "pole")))
    return out


# ---------------------------------------------------------------------------
# Etiquetas de tramo (A-B, B-C, ...)
# ---------------------------------------------------------------------------

def segment_label(index: int, n_segments: int) -> str:
    """Devuelve la etiqueta `"A-B"`, `"B-C"`, ... para el tramo `index`.

    Para `n_segments > 25` hay overflow alfabético (Z-AA), pero los
    andamios prácticos no llegan a tantos tramos.
    """
    if n_segments <= 0:
        return ""
    a = chr(ord("A") + index)
    b = chr(ord("A") + index + 1)
    return f"{a}-{b}"
