"""Diagnóstico de fallos del addon Andamios.

Cuando Blender se cierra de golpe (segfault o aborto del intérprete),
las trazas Python normales se pierden con el proceso. Este módulo persiste
eagerly a disco ANTES de cada operación crítica para que, tras el crash,
podamos reconstruir qué estaba pasando justo antes.

Componentes:
- `enable_faulthandler()` — registra el faulthandler de Python apuntando a
  `~/.config/andamios/faulthandler.log` (captura SIGSEGV/SIGABRT/SIGFPE
  con traza de los hilos Python en el momento del fallo).
- `log_breadcrumb(op, **fields)` — append-only en
  `~/.config/andamios/breadcrumbs.jsonl`. Best-effort: nunca lanza.
- `breadcrumb_op(op, **fields)` — context manager que registra start /
  exception / end. Usar como wrapper alrededor de `generate_scaffold`.
- `export_diagnostic_text(scene)` — compone un `.txt` legible con
  sysinfo + props + breadcrumbs + faulthandler log para enviar.
"""

from __future__ import annotations

import faulthandler
import io
import json
import os
import platform
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def diagnostic_dir() -> Path:
    """Directorio de logs del addon. Se crea si no existe."""
    base = Path.home() / ".config" / "andamios"
    base.mkdir(parents=True, exist_ok=True)
    return base


def breadcrumb_path() -> Path:
    return diagnostic_dir() / "breadcrumbs.jsonl"


def faulthandler_path() -> Path:
    return diagnostic_dir() / "faulthandler.log"


# Rotación del log de breadcrumbs: por encima del umbral, nos quedamos con la
# cola. Suficiente para reconstruir las últimas decenas de operaciones.
MAX_BREADCRUMB_BYTES = 256 * 1024
KEEP_BREADCRUMB_BYTES = 128 * 1024


# ---------------------------------------------------------------------------
# Faulthandler
# ---------------------------------------------------------------------------

# Se mantiene referencia al fichero abierto a nivel de módulo para que
# faulthandler no pierda el descriptor durante la vida del proceso.
_FH_FILE: io.IOBase | None = None


def enable_faulthandler() -> Path | None:
    """Habilita faulthandler de Python apuntando al log. Idempotente.

    Devuelve la ruta del log si todo va bien, None si falló (no rompe).
    """
    global _FH_FILE
    try:
        path = faulthandler_path()
        if _FH_FILE is None or getattr(_FH_FILE, "closed", True):
            _FH_FILE = open(path, "a", buffering=1, encoding="utf-8")
            _FH_FILE.write(
                f"\n----- faulthandler started {datetime.now().isoformat()} "
                f"pid={os.getpid()} -----\n"
            )
            _FH_FILE.flush()
        if not faulthandler.is_enabled():
            faulthandler.enable(file=_FH_FILE, all_threads=True)
        return path
    except Exception as e:
        print(f"[andamios diag] enable_faulthandler failed: {e}")
        return None


def disable_faulthandler() -> None:
    """Desactiva faulthandler y cierra el fichero. Llamar en unregister."""
    global _FH_FILE
    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass
    try:
        if _FH_FILE is not None and not getattr(_FH_FILE, "closed", True):
            _FH_FILE.close()
    except Exception:
        pass
    _FH_FILE = None


# ---------------------------------------------------------------------------
# Breadcrumbs JSONL
# ---------------------------------------------------------------------------

def _rotate_breadcrumbs(path: Path) -> None:
    """Si el fichero supera MAX_BREADCRUMB_BYTES, recorta la cabeza dejando
    KEEP_BREADCRUMB_BYTES desde la cola y alineado a salto de línea."""
    try:
        data = path.read_bytes()
        if len(data) <= MAX_BREADCRUMB_BYTES:
            return
        data = data[-KEEP_BREADCRUMB_BYTES:]
        nl = data.find(b"\n")
        if 0 <= nl < len(data) - 1:
            data = data[nl + 1:]
        path.write_bytes(data)
    except Exception:
        pass


def log_breadcrumb(op: str, **fields: Any) -> None:
    """Append a JSON line al log de breadcrumbs. Best-effort: nunca lanza.

    Cada entrada lleva ts (ISO-8601) + op + campos JSON-able. Valores no
    serializables se convierten con repr().
    """
    try:
        rec: dict[str, Any] = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "op": op,
        }
        for k, v in fields.items():
            try:
                json.dumps(v)
                rec[k] = v
            except (TypeError, ValueError):
                rec[k] = repr(v)
        path = breadcrumb_path()
        try:
            if path.stat().st_size > MAX_BREADCRUMB_BYTES:
                _rotate_breadcrumbs(path)
        except FileNotFoundError:
            pass
        with open(path, "a", encoding="utf-8", buffering=1) as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[andamios diag] log_breadcrumb failed: {e}")


def read_breadcrumbs(n_last: int = 200) -> list[dict]:
    """Devuelve las últimas N entradas parseadas como dicts."""
    path = breadcrumb_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-n_last:]:
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"raw": line})
    return out


def clear_breadcrumbs() -> None:
    """Borra el log (botón "Empezar de cero" en la UI)."""
    try:
        breadcrumb_path().unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Wrap de operaciones
# ---------------------------------------------------------------------------

class breadcrumb_op:
    """Context manager: registra `<op>.start`, `<op>.end` o `<op>.exception`.

    Uso típico envolviendo `generate_scaffold`:

        with breadcrumb_op("generate_scaffold", floors=props.floor_count):
            generate_scaffold(props, context)

    Si la operación lanza, se registra el tipo+mensaje+traceback recortado
    a 2 KB y se re-lanza (el context manager NO suprime la excepción).
    """

    def __init__(self, op: str, **fields: Any):
        self.op = op
        self.fields = fields
        self.t0 = 0.0

    def __enter__(self):
        self.t0 = time.monotonic()
        log_breadcrumb(f"{self.op}.start", **self.fields)
        return self

    def __exit__(self, exc_type, exc, tb):
        dur_ms = int((time.monotonic() - self.t0) * 1000)
        if exc is None:
            log_breadcrumb(f"{self.op}.end", dur_ms=dur_ms)
        else:
            log_breadcrumb(
                f"{self.op}.exception",
                dur_ms=dur_ms,
                exc_type=type(exc).__name__,
                exc_msg=str(exc),
                tb=traceback.format_exc()[-2000:],
            )
        return False


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

# Props JSON-able conocidas. Las que no existan en una versión dada se omiten.
_PROP_KEYS = (
    "floor_count", "floor_height", "scaffold_depth", "section_length",
    "base_z", "scaffold_h", "floor_h",
    "bay_length_catalog", "pole_length_catalog", "pole_segment_length",
    "deck_planks_count", "deck_plank_width", "deck_material_pref",
    "add_braces", "add_horizontal_braces", "add_corner_planks",
    "add_rosettes", "rosette_pitch",
    "use_terrain_z", "use_manual_ladders", "closed_loop",
    "auto_update", "brace_pattern",
)


def snapshot_props(props) -> dict:
    """Vuelca el estado JSON-able de `props` (andamios_props)."""
    out: dict[str, Any] = {}
    for k in _PROP_KEYS:
        if not hasattr(props, k):
            continue
        try:
            v = getattr(props, k)
            if isinstance(v, (int, float, bool, str)):
                out[k] = v
            else:
                out[k] = repr(v)
        except Exception as e:
            out[k] = f"<err: {e}>"
    try:
        pts = []
        for pp in getattr(props, "path_points", []):
            obj = pp.obj
            if obj is None:
                pts.append(None)
            else:
                t = obj.matrix_world.translation
                pts.append([obj.name, round(t.x, 3), round(t.y, 3), round(t.z, 3)])
        out["path_points"] = pts
    except Exception as e:
        out["path_points_err"] = str(e)
    return out


def snapshot_scene(scene) -> dict:
    """Datos de la escena Blender relevantes para depurar."""
    out: dict[str, Any] = {}
    try:
        import bpy
        coll = bpy.data.collections.get("Scaffold")
        if coll is None:
            out["scaffold_collection"] = None
        else:
            cnt = 0
            sample: list[str] = []
            for obj in coll.all_objects:
                cnt += 1
                if len(sample) < 5:
                    sample.append(obj.name)
            out["scaffold_collection"] = {"n_objects": cnt, "sample": sample}
    except Exception as e:
        out["scaffold_err"] = str(e)
    return out


# ---------------------------------------------------------------------------
# Informe completo
# ---------------------------------------------------------------------------

def _blender_version_str() -> str:
    try:
        import bpy
        v = bpy.app.version
        return f"{v[0]}.{v[1]}.{v[2]}"
    except Exception:
        return "unknown"


def system_info() -> dict:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "blender": _blender_version_str(),
        "executable": sys.executable,
        "pid": os.getpid(),
    }


def export_diagnostic_text(scene=None, *, n_breadcrumbs: int = 100) -> str:
    """Compone un texto humano-legible con todo el contexto necesario
    para depurar un crash. Si scene=None, omite snapshots de bpy."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("INFORME DE DIAGNÓSTICO — Andamios addon")
    lines.append(f"Generado: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("=" * 72)
    lines.append("")

    lines.append("[Sistema]")
    for k, v in system_info().items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    if scene is not None:
        props = getattr(scene, "andamios_props", None)
        if props is not None:
            lines.append("[Props snapshot]")
            for k, v in snapshot_props(props).items():
                lines.append(f"  {k}: {v}")
            lines.append("")
        lines.append("[Escena]")
        for k, v in snapshot_scene(scene).items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    crumbs = read_breadcrumbs(n_breadcrumbs)
    lines.append(f"[Breadcrumbs — últimas {len(crumbs)} entradas]")
    if not crumbs:
        lines.append("  (sin entradas — el log está vacío)")
    for c in crumbs:
        ts = c.get("ts", "?")
        op = c.get("op", "?")
        rest = {k: v for k, v in c.items() if k not in ("ts", "op")}
        rest_str = " ".join(f"{k}={v}" for k, v in rest.items())
        lines.append(f"  {ts}  {op}  {rest_str}")
    lines.append("")

    fh_path = faulthandler_path()
    if fh_path.exists():
        try:
            content = fh_path.read_text(encoding="utf-8", errors="replace")
            tail = "\n".join(content.splitlines()[-200:])
            lines.append(f"[Faulthandler log — {fh_path}]")
            lines.append(tail if tail.strip() else "(vacío — sin segfaults registrados)")
        except Exception as e:
            lines.append(f"[Faulthandler — error leyendo: {e}]")
    else:
        lines.append("[Faulthandler — sin entradas (no ha habido segfault registrado)]")
    lines.append("")

    return "\n".join(lines) + "\n"
