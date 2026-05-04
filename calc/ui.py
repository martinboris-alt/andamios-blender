"""Panel "Cálculo estructural" para el viewport de Blender.

Operadores expuestos:
    ANDAMIOS_OT_calc_run     Ejecuta extract → solve → check → colorear viewport.
    ANDAMIOS_OT_calc_restore Restaura los materiales originales.
    ANDAMIOS_OT_calc_report  Exporta un informe HTML del cálculo.

Lee la configuración de cargas y combinación de
`scene.andamios_props.calc_*` (props añadidas en `andamios_addon.py`):

    calc_apply_service / calc_service_class / calc_service_deck_width
    calc_apply_wind / calc_wind_zone / calc_wind_terrain
    calc_apply_imperfections
    calc_combo

Este módulo requiere bpy y sólo es importable dentro de Blender. Los tests
unitarios del paquete (calc/tests/) NO importan ui.py.
"""

from __future__ import annotations

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import StringProperty
from bpy.types import Operator, Panel, UIList


def _wrap_text(text: str, width: int = 48) -> list[str]:
    """Parte un texto largo en líneas de hasta `width` caracteres,
    respetando palabras. Útil para los labels del panel, que no tienen
    word-wrap nativo."""
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + 1 + len(w) <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _options_from_props(props):
    """Convierte el PropertyGroup `andamios_props` en un dict plano apto
    para pasarlo a `calc.pipeline.build_and_solve`."""
    return {
        "apply_service":       bool(props.calc_apply_service),
        "service_class":       str(props.calc_service_class),
        "deck_width":          float(props.calc_service_deck_width),
        "apply_wind":          bool(props.calc_apply_wind),
        "wind_zone":           str(props.calc_wind_zone),
        "wind_terrain":        str(props.calc_wind_terrain),
        "apply_imperfections": bool(props.calc_apply_imperfections),
        "apply_guardrail":     bool(getattr(props, "calc_apply_guardrail", False)),
        "use_pdelta":          bool(getattr(props, "calc_use_pdelta", False)),
        "combo":               str(props.calc_combo),
        "color_mode":          str(getattr(props, "calc_color_mode", "utilization")),
    }


def _build_and_solve(scene):
    """Lee la escena Blender, extrae el modelo y delega en `pipeline`."""
    from . import extract_model
    from .pipeline import build_and_solve

    options = _options_from_props(scene.andamios_props)
    model = extract_model.extract_from_scene(scene)
    if not model.members:
        raise RuntimeError(
            "No se encontraron barras estructurales en la colección 'Scaffold'"
        )
    res, checks = build_and_solve(model, options)
    return model, res, checks


# ---------------------------------------------------------------------------
# Detección del estado del workflow (3 etapas)
# ---------------------------------------------------------------------------

# Prefijos de objetos estructurales (mismo set que extract_model._TYPE_BY_PREFIX).
_STRUCTURAL_PREFIXES = ("Pole_F", "Pole_B", "Ledger_", "Brace_", "HBrace_", "Tie_")


def _count_structural_objects(scene) -> int:
    """Cuenta tubos estructurales dentro de la colección 'Scaffold'."""
    root = None
    for c in scene.collection.children_recursive:
        if c.name == "Scaffold":
            root = c
            break
    if root is None:
        return 0
    n = 0
    for obj in root.all_objects:
        if obj.type != "MESH":
            continue
        if any(obj.name.startswith(p) for p in _STRUCTURAL_PREFIXES):
            n += 1
    return n


def _detect_workflow_state(scene) -> dict:
    """Inspecciona la escena y delega en `pipeline.compute_workflow_state`."""
    from .pipeline import compute_workflow_state
    n_struct = _count_structural_objects(scene)
    return compute_workflow_state(
        n_structural=n_struct,
        validation_level=scene.get("calc_status_level"),
        n_failed=int(scene.get("calc_status_n_failed", 0)),
        n_warning=int(scene.get("calc_status_n_warning", 0)),
        n_total=int(scene.get("calc_status_n_total", 0)),
        worst=float(scene.get("calc_status_worst", 0.0)),
    )


# ---------------------------------------------------------------------------
# Operadores
# ---------------------------------------------------------------------------

class ANDAMIOS_OT_calc_validate(Operator):
    """Comprueba el modelo antes de calcular y avisa de problemas
    geométricos / normativos. No ejecuta el FEM.

    Reporta cada incidencia al usuario con icono codificado por
    severidad y guarda el listado en `scene["calc_validation_summary"]`
    para que el panel pueda mostrarlo. Útil cuando el usuario tiene
    sospechas o si el cálculo va a tardar y prefiere validar antes.
    """
    bl_idname = "andamios.calc_validate"
    bl_label = "Comprobar modelo"
    bl_description = (
        "Pasa una serie de chequeos rápidos sobre la geometría del andamio "
        "y la configuración del cálculo. Avisa de errores que harían "
        "fallar el solver y de warnings que pueden indicar incumplimiento "
        "normativo. No ejecuta el cálculo FEM"
    )

    def execute(self, context):
        from . import diagnostics, extract_model
        from .pipeline import weld_close_nodes, weld_mid_span_attachments
        from .validator import (
            summarize_issues,
            validate_model,
            validate_scene,
        )

        with diagnostics.breadcrumb_op("calc_validate"):
            scene = context.scene
            issues = list(validate_scene(scene))

            # Si la escena ya tiene Scaffold, también validamos el modelo
            # extraído (chequeos sobre conectividad, etc.). Aplicamos
            # weld_close_nodes/mid_span ANTES para reflejar el estado
            # real con el que correrá el solver — sin esto, los postes
            # segmentados aparecen como "desconectados".
            try:
                model = extract_model.extract_from_scene(scene)
                if model.members:
                    weld_close_nodes(model)
                    weld_mid_span_attachments(model)
                    issues.extend(validate_model(model))
            except Exception as e:
                # No bloqueante: la validación de la escena ya cubrió E13
                print(f"[validate] No se pudo extraer modelo: {e}")

            n_err, n_wrn, n_inf, status = summarize_issues(issues)
            scene["calc_validation_summary"] = {
                "n_errors": n_err,
                "n_warnings": n_wrn,
                "n_info": n_inf,
                "status": status,
                "issues": [
                    {"level": i.level, "code": i.code,
                     "message": i.message,
                     "suggestion": i.suggestion or ""}
                    for i in issues
                ],
            }

            # Reportar al usuario el peor item para que aparezca en el toast
            if status == "blocked":
                first_err = next(i for i in issues if i.level == "ERROR")
                self.report({'ERROR'},
                            f"[{first_err.code}] {first_err.message}")
            elif status == "warning":
                self.report(
                    {'WARNING'},
                    iface_("%d aviso(s), %d info — revisa el panel") % (n_wrn, n_inf),
                )
            else:
                self.report(
                    {'INFO'},
                    iface_("Modelo limpio · %d info · listo para calcular") % (n_inf,),
                )
        return {'FINISHED'}


class ANDAMIOS_OT_calc_run(Operator):
    bl_idname = "andamios.calc_run"
    bl_label = "Ejecutar cálculo"
    bl_description = (
        "Aplica las cargas configuradas, resuelve y colorea el viewport por "
        "utilización"
    )

    def execute(self, context):
        from . import diagnostics, viewport
        from .pipeline import (
            classify_failure_basic,
            compute_member_deflections,
            deflection_summary,
            diagnose_failure,
            format_status_message,
        )

        diagnostics.log_breadcrumb(
            "calc_run.start",
            combo=str(context.scene.andamios_props.calc_combo),
            service=str(context.scene.andamios_props.calc_service_class),
            wind=str(context.scene.andamios_props.calc_wind_zone),
        )
        try:
            model, res, checks = _build_and_solve(context.scene)
        except Exception as e:
            diagnostics.log_breadcrumb("calc_run.exception",
                                        exc_type=type(e).__name__,
                                        exc_msg=str(e))
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        scene = context.scene
        options = _options_from_props(scene.andamios_props)

        # Coloreado según el modo elegido
        deflections = compute_member_deflections(model, res)
        if options["color_mode"] == "deflection":
            viewport.apply_deflection_colors(deflections)
        else:
            viewport.apply_check_colors(checks)

        # ---- Populate calc_failures (lista clicable Fase D) ----
        props = scene.andamios_props
        props.calc_failures.clear()
        # Ordenar por util desc, quedarse con util >= 0.85, máx 20
        sorted_checks = sorted(
            checks.values(), key=lambda c: c.utilization, reverse=True,
        )
        n_added = 0
        for cr in sorted_checks:
            if cr.utilization < 0.85:
                break
            if n_added >= 20:
                break
            mem = model.members.get(cr.member)
            mtype = mem.member_type if mem else None
            diag = diagnose_failure(cr, member_type=mtype)

            entry = props.calc_failures.add()
            entry.member_id = cr.member
            entry.utilization = float(cr.utilization)
            entry.failure_type = diag["type"]
            entry.severity = diag["severity"]
            entry.severity_label = diag["severity_label"]
            entry.why = diag["why"]
            entry.fix = diag["fix"]
            entry.member_type = mtype or ""

            if mem is not None:
                ni = model.nodes.get(mem.i_node)
                nj = model.nodes.get(mem.j_node)
                if ni is not None and nj is not None:
                    entry.coords_x = float((ni.x + nj.x) * 0.5)
                    entry.coords_y = float((ni.y + nj.y) * 0.5)
                    entry.coords_z = float((ni.z + nj.z) * 0.5)
            n_added += 1
        # Resetear índice activo a la primera entrada
        props.calc_failures_index = 0 if n_added else 0

        # Guardar desplazamientos por tubo para que la visualización deformada
        # pueda construirse luego sin necesidad de re-ejecutar el cálculo.
        from . import deformed as deformed_mod
        deformed_mod.store_tube_displacements(model, res)
        # Si la colección deformada ya existía, la reconstruimos con la
        # nueva data (mantiene la coherencia entre runs).
        if bpy.data.collections.get(deformed_mod.DEFORMED_COLLECTION_NAME):
            scale = float(scene.andamios_props.calc_deformation_scale)
            deformed_mod.build_deformed_overlay(scene, scale=scale)

        # Status de utilización
        status = format_status_message(checks, options)
        scene["calc_status_level"] = status["level"]
        scene["calc_status_title"] = status["title"]
        scene["calc_status_subtitle"] = status["subtitle"]
        scene["calc_status_worst"] = float(status["worst"])
        scene["calc_status_n_total"] = int(status["n_total"])
        scene["calc_status_n_failed"] = int(status["n_failed"])
        scene["calc_status_n_warning"] = int(status["n_warning"])

        # Info de deformaciones (siempre se computa, independiente del modo)
        defl_info = deflection_summary(deflections)
        scene["calc_defl_worst_member"] = str(defl_info["worst_member"] or "")
        scene["calc_defl_worst_disp_m"] = float(defl_info["worst_disp_m"])
        scene["calc_defl_worst_ratio"] = float(defl_info["worst_ratio"])
        scene["calc_defl_worst_label"] = str(defl_info["worst_label"])
        scene["calc_defl_n_excessive"] = int(defl_info["n_excessive"])
        scene["calc_defl_n_warning"] = int(defl_info["n_warning"])
        # Coordenadas del nodo peor (para el operador "Localizar")
        if defl_info["worst_member"] and defl_info["worst_member"] in model.members:
            mem = model.members[defl_info["worst_member"]]
            ni = model.nodes[mem.i_node]
            nj = model.nodes[mem.j_node]
            d_i = ((res.nodes[mem.i_node].DX) ** 2 + (res.nodes[mem.i_node].DY) ** 2 + (res.nodes[mem.i_node].DZ) ** 2) ** 0.5
            d_j = ((res.nodes[mem.j_node].DX) ** 2 + (res.nodes[mem.j_node].DY) ** 2 + (res.nodes[mem.j_node].DZ) ** 2) ** 0.5
            wn = ni if d_i >= d_j else nj
            scene["calc_defl_worst_node_x"] = float(wn.x)
            scene["calc_defl_worst_node_y"] = float(wn.y)
            scene["calc_defl_worst_node_z"] = float(wn.z)

        bl_severity = {"ok": 'INFO', "warning": 'WARNING', "fail": 'ERROR'}
        msg = (
            f"{status['title']} · util max {status['worst']:.3f}"
            f" · δ_max {defl_info['worst_disp_m']*1000:.1f} mm"
        )
        self.report({bl_severity[status["level"]]}, msg)
        diagnostics.log_breadcrumb(
            "calc_run.end",
            status_level=status["level"],
            util_max=float(status["worst"]),
            delta_max_mm=float(defl_info["worst_disp_m"] * 1000),
            n_failed=int(status["n_failed"]),
            n_total=int(status["n_total"]),
        )
        return {'FINISHED'}


class ANDAMIOS_OT_calc_restore(Operator):
    bl_idname = "andamios.calc_restore"
    bl_label = "Restaurar colores"
    bl_description = "Devuelve cada barra a su material original"

    def execute(self, context):
        from . import viewport
        n = viewport.restore_original_colors()
        self.report({'INFO'}, f"{n} barra(s) restaurada(s)")
        scene = context.scene
        for k in (
            "calc_status_level", "calc_status_title", "calc_status_subtitle",
            "calc_status_worst", "calc_status_n_total",
            "calc_status_n_failed", "calc_status_n_warning",
            "calc_last_run",
            "calc_defl_worst_member", "calc_defl_worst_disp_m",
            "calc_defl_worst_ratio", "calc_defl_worst_label",
            "calc_defl_n_excessive", "calc_defl_n_warning",
            "calc_defl_worst_node_x", "calc_defl_worst_node_y",
            "calc_defl_worst_node_z",
        ):
            if k in scene:
                del scene[k]
        # Limpiar empties de localización si existen
        for obj in list(bpy.data.objects):
            if obj.name.startswith("Calc_DeflMax"):
                bpy.data.objects.remove(obj, do_unlink=True)
        # Eliminar la colección deformada si existe
        from . import deformed as deformed_mod
        deformed_mod.clear_deformed_overlay(scene)
        # Limpiar custom prop _calc_disp para no dejar datos obsoletos
        for obj in bpy.data.objects:
            if deformed_mod.CUSTOM_PROP_DISP in obj:
                del obj[deformed_mod.CUSTOM_PROP_DISP]
        # Limpiar lista de fallos
        if hasattr(scene, "andamios_props"):
            scene.andamios_props.calc_failures.clear()
            scene.andamios_props.calc_failures_index = 0
        return {'FINISHED'}


class ANDAMIOS_OT_calc_autofix(Operator):
    bl_idname = "andamios.calc_autofix"
    bl_label = "Auto-corregir fallos"
    bl_description = (
        "Aplica heurísticas de mejora iterativamente (estilo ANSYS): activa "
        "cruces, reduce vanos y segmentos de poste hasta que la estructura "
        "cumple. Hasta 8 iteraciones. Pulsa 'Revertir' para deshacer."
    )

    @classmethod
    def poll(cls, context):
        return bpy.data.collections.get("Scaffold") is not None

    def execute(self, context):
        from . import autofix as af
        from . import diagnostics

        diagnostics.log_breadcrumb("calc_autofix.start")
        scene = context.scene
        props = scene.andamios_props
        max_iter = 8
        target_util = 0.95

        # Snapshot del estado inicial para poder revertir
        initial_snap = af.snapshot_props(props)
        scene["calc_autofix_snapshot"] = repr(initial_snap)

        history: list[str] = []

        def _save_history(history_lines: list[str]):
            scene["calc_autofix_history"] = "\n".join(history_lines)

        for iteration in range(max_iter):
            # 1. Ejecutar cálculo (puede levantar excepción si reporta ERROR)
            try:
                bpy.ops.andamios.calc_run()
            except RuntimeError:
                pass

            util_max = float(scene.get("calc_status_worst", 999.0))
            n_failed = int(scene.get("calc_status_n_failed", 0))

            history.append(
                f"#{iteration+1}: util_max={util_max:.2f}, fallos={n_failed}"
            )

            # 2. ¿Convergió?
            if util_max < target_util and n_failed == 0:
                history.append(
                    f"✓ Convergió en {iteration} iteración(es). "
                    f"util_max final = {util_max:.2f}"
                )
                _save_history(history)
                self.report({'INFO'},
                            f"Auto-fix OK en {iteration} iter · "
                            f"util_max {util_max:.2f}")
                return {'FINISHED'}

            # 3. Decidir el siguiente fix
            failures_list = []
            for f in props.calc_failures:
                failures_list.append({
                    "member_id":    str(f.member_id),
                    "utilization":  float(f.utilization),
                    "failure_type": str(f.failure_type),
                    "member_type":  str(f.member_type),
                })
            current_state = af.snapshot_props(props)
            fix = af.decide_next_fix(current_state, failures_list)

            if fix is None:
                history.append("✗ Sin más opciones de mejora disponibles")
                _save_history(history)
                self.report({'WARNING'},
                            f"Auto-fix sin más opciones · "
                            f"util_max {util_max:.2f}")
                return {'CANCELLED'}

            history.append(f"   → {fix['action']}")

            # 4. Aplicar el fix
            try:
                setattr(props, fix["prop"], fix["after"])
            except (AttributeError, TypeError) as e:
                history.append(f"   ✗ Error aplicando fix: {e}")
                _save_history(history)
                return {'CANCELLED'}

            # 5. Regenerar la geometría con la nueva configuración
            try:
                bpy.ops.andamios.generate()
            except RuntimeError as e:
                history.append(f"   ✗ Error regenerando: {e}")
                _save_history(history)
                return {'CANCELLED'}

        # Max iter alcanzado
        history.append(f"⚠ Alcanzadas {max_iter} iteraciones sin converger")
        _save_history(history)
        self.report({'WARNING'},
                    f"Auto-fix no convergió en {max_iter} iter")
        return {'CANCELLED'}


class ANDAMIOS_OT_calc_autofix_revert(Operator):
    bl_idname = "andamios.calc_autofix_revert"
    bl_label = "Revertir auto-corrección"
    bl_description = (
        "Restaura las propiedades del andamio al estado anterior a la "
        "auto-corrección y regenera la geometría"
    )

    @classmethod
    def poll(cls, context):
        return "calc_autofix_snapshot" in context.scene

    def execute(self, context):
        from . import autofix as af
        scene = context.scene
        snap_str = scene.get("calc_autofix_snapshot")
        if not snap_str:
            return {'CANCELLED'}
        try:
            snap = eval(snap_str, {"__builtins__": {}}, {})
        except Exception:
            self.report({'ERROR'}, "Snapshot corrupto, no se puede revertir.")
            return {'CANCELLED'}
        if not isinstance(snap, dict):
            return {'CANCELLED'}
        n = af.restore_props(scene.andamios_props, snap)
        bpy.ops.andamios.generate()
        # Limpiar metadatos
        for k in ("calc_autofix_snapshot", "calc_autofix_history"):
            if k in scene:
                del scene[k]
        self.report({'INFO'},
                    f"Diseño revertido ({n} propiedades restauradas)")
        return {'FINISHED'}


class ANDAMIOS_OT_calc_show_deformed(Operator):
    bl_idname = "andamios.calc_show_deformed"
    bl_label = "Mostrar deformada (ANSYS)"
    bl_description = (
        "Crea una copia del andamio desplazada según el cálculo, amplificada "
        "por el factor configurado. Las deformaciones reales son de pocos "
        "milímetros — se exageran para que sean visibles"
    )

    @classmethod
    def poll(cls, context):
        # Necesitamos al menos un objeto con _calc_disp guardado
        from .deformed import CUSTOM_PROP_DISP
        for obj in bpy.data.objects:
            if CUSTOM_PROP_DISP in obj:
                return True
        return False

    def execute(self, context):
        from . import deformed
        scale = float(context.scene.andamios_props.calc_deformation_scale)
        n = deformed.build_deformed_overlay(context.scene, scale=scale)
        if n == 0:
            self.report({'WARNING'},
                        "No se encontraron datos de deformación. Ejecuta el cálculo primero.")
            return {'CANCELLED'}
        self.report({'INFO'},
                    f"Deformada construida con {n} tubos (×{scale:.0f})")
        return {'FINISHED'}


class ANDAMIOS_OT_calc_hide_deformed(Operator):
    bl_idname = "andamios.calc_hide_deformed"
    bl_label = "Ocultar deformada"
    bl_description = "Elimina la colección Scaffold_Deformed con la geometría deformada"

    def execute(self, context):
        from . import deformed
        n = deformed.clear_deformed_overlay(context.scene)
        self.report({'INFO'}, f"{n} tubos deformados eliminados")
        return {'FINISHED'}


class ANDAMIOS_OT_calc_locate_max_deflection(Operator):
    bl_idname = "andamios.calc_locate_max_deflection"
    bl_label = "Localizar deformación máxima"
    bl_description = (
        "Crea un Empty en el nodo donde el modelo se desplaza más, con su "
        "valor en el nombre. Útil para encontrar la zona crítica en el viewport"
    )

    @classmethod
    def poll(cls, context):
        return "calc_defl_worst_member" in context.scene

    def execute(self, context):
        scene = context.scene
        member = scene.get("calc_defl_worst_member", "")
        disp_m = float(scene.get("calc_defl_worst_disp_m", 0.0))
        if not member or disp_m <= 0:
            self.report({'WARNING'}, "Aún no hay datos de deformación. "
                                     "Ejecuta el cálculo primero.")
            return {'CANCELLED'}

        x = float(scene.get("calc_defl_worst_node_x", 0.0))
        y = float(scene.get("calc_defl_worst_node_y", 0.0))
        z = float(scene.get("calc_defl_worst_node_z", 0.0))

        # Eliminar empties anteriores de localización
        for obj in list(bpy.data.objects):
            if obj.name.startswith("Calc_DeflMax"):
                bpy.data.objects.remove(obj, do_unlink=True)

        name = f"Calc_DeflMax_{disp_m*1000:.1f}mm"
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = 'SPHERE'
        empty.empty_display_size = 0.25
        empty.location = (x, y, z)
        empty.show_in_front = True
        scene.collection.objects.link(empty)

        # Seleccionarlo y centrar la vista
        for o in bpy.data.objects:
            o.select_set(False)
        empty.select_set(True)
        context.view_layer.objects.active = empty
        try:
            bpy.ops.view3d.view_selected(use_all_regions=False)
        except RuntimeError:
            pass

        self.report({'INFO'},
                    f"Deformación máxima: {disp_m*1000:.1f} mm en {member} "
                    f"(δ/L = 1/{int(1/max(scene.get('calc_defl_worst_ratio', 1e-9), 1e-9)):d})")
        return {'FINISHED'}


class ANDAMIOS_OT_calc_cad_export(Operator):
    bl_idname = "andamios.calc_cad_export"
    bl_label = "Exportar plano CAD (HTML)"
    bl_description = (
        "Genera un plano técnico vectorial estilo NX en formato HTML/SVG: "
        "alzado frontal, alzado lateral, planta, cotas dimensionales, "
        "cuadro de rotulación con datos del proyecto y tabla BOM "
        "integrada. Imprimible a PDF a tamaño real (A3)."
    )

    filepath: StringProperty(subtype="FILE_PATH")
    filename_ext = ".html"

    @classmethod
    def poll(cls, context):
        return bpy.data.collections.get("Scaffold") is not None

    def execute(self, context):
        from . import bom, cad_plan, diagnostics

        diagnostics.log_breadcrumb("calc_cad_export.start",
                                    filepath=str(self.filepath))
        scene = context.scene
        # Recolectar geometría de líneas
        lines_3d = cad_plan.extract_scaffold_lines_3d(scene)
        if not lines_3d:
            self.report({'ERROR'},
                        "No se encontraron tubos estructurales en la escena")
            return {'CANCELLED'}

        # BOM
        items = bom.enumerate_scaffold_objects(scene)
        groups = bom.aggregate_bom(items)
        summary = bom.summarize_bom(groups)

        # Datos auxiliares para cotas y validación
        ref_points = cad_plan.extract_reference_points_3d(scene)
        floor_h = cad_plan.extract_floor_heights(scene)
        pole_x = cad_plan.extract_pole_levels(lines_3d, axis=0)
        pole_y = cad_plan.extract_pole_levels(lines_3d, axis=1)
        validation = cad_plan.build_validation_summary(scene)
        func_elems = cad_plan.extract_functional_elements_3d(scene)

        # path_points 3D para particionar en hojas tramo si la polilínea
        # tiene >= 2 segmentos rectos. Reusa extract_reference_points_3d.
        sheets = cad_plan.generate_cad_sheets(
            lines_3d, summary,
            paper="A3", orientation="landscape",
            project_name="Andamio multidireccional",
            drawing_title="PLANO GENERAL DE MONTAJE",
            author="",
            reference_points_3d=ref_points,
            floor_heights=floor_h,
            pole_x_levels=pole_x,
            pole_y_levels=pole_y,
            validation=validation,
            path_points_3d=ref_points,
            functional_elements_3d=func_elems,
        )
        html_doc = cad_plan.wrap_sheets_in_html(
            sheets, paper="A3", orientation="landscape",
            title="Andamio multidireccional",
        )

        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(html_doc)
        self.report({'INFO'},
                    f"Plano CAD escrito en {self.filepath} "
                    f"({len(sheets)} hoja{'s' if len(sheets) != 1 else ''} · "
                    f"{summary['total_weight_kg']/1000:.2f} t · "
                    f"{len(lines_3d)} líneas)")
        return {'FINISHED'}

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "plano_andamio_A3.html"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class ANDAMIOS_OT_calc_bom_export(Operator):
    bl_idname = "andamios.calc_bom_export"
    bl_label = "Exportar BOM HTML"
    bl_description = (
        "Genera un documento HTML autocontenido con la lista de materiales "
        "del andamio: peso total, breakdown por categoría, cantidades por "
        "longitud y foto representativa de cada tipo. Útil para suministros "
        "y subcontratistas."
    )

    filepath: StringProperty(subtype="FILE_PATH")
    filename_ext = ".html"

    @classmethod
    def poll(cls, context):
        return bpy.data.collections.get("Scaffold") is not None

    def execute(self, context):
        from . import bom, bom_report
        from . import screenshots as shots

        scene = context.scene
        items = bom.enumerate_scaffold_objects(scene)
        if not items:
            self.report({'ERROR'},
                        "No se encontró ningún elemento estructural")
            return {'CANCELLED'}

        groups = bom.aggregate_bom(items)
        summary = bom.summarize_bom(groups)

        # Una foto representativa por categoría (el miembro más pesado)
        reps = bom.representative_member_per_category(items)
        screenshots: dict[str, str] = {}
        if reps:
            self.report({'INFO'},
                        f"Capturando {len(reps)} imágenes representativas…")
            png_dict = shots.capture_failures_batch(
                scene, list(reps.values()), size=600,
            )
            # Mapear nombre → categoría → data_url
            name_to_cat = {name: cat for cat, name in reps.items()}
            screenshots = {
                name_to_cat[mid]: shots.png_to_base64_data_url(png)
                for mid, png in png_dict.items()
                if mid in name_to_cat
            }

        path = bom_report.write_bom_html(
            self.filepath, groups, summary,
            screenshots=screenshots,
        )
        self.report({'INFO'},
                    f"BOM escrito en {path} "
                    f"({summary['total_weight_kg']/1000:.2f} t · "
                    f"{summary['total_pieces']} piezas)")
        return {'FINISHED'}

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "BOM_andamio.html"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class ANDAMIOS_OT_calc_report(Operator):
    bl_idname = "andamios.calc_report"
    bl_label = "Exportar informe HTML"
    bl_description = (
        "Genera un archivo HTML autocontenido con resumen ejecutivo, "
        "diagnóstico de cada elemento crítico, imágenes capturadas "
        "automáticamente del 3D y glosario para no expertos"
    )

    filepath: StringProperty(subtype="FILE_PATH")
    filename_ext = ".html"

    def execute(self, context):
        from . import diagnostics, report as report_mod
        from . import screenshots as shots
        from .pipeline import compute_member_deflections

        diagnostics.log_breadcrumb("calc_report.start",
                                    filepath=str(self.filepath))
        try:
            model, res, checks = _build_and_solve(context.scene)
        except Exception as e:
            diagnostics.log_breadcrumb("calc_report.exception",
                                        exc_type=type(e).__name__,
                                        exc_msg=str(e))
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Capturar screenshots de los miembros críticos (util ≥ 0.85)
        critical_ids = [c.member for c in checks.values() if c.utilization >= 0.85]
        critical_ids.sort(
            key=lambda mid: checks[mid].utilization, reverse=True,
        )
        # Limitar para evitar tiempos excesivos en escenas grandes
        critical_ids = critical_ids[:20]

        screenshots: dict[str, str] = {}
        if critical_ids:
            self.report({'INFO'},
                        f"Capturando {len(critical_ids)} imágenes del 3D…")
            png_dict = shots.capture_failures_batch(
                context.scene, critical_ids, size=600,
            )
            screenshots = {
                mid: shots.png_to_base64_data_url(png)
                for mid, png in png_dict.items()
            }

        # Deformaciones para incluir en el resumen numérico
        deflections = compute_member_deflections(model, res)

        # Vistas globales del andamio (iso, alzado, planta, CAD)
        self.report({'INFO'}, "Capturando vistas del andamio…")
        overview_pngs = shots.capture_overview_set(
            context.scene, size=800, include_cad=True,
        )
        overview_screenshots = {
            v: shots.png_to_base64_data_url(png)
            for v, png in overview_pngs.items()
        }

        options = _options_from_props(context.scene.andamios_props)
        path = report_mod.write_html_report(
            self.filepath, model, res, checks,
            options=options,
            deflections=deflections,
            screenshots=screenshots,
            overview_screenshots=overview_screenshots,
        )
        self.report({'INFO'},
                    f"Informe escrito en {path} ({len(screenshots)} imágenes)")
        return {'FINISHED'}

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "calculo_andamio.html"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class ANDAMIOS_PT_calc(Panel):
    bl_idname = "ANDAMIOS_PT_calc"
    bl_label = "Cálculo estructural"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Andamios"

    def draw(self, context):
        """Panel raíz: sólo muestra el workflow header (resumen de las 3
        etapas). El resto va en sub-paneles colapsables (loads, run,
        results, autofix, export) cada uno con su propio poll()."""
        layout = self.layout
        scene = context.scene

        wf = _detect_workflow_state(scene)
        self._draw_workflow_header(layout, wf)

    @staticmethod
    def _draw_failures_list(layout, props):
        """Lista clicable de elementos críticos. La fila activa puede
        localizarse en el viewport con el botón inferior."""
        box = layout.box()
        n = len(props.calc_failures)
        n_failed = sum(1 for f in props.calc_failures if f.utilization > 1.0)
        n_warn = n - n_failed
        title = f"Elementos críticos ({n})"
        row = box.row(align=True)
        if n_failed > 0:
            r = row; r.alert = True
            r.label(text=title, icon="ERROR")
        else:
            row.label(text=title, icon="INFO")

        # Cabecera tipo tabla
        head = box.row(align=True)
        head.scale_y = 0.85
        head.label(text="Barra")
        sub = head.row(align=True); sub.alignment = 'RIGHT'
        sub.label(text="Util")
        sub2 = head.row(align=True); sub2.alignment = 'LEFT'
        sub2.scale_x = 0.6
        sub2.label(text="Tipo")

        # UIList propia
        box.template_list(
            "ANDAMIOS_UL_failures", "",
            props, "calc_failures",
            props, "calc_failures_index",
            rows=min(8, max(3, n)),
        )

        # Botón Localizar
        box.operator("andamios.calc_select_failure", icon="ZOOM_SELECTED")

        # Diagnóstico de la fila activa
        idx = props.calc_failures_index
        if 0 <= idx < n:
            entry = props.calc_failures[idx]
            ANDAMIOS_PT_calc._draw_failure_diagnosis(box, entry)

        if n_warn > 0 and n_failed == 0:
            sub = box.column(align=True); sub.scale_y = 0.85
            sub.label(text=f"Sin fallos críticos · {n_warn} cerca del límite",
                      icon="INFO")

    @staticmethod
    def _draw_failure_diagnosis(parent, entry):
        """Box de diagnóstico para una entrada concreta: severidad,
        ¿qué pasa? y ¿cómo corregir?"""
        sub_box = parent.box()

        # Cabecera con severidad
        head = sub_box.row(align=True)
        sev = entry.severity
        if sev == "critical":
            head.alert = True
            icon = "CANCEL"
        elif sev == "serious":
            head.alert = True
            icon = "ERROR"
        elif sev == "minor":
            icon = "ERROR"
        else:
            icon = "INFO"
        head.label(text=f"{entry.member_id}  →  {entry.severity_label} "
                        f"(util {entry.utilization:.2f})", icon=icon)

        # Tipo de fallo
        sub_box.label(text=f"Tipo de fallo: {entry.failure_type}",
                      icon="STICKY_UVS_LOC")

        # Por qué (en plano)
        col = sub_box.column(align=True)
        col.scale_y = 0.85
        col.label(text="¿Qué le pasa?", icon="QUESTION")
        for line in _wrap_text(entry.why, 48):
            col.label(text="   " + line)

        # Cómo corregir
        col.separator()
        col.label(text="¿Cómo corregir?", icon="MODIFIER")
        for line in _wrap_text(entry.fix, 48):
            col.label(text="   " + line)

    @staticmethod
    def _draw_workflow_header(layout, wf):
        """Dibuja el resumen de las 3 fases (Diseño → Validación → Informe)
        siempre visible al inicio del panel, con icono y leyenda en plano."""
        box = layout.box()
        box.label(text="Pasos del cálculo", icon="OUTLINER_OB_LATTICE")

        # ---- Fase 1: Diseño ----
        col = box.column(align=True)
        d = wf["design"]
        if d["state"] == "ok":
            row = col.row(align=True)
            row.label(text="1. Diseño", icon="CHECKMARK")
            col.label(text=f"   {d['count']} barras estructurales generadas")
        else:
            row = col.row(align=True)
            row.label(text="1. Diseño", icon="LAYER_USED")
            sub = col.column(align=True); sub.alert = True
            sub.label(text="   No se ha generado ningún andamio")
            sub.label(text="   Configura el panel de arriba y pulsa Generar")

        col.separator()

        # ---- Fase 2: Validación ----
        v = wf["validation"]
        st = v["state"]
        row = col.row(align=True)
        if st == "empty":
            row.label(text="2. Validación", icon="DOT")
            col.label(text="   Pendiente: configura cargas y pulsa Ejecutar")
        elif st == "ok":
            row.label(text="2. Validación", icon="CHECKMARK")
            col.label(text=f"   ✓ {v['n_total']} barras OK · util max {v['worst']:.2f}")
        elif st == "warning":
            row.label(text="2. Validación", icon="ERROR")
            col.label(text=f"   ⚠ {v['n_warning']} cerca del límite · util max {v['worst']:.2f}")
        elif st == "fail":
            r = row; r.alert = True
            r.label(text="2. Validación", icon="CANCEL")
            sub = col.column(align=True); sub.alert = True
            sub.label(text=f"   ✗ {v['n_failed']} elemento(s) sobrepasados")
            sub.label(text=f"   util max {v['worst']:.2f}")

        col.separator()

        # ---- Fase 3: Informe ----
        r = wf["report"]
        row = col.row(align=True)
        if r["state"] == "available":
            row.label(text="3. Informe", icon="DOCUMENTS")
            col.label(text="   Listo para exportar HTML")
        else:
            row.label(text="3. Informe", icon="DOT")
            sub = col.column(align=True); sub.enabled = False
            sub.label(text="   Esperando a que se complete la validación")

        # ---- Callout cuando hay fallos ----
        if v["state"] == "fail":
            box2 = layout.box()
            box2.alert = True
            sub = box2.column(align=True)
            sub.label(text="Hay elementos sobrepasados", icon="LOOP_BACK")
            sub.scale_y = 0.85
            sub.label(text="Vuelve al panel principal de Andamios para corregir:")
            sub.label(text="  • Acortar la altura libre entre travesaños")
            sub.label(text="  • Reducir el ancho de vano (bay_length)")
            sub.label(text="  • Añadir cruces de arriostramiento")
            sub.label(text="  • Usar perfil reforzado o S355 si la sobrecarga es leve")
            sub.label(text="Tras corregir, vuelve a pulsar Ejecutar cálculo.")

    @staticmethod
    def _draw_status(layout, scene):
        """Dibuja el cuadro de estado en lenguaje no-experto al inicio
        del panel (semáforo + frase + métricas)."""
        level = str(scene.get("calc_status_level", "ok"))
        title = str(scene.get("calc_status_title", ""))
        subtitle = str(scene.get("calc_status_subtitle", ""))
        worst = float(scene.get("calc_status_worst", 0.0))
        n_total = int(scene.get("calc_status_n_total", 0))
        n_failed = int(scene.get("calc_status_n_failed", 0))
        n_warning = int(scene.get("calc_status_n_warning", 0))

        icon = {
            "ok":      "CHECKMARK",
            "warning": "ERROR",
            "fail":    "CANCEL",
        }.get(level, "INFO")
        alert = (level == "fail")

        box = layout.box()
        row = box.row()
        row.alert = alert
        row.label(text=title, icon=icon)

        # Subtítulo en gris
        sub = box.column(align=True)
        sub.scale_y = 0.85
        # El subtítulo puede ser largo: lo partimos por '·' para que se lea bien
        for chunk in subtitle.split(" · "):
            sub.label(text=chunk)

        # Métricas en una sola fila
        metrics = box.row(align=True)
        metrics.label(text=f"Barras: {n_total}")
        metrics.label(text=f"Util max: {worst:.2f}")
        if n_failed:
            r = metrics.row(); r.alert = True
            r.label(text=f"Fallos: {n_failed}")
        elif n_warning:
            metrics.label(text=f"Cerca límite: {n_warning}")
        else:
            metrics.label(text="Todo holgado", icon="CHECKMARK")


# ===========================================================================
# Sub-paneles colapsables — cada uno con su poll() para visibility condicional
# ===========================================================================

class _SubPanelBase:
    """Mixin común para los sub-paneles del panel de cálculo."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Andamios"
    bl_parent_id = "ANDAMIOS_PT_calc"

    @staticmethod
    def _has_design(scene) -> bool:
        return _detect_workflow_state(scene)["design"]["state"] == "ok"

    @staticmethod
    def _has_results(scene) -> bool:
        return scene.get("calc_status_level") in ("ok", "warning", "fail")


class ANDAMIOS_PT_calc_loads(_SubPanelBase, Panel):
    """Sub-panel: cargas variables + combinación. Visible cuando hay diseño."""
    bl_idname = "ANDAMIOS_PT_calc_loads"
    bl_label = "Cargas y combinación"

    @classmethod
    def poll(cls, context):
        return cls._has_design(context.scene)

    def draw(self, context):
        layout = self.layout
        props = context.scene.andamios_props

        # Cargas variables
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(props, "calc_apply_service", text="")
        row.label(text="Servicio (L)")
        sub = col.column(align=True)
        sub.enabled = props.calc_apply_service
        sub.prop(props, "calc_service_class")
        # Descripción legible del Q seleccionado bajo el dropdown
        from .pipeline import SERVICE_DESCRIPTION
        q_klass = str(props.calc_service_class)
        q_desc = SERVICE_DESCRIPTION.get(q_klass, "")
        if q_desc:
            sub.label(text=f"   ↳ {q_desc}", icon='INFO')
        sub.prop(props, "calc_service_deck_width")

        col.separator()
        row = col.row(align=True)
        row.prop(props, "calc_apply_wind", text="")
        row.label(text="Viento (W)")
        sub = col.column(align=True)
        sub.enabled = props.calc_apply_wind
        sub.prop(props, "calc_wind_zone")
        sub.prop(props, "calc_wind_terrain")

        col.separator()
        row = col.row(align=True)
        row.prop(props, "calc_apply_imperfections", text="")
        row.label(text="Imperfecciones (I)")

        col.separator()
        row = col.row(align=True)
        row.prop(props, "calc_apply_guardrail", text="")
        row.label(text="Carga barandilla (Q, EN 12811)")

        # Combinación
        layout.separator()
        layout.label(text="Combinación a comprobar:", icon="MOD_LATTICE")
        layout.prop(props, "calc_combo", text="")

        # Avanzado: análisis 2º orden
        layout.separator()
        adv = layout.box()
        adv.label(text="Avanzado", icon="PREFERENCES")
        row = adv.row(align=True)
        row.prop(props, "calc_use_pdelta", text="")
        row.label(text="Análisis P-Δ (2º orden)")
        if props.calc_use_pdelta:
            adv.label(
                text="↳ Captura desplome — más lento, requerido en torres esbeltas",
                icon='INFO',
            )


class ANDAMIOS_PT_calc_run(_SubPanelBase, Panel):
    """Sub-panel: botones de ejecutar/restaurar."""
    bl_idname = "ANDAMIOS_PT_calc_run"
    bl_label = "Ejecutar"

    @classmethod
    def poll(cls, context):
        return cls._has_design(context.scene)

    def draw(self, context):
        layout = self.layout
        # Botón "Comprobar" + resultado del último validate (semáforo)
        scene = context.scene
        sumr = scene.get("calc_validation_summary")
        validate_row = layout.row(align=True)
        validate_row.operator("andamios.calc_validate", icon="CHECKMARK")
        if sumr:
            status = sumr.get("status", "ok")
            sub = validate_row.row(align=True)
            if status == "blocked":
                sub.alert = True
                sub.label(
                    text=iface_("✗ %dE / %dW") % (sumr['n_errors'], sumr['n_warnings']),
                    icon="CANCEL",
                )
            elif status == "warning":
                sub.label(
                    text=iface_("⚠ %dW") % (sumr['n_warnings'],),
                    icon="ERROR",
                )
            else:
                sub.label(text=iface_("✓ Limpio"), icon="CHECKMARK")

            # Lista resumida de issues (max 5 worst-first)
            issues = sumr.get("issues", [])
            if issues:
                box = layout.box()
                box.scale_y = 0.85
                shown = 0
                for it in issues:
                    if shown >= 5:
                        break
                    if it["level"] == "INFO":
                        continue
                    row = box.row()
                    if it["level"] == "ERROR":
                        row.alert = True
                        ic = "CANCEL"
                    else:
                        ic = "ERROR"
                    row.label(text=f"[{it['code']}] {it['message']}",
                              icon=ic)
                    shown += 1
                rest = sum(1 for it in issues
                            if it["level"] != "INFO") - shown
                if rest > 0:
                    box.label(
                        text=iface_("… y %d más") % (rest,),
                        icon="THREE_DOTS",
                    )

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("andamios.calc_run", icon="PHYSICS")
        col.scale_y = 1.0
        col.operator("andamios.calc_restore", icon="LOOP_BACK")


class ANDAMIOS_PT_calc_results(_SubPanelBase, Panel):
    """Sub-panel: status del último cálculo + lista de elementos críticos.
    Sólo visible tras el primer `calc_run`."""
    bl_idname = "ANDAMIOS_PT_calc_results"
    bl_label = "Resultados"

    @classmethod
    def poll(cls, context):
        return cls._has_results(context.scene)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.andamios_props

        # Status (semáforo + métricas)
        ANDAMIOS_PT_calc._draw_status(layout, scene)

        # Elementos críticos
        if len(props.calc_failures) > 0:
            ANDAMIOS_PT_calc._draw_failures_list(layout, props)


class ANDAMIOS_PT_calc_visualization(_SubPanelBase, Panel):
    """Sub-panel: modo de coloreado + deformada + localizar."""
    bl_idname = "ANDAMIOS_PT_calc_visualization"
    bl_label = "Visualización"

    @classmethod
    def poll(cls, context):
        return cls._has_results(context.scene)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.andamios_props

        # Modo de coloreado
        layout.label(text="Coloreado:", icon="HIDE_OFF")
        layout.prop(props, "calc_color_mode", text="")

        # Resumen de deformación + botón localizar
        if "calc_defl_worst_disp_m" in scene:
            disp_mm = float(scene.get("calc_defl_worst_disp_m", 0.0)) * 1000
            ratio = float(scene.get("calc_defl_worst_ratio", 0.0))
            label = str(scene.get("calc_defl_worst_label", ""))
            box = layout.box()
            sub = box.column(align=True); sub.scale_y = 0.85
            sub.label(text=iface_("δ máx: %.1f mm  (%s)") % (disp_mm, label))
            if ratio > 0:
                sub.label(text=iface_("   ≈ L/%.0f") % (1.0 / ratio,))
            n_excessive = int(scene.get("calc_defl_n_excessive", 0))
            if n_excessive:
                r = sub.row(); r.alert = True
                r.label(
                    text=iface_("   %d barra(s) > L/100") % (n_excessive,),
                    icon="ERROR",
                )
            box.operator("andamios.calc_locate_max_deflection",
                         icon="OUTLINER_DATA_EMPTY")

        # Geometría deformada (vista ANSYS)
        layout.separator()
        box = layout.box()
        box.label(text="Geometría deformada", icon="MOD_LATTICE")
        box.prop(props, "calc_deformation_scale", text="Amplificación ×")
        row = box.row(align=True)
        row.operator("andamios.calc_show_deformed", icon="MOD_MESHDEFORM")
        row.operator("andamios.calc_hide_deformed", icon="HIDE_ON",
                     text="Ocultar")
        if bpy.data.collections.get("Scaffold_Deformed"):
            box.label(text="✓ Vista deformada activa", icon="CHECKMARK")


class ANDAMIOS_PT_calc_autofix(_SubPanelBase, Panel):
    """Sub-panel: auto-corrección iterativa estilo ANSYS."""
    bl_idname = "ANDAMIOS_PT_calc_autofix"
    bl_label = "Auto-corrección"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return cls._has_design(context.scene)

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        head = layout.column(align=True); head.scale_y = 0.85
        head.label(text="Mejora tu andamio automáticamente:", icon='INFO')
        head.label(text="añade cruces, acorta vanos y ajusta")
        head.label(text="postes hasta que cumpla (8 intentos).")

        col = layout.column(align=True)
        col.scale_y = 1.2
        col.operator("andamios.calc_autofix", icon="OUTLINER_OB_LIGHTPROBE")

        history = scene.get("calc_autofix_history", "")

        if history:
            converged = "Convergió" in str(history)
            status = layout.box()
            if converged:
                status.label(text="✓ Listo, tu andamio se ha mejorado",
                             icon='CHECKMARK')
            else:
                status.label(text="Geometría modificada · vuelve a comprobar",
                             icon='FILE_REFRESH')
            status.operator("andamios.calc_run",
                            text="Volver a comprobar", icon='PLAY')

        if "calc_autofix_snapshot" in scene:
            undo = layout.column(align=True)
            undo.operator("andamios.calc_autofix_revert",
                          text="Deshacer cambios", icon="LOOP_BACK")

        if history:
            box = layout.box()
            sub = box.column(align=True); sub.scale_y = 0.85
            sub.label(text="Historial de iteraciones:", icon="INFO")
            for line in str(history).split("\n"):
                s = str(line)
                if s.startswith("✓"):
                    icon, text = 'CHECKMARK', s[1:].lstrip()
                elif s.startswith("✗"):
                    icon, text = 'CANCEL', s[1:].lstrip()
                elif s.startswith("⚠"):
                    icon, text = 'ERROR', s[1:].lstrip()
                else:
                    icon, text = 'DOT', s
                sub.label(text=text, icon=icon)


class ANDAMIOS_PT_calc_export(_SubPanelBase, Panel):
    """Sub-panel: exportar informe HTML, BOM y plano CAD."""
    bl_idname = "ANDAMIOS_PT_calc_export"
    bl_label = "Exportar documentos"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return cls._has_design(context.scene)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("andamios.calc_report", icon="DOCUMENTS")
        col.operator("andamios.calc_bom_export", icon="LINENUMBERS_ON")
        col.operator("andamios.calc_cad_export", icon="OUTLINER_OB_LATTICE")


class ANDAMIOS_UL_failures(UIList):
    """Lista de elementos críticos del cálculo. Cada fila muestra:
    icono según tipo de fallo · id de la barra · utilización · etiqueta."""

    _ICON_BY_TYPE = {
        "compresión": "EMPTY_SINGLE_ARROW",
        "tracción":   "FORWARD",
        "pandeo":     "STICKY_UVS_LOC",
        "flexión":    "MOD_CURVE",
        "cortante":   "MOD_BEVEL",
        "combinada":  "X",
        "—":          "DOT",
    }

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        # Membre id
        type_icon = self._ICON_BY_TYPE.get(item.failure_type, "DOT")
        row = layout.row(align=True)
        row.label(text=item.member_id, icon=type_icon)
        # Utilización (alert si > 1)
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        if item.utilization > 1.0:
            sub.alert = True
        sub.label(text=f"{item.utilization:.2f}")
        # Tipo
        sub2 = row.row(align=True)
        sub2.alignment = 'LEFT'
        sub2.scale_x = 0.6
        sub2.label(text=item.failure_type)


class ANDAMIOS_OT_calc_select_failure(Operator):
    bl_idname = "andamios.calc_select_failure"
    bl_label = "Localizar barra en viewport"
    bl_description = (
        "Selecciona la barra correspondiente a la fila activa y centra la "
        "vista 3D sobre ella"
    )

    @classmethod
    def poll(cls, context):
        props = getattr(context.scene, "andamios_props", None)
        return bool(props and len(props.calc_failures))

    def execute(self, context):
        from . import deformed as deformed_mod
        props = context.scene.andamios_props
        idx = props.calc_failures_index
        if idx < 0 or idx >= len(props.calc_failures):
            self.report({'WARNING'}, iface_("Selecciona una fila de la lista primero."))
            return {'CANCELLED'}

        entry = props.calc_failures[idx]
        # Mapear id de modelo (M_<obj_name>) → objeto Blender
        obj_name = (entry.member_id[2:]
                    if entry.member_id.startswith("M_") else entry.member_id)
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            # Si la deformada está visible, intentar con la copia
            deformed_name = obj_name + deformed_mod.DEFORMED_OBJ_SUFFIX
            obj = bpy.data.objects.get(deformed_name)
        if obj is None:
            self.report(
                {'WARNING'},
                iface_("No se encuentra el objeto en la escena: %s") % (obj_name,),
            )
            return {'CANCELLED'}

        # Deseleccionar todo, seleccionar éste, hacerlo activo
        for o in bpy.context.selected_objects:
            try:
                o.select_set(False)
            except RuntimeError:
                pass
        try:
            obj.select_set(True)
            context.view_layer.objects.active = obj
        except RuntimeError:
            pass

        # Encuadrar la vista 3D
        try:
            bpy.ops.view3d.view_selected()
        except RuntimeError:
            pass

        self.report({'INFO'},
                    f"{entry.member_id} · util={entry.utilization:.2f} · "
                    f"{entry.failure_type}")
        return {'FINISHED'}


_CLASSES = (
    # Operadores
    ANDAMIOS_OT_calc_validate,
    ANDAMIOS_OT_calc_run,
    ANDAMIOS_OT_calc_restore,
    ANDAMIOS_OT_calc_autofix,
    ANDAMIOS_OT_calc_autofix_revert,
    ANDAMIOS_OT_calc_locate_max_deflection,
    ANDAMIOS_OT_calc_show_deformed,
    ANDAMIOS_OT_calc_hide_deformed,
    ANDAMIOS_OT_calc_select_failure,
    ANDAMIOS_OT_calc_bom_export,
    ANDAMIOS_OT_calc_cad_export,
    ANDAMIOS_OT_calc_report,
    # UIList
    ANDAMIOS_UL_failures,
    # Paneles: parent ANTES que sub-paneles (bl_parent_id requirement)
    ANDAMIOS_PT_calc,
    ANDAMIOS_PT_calc_loads,
    ANDAMIOS_PT_calc_run,
    ANDAMIOS_PT_calc_results,
    ANDAMIOS_PT_calc_visualization,
    ANDAMIOS_PT_calc_autofix,
    ANDAMIOS_PT_calc_export,
)


# ---------------------------------------------------------------------------
# Registro Blender
# ---------------------------------------------------------------------------

def register() -> None:
    """Registra los operadores y el panel. Idempotente."""
    for c in _CLASSES:
        try:
            bpy.utils.register_class(c)
        except ValueError:
            bpy.utils.unregister_class(c)
            bpy.utils.register_class(c)


def unregister() -> None:
    """Desregistra todas las clases del módulo."""
    for c in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass
