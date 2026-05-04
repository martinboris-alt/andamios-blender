"""Generación del informe HTML del cálculo estructural.

Diseñado para ser leído por personas **no expertas** en cálculo
estructural (jefe de obra, técnico de seguridad, inspector). El HTML es
autocontenido (CSS embebido + imágenes en base64) — un único fichero
adjuntable a un informe de seguridad.

Estructura del informe:

    1. Cabecera con fecha y nombre
    2. Resumen ejecutivo — semáforo grande + frase clara
    3. Cómo leer este informe — un párrafo explicativo
    4. Configuración del cálculo — qué cargas se aplicaron, en plano
    5. Resumen numérico — barras OK / al límite / sobrepasadas + δ_max
    6. Elementos críticos (tarjetas) — imagen del miembro + diagnóstico
       (qué le pasa + cómo corregir) por cada barra fallida
    7. Tabla completa con las top N utilizaciones (auditoría)
    8. Glosario — términos técnicos en plano
"""

from __future__ import annotations

import html
import os
from datetime import datetime
from typing import Mapping

from .checks import MemberCheckResult
from .model import Model
from .pipeline import (
    SERVICE_DESCRIPTION,
    WIND_DESCRIPTION,
    deflection_summary,
    diagnose_failure,
    format_status_message,
)
from .solver import Results


# ---------------------------------------------------------------------------
# Constantes y plantillas auxiliares
# ---------------------------------------------------------------------------

_SEVERITY_COLOR = {
    "ok":       "#27ae60",
    "minor":    "#f39c12",
    "serious":  "#e67e22",
    "critical": "#c0392b",
}

_SEVERITY_BG = {
    "ok":       "#e8f8ee",
    "minor":    "#fef5e7",
    "serious":  "#fdebd0",
    "critical": "#f9d6d5",
}

_LEVEL_TO_TRAFFIC_LIGHT = {
    "ok":      ("✓", "#27ae60", "ANDAMIO SEGURO"),
    "warning": ("⚠", "#f39c12", "MARGEN AJUSTADO"),
    "fail":    ("✗", "#c0392b", "ATENCIÓN: NO CUMPLE"),
}


_GLOSSARY = [
    ("Utilización (util)",
     "Ratio entre la carga que sufre la barra y su capacidad máxima. "
     "0 = la barra está en reposo, 1 = está al límite, > 1 = sobrepasada."),
    ("ULS (Estado Límite Último)",
     "Comprobación de seguridad — verifica que la estructura no rompe ni "
     "vuelca. Las cargas se mayoran (multiplicar por 1,35–1,5) para tener "
     "un margen de seguridad."),
    ("SLS (Estado Límite de Servicio)",
     "Comprobación de comodidad de uso — verifica que las deformaciones "
     "y vibraciones no son molestas. Cargas sin mayorar."),
    ("Compresión",
     "El elemento se aplasta longitudinalmente. Típico en postes verticales "
     "que reciben el peso desde arriba."),
    ("Pandeo",
     "El elemento se dobla por compresión: pierde la verticalidad antes "
     "de aplastarse. Para evitarlo se acortan los tramos sin arriostrar."),
    ("Flexión",
     "El elemento se curva bajo cargas perpendiculares a su eje. Típico "
     "en travesaños horizontales que reciben peso encima."),
    ("Tracción",
     "El elemento se estira por fuerzas que tiran de él en sus extremos. "
     "Típico en anclajes a fachada cuando hay viento de levantamiento."),
    ("Combinada (axil + flexión)",
     "Fallo por la suma de compresión y flexión simultáneas. El elemento "
     "se aplasta mientras se flexa lateralmente."),
    ("Deformación δ",
     "Cuánto se mueve un punto de la estructura al cargarla. Se compara "
     "con la longitud del elemento — un travesaño de 3 m no debe deformarse "
     "más de 30 mm (L/100)."),
    ("Q1..Q6 (clases EN 12811-1)",
     "Cuánto peso de servicio aguanta el andamio: Q1=75 kg/m² (sólo "
     "inspección), Q3=200 kg/m² (uso general), Q6=600 kg/m² "
     "(almacenaje muy pesado)."),
    ("Zona de viento (CTE A/B/C)",
     "Velocidad básica del viento según ubicación geográfica. "
     "A=26 m/s (la mayor parte de España), B=27, C=29 (Canarias y "
     "litoral expuesto)."),
]


# ---------------------------------------------------------------------------
# CSS embebido — todo el aspecto visual en un único fichero HTML
# ---------------------------------------------------------------------------

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
h3 { color: #0a3055; margin-top: 1.5em; font-size: 1.1em; }
h4 { color: #0a3055; margin: 0.8em 0 0.3em; font-size: 0.95em; font-weight: 600; }
small { color: #6b7280; }
code { font-family: ui-monospace, "SF Mono", Menlo, monospace;
       font-size: 0.92em; background: #f4f6fa; padding: 1px 4px;
       border-radius: 3px; }
.muted { color: #6b7280; }

/* Resumen ejecutivo — semáforo grande */
.exec-summary {
    background: #fff; border-radius: 12px; padding: 1.5em 2em;
    margin: 1em 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    display: flex; gap: 1.5em; align-items: center;
}
.exec-light {
    width: 80px; height: 80px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 3em; font-weight: bold; flex-shrink: 0;
}
.exec-text h2 { border: none; margin: 0 0 0.2em; padding: 0; }
.exec-text p { margin: 0; color: #4a5568; }

/* Cards genéricos */
.card {
    background: #fff; border-radius: 8px; padding: 1.2em 1.5em;
    margin: 1em 0; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}
.help-card {
    background: #eff6ff; border-left: 4px solid #3b82f6;
    padding: 1em 1.2em; margin: 1em 0; border-radius: 4px;
}

/* Tabla resumen de configuración */
.cfg-table { width: 100%; border-collapse: collapse; }
.cfg-table th { text-align: left; padding: 0.4em 0.6em; background: #f4f6fa;
                color: #4a5568; font-weight: 600; }
.cfg-table td { padding: 0.4em 0.6em; border-bottom: 1px solid #e5e7eb; }

/* Métricas en grid */
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 1em; margin: 1em 0; }
.metric { background: #fff; border-radius: 8px; padding: 1em;
          box-shadow: 0 1px 3px rgba(0,0,0,0.05); text-align: center; }
.metric-value { font-size: 2em; font-weight: bold; margin: 0.2em 0; }
.metric-label { color: #6b7280; font-size: 0.9em; }

/* Tarjetas de fallo */
.failure-card {
    border-left: 6px solid #c0392b; border-radius: 8px;
    background: #fff; padding: 1.2em 1.5em; margin: 1em 0;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    display: grid; grid-template-columns: 320px 1fr; gap: 1.5em;
    align-items: start;
}
.failure-card.severity-minor    { border-left-color: #f39c12; }
.failure-card.severity-serious  { border-left-color: #e67e22; }
.failure-card.severity-critical { border-left-color: #c0392b; }
.failure-card .img-box { background: #f8fafc; border-radius: 6px;
                         overflow: hidden; aspect-ratio: 1; }
.failure-card img { width: 100%; height: 100%; object-fit: cover; display: block; }
.failure-card .no-img { display: flex; align-items: center; justify-content: center;
                        color: #9ca3af; aspect-ratio: 1; }
.failure-head { display: flex; gap: 0.8em; align-items: baseline;
                margin-bottom: 0.4em; flex-wrap: wrap; }
.failure-head h3 { margin: 0; }
.severity-badge { font-size: 0.85em; font-weight: 600;
                  padding: 0.2em 0.7em; border-radius: 999px;
                  white-space: nowrap; }
.severity-badge.minor    { color: #92400e; background: #fef3c7; }
.severity-badge.serious  { color: #9a3412; background: #fed7aa; }
.severity-badge.critical { color: #fff;    background: #c0392b; }
.failure-meta { display: flex; gap: 1em; color: #6b7280;
                font-size: 0.92em; margin-bottom: 0.6em; }
.failure-meta strong { color: #1a1a1a; font-weight: 600; }

/* Tabla detallada */
.detail-table { width: 100%; border-collapse: collapse; font-size: 0.92em; }
.detail-table th, .detail-table td {
    padding: 0.4em 0.6em; border-bottom: 1px solid #e5e7eb; text-align: right;
}
.detail-table th { background: #f4f6fa; text-align: center; }
.detail-table td:first-child, .detail-table th:first-child { text-align: left; }
.row-bucket-0 td { background: #d4f7d4; }
.row-bucket-1 td { background: #ecf7c4; }
.row-bucket-2 td { background: #fff3a8; }
.row-bucket-3 td { background: #ffd699; }
.row-bucket-4 td { background: #ffacac; }
.row-bucket-5 td { background: #c00000; color: #fff; }
.fail-text { color: #c0392b; font-weight: bold; }
.ok-text   { color: #27ae60; }

/* Glosario */
.glossary dt { font-weight: 600; color: #0a3055; margin-top: 0.8em; }
.glossary dd { margin-left: 0; color: #4a5568; }

/* Vistas del andamio (overview) */
.overview-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
    gap: 1em; margin: 1em 0;
}
.overview-figure {
    margin: 0; background: #fff; border-radius: 6px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05); overflow: hidden;
}
.overview-figure img { width: 100%; height: auto; display: block;
                       background: #fff; }
.overview-figure figcaption {
    padding: 0.5em 0.8em; background: #f4f6fa;
    color: #0a3055; font-weight: 600; text-align: center;
    border-top: 1px solid #e5e7eb;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OVERVIEW_VIEW_LABELS = {
    "iso":   "Vista isométrica",
    "front": "Alzado frontal",
    "side":  "Alzado lateral",
    "top":   "Planta",
    "cad":   "Plano técnico (CAD)",
}


def _overview_views_html(overview_screenshots: Mapping[str, str]) -> str:
    """Renderiza las vistas globales del andamio en un grid 2×2 (+CAD si hay)."""
    # Orden fijo: iso, front, side, top, cad
    view_order = ("iso", "front", "side", "top", "cad")
    views_present = [v for v in view_order if v in overview_screenshots]
    if not views_present:
        return ""

    parts = ["<h2>Vistas del andamio</h2>"]
    parts.append("<div class='overview-grid'>")
    for view in views_present:
        label = _OVERVIEW_VIEW_LABELS.get(view, view)
        url = overview_screenshots[view]
        parts.append(
            f"<figure class='overview-figure'>"
            f"<img src='{url}' alt='{_esc(label)}'/>"
            f"<figcaption>{_esc(label)}</figcaption>"
            f"</figure>"
        )
    parts.append("</div>")
    return "\n".join(parts)


def _bucket(util: float) -> int:
    thresholds = [0.50, 0.70, 0.85, 1.00, 1.30]
    for i, t in enumerate(thresholds):
        if util < t:
            return i
    return 5


def _esc(s: str) -> str:
    return html.escape(str(s))


def _config_rows_html(options: Mapping[str, object]) -> str:
    """Renderiza la tabla de configuración del cálculo en plano."""
    if not options:
        return "<p class='muted'>No se ha registrado configuración.</p>"

    rows = []
    rows.append("<table class='cfg-table'><tbody>")

    if options.get("apply_service"):
        klass = str(options.get("service_class", "Q3"))
        rows.append(
            "<tr><th>Carga de uso (servicio)</th>"
            f"<td>{_esc(klass)} — {_esc(SERVICE_DESCRIPTION.get(klass, klass))}</td></tr>"
        )
        deck_w = options.get("deck_width")
        if deck_w is not None:
            rows.append(f"<tr><th>Ancho de plataforma</th>"
                        f"<td>{float(deck_w)*100:.0f} cm</td></tr>")
    else:
        rows.append("<tr><th>Carga de uso</th><td>No considerada</td></tr>")

    if options.get("apply_wind"):
        zone = str(options.get("wind_zone", "A"))
        terrain = str(options.get("wind_terrain", "II"))
        rows.append(
            "<tr><th>Viento</th>"
            f"<td>{_esc(WIND_DESCRIPTION.get(zone, 'zona ' + zone))}, terreno categoría {_esc(terrain)}</td></tr>"
        )
    else:
        rows.append("<tr><th>Viento</th><td>No considerado</td></tr>")

    if options.get("apply_imperfections"):
        rows.append("<tr><th>Tolerancias de montaje</th>"
                    "<td>Aplicadas (EN 1993-1-1 §5.3, ≈0,5 % del peso total)</td></tr>")
    else:
        rows.append("<tr><th>Tolerancias de montaje</th><td>No consideradas</td></tr>")

    combo_label = {
        "ULS_LeadL":  "Resistencia con uso dominante (1,35 G + 1,5 L + 0,9 W)",
        "ULS_LeadW":  "Resistencia con viento dominante (1,35 G + 1,05 L + 1,5 W)",
        "ULS_Uplift": "Resistencia frente a levantamiento (1,0 G + 1,5 W)",
        "SLS_char_L": "Servicio — característica",
        "SLS_freq_L": "Servicio — frecuente",
        "SLS_quasi":  "Servicio — casi-permanente",
    }.get(str(options.get("combo", "ULS_LeadL")), str(options.get("combo", "—")))
    rows.append(f"<tr><th>Caso analizado</th><td>{_esc(combo_label)}</td></tr>")

    if options.get("use_pdelta"):
        rows.append(
            "<tr><th>Tipo de análisis</th>"
            "<td><strong>2º orden geométrico (P-Δ)</strong> — la rigidez se "
            "actualiza iterativamente con la posición deformada de los postes. "
            "Captura la amplificación de momentos por desplome de la cúspide. "
            "Recomendado por EN 1993-1-1 §5.2 cuando α<sub>cr</sub> ≤ 10.</td></tr>"
        )
    else:
        rows.append(
            "<tr><th>Tipo de análisis</th>"
            "<td>Lineal de 1<sup>er</sup> orden (rigidez basada en geometría "
            "indeformada). Adecuado para la mayoría de andamios; en torres "
            "esbeltas (>15 m sin anclajes) considerar activar P-Δ.</td></tr>"
        )

    rows.append("</tbody></table>")
    return "".join(rows)


def _failure_card_html(
    cr: MemberCheckResult,
    member_type: str | None,
    img_data_url: str | None,
) -> str:
    """Renderiza una tarjeta de fallo con diagnóstico narrativo + imagen."""
    diag = diagnose_failure(cr, member_type=member_type)
    severity = diag["severity"]

    if img_data_url:
        img = f"<div class='img-box'><img src='{img_data_url}' alt='{_esc(cr.member)}'/></div>"
    else:
        img = "<div class='img-box no-img'>Imagen no disponible</div>"

    return f"""\
<div class='failure-card severity-{severity}'>
  {img}
  <div class='member-info'>
    <div class='failure-head'>
      <h3>{_esc(cr.member)}</h3>
      <span class='severity-badge {severity}'>{_esc(diag['severity_label'])}</span>
    </div>
    <div class='failure-meta'>
      <span>Util <strong>{cr.utilization:.2f}</strong></span>
      <span>Tipo: <strong>{_esc(diag['type'])}</strong></span>
      <span>Sección: <strong>{_esc(cr.section)}</strong></span>
      <span>L: <strong>{cr.L:.2f} m</strong></span>
    </div>
    <h4>¿Qué le pasa?</h4>
    <p>{_esc(diag['why'])}</p>
    <h4>¿Cómo corregir?</h4>
    <p>{_esc(diag['fix'])}</p>
  </div>
</div>"""


def _detail_table_html(
    sorted_checks: list[MemberCheckResult],
    top_n: int,
) -> str:
    rows = ["<table class='detail-table'>"]
    rows.append(
        "<thead><tr><th>#</th><th>Barra</th><th>Sección</th>"
        "<th>L (m)</th><th>L_cr (m)</th>"
        "<th>Tracción</th><th>Compresión</th><th>Pandeo</th>"
        "<th>Combinada</th><th>Util peor</th><th>OK</th></tr></thead><tbody>"
    )
    for i, cr in enumerate(sorted_checks[:top_n], 1):
        sc = cr.section_check
        bucket = _bucket(cr.utilization)
        ok_text = "✓" if cr.passed else "✗"
        ok_class = "ok-text" if cr.passed else "fail-text"
        rows.append(
            f"<tr class='row-bucket-{bucket}'>"
            f"<td>{i}</td>"
            f"<td><code>{_esc(cr.member)}</code></td>"
            f"<td>{_esc(cr.section)}</td>"
            f"<td>{cr.L:.2f}</td><td>{cr.L_cr:.2f}</td>"
            f"<td>{sc.tension:.2f}</td><td>{sc.compression:.2f}</td>"
            f"<td>{sc.buckling:.2f}</td><td>{sc.combined:.2f}</td>"
            f"<td><strong>{cr.utilization:.2f}</strong></td>"
            f"<td class='{ok_class}'>{ok_text}</td></tr>"
        )
    rows.append("</tbody></table>")
    return "".join(rows)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def generate_html_report(
    model: Model,
    results: Results,
    checks: Mapping[str, MemberCheckResult],
    *,
    options: Mapping[str, object] | None = None,
    deflections: Mapping[str, Mapping] | None = None,
    screenshots: Mapping[str, str] | None = None,
    overview_screenshots: Mapping[str, str] | None = None,
    title: str = "Andamio multidireccional",
    top_n: int = 15,
) -> str:
    """Genera el HTML completo del informe.

    Parameters
    ----------
    model, results, checks
        Como en versiones anteriores.
    options : dict | None
        Configuración del cálculo (las options del pipeline). Si None, no
        se mostrará la sección "Configuración".
    deflections : dict | None
        Salida de `compute_member_deflections`. Si se pasa, se incluye la
        deformación máxima en el resumen.
    screenshots : dict | None
        Mapa `{member_id: data_url_PNG}` con las imágenes de cada fallo.
        Si no se pasa, las tarjetas de fallo no llevan imagen.
    title : str
        Título principal del informe.
    top_n : int
        Cuántas filas mostrar en la tabla detallada.
    """
    options = options or {}
    screenshots = screenshots or {}
    overview_screenshots = overview_screenshots or {}

    # ---- Métricas globales -----------------------------------------------
    status = format_status_message(checks, options)
    sorted_checks = sorted(
        checks.values(), key=lambda c: c.utilization, reverse=True,
    )
    failed_checks = [c for c in sorted_checks if c.utilization > 1.0]
    near_limit = [c for c in sorted_checks
                  if 0.85 <= c.utilization <= 1.0]

    defl_info = deflection_summary(deflections or {}) if deflections else None

    # ---- HTML ------------------------------------------------------------
    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe de cálculo estructural — {_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Informe de cálculo estructural</h1>
<p><small>{_esc(title)} · Generado el {_esc(datetime.now().isoformat(timespec='seconds'))}</small></p>
""")

    # ---- 1. Resumen ejecutivo --------------------------------------------
    icon, color, headline = _LEVEL_TO_TRAFFIC_LIGHT.get(
        status["level"], ("?", "#888", status["title"])
    )
    parts.append(f"""\
<div class='exec-summary'>
  <div class='exec-light' style='background: {color}'>{icon}</div>
  <div class='exec-text'>
    <h2 style='color: {color}'>{_esc(headline)}</h2>
    <p>{_esc(status['subtitle'])}</p>
    <p><small>Utilización máxima: <strong>{status['worst']:.2f}</strong>
       · Barras analizadas: {status['n_total']}
       · Sobrepasadas: {status['n_failed']}
       · Cerca del límite: {status['n_warning']}</small></p>
  </div>
</div>
""")

    # ---- 1.5. Vistas globales del andamio --------------------------------
    if overview_screenshots:
        parts.append(_overview_views_html(overview_screenshots))

    # ---- 2. Cómo leer este informe ---------------------------------------
    parts.append("""\
<div class='help-card'>
<h3 style='margin-top:0'>Cómo leer este informe</h3>
<p>
  Cada barra del andamio tiene una <em>utilización</em>: 0 = no recibe carga,
  1 = trabaja al máximo de su capacidad, mayor que 1 = sobrepasa la seguridad.
  El semáforo de arriba resume si el andamio cumple en su conjunto.
  En la sección "Elementos críticos" se explica, para cada barra problemática,
  qué le ocurre y qué cambiar en el diseño para resolverlo.
  El glosario al final aclara los términos técnicos.
</p>
</div>
""")

    # ---- 3. Configuración del cálculo ------------------------------------
    parts.append("<h2>Configuración del cálculo</h2>")
    parts.append("<div class='card'>")
    parts.append(_config_rows_html(options))
    parts.append("</div>")

    # ---- 4. Resumen numérico ---------------------------------------------
    parts.append("<h2>Resumen de comprobaciones</h2>")
    parts.append("<div class='metrics'>")
    parts.append(
        f"<div class='metric'><div class='metric-label'>Barras analizadas</div>"
        f"<div class='metric-value'>{status['n_total']}</div></div>"
    )
    ok_count = status['n_total'] - status['n_failed'] - status['n_warning']
    parts.append(
        f"<div class='metric'><div class='metric-label'>OK (holgadas)</div>"
        f"<div class='metric-value' style='color:#27ae60'>{ok_count}</div></div>"
    )
    parts.append(
        f"<div class='metric'><div class='metric-label'>Cerca del límite</div>"
        f"<div class='metric-value' style='color:#f39c12'>{status['n_warning']}</div></div>"
    )
    parts.append(
        f"<div class='metric'><div class='metric-label'>Sobrepasadas</div>"
        f"<div class='metric-value' style='color:#c0392b'>{status['n_failed']}</div></div>"
    )
    if defl_info:
        worst_disp_mm = defl_info['worst_disp_m'] * 1000
        ratio = defl_info['worst_ratio']
        ratio_str = f"L/{int(1.0/ratio):.0f}" if ratio > 0 else "—"
        parts.append(
            f"<div class='metric'><div class='metric-label'>Deformación máxima</div>"
            f"<div class='metric-value'>{worst_disp_mm:.1f} mm</div>"
            f"<div class='metric-label'>{_esc(ratio_str)}</div></div>"
        )
    parts.append("</div>")

    # ---- 5. Elementos críticos (tarjetas) --------------------------------
    if failed_checks or near_limit:
        n_critical = len(failed_checks) + len(near_limit)
        parts.append(f"<h2>Elementos críticos ({n_critical})</h2>")
        if failed_checks:
            parts.append(f"<p class='muted'>Sobrepasados ({len(failed_checks)}) — corregir antes de poner en uso:</p>")
            for cr in failed_checks:
                mtype = (model.members[cr.member].member_type
                         if cr.member in model.members else None)
                parts.append(_failure_card_html(
                    cr, mtype, screenshots.get(cr.member),
                ))
        if near_limit:
            parts.append(f"<p class='muted'>Cerca del límite ({len(near_limit)}) — revisar:</p>")
            for cr in near_limit:
                mtype = (model.members[cr.member].member_type
                         if cr.member in model.members else None)
                parts.append(_failure_card_html(
                    cr, mtype, screenshots.get(cr.member),
                ))
    else:
        parts.append("<h2>Elementos críticos</h2>")
        parts.append("<div class='card'><p class='ok-text'>"
                     "✓ Todas las barras están holgadas frente a su capacidad.</p></div>")

    # ---- 6. Tabla detallada ---------------------------------------------
    parts.append(f"<h2>Detalle de las {min(top_n, len(sorted_checks))} barras más solicitadas</h2>")
    parts.append("<div class='card'>")
    parts.append(_detail_table_html(sorted_checks, top_n))
    parts.append("</div>")

    # ---- 7. Glosario -----------------------------------------------------
    parts.append("<h2>Glosario</h2>")
    parts.append("<div class='card glossary'><dl>")
    for term, definition in _GLOSSARY:
        parts.append(f"<dt>{_esc(term)}</dt><dd>{_esc(definition)}</dd>")
    parts.append("</dl></div>")

    parts.append("</body></html>")
    return "\n".join(parts)


def write_html_report(
    path: str,
    model: Model,
    results: Results,
    checks: Mapping[str, MemberCheckResult],
    **kwargs,
) -> str:
    """Genera el informe y lo escribe en `path`. Devuelve la ruta absoluta."""
    text = generate_html_report(model, results, checks, **kwargs)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.abspath(path)
