"""Generación HTML del Bill of Materials.

Documento autocontenido (CSS + imágenes en base64) pensado para
suministros y subcontratistas. Incluye:

    1. Cabecera con fecha y nombre del proyecto.
    2. Resumen ejecutivo: peso total, nº de piezas, metros lineales de tubo.
    3. Breakdown por categoría con métricas (peso, cantidad, longitud
       acumulada de tubo).
    4. Tabla detallada por categoría con descripción + tipos agrupados
       por longitud + foto representativa.
    5. Glosario con explicación de cada categoría.
"""

from __future__ import annotations

import html
import os
from datetime import datetime

from .bom import CATEGORY_LABELS


_CSS = """\
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 1200px;
    margin: 2em auto;
    padding: 0 1.5em;
    color: #1a1a1a;
    line-height: 1.55;
    background: #fafafa;
}
h1 { color: #0a3055; margin-bottom: 0.2em; font-size: 1.8em; }
h2 { color: #0a3055; border-bottom: 2px solid #0a3055; padding-bottom: 0.3em;
     margin-top: 2.2em; font-size: 1.35em; }
h3 { color: #0a3055; margin-top: 1.5em; font-size: 1.15em; }
small { color: #6b7280; }
.muted { color: #6b7280; }
code { font-family: ui-monospace, "SF Mono", Menlo, monospace;
       font-size: 0.92em; background: #f4f6fa; padding: 1px 4px;
       border-radius: 3px; }

.summary {
    background: #fff; border-radius: 12px; padding: 1.5em 2em;
    margin: 1em 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1.5em;
}
.summary-metric { text-align: center; }
.summary-metric .value {
    font-size: 2.6em; font-weight: bold; color: #0a3055; margin: 0.1em 0;
}
.summary-metric .label { color: #6b7280; font-size: 0.95em; }

.cat-breakdown { width: 100%; border-collapse: collapse; margin: 1em 0; }
.cat-breakdown th, .cat-breakdown td {
    padding: 0.6em 0.8em; border-bottom: 1px solid #e5e7eb; text-align: right;
}
.cat-breakdown th { background: #f4f6fa; color: #4a5568; }
.cat-breakdown td:first-child, .cat-breakdown th:first-child {
    text-align: left;
}
.cat-breakdown tfoot td { font-weight: bold; background: #fef9e7;
                          border-top: 2px solid #0a3055; }

.cat-section {
    background: #fff; border-radius: 8px; padding: 1.2em 1.5em;
    margin: 1.5em 0; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    display: grid; grid-template-columns: 320px 1fr; gap: 1.5em;
    align-items: start;
}
.cat-section .img-box { background: #f8fafc; border-radius: 6px;
                        overflow: hidden; aspect-ratio: 1; }
.cat-section img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cat-section .no-img { display: flex; align-items: center;
                       justify-content: center; color: #9ca3af;
                       aspect-ratio: 1; }
.cat-info p.desc { color: #4a5568; margin: 0.2em 0 0.8em; }
.cat-info table { width: 100%; border-collapse: collapse;
                  font-size: 0.95em; }
.cat-info th, .cat-info td {
    padding: 0.4em 0.6em; border-bottom: 1px solid #e5e7eb; text-align: right;
}
.cat-info th { background: #f4f6fa; color: #4a5568; }
.cat-info td:first-child, .cat-info th:first-child { text-align: left; }
.cat-info tfoot td { font-weight: bold; background: #f4f6fa; }
.cat-info .total-row { font-weight: bold; }

.help-card {
    background: #eff6ff; border-left: 4px solid #3b82f6;
    padding: 1em 1.2em; margin: 1em 0; border-radius: 4px;
}
.glossary dt { font-weight: 600; color: #0a3055; margin-top: 0.8em; }
.glossary dd { margin-left: 0; color: #4a5568; }
"""


def _esc(s: object) -> str:
    return html.escape(str(s))


def _format_qty(n: int | float) -> str:
    if isinstance(n, float):
        if abs(n - round(n)) < 1e-6:
            return f"{int(round(n))}"
        return f"{n:.2f}"
    return str(n)


def _format_kg(kg: float) -> str:
    if kg >= 1000:
        return f"{kg/1000:.2f} t  ({kg:.0f} kg)"
    return f"{kg:.1f} kg"


def _format_length(length_m: float) -> str:
    return f"{length_m:.2f} m"


def _category_table(groups: list[dict]) -> str:
    """Tabla de tipos dentro de una categoría: longitud / cantidad /
    peso unitario / peso total."""
    rows = ["<table>"]
    rows.append(
        "<thead><tr><th>Descripción</th>"
        "<th>Cantidad</th><th>Peso unit.</th>"
        "<th>Peso total</th></tr></thead><tbody>"
    )
    total_count = 0
    total_weight = 0.0
    for g in groups:
        if g["is_tube"]:
            desc = f"Longitud {_format_length(g['length_m'])}"
        else:
            deck_id = g["deck_id"] or "—"
            desc = f"<code>{_esc(deck_id)}</code>"
        rows.append(
            f"<tr><td>{desc}</td>"
            f"<td>{g['count']}</td>"
            f"<td>{g['unit_weight_kg']:.2f} kg</td>"
            f"<td>{g['total_weight_kg']:.1f} kg</td></tr>"
        )
        total_count += g["count"]
        total_weight += g["total_weight_kg"]
    rows.append(
        f"<tr class='total-row'><td>Total categoría</td>"
        f"<td>{total_count}</td><td>—</td>"
        f"<td>{total_weight:.1f} kg</td></tr>"
    )
    rows.append("</tbody></table>")
    return "".join(rows)


def generate_bom_html(
    groups: list[dict],
    summary: dict,
    *,
    screenshots: dict[str, str] | None = None,
    title: str = "Andamio multidireccional",
    project_name: str = "",
) -> str:
    """Genera el HTML del Bill of Materials.

    Parameters
    ----------
    groups : list of dict
        Salida de `bom.aggregate_bom`.
    summary : dict
        Salida de `bom.summarize_bom`.
    screenshots : dict[str, str] | None
        Mapa `{category_id: data_url_PNG}` con la imagen representativa
        de cada categoría. Si no se pasa, las secciones aparecen sin foto.
    title, project_name : str
        Cabecera del documento.
    """
    screenshots = screenshots or {}

    # Agrupar groups por categoría para producir secciones
    by_cat: dict[str, list[dict]] = {}
    for g in groups:
        by_cat.setdefault(g["category"], []).append(g)

    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>BOM — {_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Lista de materiales (BOM)</h1>
<p><small>{_esc(title)}{' · ' + _esc(project_name) if project_name else ''}
   · Generado el {_esc(datetime.now().isoformat(timespec='seconds'))}</small></p>
""")

    # ---- Resumen ejecutivo ----------------------------------------------
    parts.append("<h2>Resumen</h2>")
    parts.append("<div class='summary'>")
    parts.append(
        f"<div class='summary-metric'><div class='value'>"
        f"{summary['total_weight_kg']/1000:.2f} t</div>"
        f"<div class='label'>Peso total</div>"
        f"<div class='label'><small>({summary['total_weight_kg']:.0f} kg)</small></div></div>"
    )
    parts.append(
        f"<div class='summary-metric'><div class='value'>"
        f"{summary['total_pieces']}</div>"
        f"<div class='label'>Piezas totales</div></div>"
    )
    parts.append(
        f"<div class='summary-metric'><div class='value'>"
        f"{summary['total_tube_length_m']:.0f} m</div>"
        f"<div class='label'>Longitud lineal de tubo</div></div>"
    )
    parts.append(
        f"<div class='summary-metric'><div class='value'>"
        f"{len(summary['by_category'])}</div>"
        f"<div class='label'>Categorías</div></div>"
    )
    parts.append("</div>")

    # ---- Breakdown por categoría (tabla) --------------------------------
    parts.append("<h2>Distribución por categoría</h2>")
    parts.append("<table class='cat-breakdown'>")
    parts.append("<thead><tr><th>Categoría</th><th>Piezas</th>"
                 "<th>Tubo (m)</th><th>Peso</th><th>%</th></tr></thead><tbody>")
    total_w = max(summary['total_weight_kg'], 1e-9)
    for entry in summary["by_category"]:
        pct = 100.0 * entry["weight_kg"] / total_w
        tube_m = entry.get("tube_length_m", 0.0)
        parts.append(
            f"<tr><td>{_esc(entry['label'])}</td>"
            f"<td>{entry['count']}</td>"
            f"<td>{tube_m:.1f}</td>"
            f"<td>{entry['weight_kg']:.1f} kg</td>"
            f"<td>{pct:.1f} %</td></tr>"
        )
    parts.append(
        f"<tfoot><tr><td>TOTAL</td>"
        f"<td>{summary['total_pieces']}</td>"
        f"<td>{summary['total_tube_length_m']:.1f}</td>"
        f"<td>{summary['total_weight_kg']:.1f} kg</td>"
        f"<td>100,0 %</td></tr></tfoot>"
    )
    parts.append("</table>")

    # ---- Cómo leer este informe -----------------------------------------
    parts.append("""\
<div class='help-card'>
<h3 style='margin-top:0'>Cómo leer este documento</h3>
<p>
  Este documento lista todos los elementos del andamio agrupados por
  categoría (postes, travesaños, plataformas, etc.) y por longitud. Cada
  fila indica cuántas piezas de un tamaño dado se necesitan, el peso
  unitario y el peso acumulado. Usa el peso total del resumen para
  dimensionar el transporte; usa las cantidades por longitud para
  pedir las piezas al fabricante.
</p>
</div>
""")

    # ---- Detalle por categoría ------------------------------------------
    parts.append("<h2>Detalle por categoría</h2>")
    for cat_id, cat_groups in by_cat.items():
        cat_info = CATEGORY_LABELS.get(cat_id, {})
        label = cat_info.get("label", cat_id)
        description = cat_info.get("description", "")

        img_url = screenshots.get(cat_id)
        if img_url:
            img_html = f"<div class='img-box'><img src='{img_url}' alt='{_esc(label)}'/></div>"
        else:
            img_html = "<div class='img-box no-img'>Imagen no disponible</div>"

        parts.append(f"<div class='cat-section'>")
        parts.append(img_html)
        parts.append("<div class='cat-info'>")
        parts.append(f"<h3>{_esc(label)}</h3>")
        if description:
            parts.append(f"<p class='desc'>{_esc(description)}</p>")
        parts.append(_category_table(cat_groups))
        parts.append("</div></div>")

    # ---- Glosario --------------------------------------------------------
    parts.append("<h2>Glosario</h2>")
    parts.append("<div class='help-card glossary'><dl>")
    parts.append(
        "<dt>Tubo CHS Ø48,3×3,2</dt>"
        "<dd>Sección estándar Layher / Ringlock EU. Acero S235JR, "
        "ρ=7850 kg/m³, peso lineal ≈ 3,56 kg/m.</dd>"
    )
    for cat_id, cat_info in CATEGORY_LABELS.items():
        parts.append(f"<dt>{_esc(cat_info['label'])}</dt>"
                     f"<dd>{_esc(cat_info['description'])}</dd>")
    parts.append("</dl></div>")

    parts.append("</body></html>")
    return "\n".join(parts)


def write_bom_html(path: str, *args, **kwargs) -> str:
    """Genera y escribe el BOM en `path`. Devuelve la ruta absoluta."""
    text = generate_bom_html(*args, **kwargs)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.abspath(path)
