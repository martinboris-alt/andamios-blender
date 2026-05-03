"""Plano técnico CAD del andamio (estilo NX / Inventor).

Genera SVG vectorial en formato de hoja A3/A4 con:
    - Marco doble de hoja
    - Vistas ortográficas 1ª-ángulo: alzado frontal + planta + alzado lateral
    - Vista isométrica 3/4 esquemática como referencia
    - Cotas dimensionales automáticas (totales y por planta)
    - Cuadro de rotulación tipo NX en la esquina inferior derecha
    - Tabla BOM integrada (cantidad + peso por categoría)

Salida: string SVG y wrapper HTML autocontenido con CSS `@page` que permite
imprimir a PDF a escala real (Chrome/Firefox respetan el tamaño físico de
la hoja).

Consume `calc.bom.enumerate_scaffold_objects` para los datos de líneas y
metadatos. Helpers puros sin dependencia de bpy excepto en el extractor.
"""

from __future__ import annotations

import html as _html
from datetime import datetime


# ---------------------------------------------------------------------------
# Constantes de papel
# ---------------------------------------------------------------------------

PAPER_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
}


def paper_dims(paper: str = "A3", orientation: str = "landscape") -> tuple[float, float]:
    short, long = PAPER_SIZES_MM[paper]
    return (long, short) if orientation == "landscape" else (short, long)


# ---------------------------------------------------------------------------
# Estilos por categoría: (color, grosor en mm, dasharray | None)
# ---------------------------------------------------------------------------

_CATEGORY_STROKES: dict[str, tuple[str, float, str | None]] = {
    "pole":         ("#000000", 0.8,  None),
    "ledger_floor": ("#000000", 0.6,  None),
    "ledger_rail":  ("#666666", 0.35, None),
    "toe":          ("#888888", 0.3,  None),
    "brace":        ("#0a3055", 0.55, None),
    "tie":          ("#992222", 0.55, None),
    "husillo":      ("#000000", 0.5,  None),
    # Bandeja: línea discontinua marrón a la altura del deck — diferente
    # a los travesaños para no confundirse al leer el alzado/planta.
    "plank":        ("#a06030", 0.4,  "1.6,1.0"),
}

# Categorías que NO se extraen como línea de andamio:
# - trapdoor, ladder: ya tienen markers funcionales (T / E) en planta;
#   añadir su geometría como líneas oscurecería más que aclararía.
# - rosette: hay cientos (cada 0,5 m por poste); inundarían el dibujo.
_SKIP_LINE_CATEGORIES: set[str] = {"trapdoor", "ladder", "rosette"}


# ---------------------------------------------------------------------------
# Proyecciones 3D → 2D
# ---------------------------------------------------------------------------

def project_to_view(p3d: tuple[float, float, float], view: str) -> tuple[float, float]:
    """Proyecta un punto 3D a 2D según vista. Coords en metros, +X derecha,
    +Y arriba (convención matemática, no SVG)."""
    x, y, z = p3d
    if view == "front":
        return (x, z)
    if view == "side":
        return (y, z)
    if view == "top":
        return (x, y)
    raise ValueError(f"Vista desconocida: {view!r}")


def bbox_of_lines(lines_2d: list) -> tuple[tuple[float, float], tuple[float, float]]:
    """Bounding box 2D de una lista de líneas (cada una con (p1, p2, ...))."""
    if not lines_2d:
        return ((0.0, 0.0), (1.0, 1.0))
    xs, ys = [], []
    for ln in lines_2d:
        p1, p2 = ln[0], ln[1]
        xs.extend((p1[0], p2[0]))
        ys.extend((p1[1], p2[1]))
    return ((min(xs), min(ys)), (max(xs), max(ys)))


def fit_in_rect(
    bbox_min: tuple[float, float],
    bbox_max: tuple[float, float],
    rect: tuple[float, float, float, float],
    *,
    padding_mm: float = 8.0,
) -> tuple[float, float, float]:
    """Calcula transform (x_off, y_off, scale) para que el bbox 2D quepa
    centrado dentro de `rect = (x, y, w, h)` en mm.
    Y se invierte porque SVG va de arriba hacia abajo.
    Scale en mm/m.
    """
    rx, ry, rw, rh = rect
    bw = bbox_max[0] - bbox_min[0]
    bh = bbox_max[1] - bbox_min[1]
    if bw <= 0:
        bw = 1
    if bh <= 0:
        bh = 1
    avail_w = max(rw - 2 * padding_mm, 1)
    avail_h = max(rh - 2 * padding_mm, 1)
    scale = min(avail_w / bw, avail_h / bh)
    used_w = bw * scale
    used_h = bh * scale
    cx = rx + (rw - used_w) / 2
    cy_top = ry + (rh - used_h) / 2  # parte superior del bbox dibujado
    x_off = cx - bbox_min[0] * scale
    # Y_world máximo cae en cy_top; y SVG = cy_top + (y_max - y_world) * scale
    # Re-derivamos: y_svg = y_off - y_world * scale
    # y cuando y_world = bbox_max[1] queremos y_svg = cy_top
    # → y_off = cy_top + bbox_max[1] * scale
    y_off = cy_top + bbox_max[1] * scale
    return (x_off, y_off, scale)


def project_world_to_svg(
    p2d: tuple[float, float], transform: tuple[float, float, float],
) -> tuple[float, float]:
    x_off, y_off, scale = transform
    return (x_off + p2d[0] * scale, y_off - p2d[1] * scale)


# ---------------------------------------------------------------------------
# Helpers SVG
# ---------------------------------------------------------------------------

def _esc(s: object) -> str:
    return _html.escape(str(s))


def _svg_line(p1, p2, stroke="#000", width=0.3, dash=None) -> str:
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" '
            f'x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" '
            f'stroke="{stroke}" stroke-width="{width}"{extra} />')


def _svg_text(x, y, text, *, font_size=3.0, anchor="middle", weight="normal",
              color="#000") -> str:
    return (f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-size="{font_size}" text-anchor="{anchor}" '
            f'fill="{color}" font-weight="{weight}">'
            f'{_esc(text)}</text>')


def _svg_rect(x, y, w, h, *, stroke="#000", width=0.3, fill="none") -> str:
    return (f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{width}" />')


def _format_mm(distance_m: float) -> str:
    """Formato técnico: longitudes en mm, sin decimales para >= 100 mm,
    1 decimal para distancias menores."""
    mm = distance_m * 1000.0
    if abs(mm) >= 100:
        return f"{mm:.0f} mm"
    return f"{mm:.1f} mm"


def _dim_line_h(x1, x2, y, label, *, font_size=2.8, stroke="#0a3055",
                ext_above=0.0) -> str:
    """Cota horizontal entre x1 y x2 a la altura y, con etiqueta en el centro.
    Dibuja flechas en los extremos y línea horizontal. `ext_above` añade
    líneas auxiliares verticales que conectan con la cota desde arriba."""
    if x1 > x2:
        x1, x2 = x2, x1
    arrow = 1.4
    parts = [
        _svg_line((x1, y), (x2, y), stroke=stroke, width=0.25),
        f'<polygon points="{x1:.2f},{y:.2f} {x1+arrow:.2f},{y-arrow*0.4:.2f} '
        f'{x1+arrow:.2f},{y+arrow*0.4:.2f}" fill="{stroke}" />',
        f'<polygon points="{x2:.2f},{y:.2f} {x2-arrow:.2f},{y-arrow*0.4:.2f} '
        f'{x2-arrow:.2f},{y+arrow*0.4:.2f}" fill="{stroke}" />',
        _svg_text((x1+x2)/2, y - 1.2, label,
                  font_size=font_size, color=stroke, weight="600"),
    ]
    if ext_above > 0:
        parts.append(_svg_line((x1, y - ext_above), (x1, y + 0.5),
                               stroke=stroke, width=0.18))
        parts.append(_svg_line((x2, y - ext_above), (x2, y + 0.5),
                               stroke=stroke, width=0.18))
    return "\n".join(parts)


def _dim_line_v(x, y1, y2, label, *, font_size=2.8, stroke="#0a3055",
                ext_right=0.0) -> str:
    if y1 > y2:
        y1, y2 = y2, y1
    arrow = 1.4
    parts = [
        _svg_line((x, y1), (x, y2), stroke=stroke, width=0.25),
        f'<polygon points="{x:.2f},{y1:.2f} {x-arrow*0.4:.2f},{y1+arrow:.2f} '
        f'{x+arrow*0.4:.2f},{y1+arrow:.2f}" fill="{stroke}" />',
        f'<polygon points="{x:.2f},{y2:.2f} {x-arrow*0.4:.2f},{y2-arrow:.2f} '
        f'{x+arrow*0.4:.2f},{y2-arrow:.2f}" fill="{stroke}" />',
        f'<text x="{x-1.5:.2f}" y="{(y1+y2)/2:.2f}" '
        f'font-size="{font_size}" text-anchor="middle" '
        f'fill="{stroke}" font-weight="600" '
        f'transform="rotate(-90 {x-1.5:.2f} {(y1+y2)/2:.2f})">'
        f'{_esc(label)}</text>',
    ]
    if ext_right > 0:
        parts.append(_svg_line((x - 0.5, y1), (x + ext_right, y1),
                               stroke=stroke, width=0.18))
        parts.append(_svg_line((x - 0.5, y2), (x + ext_right, y2),
                               stroke=stroke, width=0.18))
    return "\n".join(parts)


def _chain_dim_h(svg_xs: list[float], y_dim: float, *,
                 segment_labels: list[str] | None = None,
                 font_size: float = 2.4,
                 stroke: str = "#0a3055",
                 ext_above: float = 4.0) -> str:
    """Cadena de cotas horizontales entre puntos consecutivos en `svg_xs`.

    `segment_labels`: si None se autogeneran usando _format_mm en función
    de la distancia entre xs (asumiendo que vienen en escala SVG y
    necesitamos convertir). Por simplicidad el caller pasa labels.
    """
    if len(svg_xs) < 2:
        return ""
    xs = list(sorted(svg_xs))
    parts: list[str] = []
    arrow = 1.0
    # Líneas auxiliares verticales (extension lines)
    for x in xs:
        parts.append(_svg_line((x, y_dim - ext_above), (x, y_dim + 0.5),
                               stroke=stroke, width=0.18))
    # Segmentos
    for i in range(len(xs) - 1):
        x1, x2 = xs[i], xs[i+1]
        if x2 - x1 < 0.5:        # demasiado cerca: salta
            continue
        parts.append(_svg_line((x1, y_dim), (x2, y_dim),
                               stroke=stroke, width=0.22))
        parts.append(
            f'<polygon points="{x1:.2f},{y_dim:.2f} '
            f'{x1+arrow:.2f},{y_dim-arrow*0.4:.2f} '
            f'{x1+arrow:.2f},{y_dim+arrow*0.4:.2f}" fill="{stroke}" />'
        )
        parts.append(
            f'<polygon points="{x2:.2f},{y_dim:.2f} '
            f'{x2-arrow:.2f},{y_dim-arrow*0.4:.2f} '
            f'{x2-arrow:.2f},{y_dim+arrow*0.4:.2f}" fill="{stroke}" />'
        )
        label = segment_labels[i] if segment_labels else ""
        parts.append(_svg_text((x1+x2)/2, y_dim - 0.8, label,
                               font_size=font_size, color=stroke, weight="500"))
    return "\n".join(parts)


def _chain_dim_v(svg_ys: list[float], x_dim: float, *,
                 segment_labels: list[str] | None = None,
                 font_size: float = 2.4,
                 stroke: str = "#0a3055",
                 ext_left: float = 4.0) -> str:
    """Cadena de cotas verticales entre puntos consecutivos."""
    if len(svg_ys) < 2:
        return ""
    ys = list(sorted(svg_ys))   # SVG: menor Y es arriba
    parts: list[str] = []
    arrow = 1.0
    for y in ys:
        parts.append(_svg_line((x_dim - 0.5, y), (x_dim + ext_left, y),
                               stroke=stroke, width=0.18))
    for i in range(len(ys) - 1):
        y1, y2 = ys[i], ys[i+1]
        if y2 - y1 < 0.5:
            continue
        parts.append(_svg_line((x_dim, y1), (x_dim, y2),
                               stroke=stroke, width=0.22))
        parts.append(
            f'<polygon points="{x_dim:.2f},{y1:.2f} '
            f'{x_dim-arrow*0.4:.2f},{y1+arrow:.2f} '
            f'{x_dim+arrow*0.4:.2f},{y1+arrow:.2f}" fill="{stroke}" />'
        )
        parts.append(
            f'<polygon points="{x_dim:.2f},{y2:.2f} '
            f'{x_dim-arrow*0.4:.2f},{y2-arrow:.2f} '
            f'{x_dim+arrow*0.4:.2f},{y2-arrow:.2f}" fill="{stroke}" />'
        )
        label = segment_labels[i] if segment_labels else ""
        cy = (y1 + y2) / 2
        parts.append(
            f'<text x="{x_dim-1.0:.2f}" y="{cy:.2f}" '
            f'font-size="{font_size}" text-anchor="middle" '
            f'fill="{stroke}" font-weight="500" '
            f'transform="rotate(-90 {x_dim-1.0:.2f} {cy:.2f})">'
            f'{_esc(label)}</text>'
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Cuadro de rotulación tipo NX
# ---------------------------------------------------------------------------

def _title_block(
    rect: tuple[float, float, float, float],
    *,
    project_name: str,
    drawing_title: str,
    scale_label: str,
    paper: str,
    author: str,
    weight_kg: float,
    n_pieces: int,
    revision: str = "A",
    material: str = "S235JR · CHS Ø48,3×3,2",
    validation: dict | None = None,
) -> str:
    """Renderiza un cuadro de rotulación tipo NX en `rect` (x, y, w, h) en mm.

    Layout:
        +------------------+--------------+
        | Proyecto         | Empresa      |
        +------------------+--------------+
        | Título del plano                |
        +-------+--------+--------+-------+
        | Fecha | Esc.   | Autor  | Rev.  |
        +-------+--------+--------+-------+
        | Material                        |
        +------+-------+----------+-------+
        | Peso | Pzas. | Hoja     | Pap.  |
        +------+-------+----------+-------+
    """
    x, y, w, h = rect
    parts = [_svg_rect(x, y, w, h, width=0.5)]

    # Filas de altura proporcional
    row_heights = [h*0.18, h*0.22, h*0.16, h*0.16, h*0.14, h*0.14]
    cy = y
    for rh in row_heights:
        cy += rh
        if cy < y + h - 0.5:
            parts.append(_svg_line((x, cy), (x + w, cy), width=0.3))

    # Definir filas
    r1_y = y;             r1_h = row_heights[0]
    r2_y = r1_y + r1_h;   r2_h = row_heights[1]
    r3_y = r2_y + r2_h;   r3_h = row_heights[2]
    r4_y = r3_y + r3_h;   r4_h = row_heights[3]
    r5_y = r4_y + r4_h;   r5_h = row_heights[4]
    r6_y = r5_y + r5_h;   r6_h = row_heights[5]

    # Fila 1: Proyecto / Empresa (split a la mitad)
    parts.append(_svg_line((x + w*0.6, r1_y), (x + w*0.6, r1_y + r1_h), width=0.3))
    parts.append(_svg_text(x + 1.5, r1_y + 2.6, "PROYECTO", font_size=1.8,
                           anchor="start", color="#666"))
    parts.append(_svg_text(x + 1.5, r1_y + r1_h - 0.8, project_name,
                           font_size=3.0, anchor="start", weight="600"))
    parts.append(_svg_text(x + w*0.6 + 1.5, r1_y + 2.6, "EMPRESA",
                           font_size=1.8, anchor="start", color="#666"))
    parts.append(_svg_text(x + w*0.6 + 1.5, r1_y + r1_h - 0.8,
                           "Andamios Addon", font_size=3.0,
                           anchor="start", weight="600"))

    # Fila 2: Título del plano
    parts.append(_svg_text(x + 1.5, r2_y + 2.6, "TÍTULO DEL PLANO",
                           font_size=1.8, anchor="start", color="#666"))
    parts.append(_svg_text(x + w/2, r2_y + r2_h - 1, drawing_title,
                           font_size=4.5, anchor="middle", weight="700"))

    # Fila 3: Fecha / Escala / Autor / Revisión (cuatro celdas)
    qw = w / 4
    for i in range(1, 4):
        parts.append(_svg_line((x + i*qw, r3_y), (x + i*qw, r3_y + r3_h), width=0.3))
    cells_3 = [
        ("FECHA",  datetime.now().strftime("%Y-%m-%d")),
        ("ESCALA", scale_label),
        ("AUTOR",  author or "—"),
        ("REV.",   revision),
    ]
    for i, (lbl, val) in enumerate(cells_3):
        cx = x + i*qw
        parts.append(_svg_text(cx + 1.0, r3_y + 2.0, lbl, font_size=1.7,
                               anchor="start", color="#666"))
        parts.append(_svg_text(cx + qw/2, r3_y + r3_h - 1, val,
                               font_size=3.0, anchor="middle", weight="500"))

    # Fila 4: Material (full width)
    parts.append(_svg_text(x + 1.5, r4_y + 2.0, "MATERIAL", font_size=1.7,
                           anchor="start", color="#666"))
    parts.append(_svg_text(x + w/2, r4_y + r4_h - 1, material,
                           font_size=2.8, anchor="middle"))

    # Fila 5: Peso / Piezas / Hoja / Papel
    for i in range(1, 4):
        parts.append(_svg_line((x + i*qw, r5_y), (x + i*qw, r5_y + r5_h), width=0.3))
    cells_5 = [
        ("PESO TOTAL", f"{weight_kg:.0f} kg"),
        ("PIEZAS",     f"{n_pieces}"),
        ("HOJA",       "1 / 1"),
        ("FORMATO",    paper),
    ]
    for i, (lbl, val) in enumerate(cells_5):
        cx = x + i*qw
        parts.append(_svg_text(cx + 1.0, r5_y + 1.8, lbl, font_size=1.6,
                               anchor="start", color="#666"))
        parts.append(_svg_text(cx + qw/2, r5_y + r5_h - 0.8, val,
                               font_size=2.6, anchor="middle"))

    # Fila 6: validación estructural (si hay datos) o firma
    if validation:
        # Caja diferenciada con fondo según el estado
        bg = {
            "ok":      "#e8f8ee",
            "warning": "#fef5e7",
            "fail":    "#f9d6d5",
        }.get(validation.get("level", ""), "#f4f6fa")
        text_color = {
            "ok":      "#1f7a3e",
            "warning": "#9a6e0a",
            "fail":    "#a01f1f",
        }.get(validation.get("level", ""), "#0a3055")
        # Pintar fondo de la fila
        parts.append(
            f'<rect x="{x:.2f}" y="{r6_y:.2f}" '
            f'width="{w:.2f}" height="{r6_h:.2f}" '
            f'fill="{bg}" stroke="none" />'
        )
        # Vuelve a dibujar el borde superior
        parts.append(_svg_line((x, r6_y), (x + w, r6_y), width=0.3))
        parts.append(_svg_line((x, r6_y + r6_h),
                               (x + w, r6_y + r6_h), width=0.3))
        # Texto: STATUS · util · δ_max · combinación
        status_text = validation.get("status_text", "")
        details = validation.get("details", "")
        parts.append(_svg_text(x + 1.5, r6_y + r6_h * 0.55, status_text,
                               font_size=2.6, anchor="start", weight="700",
                               color=text_color))
        parts.append(_svg_text(x + w - 1.5, r6_y + r6_h * 0.55, details,
                               font_size=2.0, anchor="end",
                               color=text_color))
        parts.append(_svg_text(x + w/2, r6_y + r6_h - 0.6,
                               "VALIDACIÓN ESTRUCTURAL · EN 1993-1-1 + EN 12811-1",
                               font_size=1.5, anchor="middle", color="#666"))
    else:
        parts.append(_svg_text(x + w/2, r6_y + r6_h - 0.8,
                               "Generado automáticamente · Andamios Addon FEM",
                               font_size=1.8, anchor="middle", color="#666"))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tabla BOM integrada
# ---------------------------------------------------------------------------

def _bom_table(
    rect: tuple[float, float, float, float],
    summary: dict,
) -> str:
    """Tabla BOM dentro de `rect`. Una fila por categoría + total."""
    x, y, w, h = rect
    parts = [_svg_rect(x, y, w, h, width=0.5)]

    title_h = 5
    parts.append(_svg_line((x, y + title_h), (x + w, y + title_h), width=0.4))
    parts.append(_svg_text(x + w/2, y + title_h - 1, "LISTA DE MATERIALES",
                           font_size=2.8, anchor="middle", weight="700"))

    # Cabecera tabla
    rows = list(summary.get("by_category", []))
    n_rows = len(rows) + 1   # +1 para fila TOTAL
    if n_rows == 0:
        return "\n".join(parts)

    body_h = h - title_h
    row_h = body_h / (n_rows + 1)   # +1 para la cabecera de columnas

    # Columnas: Categoría 50%, Cant 18%, Tubo (m) 16%, Peso 16%
    col_x = [x, x + w*0.50, x + w*0.68, x + w*0.84, x + w]

    # Cabecera columnas
    hdr_y = y + title_h
    parts.append(_svg_line((x, hdr_y + row_h), (x + w, hdr_y + row_h), width=0.3))
    headers = ["Categoría", "Cant.", "Tubo (m)", "Peso (kg)"]
    for i, hdr in enumerate(headers):
        parts.append(_svg_text(
            (col_x[i] + col_x[i+1]) / 2, hdr_y + row_h - 1, hdr,
            font_size=2.2, weight="600", color="#444",
        ))

    # Líneas verticales entre columnas
    for cx in col_x[1:-1]:
        parts.append(_svg_line((cx, hdr_y), (cx, y + h), width=0.2))

    # Filas
    cy = hdr_y + row_h
    for entry in rows:
        cy += row_h
        parts.append(_svg_line((x, cy), (x + w, cy), width=0.15))
        # Categoría
        parts.append(_svg_text(col_x[0] + 1.0, cy - 1, entry["label"],
                               font_size=2.2, anchor="start"))
        # Cantidad
        parts.append(_svg_text((col_x[1]+col_x[2])/2, cy - 1,
                               str(entry["count"]), font_size=2.2))
        # Tubo (m)
        tube_m = entry.get("tube_length_m", 0.0)
        parts.append(_svg_text((col_x[2]+col_x[3])/2, cy - 1,
                               f"{tube_m:.1f}" if tube_m else "—",
                               font_size=2.2))
        # Peso
        parts.append(_svg_text((col_x[3]+col_x[4])/2, cy - 1,
                               f"{entry['weight_kg']:.1f}", font_size=2.2))

    # Fila TOTAL
    cy += row_h
    parts.append(_svg_line((x, cy - row_h), (x + w, cy - row_h), width=0.4))
    parts.append(_svg_text(col_x[0] + 1.0, cy - 1, "TOTAL",
                           font_size=2.4, anchor="start", weight="700"))
    parts.append(_svg_text((col_x[1]+col_x[2])/2, cy - 1,
                           str(summary.get("total_pieces", 0)),
                           font_size=2.4, weight="700"))
    parts.append(_svg_text((col_x[2]+col_x[3])/2, cy - 1,
                           f"{summary.get('total_tube_length_m', 0):.1f}",
                           font_size=2.4, weight="700"))
    parts.append(_svg_text((col_x[3]+col_x[4])/2, cy - 1,
                           f"{summary.get('total_weight_kg', 0):.1f}",
                           font_size=2.4, weight="700"))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Vista (rectángulo con líneas + bbox + cotas + título)
# ---------------------------------------------------------------------------

def _draw_dim_chain(
    svg_xs: list[float],
    y_dim: float,
    groups: list,
    *,
    font_size: float = 2.5,
    stroke: str = "#0a3055",
    ext_above: float = 4.0,
    horizontal: bool = True,
) -> str:
    """Dibuja una cadena de cotas con notación N×L=T y compensadores marcados.

    `svg_xs` lista de coordenadas SVG de cada montante (n+1 valores para
    n segmentos). `groups` lista de ChainGroup (cad_dim) — su orden debe
    coincidir con los segmentos entre xs consecutivos.
    """
    if len(svg_xs) < 2 or not groups:
        return ""
    parts: list[str] = []
    arrow = 1.2
    # Líneas auxiliares verticales (extension lines)
    for x in svg_xs:
        parts.append(_svg_line((x, y_dim - ext_above), (x, y_dim + 0.5),
                               stroke=stroke, width=0.18))

    # Por cada grupo, abarca segmentos consecutivos en svg_xs
    seg_idx = 0
    for g in groups:
        n_seg = g.n
        if seg_idx + n_seg > len(svg_xs) - 1:
            break
        x1 = svg_xs[seg_idx]
        x2 = svg_xs[seg_idx + n_seg]
        if x1 > x2:
            x1, x2 = x2, x1
        # Línea + flechas
        parts.append(_svg_line((x1, y_dim), (x2, y_dim),
                               stroke=stroke, width=0.22))
        parts.append(
            f'<polygon points="{x1:.2f},{y_dim:.2f} '
            f'{x1+arrow:.2f},{y_dim-arrow*0.4:.2f} '
            f'{x1+arrow:.2f},{y_dim+arrow*0.4:.2f}" fill="{stroke}" />'
        )
        parts.append(
            f'<polygon points="{x2:.2f},{y_dim:.2f} '
            f'{x2-arrow:.2f},{y_dim-arrow*0.4:.2f} '
            f'{x2-arrow:.2f},{y_dim+arrow*0.4:.2f}" fill="{stroke}" />'
        )
        # Etiqueta — compensadores en color rojo apagado para distinguir
        label_color = "#9b2226" if g.is_compensator else stroke
        label_weight = "700" if g.is_compensator else "600"
        parts.append(_svg_text((x1+x2)/2, y_dim - 0.8, g.label(),
                               font_size=font_size, color=label_color,
                               weight=label_weight))
        if g.is_compensator:
            # Anotación pequeña debajo
            parts.append(_svg_text((x1+x2)/2, y_dim + 2.5,
                                   "compens.", font_size=1.7,
                                   color=label_color))
        seg_idx += n_seg
    return "\n".join(parts)


def _draw_axis_labels(
    svg_xs: list[float], y_pos: float, labels: list[str],
    *, radius: float = 3.5,
) -> str:
    """Burbujas con letras/números de eje encima de cada montante."""
    parts: list[str] = []
    for x, lab in zip(svg_xs, labels):
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y_pos:.2f}" r="{radius:.2f}" '
            f'fill="white" stroke="#0a3055" stroke-width="0.4" />'
        )
        parts.append(_svg_text(x, y_pos + radius * 0.4, lab,
                               font_size=3.0, weight="700",
                               color="#0a3055"))
    return "\n".join(parts)


def _draw_view(
    rect: tuple[float, float, float, float],
    lines_2d: list,
    *,
    view_label: str,
    show_dimensions: bool = True,
    chain_dim_x: list[float] | None = None,
    chain_dim_y: list[float] | None = None,
    axes_x_labels: list[str] | None = None,
    axes_y_labels: list[str] | None = None,
    modular_steps_x: tuple[float, ...] | None = None,
    modular_steps_y: tuple[float, ...] | None = None,
    fixed_scale_denom: int | None = None,
    fit_to_canvas: bool = False,
) -> tuple[str, float, int, tuple[float, float, float] | None]:
    """Dibuja una vista 2D del andamio dentro de `rect` cumpliendo
    UNE-EN ISO 129-1: tres cadenas jerárquicas (parcial / ejes / total) con
    snap modular Layher, sistema de ejes A/B/C... y escala normalizada.

    Devuelve (svg_str, scale_mm_per_m, scale_denom, transform). El
    transform es la tupla (x_off, y_off, scale_mm_per_m) que el caller
    puede reutilizar para superponer markers/etiquetas funcionales sobre
    el mismo encuadre. Es None cuando no hubo datos que dibujar.

    Si `fit_to_canvas=True` se descarta la restricción de escala
    normalizada (1:20/1:50/1:100/1:200/1:500) y se elige el denominador
    entero óptimo que llene el lienzo. Útil en hojas de detalle (tramos)
    donde el aprovechamiento de espacio importa más que el valor exacto
    de la escala — el lector consulta cotas en mm, no mide con regla.
    """
    from .cad_dim import (
        LAYHER_BAY_LENGTHS_M,
        LAYHER_FLOOR_HEIGHTS_M,
        prepare_dimension_chain,
        pick_best_integer_scale,
        pick_normalized_scale,
    )

    # Márgenes FIJOS por vista — la geometría se ancla a la esquina superior
    # derecha del área restante para que SIEMPRE haya espacio reservado para
    # cotas/ejes a la izquierda y abajo, sin riesgo de salirse del rect.
    LEFT_MARGIN = 24.0     # cota total Y + cota a ejes Y + globos eje Y
    BOTTOM_MARGIN = 22.0   # cota total X + cota a ejes X
    TOP_MARGIN = 10.0      # título de vista + globos eje X
    RIGHT_MARGIN = 4.0

    rx, ry, rw, rh = rect
    parts = [_svg_rect(rx, ry, rw, rh, width=0.4)]
    # Título de la vista (≥ 5 mm en papel)
    parts.append(_svg_text(rx + 2, ry + 5, view_label,
                           font_size=4.5, anchor="start", weight="700",
                           color="#0a3055"))

    if not lines_2d:
        parts.append(_svg_text(rx + rw/2, ry + rh/2,
                               "(sin datos)", font_size=3, color="#888"))
        return "\n".join(parts), 1.0, 100, None

    bmin, bmax = bbox_of_lines(lines_2d)
    bw_m = bmax[0] - bmin[0]
    bh_m = bmax[1] - bmin[1]

    # Área disponible para la geometría (después de reservar márgenes)
    geom_x = rx + LEFT_MARGIN
    geom_y = ry + TOP_MARGIN
    geom_w = max(rw - LEFT_MARGIN - RIGHT_MARGIN, 30)
    geom_h = max(rh - TOP_MARGIN - BOTTOM_MARGIN, 30)

    # Escala que cabe en `geom_w × geom_h`. Tres modos:
    #   - fixed_scale_denom: forzada por el caller (planta y lateral del
    #     overview comparten escala con el alzado para coherencia)
    #   - fit_to_canvas: óptimo entero (hojas de detalle / tramo)
    #   - default: la más fina entre las normalizadas ISO 5455
    if fixed_scale_denom is not None:
        scale_denom = fixed_scale_denom
        mm_per_m = 1000.0 / scale_denom
    elif fit_to_canvas:
        scale_denom, mm_per_m = pick_best_integer_scale(
            bw_m, bh_m, geom_w, geom_h,
        )
    else:
        scale_denom, mm_per_m = pick_normalized_scale(
            bw_m, bh_m, geom_w, geom_h,
        )

    # Anclar bbox a la esquina superior izquierda del área de geometría —
    # las cotas y ejes se dibujarán a la izquierda y abajo del bbox, dentro
    # de los márgenes reservados.
    used_w = bw_m * mm_per_m
    used_h = bh_m * mm_per_m
    # Centrar la geometría dentro del área (sin invadir márgenes)
    cx = geom_x + (geom_w - used_w) / 2
    cy_top = geom_y + (geom_h - used_h) / 2
    x_off = cx - bmin[0] * mm_per_m
    y_off = cy_top + bmax[1] * mm_per_m
    transform = (x_off, y_off, mm_per_m)

    # Líneas del andamio
    for ln in lines_2d:
        p1, p2, cat = ln[0], ln[1], ln[2]
        stroke, width, dash = _CATEGORY_STROKES.get(cat, ("#444", 0.4, None))
        a = project_world_to_svg(p1, transform)
        b = project_world_to_svg(p2, transform)
        parts.append(_svg_line(a, b, stroke=stroke, width=width, dash=dash))

    # Cotas — sistema jerárquico ISO 129-1 dentro de los márgenes reservados
    if show_dimensions:
        a_min = project_world_to_svg(bmin, transform)
        a_max = project_world_to_svg(bmax, transform)

        # ---- Eje X (cadena horizontal abajo) ----
        if chain_dim_x and len(chain_dim_x) >= 2:
            spec_x = prepare_dimension_chain(
                chain_dim_x,
                modular_steps=modular_steps_x or LAYHER_BAY_LENGTHS_M,
            )
            xs_svg = [project_world_to_svg((c, 0), transform)[0]
                      for c in spec_x.coords_m]
            # Cadena A EJES — 8 mm bajo el bbox (≥ ISO ext mínima)
            chain_y = a_min[1] + 8
            parts.append(_draw_dim_chain(
                xs_svg, chain_y, spec_x.groups, font_size=3.0,
            ))
            # Cota TOTAL — 9 mm más abajo (separación ≥ 7 mm ISO 129-1 §5.4)
            total_y = chain_y + 10
            parts.append(_dim_line_h(
                a_min[0], a_max[0], total_y,
                f"{spec_x.total_mm} mm",
                font_size=3.5, ext_above=2.0,
            ))
            # Globos de eje encima del dibujo (en el TOP_MARGIN)
            if axes_x_labels and len(axes_x_labels) == len(xs_svg):
                axes_y = a_max[1] - 4
                parts.append(_draw_axis_labels(
                    xs_svg, axes_y, axes_x_labels, radius=2.8,
                ))

        # ---- Eje Y (cadena vertical a la izquierda) ----
        if chain_dim_y and len(chain_dim_y) >= 2:
            spec_y = prepare_dimension_chain(
                chain_dim_y,
                modular_steps=modular_steps_y or LAYHER_FLOOR_HEIGHTS_M,
            )
            ys_svg = [project_world_to_svg((0, c), transform)[1]
                      for c in spec_y.coords_m]
            # Cadena A EJES — 8 mm a la izquierda del bbox
            chain_x = a_min[0] - 8
            parts.append(_draw_dim_chain_v(
                ys_svg, chain_x, spec_y.groups, font_size=3.0,
            ))
            # Cota TOTAL
            total_x = chain_x - 10
            parts.append(_dim_line_v(
                total_x, a_min[1], a_max[1],
                f"{spec_y.total_mm} mm",
                font_size=3.5, ext_right=2.0,
            ))
            # Globos eje Y a la izquierda del total
            if axes_y_labels and len(axes_y_labels) == len(ys_svg):
                axes_x = total_x - 4
                for y, lab in zip(ys_svg, axes_y_labels):
                    parts.append(
                        f'<circle cx="{axes_x:.2f}" cy="{y:.2f}" r="2.8" '
                        f'fill="white" stroke="#0a3055" stroke-width="0.4" />'
                    )
                    parts.append(_svg_text(axes_x, y + 1.0, lab,
                                           font_size=2.5, weight="700",
                                           color="#0a3055"))

    # Etiqueta de escala dentro de la vista (esquina superior derecha)
    parts.append(_svg_text(rx + rw - 2, ry + 4,
                           f"Esc. 1:{scale_denom}",
                           font_size=2.8, anchor="end",
                           color="#444"))

    return "\n".join(parts), mm_per_m, scale_denom, transform


def _draw_dim_chain_v(
    svg_ys: list[float],
    x_dim: float,
    groups: list,
    *,
    font_size: float = 2.5,
    stroke: str = "#0a3055",
    ext_left: float = 4.0,
) -> str:
    """Versión vertical de _draw_dim_chain — texto rotado para lectura
    desde la derecha del plano."""
    if len(svg_ys) < 2 or not groups:
        return ""
    parts: list[str] = []
    arrow = 1.2
    # Extension lines
    for y in svg_ys:
        parts.append(_svg_line((x_dim - 0.5, y), (x_dim + ext_left, y),
                               stroke=stroke, width=0.18))
    seg_idx = 0
    for g in groups:
        n_seg = g.n
        if seg_idx + n_seg > len(svg_ys) - 1:
            break
        y1 = svg_ys[seg_idx]
        y2 = svg_ys[seg_idx + n_seg]
        if y1 > y2:
            y1, y2 = y2, y1
        parts.append(_svg_line((x_dim, y1), (x_dim, y2),
                               stroke=stroke, width=0.22))
        parts.append(
            f'<polygon points="{x_dim:.2f},{y1:.2f} '
            f'{x_dim-arrow*0.4:.2f},{y1+arrow:.2f} '
            f'{x_dim+arrow*0.4:.2f},{y1+arrow:.2f}" fill="{stroke}" />'
        )
        parts.append(
            f'<polygon points="{x_dim:.2f},{y2:.2f} '
            f'{x_dim-arrow*0.4:.2f},{y2-arrow:.2f} '
            f'{x_dim+arrow*0.4:.2f},{y2-arrow:.2f}" fill="{stroke}" />'
        )
        cy = (y1 + y2) / 2
        label_color = "#9b2226" if g.is_compensator else stroke
        label_weight = "700" if g.is_compensator else "600"
        parts.append(
            f'<text x="{x_dim-1.0:.2f}" y="{cy:.2f}" '
            f'font-size="{font_size}" text-anchor="middle" '
            f'fill="{label_color}" font-weight="{label_weight}" '
            f'transform="rotate(-90 {x_dim-1.0:.2f} {cy:.2f})">'
            f'{_esc(g.label())}</text>'
        )
        seg_idx += n_seg
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Vista isométrica (axonometría 30°/30°)
# ---------------------------------------------------------------------------

def _draw_iso_view(
    rect: tuple[float, float, float, float],
    lines_3d: list[dict],
    *,
    view_label: str = "ISOMETRÍA (esquemática)",
) -> str:
    """Dibuja la proyección isométrica de las líneas 3D dentro de `rect`.

    Usa la misma paleta `_CATEGORY_STROKES` que las vistas ortográficas
    pero con grosores reducidos (la iso es una vista de referencia,
    no debe competir con el alzado/planta acotados).

    No lleva cotas ni cadenas: es una imagen esquemática que ayuda al
    montador a identificar el tipo de andamio de un vistazo.
    """
    from .cad_views import iso_project

    rx, ry, rw, rh = rect
    parts = [_svg_rect(rx, ry, rw, rh, width=0.4)]
    parts.append(_svg_text(rx + 2, ry + 5, view_label,
                           font_size=4.5, anchor="start", weight="700",
                           color="#0a3055"))

    # Filtrar líneas dibujables (sólo tubos)
    drawable = [ln for ln in lines_3d
                if ln.get("category") not in _SKIP_LINE_CATEGORIES]
    if not drawable:
        parts.append(_svg_text(rx + rw/2, ry + rh/2,
                               "(sin datos)", font_size=3, color="#888"))
        return "\n".join(parts)

    # Proyectar todos los extremos a 2D iso
    iso_pairs: list[tuple[tuple[float, float], tuple[float, float], str]] = []
    xs: list[float] = []
    ys: list[float] = []
    for ln in drawable:
        a = iso_project(ln["p1"])
        b = iso_project(ln["p2"])
        iso_pairs.append((a, b, ln.get("category", "pole")))
        xs.extend((a[0], b[0]))
        ys.extend((a[1], b[1]))
    bmin = (min(xs), min(ys))
    bmax = (max(xs), max(ys))

    # Reservar título arriba y un margen mínimo
    geom_x = rx + 4.0
    geom_y = ry + 8.0
    geom_w = max(rw - 8.0, 30)
    geom_h = max(rh - 12.0, 30)

    # Fit con padding pequeño (la iso es esquemática, no acotada)
    transform = fit_in_rect(bmin, bmax, (geom_x, geom_y, geom_w, geom_h),
                            padding_mm=2.0)

    for a, b, cat in iso_pairs:
        stroke, width, dash = _CATEGORY_STROKES.get(cat, ("#444", 0.4, None))
        # Iso usa stroke ~70 % del grosor del frontal para que no compita
        a_svg = project_world_to_svg(a, transform)
        b_svg = project_world_to_svg(b, transform)
        parts.append(_svg_line(a_svg, b_svg, stroke=stroke,
                               width=width * 0.7, dash=dash))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Leyenda de simbología (para hoja overview)
# ---------------------------------------------------------------------------

_LEGEND_ITEMS: tuple[tuple[str, str], ...] = (
    ("pole",         "Montante (poste vertical)"),
    ("ledger_floor", "Larguero / travesaño de planta"),
    ("ledger_rail",  "Barandilla / mid-rail"),
    ("brace",        "Diagonal de arriostramiento"),
    ("tie",          "Anclaje a fachada"),
    ("toe",          "Rodapié"),
    ("plank",        "Bandeja / deck (línea discontinua)"),
    ("husillo",      "Husillo / base regulable"),
)


def _draw_legend(
    rect: tuple[float, float, float, float],
    *, title: str = "LEYENDA",
    segment_labels: list[str] | None = None,
) -> str:
    """Caja de leyenda con muestras de cada categoría.

    Si `segment_labels` se pasa (multi-tramo), añade una sección con la
    lista de tramos identificados (A-B, B-C, ...) para que el montador
    sepa cuántas hojas tramo tiene que mirar.
    """
    x, y, w, h = rect
    parts = [_svg_rect(x, y, w, h, width=0.4)]
    title_h = 5.0
    parts.append(_svg_line((x, y + title_h), (x + w, y + title_h), width=0.3))
    parts.append(_svg_text(x + w/2, y + title_h - 1, title,
                           font_size=2.8, anchor="middle", weight="700"))

    cy = y + title_h + 1.5
    sample_x = x + 3.0
    sample_w = 8.0
    text_x = sample_x + sample_w + 2.0
    line_h = 4.2
    for cat, label in _LEGEND_ITEMS:
        if cy + line_h > y + h - 2:
            break
        stroke, width, dash = _CATEGORY_STROKES.get(cat, ("#444", 0.4, None))
        parts.append(_svg_line(
            (sample_x, cy + 1.4), (sample_x + sample_w, cy + 1.4),
            stroke=stroke, width=width, dash=dash,
        ))
        parts.append(_svg_text(text_x, cy + 2.2, label,
                               font_size=2.2, anchor="start"))
        cy += line_h

    if segment_labels:
        cy += 1.5
        if cy + line_h <= y + h - 2:
            parts.append(_svg_line((x + 1, cy - 0.5),
                                   (x + w - 1, cy - 0.5), width=0.2))
            parts.append(_svg_text(x + 3, cy + 2.0,
                                   "Tramos del andamio:",
                                   font_size=2.2, anchor="start",
                                   weight="600"))
            cy += line_h
            for label in segment_labels:
                if cy + line_h > y + h - 2:
                    break
                parts.append(_svg_text(x + 5, cy + 2.0,
                                       f"· {label}",
                                       font_size=2.2, anchor="start"))
                cy += line_h * 0.85

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Markers funcionales en planta (plataformas, trampillas, escaleras, anclajes)
# y flecha de Norte
# ---------------------------------------------------------------------------

# Símbolos por kind. Cada entrada: (color_fill, color_stroke, label_text)
# Planks NO llevan marker porque ya se dibujan como línea discontinua
# marrón en cualquier vista (vía extract_scaffold_lines_3d). Las
# trampillas y escaleras sí, porque están filtradas explícitamente
# (sus geometrías como líneas serían confusas).
_MARKER_STYLE: dict[str, tuple[str, str, str]] = {
    "trapdoor":  ("#30a050", "#30a050", "T"),     # trampilla — cuadrado verde
    "ladder":    ("#d04040", "#d04040", "E"),     # escalera — rectángulo rojo
    "tie":       ("#992222", "#992222", ""),      # anclaje — triángulo rojo
}


def kind_for_object_name(name: str) -> str | None:
    """Clasifica un objeto del Scaffold por kind funcional para markers.

    Devuelve el kind ∈ {plank, trapdoor, ladder, tie} o None si el objeto
    no debe llevar marker (postes, ledgers, rails, husillos…).
    Sólo el `_rail_a` de las escaleras cuenta como una escalera ensamblada
    (igual que en bom.py).
    """
    if name.startswith("Lid_") or name.startswith("Trapdoor_"):
        return "trapdoor"
    if name.startswith("Ladder_") and name.endswith("_rail_a"):
        return "ladder"
    if name.startswith("Tie_"):
        return "tie"
    if (name.startswith("Deck_")
        or name.startswith("Plank_")
        or name.startswith("Corner_Plank_")):
        return "plank"
    return None


def extract_functional_elements_3d(scene) -> list[dict]:
    """Recorre la colección Scaffold y devuelve los elementos funcionales
    con su centroide en coordenadas mundiales.

    Cada item: `{kind, x, y, z, label}` donde `kind ∈ _MARKER_STYLE`.
    `label` se rellena para trampillas/escaleras (T/E); las plataformas y
    anclajes usan su forma como identificador visual.
    """
    import bpy
    from mathutils import Vector

    coll = bpy.data.collections.get("Scaffold")
    if coll is None:
        return []
    out: list[dict] = []
    for obj in coll.all_objects:
        if obj.type != "MESH":
            continue
        kind = kind_for_object_name(obj.name)
        # Salta kinds sin marker (p. ej. plank, que se dibuja como línea
        # discontinua y no necesita ícono extra en planta).
        if kind is None or kind not in _MARKER_STYLE:
            continue
        # Centroide del bbox local en mundo (más estable que matrix.translation
        # cuando el origen del mesh no está centrado)
        bb_center = sum((Vector(c) for c in obj.bound_box), Vector()) / 8
        center = obj.matrix_world @ bb_center
        out.append({
            "kind": kind,
            "x": float(center.x),
            "y": float(center.y),
            "z": float(center.z),
            "label": _MARKER_STYLE[kind][2],
            "name": obj.name,
        })
    return out


def _draw_top_markers(
    transform: tuple[float, float, float] | None,
    elements: list[dict],
) -> str:
    """Pinta los markers funcionales sobre la planta usando el `transform`
    devuelto por `_draw_view`. Si `transform` es None (vista vacía) o no
    hay elementos, devuelve cadena vacía.
    """
    if transform is None or not elements:
        return ""
    parts: list[str] = []
    for el in elements:
        x_svg, y_svg = project_world_to_svg((el["x"], el["y"]), transform)
        kind = el.get("kind", "")
        if kind not in _MARKER_STYLE:
            continue
        fill, stroke, label = _MARKER_STYLE[kind]
        if kind == "trapdoor":
            parts.append(
                f'<rect x="{x_svg-1.7:.2f}" y="{y_svg-1.7:.2f}" '
                f'width="3.4" height="3.4" '
                f'fill="{fill}" fill-opacity="0.55" '
                f'stroke="{stroke}" stroke-width="0.3"/>'
            )
            parts.append(_svg_text(x_svg, y_svg + 1.0, label,
                                   font_size=2.4, weight="700",
                                   color="white"))
        elif kind == "ladder":
            parts.append(
                f'<rect x="{x_svg-2.2:.2f}" y="{y_svg-1.2:.2f}" '
                f'width="4.4" height="2.4" '
                f'fill="{fill}" fill-opacity="0.4" '
                f'stroke="{stroke}" stroke-width="0.3"/>'
            )
            parts.append(_svg_text(x_svg, y_svg + 0.8, label,
                                   font_size=2.2, weight="700",
                                   color="white"))
        elif kind == "tie":
            parts.append(
                f'<polygon points="'
                f'{x_svg:.2f},{y_svg-1.8:.2f} '
                f'{x_svg-1.6:.2f},{y_svg+1.0:.2f} '
                f'{x_svg+1.6:.2f},{y_svg+1.0:.2f}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="0.3"/>'
            )
    return "\n".join(parts)


def _draw_north(
    rect: tuple[float, float, float, float],
    *, position: str = "bottom-right", radius_mm: float = 5.5,
) -> str:
    """Flecha de Norte en una esquina del rect de planta. Asume +Y mundo
    = Norte (convención del addon: la fachada está en y=0 y el andamio
    crece hacia +Y interior). Como el SVG invierte Y al pintar, una
    flecha apuntando hacia ARRIBA en SVG corresponde a +Y mundo."""
    x, y, w, h = rect
    margin = 6.0
    if position == "bottom-right":
        cx = x + w - margin - radius_mm
        cy = y + h - margin - radius_mm
    elif position == "bottom-left":
        cx = x + margin + radius_mm
        cy = y + h - margin - radius_mm
    elif position == "top-right":
        cx = x + w - margin - radius_mm
        cy = y + margin + radius_mm
    else:  # top-left
        cx = x + margin + radius_mm
        cy = y + margin + radius_mm
    r = radius_mm
    parts = [
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
        f'fill="white" stroke="#0a3055" stroke-width="0.4"/>',
        # Flecha hacia arriba: vértice arriba, base ancha abajo (cuerpo
        # pintado en negro)
        f'<polygon points="'
        f'{cx:.2f},{cy-r+1:.2f} '
        f'{cx-r*0.45:.2f},{cy+r*0.2:.2f} '
        f'{cx:.2f},{cy:.2f} '
        f'{cx+r*0.45:.2f},{cy+r*0.2:.2f}" '
        f'fill="#0a3055" stroke="#0a3055" stroke-width="0.2"/>',
        _svg_text(cx, cy + r - 1.0, "N",
                  font_size=2.6, weight="700", color="#0a3055"),
    ]
    return "\n".join(parts)


def _draw_tramo_labels(
    transform: tuple[float, float, float] | None,
    frames: list,
) -> str:
    """Etiqueta cada tramo de la polilínea con su nombre (`TRAMO A-B` …)
    centrado en el midpoint del segmento, sobre fondo blanco.

    Sirve como índice visual: el lector ve dónde empieza cada tramo en la
    planta general y sabe a qué hoja saltar para el detalle.
    """
    if transform is None or not frames:
        return ""
    from .cad_views import segment_label

    parts: list[str] = []
    for i, fr in enumerate(frames):
        label = segment_label(i, len(frames))
        mx = (fr.origin[0] + fr.end[0]) / 2.0
        my = (fr.origin[1] + fr.end[1]) / 2.0
        x_svg, y_svg = project_world_to_svg((mx, my), transform)
        # Cuadro blanco semi-opaco para que el texto se lea sobre las
        # líneas del andamio
        parts.append(
            f'<rect x="{x_svg-7.0:.2f}" y="{y_svg-2.4:.2f}" '
            f'width="14.0" height="4.2" '
            f'fill="white" fill-opacity="0.88" '
            f'stroke="#0a3055" stroke-width="0.4"/>'
        )
        parts.append(_svg_text(x_svg, y_svg + 0.7,
                               f"TRAMO {label}",
                               font_size=2.6, weight="700",
                               color="#0a3055"))
    return "\n".join(parts)


def _draw_top_overlays(
    rect: tuple[float, float, float, float],
    transform: tuple[float, float, float] | None,
    elements: list[dict],
    *,
    frames: list | None = None,
) -> str:
    """Conjunto de overlays que van encima de la planta: markers
    funcionales + flecha de Norte. Si se pasan `frames` (overview
    multi-tramo), también dibuja las etiquetas TRAMO A-B / B-C / ... .
    Llamado por los sheet builders tras `_draw_view`.
    """
    parts: list[str] = []
    parts.append(_draw_top_markers(transform, elements))
    if frames:
        parts.append(_draw_tramo_labels(transform, frames))
    parts.append(_draw_north(rect))
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Builders de hoja
# ---------------------------------------------------------------------------

def _svg_header(w_mm: float, h_mm: float, margin: float) -> list[str]:
    """Cabecera SVG común a todas las hojas: viewBox + fondo + marco doble."""
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w_mm} {h_mm}" '
        f'width="{w_mm}mm" height="{h_mm}mm" '
        f'font-family="\'Helvetica\', \'Arial\', sans-serif">'
    )
    parts.append(f'<rect x="0" y="0" width="{w_mm}" height="{h_mm}" '
                 f'fill="white"/>')
    parts.append(_svg_rect(margin/2, margin/2,
                           w_mm - margin, h_mm - margin, width=0.4))
    parts.append(_svg_rect(margin, margin,
                           w_mm - 2*margin, h_mm - 2*margin, width=0.6))
    return parts


def _build_single_sheet(
    lines_3d: list[dict],
    summary: dict,
    *,
    paper: str,
    orientation: str,
    project_name: str,
    drawing_title: str,
    author: str,
    reference_points_3d: list[tuple[float, float, float]],
    floor_heights: list[float],
    pole_x_levels: list[float],
    pole_y_levels: list[float],
    validation: dict | None,
    functional_elements_3d: list[dict] | None = None,
) -> str:
    """Hoja única — uso para andamios rectos (1 tramo) o sin path_points.

    Layout: alzado frontal + planta + isometría + BOM + cajetín + leyenda.
    Respecto al layout previo: se sustituye el alzado lateral por la
    isometría (más informativa para andamios rectos), y se añade leyenda.
    Las plataformas/trampillas/escaleras/anclajes se etiquetan en planta
    sobre sus centroides (antipatrón H del prompt: dibujados sin
    identificar). En la planta se incluye una flecha de Norte (asume
    +Y mundo = Norte; convención del addon).
    """
    from .cad_dim import (
        LAYHER_BAY_LENGTHS_M, LAYHER_FLOOR_HEIGHTS_M,
        axis_labels_alpha, axis_labels_numeric, consolidate_coords,
    )

    w_mm, h_mm = paper_dims(paper, orientation)
    margin = 10.0

    lines = [ln for ln in lines_3d
             if ln.get("category") not in _SKIP_LINE_CATEGORIES]
    front = [(project_to_view(ln["p1"], "front"),
              project_to_view(ln["p2"], "front"),
              ln["category"]) for ln in lines]
    top = [(project_to_view(ln["p1"], "top"),
            project_to_view(ln["p2"], "top"),
            ln["category"]) for ln in lines]

    # Layout (idem al previo, pero con iso en vez de lateral)
    inner_x = margin
    inner_y = margin
    inner_w = w_mm - 2 * margin
    inner_h = h_mm - 2 * margin
    left_w = inner_w * 0.60 - 1
    right_w = inner_w * 0.40 - 1
    sep = 4.0
    front_h = (inner_h - sep) * 0.55
    plan_h = (inner_h - sep) * 0.45
    front_rect = (inner_x, inner_y, left_w, front_h)
    plan_rect = (inner_x, inner_y + front_h + sep, left_w, plan_h)
    right_x = inner_x + left_w + 2
    iso_h = (inner_h - 2 * sep) * 0.30
    legend_h = (inner_h - 2 * sep) * 0.16
    bom_h = (inner_h - 2 * sep) * 0.22
    title_h = (inner_h - 2 * sep) * 0.32
    iso_rect = (right_x, inner_y, right_w, iso_h)
    legend_rect = (right_x, inner_y + iso_h + sep, right_w, legend_h)
    bom_rect = (right_x, inner_y + iso_h + legend_h + sep,
                right_w, bom_h)
    title_rect = (right_x, inner_y + iso_h + legend_h + bom_h + 2 * sep,
                  right_w, title_h)

    parts = _svg_header(w_mm, h_mm, margin)

    ref_pts = reference_points_3d or []
    floor_levels = floor_heights or []
    front_chain_x = sorted(set(list(pole_x_levels or [])
                               + [p[0] for p in ref_pts]))
    front_chain_y = sorted(set(floor_levels))
    plan_chain_x = sorted(set([p[0] for p in ref_pts] + (pole_x_levels or [])))
    plan_chain_y = sorted(set([p[1] for p in ref_pts] + (pole_y_levels or [])))

    front_xs_consol = consolidate_coords(front_chain_x or [])
    plan_xs_consol = consolidate_coords(plan_chain_x or [])
    plan_ys_consol = consolidate_coords(plan_chain_y or [])

    front_svg, _, front_denom, _ = _draw_view(
        front_rect, front, view_label="ALZADO FRONTAL",
        chain_dim_x=front_chain_x, chain_dim_y=front_chain_y,
        axes_x_labels=axis_labels_numeric(len(front_xs_consol)),
        modular_steps_x=LAYHER_BAY_LENGTHS_M,
        modular_steps_y=LAYHER_FLOOR_HEIGHTS_M,
    )
    plan_svg, _, _, plan_transform = _draw_view(
        plan_rect, top, view_label="PLANTA",
        chain_dim_x=plan_chain_x, chain_dim_y=plan_chain_y,
        axes_x_labels=axis_labels_numeric(len(plan_xs_consol)),
        axes_y_labels=axis_labels_alpha(len(plan_ys_consol)),
        modular_steps_x=LAYHER_BAY_LENGTHS_M,
        modular_steps_y=LAYHER_BAY_LENGTHS_M,
        fixed_scale_denom=front_denom,
    )
    plan_overlays = _draw_top_overlays(
        plan_rect, plan_transform,
        functional_elements_3d or [],
    )
    iso_svg = _draw_iso_view(iso_rect, lines_3d)
    legend_svg = _draw_legend(legend_rect)
    parts.extend([front_svg, plan_svg, plan_overlays, iso_svg, legend_svg])

    parts.append(_bom_table(bom_rect, summary))
    parts.append(_title_block(
        title_rect,
        project_name=project_name,
        drawing_title=drawing_title,
        scale_label=f"1:{front_denom}",
        paper=paper,
        author=author,
        weight_kg=summary.get("total_weight_kg", 0.0),
        n_pieces=summary.get("total_pieces", 0),
        validation=validation,
    ))
    parts.append('</svg>')
    return "\n".join(parts)


def _build_overview_sheet(
    lines_3d: list[dict],
    summary: dict,
    frames: list,                          # list[SegmentFrame]
    *,
    paper: str,
    orientation: str,
    project_name: str,
    drawing_title: str,
    author: str,
    reference_points_3d: list[tuple[float, float, float]],
    floor_heights: list[float],
    pole_x_levels: list[float],
    pole_y_levels: list[float],
    validation: dict | None,
    sheet_n: int,
    sheet_total: int,
    functional_elements_3d: list[dict] | None = None,
) -> str:
    """Hoja overview para andamios multi-tramo.

    Contiene: planta global con todos los tramos identificados +
    isometría + leyenda + BOM + cajetín. Las hojas de tramo siguen
    detrás con el alzado local de cada uno. La planta lleva markers
    de plataformas/trampillas/escaleras/anclajes y flecha de Norte.
    """
    from .cad_dim import (
        LAYHER_BAY_LENGTHS_M,
        axis_labels_alpha, axis_labels_numeric, consolidate_coords,
    )
    from .cad_views import segment_label

    w_mm, h_mm = paper_dims(paper, orientation)
    margin = 10.0

    lines = [ln for ln in lines_3d
             if ln.get("category") not in _SKIP_LINE_CATEGORIES]
    top = [(project_to_view(ln["p1"], "top"),
            project_to_view(ln["p2"], "top"),
            ln["category"]) for ln in lines]

    inner_x = margin
    inner_y = margin
    inner_w = w_mm - 2 * margin
    inner_h = h_mm - 2 * margin
    left_w = inner_w * 0.58 - 1
    right_w = inner_w * 0.42 - 1
    sep = 4.0
    plan_h = (inner_h - sep) * 0.62
    iso_left_h = (inner_h - sep) * 0.34
    plan_rect = (inner_x, inner_y, left_w, plan_h)
    iso_rect = (inner_x, inner_y + plan_h + sep, left_w, iso_left_h)
    right_x = inner_x + left_w + 2
    legend_h = (inner_h - 2 * sep) * 0.24
    bom_h = (inner_h - 2 * sep) * 0.42
    title_h = (inner_h - 2 * sep) * 0.34
    legend_rect = (right_x, inner_y, right_w, legend_h)
    bom_rect = (right_x, inner_y + legend_h + sep, right_w, bom_h)
    title_rect = (right_x, inner_y + legend_h + bom_h + 2 * sep,
                  right_w, title_h)

    parts = _svg_header(w_mm, h_mm, margin)

    ref_pts = reference_points_3d or []
    # Modo referencia: la planta general sólo lleva las cotas de los
    # path_points (los vértices de la polilínea que define el andamio).
    # El detalle bay-a-bay queda en las hojas tramo. Mantener la planta
    # como índice visual, no como plano detallado.
    plan_chain_x = sorted(set(p[0] for p in ref_pts))
    plan_chain_y = sorted(set(p[1] for p in ref_pts))
    plan_xs_consol = consolidate_coords(plan_chain_x or [])
    plan_ys_consol = consolidate_coords(plan_chain_y or [])

    plan_svg, _, plan_denom, plan_transform = _draw_view(
        plan_rect, top, view_label="PLANTA GENERAL (referencia)",
        chain_dim_x=plan_chain_x, chain_dim_y=plan_chain_y,
        axes_x_labels=axis_labels_numeric(len(plan_xs_consol)),
        axes_y_labels=axis_labels_alpha(len(plan_ys_consol)),
        modular_steps_x=LAYHER_BAY_LENGTHS_M,
        modular_steps_y=LAYHER_BAY_LENGTHS_M,
    )
    parts.append(plan_svg)
    parts.append(_draw_top_overlays(
        plan_rect, plan_transform,
        functional_elements_3d or [],
        frames=frames,
    ))
    parts.append(_draw_iso_view(iso_rect, lines_3d))

    seg_labels = [segment_label(i, len(frames)) for i in range(len(frames))]
    parts.append(_draw_legend(legend_rect, segment_labels=seg_labels))
    parts.append(_bom_table(bom_rect, summary))
    parts.append(_title_block(
        title_rect,
        project_name=project_name,
        drawing_title=f"{drawing_title} — VISTA GENERAL  ({sheet_n}/{sheet_total})",
        scale_label=f"1:{plan_denom}",
        paper=paper,
        author=author,
        weight_kg=summary.get("total_weight_kg", 0.0),
        n_pieces=summary.get("total_pieces", 0),
        validation=validation,
    ))
    parts.append('</svg>')
    return "\n".join(parts)


def _build_tramo_sheet(
    bucket_lines: list[dict],
    frame,                                  # SegmentFrame
    seg_index: int,
    n_segments: int,
    summary: dict,
    *,
    paper: str,
    orientation: str,
    project_name: str,
    drawing_title: str,
    author: str,
    floor_heights: list[float],
    validation: dict | None,
    sheet_n: int,
    sheet_total: int,
) -> str:
    """Hoja de un tramo: alzado frontal local + cota a ejes + cajetín.

    El alzado se proyecta sobre el plano local del tramo, así que un
    andamio en U produce 3 alzados rectos en lugar de uno aplastado.
    """
    from .cad_dim import (
        LAYHER_BAY_LENGTHS_M, LAYHER_FLOOR_HEIGHTS_M,
        axis_labels_numeric, consolidate_coords,
    )
    from .cad_views import (
        project_lines_to_segment, segment_label,
    )

    w_mm, h_mm = paper_dims(paper, orientation)
    margin = 10.0

    parts = _svg_header(w_mm, h_mm, margin)

    # Alzado frontal local: ocupa la mayor parte de la hoja (es lo que el
    # montador realmente consulta). Franja inferior comprimida con el
    # cajetín a la derecha y los datos del tramo a la izquierda.
    # Antes era 20 % de inner_h → ahora 12 %, lo que da ~22 mm más al
    # alzado en A3 (de 217 → 239 mm).
    inner_x = margin
    inner_y = margin
    inner_w = w_mm - 2 * margin
    inner_h = h_mm - 2 * margin
    sep = 4.0
    title_h = inner_h * 0.12
    front_h = inner_h - title_h - sep
    front_rect = (inner_x, inner_y, inner_w, front_h)
    # Cajetín gana del 45 % al 65 % del ancho: con la franja más fina
    # necesita más ancho para que las 6 filas sigan ≥ 2,5 mm normativo.
    info_w = inner_w * 0.35 - 2
    title_w = inner_w * 0.65
    info_rect = (inner_x, inner_y + front_h + sep, info_w, title_h)
    title_rect = (inner_x + info_w + 2,
                  inner_y + front_h + sep,
                  title_w, title_h)

    # Líneas locales del tramo
    front = project_lines_to_segment(bucket_lines, frame)

    # Cadenas: en X (longitudinal) los u únicos donde hay postes;
    # en Y (vertical) los floor_heights
    pole_us: list[float] = []
    for ln in bucket_lines:
        if ln.get("category") != "pole":
            continue
        for p in (ln["p1"], ln["p2"]):
            u, _ = frame.project(p)
            pole_us.append(round(u, 3))
    chain_dim_x = sorted(set(pole_us))
    chain_dim_y = sorted(set(floor_heights or []))
    chain_xs_consol = consolidate_coords(chain_dim_x or [])

    label = segment_label(seg_index, n_segments)
    front_svg, _, front_denom, _ = _draw_view(
        front_rect, front,
        view_label=f"ALZADO TRAMO {label}",
        chain_dim_x=chain_dim_x, chain_dim_y=chain_dim_y,
        axes_x_labels=axis_labels_numeric(len(chain_xs_consol)),
        modular_steps_x=LAYHER_BAY_LENGTHS_M,
        modular_steps_y=LAYHER_FLOOR_HEIGHTS_M,
        fit_to_canvas=True,
    )
    parts.append(front_svg)

    # Cuadro de info del tramo (reusa _svg_rect + _svg_text)
    ix, iy, iw, ih = info_rect
    parts.append(_svg_rect(ix, iy, iw, ih, width=0.4))
    parts.append(_svg_text(ix + iw/2, iy + 5,
                           f"DATOS DEL TRAMO {label}",
                           font_size=3.0, anchor="middle", weight="700"))
    info_lines = [
        f"Origen (m):  ({frame.origin[0]:.2f}, {frame.origin[1]:.2f}, {frame.origin[2]:.2f})",
        f"Final (m):   ({frame.end[0]:.2f}, {frame.end[1]:.2f}, {frame.end[2]:.2f})",
        f"Longitud:    {frame.length*1000:.0f} mm",
        f"Postes:      {len(chain_xs_consol)}",
        f"Líneas:      {len(bucket_lines)}",
    ]
    for i, line in enumerate(info_lines):
        parts.append(_svg_text(ix + 3, iy + 10 + i*4, line,
                               font_size=2.4, anchor="start"))

    parts.append(_title_block(
        title_rect,
        project_name=project_name,
        drawing_title=f"{drawing_title} — TRAMO {label}  ({sheet_n}/{sheet_total})",
        scale_label=f"1:{front_denom}",
        paper=paper,
        author=author,
        weight_kg=summary.get("total_weight_kg", 0.0),
        n_pieces=summary.get("total_pieces", 0),
        validation=validation,
    ))
    parts.append('</svg>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def generate_cad_sheets(
    lines_3d: list[dict],
    summary: dict,
    *,
    paper: str = "A3",
    orientation: str = "landscape",
    project_name: str = "Andamio multidireccional",
    drawing_title: str = "PLANO GENERAL",
    author: str = "",
    reference_points_3d: list[tuple[float, float, float]] | None = None,
    floor_heights: list[float] | None = None,
    pole_x_levels: list[float] | None = None,
    pole_y_levels: list[float] | None = None,
    validation: dict | None = None,
    path_points_3d: list[tuple[float, float, float]] | None = None,
    functional_elements_3d: list[dict] | None = None,
) -> list[str]:
    """Genera el conjunto de hojas SVG del plano CAD.

    Caso 1 (1 tramo o sin path_points): devuelve `[overview_sheet]`.
    El layout es alzado frontal + planta + isometría + BOM + cajetín.

    Caso 2 (≥ 2 tramos rectos en la polilínea): devuelve la lista
    `[overview_sheet, tramo_1, tramo_2, ...]`. El overview tiene la
    planta global; cada hoja tramo lleva el alzado frontal local de
    su tramo, evitando el aplastamiento del frontal global de un
    andamio en U.
    """
    from .cad_views import segment_frames, split_lines_by_segments

    pts = list(path_points_3d or [])
    frames = segment_frames(pts)

    common = dict(
        paper=paper, orientation=orientation,
        project_name=project_name, drawing_title=drawing_title,
        author=author,
        floor_heights=floor_heights or [],
        validation=validation,
    )
    if len(frames) <= 1:
        return [_build_single_sheet(
            lines_3d, summary,
            reference_points_3d=reference_points_3d or [],
            pole_x_levels=pole_x_levels or [],
            pole_y_levels=pole_y_levels or [],
            functional_elements_3d=functional_elements_3d or [],
            **common,
        )]

    sheet_total = 1 + len(frames)
    sheets = [_build_overview_sheet(
        lines_3d, summary, frames,
        reference_points_3d=reference_points_3d or [],
        pole_x_levels=pole_x_levels or [],
        pole_y_levels=pole_y_levels or [],
        sheet_n=1, sheet_total=sheet_total,
        functional_elements_3d=functional_elements_3d or [],
        **common,
    )]
    buckets = split_lines_by_segments(lines_3d, pts)
    for i, frame in enumerate(frames):
        sheets.append(_build_tramo_sheet(
            buckets[i], frame, i, len(frames), summary,
            sheet_n=2 + i, sheet_total=sheet_total,
            **common,
        ))
    return sheets


def generate_cad_svg(
    lines_3d: list[dict],
    summary: dict,
    *,
    paper: str = "A3",
    orientation: str = "landscape",
    project_name: str = "Andamio multidireccional",
    drawing_title: str = "PLANO GENERAL",
    author: str = "",
    reference_points_3d: list[tuple[float, float, float]] | None = None,
    floor_heights: list[float] | None = None,
    pole_x_levels: list[float] | None = None,
    pole_y_levels: list[float] | None = None,
    validation: dict | None = None,
) -> str:
    """Compatibilidad: devuelve la primera hoja del plano CAD (overview).

    Para multi-tramo úsese `generate_cad_sheets` que devuelve también
    las hojas por tramo. Esta función fuerza el modo single-sheet sin
    pasar `path_points_3d`, lo que produce un plano clásico con
    alzado + planta + iso (no se generan hojas tramo).
    """
    sheets = generate_cad_sheets(
        lines_3d, summary,
        paper=paper, orientation=orientation,
        project_name=project_name, drawing_title=drawing_title,
        author=author,
        reference_points_3d=reference_points_3d,
        floor_heights=floor_heights,
        pole_x_levels=pole_x_levels,
        pole_y_levels=pole_y_levels,
        validation=validation,
        path_points_3d=None,
    )
    return sheets[0]


# ---------------------------------------------------------------------------
# Wrapper HTML autocontenido con CSS @page para impresión
# ---------------------------------------------------------------------------

_HTML_DOC = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Plano CAD — {title}</title>
<style>
@page {{ size: {paper_w}mm {paper_h}mm; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{ background: #e5e7eb; font-family: sans-serif; }}
.toolbar {{ background: #0a3055; color: white; padding: 0.6em 1em;
           text-align: center; font-size: 14px; }}
.toolbar strong {{ color: #ffd; }}
/* La hoja tiene dimensiones EXACTAS de la página (sin diferencia de
   subpíxeles que provoque salto extra). page-break-before en las hojas
   2..N evita la blanca final que produce page-break-after. */
.sheet {{ display: block;
         width: {paper_w}mm;
         height: {paper_h}mm;
         margin: 1em auto;
         background: white;
         box-shadow: 0 4px 16px rgba(0,0,0,0.15);
         overflow: hidden; }}
.sheet + .sheet {{ page-break-before: always; }}
/* La SVG escala al 100 % del contenedor; viewBox se encarga del aspect
   ratio. Sin esto, ciertos navegadores en modo impresión envían la SVG
   a su tamaño intrínseco y la recortan o la dejan en blanco. */
.sheet svg {{ display: block; width: 100%; height: 100%; }}
@media print {{
    .toolbar {{ display: none; }}
    body {{ background: white; }}
    .sheet {{ box-shadow: none; margin: 0; }}
}}
</style>
</head>
<body>
<div class="toolbar">
    Plano técnico — {title} · {n_sheets} {hoja_word} · Pulsa <strong>Ctrl+P</strong>
    para exportar a PDF. Tamaño del papel: {paper}, Márgenes: ninguno, Escala: 100 %.
</div>
{sheets_html}
</body>
</html>
"""


def wrap_sheets_in_html(
    sheets: list[str], *,
    paper: str = "A3",
    orientation: str = "landscape",
    title: str = "Andamio",
) -> str:
    """Envuelve una lista de SVGs en un único HTML imprimible.

    Cada hoja queda en su propio `<div class="sheet">` con
    `page-break-after: always` para que Chrome/Firefox impriman 1 hoja
    por SVG en orden.
    """
    sheets_html = "\n".join(f'<div class="sheet">\n{svg}\n</div>'
                            for svg in sheets)
    n = len(sheets)
    paper_w, paper_h = paper_dims(paper, orientation)
    return _HTML_DOC.format(
        title=_esc(title), paper=paper, orientation=orientation,
        paper_w=paper_w, paper_h=paper_h,
        n_sheets=n, hoja_word="hoja" if n == 1 else "hojas",
        sheets_html=sheets_html,
    )


def wrap_in_html(svg: str, *,
                 paper: str = "A3",
                 orientation: str = "landscape",
                 title: str = "Andamio") -> str:
    """Compatibilidad: envuelve un único SVG. Para multi-hoja úsese
    `wrap_sheets_in_html`."""
    return wrap_sheets_in_html(
        [svg], paper=paper, orientation=orientation, title=title,
    )


# ---------------------------------------------------------------------------
# Extracción de líneas desde la escena Blender
# ---------------------------------------------------------------------------

def extract_reference_points_3d(scene) -> list[tuple[float, float, float]]:
    """Devuelve coordenadas mundiales de los empties que el usuario colocó
    como `path_points` (puntos de referencia para la generación)."""
    props = getattr(scene, "andamios_props", None)
    if props is None:
        return []
    out: list[tuple[float, float, float]] = []
    for pp in props.path_points:
        obj = pp.obj
        if obj is None:
            continue
        loc = obj.matrix_world.translation
        out.append((loc.x, loc.y, loc.z))
    return out


def extract_floor_heights(scene) -> list[float]:
    """Calcula las alturas Z absolutas de cada planta del andamio:
    [base_z, base_z + h, base_z + 2h, …, base_z + n·h] donde n viene
    de props.scaffold_h / props.floor_h."""
    props = getattr(scene, "andamios_props", None)
    if props is None:
        return []
    base_z = float(getattr(props, "base_z", 0.0))
    floor_h = float(getattr(props, "floor_h", 2.0))
    total_h = float(getattr(props, "scaffold_h", floor_h))
    if floor_h <= 0:
        return [base_z, base_z + total_h]
    n_floors = max(1, int(round(total_h / floor_h)))
    return [base_z + i * floor_h for i in range(n_floors + 1)]


def extract_pole_levels(lines_3d: list[dict],
                       *, axis: int) -> list[float]:
    """Extrae las coordenadas únicas del eje indicado donde hay un poste.

    `axis = 0` → X (longitud andamio), `axis = 1` → Y (profundidad).
    Detecta postes mirando los miembros con category == "pole" y
    tomando el valor del eje en ambos extremos (deberían ser iguales,
    ya que los postes son verticales).
    """
    seen: set[float] = set()
    for ln in lines_3d:
        if ln.get("category") != "pole":
            continue
        for p in (ln["p1"], ln["p2"]):
            seen.add(round(float(p[axis]), 3))
    return sorted(seen)


def build_validation_summary(scene) -> dict | None:
    """Construye el dict de validación a partir de los custom props del
    último cálculo. Devuelve None si no hay datos."""
    if "calc_status_level" not in scene:
        return None
    level = str(scene.get("calc_status_level", ""))
    util_max = float(scene.get("calc_status_worst", 0.0))
    n_total = int(scene.get("calc_status_n_total", 0))
    n_failed = int(scene.get("calc_status_n_failed", 0))
    delta_max_mm = float(scene.get("calc_defl_worst_disp_m", 0.0)) * 1000.0

    status_map = {
        "ok":      ("✓ ANDAMIO SEGURO",     "Cumple resistencia y servicio"),
        "warning": ("⚠ MARGEN AJUSTADO",   "Cerca del límite — revisar"),
        "fail":    ("✗ NO CUMPLE",           "Hay elementos sobrepasados"),
    }
    status_text, _ = status_map.get(level, ("?", ""))

    # Combo y configuración de cargas
    combo = "ULS_LeadL"
    service = "Q3"
    wind_zone = "A"
    try:
        props = scene.andamios_props
        combo = str(props.calc_combo)
        service = str(props.calc_service_class)
        wind_zone = str(props.calc_wind_zone)
    except AttributeError:
        pass

    details = (
        f"util max {util_max:.2f} · "
        f"δ máx {delta_max_mm:.0f} mm · "
        f"{n_failed}/{n_total} fallos · "
        f"{combo} · {service} · viento {wind_zone}"
    )

    return {
        "level": level,
        "status_text": status_text,
        "details": details,
        "util_max": util_max,
        "delta_max_mm": delta_max_mm,
        "n_total": n_total,
        "n_failed": n_failed,
    }


def extract_scaffold_lines_3d(scene) -> list[dict]:
    """Recorre la colección Scaffold y devuelve list de dicts con
    p1, p2 (tuplas), category, name.

    Para cada objeto, identifica el eje local más largo (en mundo, tras
    aplicar `obj.scale`) y extrae la línea entre los dos extremos del
    bbox a lo largo de ese eje, centrada en los otros dos. Esto trata
    correctamente:
      - Tubos cilíndricos (`_make_tube`, depth en Z local) → línea Z
      - Cajas / rodapiés (`_make_box`, escala en X) → línea X local
      - Tubos rotados (braces diagonales) → siguen siendo Z local
      - Rosetas (annulus, decorativas) → filtradas vía SKIP_CATEGORIES

    Antes el extractor asumía siempre el eje Z local, lo que
    convertía rodapiés en palitos de 4 cm (su espesor) en lugar de
    barras de 2,5 m (su longitud)."""
    import bpy
    from mathutils import Vector
    from .bom import category_for_name

    coll = bpy.data.collections.get("Scaffold")
    if coll is None:
        return []

    out: list[dict] = []
    for obj in coll.all_objects:
        if obj.type != "MESH":
            continue
        cat = category_for_name(obj.name)
        if cat is None or cat in _SKIP_LINE_CATEGORIES:
            continue
        bb = list(obj.bound_box)
        xs = [c[0] for c in bb]
        ys = [c[1] for c in bb]
        zs = [c[2] for c in bb]
        # Tamaño en mundo (incluyendo obj.scale por componente)
        sx = (max(xs) - min(xs)) * abs(obj.scale.x)
        sy = (max(ys) - min(ys)) * abs(obj.scale.y)
        sz = (max(zs) - min(zs)) * abs(obj.scale.z)
        sizes = (sx, sy, sz)
        axis = max(range(3), key=lambda i: sizes[i])
        if sizes[axis] < 1e-4:
            continue   # objeto degenerado
        # Endpoints en local: extremo en el eje dominante, punto medio
        # en los otros dos.
        loc_min = [(min(xs)+max(xs))/2.0,
                   (min(ys)+max(ys))/2.0,
                   (min(zs)+max(zs))/2.0]
        loc_max = list(loc_min)
        axis_coords = (xs, ys, zs)[axis]
        loc_min[axis] = min(axis_coords)
        loc_max[axis] = max(axis_coords)
        M = obj.matrix_world
        p1 = M @ Vector(loc_min)
        p2 = M @ Vector(loc_max)
        out.append({
            "p1": (p1.x, p1.y, p1.z),
            "p2": (p2.x, p2.y, p2.z),
            "category": cat,
            "name": obj.name,
        })
    return out
