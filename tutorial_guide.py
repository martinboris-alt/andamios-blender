"""Tutorial guiado in-Blender — wizard estilo Illustrator.

Operador modal que dibuja un overlay sobre el viewport 3D con
instrucciones paso a paso, detecta automáticamente cuándo el usuario
completa cada acción y avanza al siguiente paso.

Estructura
----------
- `TutorialState` — singleton con el estado actual (paso, contadores
  iniciales para detectar progreso).
- 6 pasos: WELCOME → CREATE_E1 → CREATE_E2 → ASSIGN_PATH → GENERATE → DONE
- `ANDAMIOS_OT_tutorial_start` — operador modal que registra el draw
  handler + timer y procesa eventos.
- `ANDAMIOS_OT_tutorial_next` / `tutorial_skip` — controles manuales.
- `_draw_overlay()` — pinta caja flotante con título, instrucción y
  flecha pulsante usando `gpu` + `blf`.

Detección automática
--------------------
- `CREATE_E1` → contar empties en escena, avanzar al añadir uno.
- `CREATE_E2` → idem, avanzar al haber 2 más que al inicio del paso.
- `ASSIGN_PATH` → comprobar `len(path_points) >= 2 con obj != None`.
- `GENERATE` → comprobar que existe colección Scaffold con objetos.

Limitaciones conocidas
----------------------
- El overlay sólo se pinta sobre el viewport 3D. Para guiar al panel
  N-bar, se dibuja una flecha pulsante hacia la derecha del viewport.
- Los controles nativos de Blender no se "animan" pulsándose solos.
  Sólo se highlight con `alert=True` en el panel propio.
- El tutorial detecta acciones por contadores (frágil si el usuario
  hace cosas adicionales). Los contadores se cogen al inicio de cada
  paso para mitigar.
"""

from __future__ import annotations

import math
from typing import Optional

import bpy
import blf
import gpu
from bpy.app.translations import pgettext_iface as iface_
from bpy.types import Operator, Panel
from gpu_extras.batch import batch_for_shader


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

STEP_WELCOME = "welcome"
STEP_CREATE_E1 = "create_e1"
STEP_CREATE_E2 = "create_e2"
STEP_ASSIGN_PATH = "assign_path"
STEP_GENERATE = "generate"
STEP_DONE = "done"

STEPS_ORDER = (
    STEP_WELCOME,
    STEP_CREATE_E1,
    STEP_CREATE_E2,
    STEP_ASSIGN_PATH,
    STEP_GENERATE,
    STEP_DONE,
)

STEP_INFO = {
    STEP_WELCOME: {
        "n":     0,
        "total": 5,
        "title": "👋 ¡Bienvenido al tutorial guiado!",
        "instr": ("Vas a crear tu primer andamio en 5 pasos. "
                  "Sigue las instrucciones aquí abajo."),
        "subtext": "Pulsa SIGUIENTE para empezar · ESC para cancelar.",
        "highlight_panel": None,
        "auto_advance": False,
    },
    STEP_CREATE_E1: {
        "n":     1,
        "total": 5,
        "title": "Paso 1 de 5 — Crea el primer punto",
        "instr": "En el menú superior del viewport: Add → Empty → Plain Axes.",
        "subtext": ("Esto crea un marcador 3D que será el inicio de "
                    "tu andamio. Avanza automáticamente al detectarlo."),
        "highlight_panel": None,
        "auto_advance": True,
    },
    STEP_CREATE_E2: {
        "n":     2,
        "total": 5,
        "title": "Paso 2 de 5 — Crea el segundo punto",
        "instr": "Añade otro empty: Add → Empty → Plain Axes.",
        "subtext": ("Sepáralo del primero (mueve con G y X 8 unidades). "
                    "Será el otro extremo del andamio."),
        "highlight_panel": None,
        "auto_advance": True,
    },
    STEP_ASSIGN_PATH: {
        "n":     3,
        "total": 5,
        "title": "Paso 3 de 5 — Añádelos a la lista",
        "instr": ("Abre la pestaña Andamios (N) y, en Trayectoria, "
                  "pulsa + dos veces y asigna los dos empties."),
        "subtext": "Avanza cuando los dos puntos estén en la lista.",
        "highlight_panel": "trayectoria",
        "auto_advance": True,
    },
    STEP_GENERATE: {
        "n":     4,
        "total": 5,
        "title": "Paso 4 de 5 — Genera el andamio",
        "instr": "Pulsa el botón ⟳ Generar / Actualizar.",
        "subtext": ("Por defecto crea un andamio de 2 plantas con "
                    "plataformas, barandillas y escalera."),
        "highlight_panel": "generate",
        "auto_advance": True,
    },
    STEP_DONE: {
        "n":     5,
        "total": 5,
        "title": "🎉 ¡Listo! Has creado tu primer andamio",
        "instr": "Ahora puedes calcular su resistencia o exportar un plano CAD.",
        "subtext": ("Pulsa CERRAR para terminar. El modo guía se desactiva."),
        "highlight_panel": None,
        "auto_advance": False,
    },
}


class TutorialState:
    """Singleton de estado. Atributos de clase porque sólo existe uno."""
    active: bool = False
    step: str = STEP_WELCOME
    # Contadores capturados al entrar en cada paso para detectar deltas
    n_empties_at_step: int = 0
    n_path_points_at_step: int = 0
    scaffold_at_step: bool = False
    # Animación
    frame: int = 0

    @classmethod
    def reset(cls) -> None:
        cls.active = False
        cls.step = STEP_WELCOME
        cls.frame = 0

    @classmethod
    def go_to_step(cls, step: str, context: bpy.types.Context) -> None:
        cls.step = step
        cls.frame = 0
        cls.n_empties_at_step = _count_empties(context)
        cls.n_path_points_at_step = _count_path_points(context)
        cls.scaffold_at_step = _scaffold_exists()


def _step_index(step: str) -> int:
    try:
        return STEPS_ORDER.index(step)
    except ValueError:
        return 0


def _next_step(step: str) -> str:
    i = _step_index(step)
    if i + 1 < len(STEPS_ORDER):
        return STEPS_ORDER[i + 1]
    return STEP_DONE


# ---------------------------------------------------------------------------
# Detección automática
# ---------------------------------------------------------------------------

def _count_empties(context: bpy.types.Context) -> int:
    return sum(1 for o in context.scene.objects if o.type == 'EMPTY')


def _count_path_points(context: bpy.types.Context) -> int:
    """Path points con obj asignado (no None)."""
    props = getattr(context.scene, "andamios_props", None)
    if props is None:
        return 0
    return sum(1 for pp in props.path_points if pp.obj is not None)


def _scaffold_exists() -> bool:
    coll = bpy.data.collections.get("Scaffold")
    return coll is not None and len(coll.all_objects) > 0


def _check_auto_advance(context: bpy.types.Context) -> bool:
    """Mira si la condición de avance del paso actual se cumple.
    Si sí, avanza al siguiente paso y devuelve True (para forzar redraw)."""
    info = STEP_INFO.get(TutorialState.step, {})
    if not info.get("auto_advance"):
        return False

    step = TutorialState.step
    if step == STEP_CREATE_E1:
        if _count_empties(context) > TutorialState.n_empties_at_step:
            TutorialState.go_to_step(STEP_CREATE_E2, context)
            return True
    elif step == STEP_CREATE_E2:
        # Necesita 2 empties más que cuando empezó el paso 1 (welcome)
        # Como reseteamos contadores en cada step, basta con 1 más
        if _count_empties(context) > TutorialState.n_empties_at_step:
            TutorialState.go_to_step(STEP_ASSIGN_PATH, context)
            return True
    elif step == STEP_ASSIGN_PATH:
        if _count_path_points(context) >= 2:
            TutorialState.go_to_step(STEP_GENERATE, context)
            return True
    elif step == STEP_GENERATE:
        if _scaffold_exists() and not TutorialState.scaffold_at_step:
            TutorialState.go_to_step(STEP_DONE, context)
            return True
    return False


# ---------------------------------------------------------------------------
# Overlay drawing (gpu + blf)
# ---------------------------------------------------------------------------

# Paleta consistente con el HTML del tutorial
COLOR_BG_PANEL  = (0.04, 0.06, 0.13, 0.92)   # azul oscuro casi opaco
COLOR_BG_BORDER = (0.15, 0.40, 0.85, 1.00)   # azul corporativo
COLOR_TITLE     = (1.00, 1.00, 1.00, 1.00)
COLOR_INSTR     = (0.90, 0.95, 1.00, 1.00)
COLOR_SUBTEXT   = (0.60, 0.70, 0.85, 1.00)
COLOR_ARROW     = (0.96, 0.62, 0.04, 1.00)   # ámbar
COLOR_PROGRESS  = (0.15, 0.65, 0.40, 1.00)   # verde


# Multiplicador extra sobre el ui_scale del sistema. El módulo `gpu`+`blf`
# no respeta el ui_scale del tema, por lo que en monitores HiDPI las cajas
# y las fuentes salen visiblemente pequeñas. 2.3 = 130 % más grande
# respecto al ui_scale base. Si quieres ajustar, modifica esta constante.
TUTORIAL_OVERLAY_BOOST: float = 2.3


def _ui_scale() -> float:
    """Factor de escala efectivo del overlay (combina `view.ui_scale` de
    Blender × `TUTORIAL_OVERLAY_BOOST`).

    El módulo `gpu` y `blf` no respeta el ui_scale del tema; al pintar en
    `POST_PIXEL` las dimensiones son píxeles físicos. Sin este multiplicador,
    el texto en monitores HiDPI/4K queda diminuto.

    Lee `view.ui_scale` y, si no existe, cae al `pixel_size` o a 1.0.
    """
    try:
        base = float(bpy.context.preferences.view.ui_scale)
    except (AttributeError, TypeError):
        try:
            base = float(bpy.context.preferences.system.pixel_size)
        except (AttributeError, TypeError):
            base = 1.0
    return base * TUTORIAL_OVERLAY_BOOST


def _draw_rect_filled(x: float, y: float, w: float, h: float,
                       color: tuple) -> None:
    vertices = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    indices = ((0, 1, 2), (2, 3, 0))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS',
                              {"pos": vertices}, indices=indices)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _draw_rect_outline(x: float, y: float, w: float, h: float,
                        color: tuple, width: float = 2.0) -> None:
    vertices = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    indices = ((0, 1), (1, 2), (2, 3), (3, 0))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES',
                              {"pos": vertices}, indices=indices)
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _draw_text(text: str, x: float, y: float, *,
                size: int = 14, color: tuple = (1, 1, 1, 1)) -> None:
    font_id = 0
    blf.position(font_id, x, y, 0)
    blf.size(font_id, size)
    blf.color(font_id, *color)
    blf.draw(font_id, text)


def _draw_arrow(start: tuple, end: tuple, color: tuple,
                 width: float = 4.0, head_size: float = 14.0) -> None:
    """Flecha simple con cabeza triangular."""
    sx, sy = start
    ex, ey = end
    # Cuerpo
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    body = batch_for_shader(shader, 'LINES',
                             {"pos": ((sx, sy), (ex, ey))})
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float("color", color)
    body.draw(shader)
    # Cabeza triangular
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length < 1e-6:
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')
        return
    ux, uy = dx / length, dy / length
    # Perpendicular
    px, py = -uy, ux
    p1 = (ex, ey)
    p2 = (ex - ux * head_size + px * head_size * 0.5,
          ey - uy * head_size + py * head_size * 0.5)
    p3 = (ex - ux * head_size - px * head_size * 0.5,
          ey - uy * head_size - py * head_size * 0.5)
    head = batch_for_shader(shader, 'TRIS',
                             {"pos": (p1, p2, p3)},
                             indices=((0, 1, 2),))
    head.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _wrap_text(text: str, max_chars: int = 60) -> list[str]:
    """Word-wrap simple para no salir de la caja."""
    words = text.split()
    lines = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 <= max_chars:
            current = (current + " " + w).strip()
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def _draw_overlay() -> None:
    """Callback registrado en SpaceView3D.draw_handler.

    Todas las dimensiones se escalan con `_ui_scale()` para que se vean
    bien en monitores HiDPI/4K (donde Blender suele usar ui_scale 1,5-2,0).
    """
    if not TutorialState.active:
        return

    info = STEP_INFO.get(TutorialState.step)
    if info is None:
        return

    region = bpy.context.region
    if region is None:
        return
    rw, rh = region.width, region.height

    s = _ui_scale()

    # Caja flotante centrada en bottom — todo escalado con `s`
    box_w = min(int(820 * s), int(rw - 80 * s))
    box_h = int(220 * s)
    box_x = (rw - box_w) // 2
    box_y = int(30 * s)

    # Fondo + borde
    _draw_rect_filled(box_x, box_y, box_w, box_h, COLOR_BG_PANEL)
    _draw_rect_outline(box_x, box_y, box_w, box_h, COLOR_BG_BORDER, 2.5 * s)

    # Barra de progreso superior
    n = info.get("n", 0)
    total = info.get("total", 5)
    if total > 0:
        prog_h = int(5 * s)
        prog_w = box_w
        prog_x = box_x
        prog_y = box_y + box_h - prog_h
        _draw_rect_filled(prog_x, prog_y, prog_w, prog_h,
                           (0.2, 0.25, 0.35, 0.6))
        if n > 0:
            fill_w = (prog_w * n) // total
            _draw_rect_filled(prog_x, prog_y, fill_w, prog_h, COLOR_PROGRESS)

    pad = int(28 * s)
    # Título — base 24 pt
    _draw_text(iface_(info["title"]),
                box_x + pad, int(box_y + box_h - 44 * s),
                size=int(24 * s), color=COLOR_TITLE)

    # Instrucción — base 17 pt, con wrap
    instr_lines = _wrap_text(iface_(info["instr"]), max_chars=70)
    y_cur = int(box_y + box_h - 78 * s)
    line_h_instr = int(26 * s)
    for line in instr_lines:
        _draw_text(line, box_x + pad, y_cur,
                    size=int(17 * s), color=COLOR_INSTR)
        y_cur -= line_h_instr

    # Subtexto — base 14 pt
    if info.get("subtext"):
        sub_lines = _wrap_text(iface_(info["subtext"]), max_chars=78)
        y_cur -= int(8 * s)
        line_h_sub = int(22 * s)
        for line in sub_lines:
            _draw_text(line, box_x + pad, y_cur,
                        size=int(14 * s), color=COLOR_SUBTEXT)
            y_cur -= line_h_sub

    # Footer con shortcuts — base 12 pt
    _draw_text(iface_("ESC para salir · ▶ Siguiente en el panel lateral para avanzar"),
                box_x + pad, int(box_y + 16 * s),
                size=int(12 * s), color=(0.5, 0.6, 0.75, 0.85))

    # Flecha pulsante (escalada también)
    pulse = (math.sin(TutorialState.frame * 0.12) + 1) * 0.5
    arrow_color = (
        COLOR_ARROW[0],
        COLOR_ARROW[1],
        COLOR_ARROW[2],
        0.4 + 0.5 * pulse,
    )
    arrow_width = (3 + pulse * 3) * s
    arrow_head = 22 * s
    step = TutorialState.step
    if step in (STEP_CREATE_E1, STEP_CREATE_E2):
        target_x, target_y = int(80 * s), int(rh - 30 * s)
        start_x = box_x + box_w * 0.3
        start_y = box_y + box_h + 25 * s
        _draw_arrow((start_x, start_y), (target_x, target_y),
                     arrow_color, width=arrow_width, head_size=arrow_head)
    elif step in (STEP_ASSIGN_PATH, STEP_GENERATE):
        target_x, target_y = int(rw - 20 * s), int(rh - 200 * s)
        start_x = box_x + box_w * 0.7
        start_y = box_y + box_h + 25 * s
        _draw_arrow((start_x, start_y), (target_x, target_y),
                     arrow_color, width=arrow_width, head_size=arrow_head)


# ---------------------------------------------------------------------------
# Helpers públicos para el panel
# ---------------------------------------------------------------------------

def panel_should_alert(panel_section: str) -> bool:
    """¿La sección `panel_section` del panel principal debe pintarse en
    alert (naranja)? Llamado desde el panel principal del addon."""
    if not TutorialState.active:
        return False
    info = STEP_INFO.get(TutorialState.step, {})
    return info.get("highlight_panel") == panel_section


def progress_label() -> Optional[str]:
    if not TutorialState.active:
        return None
    info = STEP_INFO.get(TutorialState.step, {})
    n = info.get("n", 0)
    total = info.get("total", 5)
    title_short = iface_(info.get("title", "")).split("—")[0].strip()
    return iface_("Paso %d/%d: %s") % (n, total, title_short)


# ---------------------------------------------------------------------------
# Operadores
# ---------------------------------------------------------------------------

class ANDAMIOS_OT_tutorial_start(Operator):
    """Empieza el tutorial guiado interactivo."""
    bl_idname = "andamios.tutorial_start"
    bl_label = "Empezar tutorial guiado"
    bl_description = (
        "Asistente paso a paso para crear tu primer andamio. "
        "Te guía con instrucciones sobre el viewport y detecta "
        "automáticamente cuándo completas cada acción"
    )

    _draw_handler = None
    _timer = None

    def invoke(self, context, event):
        if TutorialState.active:
            self.report({'INFO'}, iface_("El tutorial ya está activo"))
            return {'CANCELLED'}

        TutorialState.active = True
        TutorialState.go_to_step(STEP_WELCOME, context)

        # Registrar overlay sobre viewport
        ANDAMIOS_OT_tutorial_start._draw_handler = (
            bpy.types.SpaceView3D.draw_handler_add(
                _draw_overlay, (), 'WINDOW', 'POST_PIXEL'
            )
        )
        # Timer para animaciones (~30 fps)
        wm = context.window_manager
        ANDAMIOS_OT_tutorial_start._timer = wm.event_timer_add(
            0.05, window=context.window
        )
        wm.modal_handler_add(self)

        # Forzar refresco
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Cancelación explícita
        if not TutorialState.active:
            return self._cleanup(context, cancelled=True)

        if event.type == 'TIMER':
            TutorialState.frame += 1
            # Detección automática de avance
            advanced = _check_auto_advance(context)
            # Refresco del viewport
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

        elif event.type == 'ESC' and event.value == 'PRESS':
            return self._cleanup(context, cancelled=True)

        # Pasar todos los demás eventos a Blender
        return {'PASS_THROUGH'}

    def _cleanup(self, context, cancelled=False):
        if ANDAMIOS_OT_tutorial_start._draw_handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(
                    ANDAMIOS_OT_tutorial_start._draw_handler, 'WINDOW',
                )
            except Exception:
                pass
            ANDAMIOS_OT_tutorial_start._draw_handler = None
        if ANDAMIOS_OT_tutorial_start._timer is not None:
            try:
                context.window_manager.event_timer_remove(
                    ANDAMIOS_OT_tutorial_start._timer
                )
            except Exception:
                pass
            ANDAMIOS_OT_tutorial_start._timer = None
        TutorialState.reset()
        # Refresco final
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        if cancelled:
            return {'CANCELLED'}
        return {'FINISHED'}


class ANDAMIOS_OT_tutorial_next(Operator):
    """Avanza manualmente al siguiente paso del tutorial."""
    bl_idname = "andamios.tutorial_next"
    bl_label = "Siguiente"
    bl_description = (
        "Avanza al siguiente paso del tutorial sin esperar a la detección "
        "automática"
    )

    @classmethod
    def poll(cls, context):
        return TutorialState.active

    def execute(self, context):
        next_step = _next_step(TutorialState.step)
        TutorialState.go_to_step(next_step, context)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


class ANDAMIOS_OT_tutorial_skip(Operator):
    """Cancela el tutorial guiado."""
    bl_idname = "andamios.tutorial_skip"
    bl_label = "Cancelar tutorial"
    bl_description = "Termina el tutorial sin completarlo"

    @classmethod
    def poll(cls, context):
        return TutorialState.active

    def execute(self, context):
        TutorialState.active = False   # el modal lo detecta y se limpia solo
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Sub-panel "Tutorial guiado" en el panel principal del addon
# ---------------------------------------------------------------------------

class ANDAMIOS_PT_tutorial(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Andamios"
    bl_label = "Tutorial guiado"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        if not TutorialState.active:
            col = layout.column(align=True)
            col.scale_y = 1.4
            col.operator("andamios.tutorial_start",
                          text=iface_("▶ Empezar tutorial"),
                          icon='PLAY')
            col.scale_y = 1.0
            col.label(text=iface_("Te guía a crear tu primer andamio."),
                       icon='INFO')
            col.label(text=iface_("5 pasos · 5 minutos."))
        else:
            info = STEP_INFO.get(TutorialState.step, {})
            n = info.get("n", 0)
            total = info.get("total", 5)
            box = layout.box()
            box.label(text=iface_("Paso %d de %d") % (n, total), icon='LIGHT_SUN')
            # Título corto (sin emoji)
            title = iface_(info.get("title", ""))
            if "—" in title:
                title = title.split("—", 1)[1].strip()
            box.label(text=title)
            # Texto envuelto
            for line in _wrap_text(iface_(info.get("instr", "")), max_chars=32):
                box.label(text=line)
            # Botones de control
            row = layout.row(align=True)
            row.scale_y = 1.2
            if TutorialState.step == STEP_DONE:
                row.operator("andamios.tutorial_skip",
                             text=iface_("✓ Cerrar"), icon='CHECKMARK')
            else:
                row.operator("andamios.tutorial_next",
                             text=iface_("Siguiente ▶"), icon='FORWARD')
                row.operator("andamios.tutorial_skip",
                             text="", icon='X')


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

CLASSES = (
    ANDAMIOS_OT_tutorial_start,
    ANDAMIOS_OT_tutorial_next,
    ANDAMIOS_OT_tutorial_skip,
    ANDAMIOS_PT_tutorial,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    # Si hay un tutorial activo, cancelarlo limpiamente
    if TutorialState.active:
        TutorialState.reset()
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
