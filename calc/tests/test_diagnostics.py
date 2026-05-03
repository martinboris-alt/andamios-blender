"""Tests del módulo calc/diagnostics.py — sistema de breadcrumbs y
faulthandler para depurar crashes del addon.

Tests puros (sin bpy). Aislamos cada caso redirigiendo `diagnostic_dir`
a un tmp_path por test para no contaminar `~/.config/andamios`.
"""

from __future__ import annotations

import json
import time

import pytest

from calc import diagnostics


@pytest.fixture
def isolated_dir(tmp_path, monkeypatch):
    """Redirige diagnostic_dir() al tmp_path para que cada test sea
    independiente y no toque ~/.config/andamios."""
    monkeypatch.setattr(diagnostics, "diagnostic_dir",
                        lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# log_breadcrumb / read_breadcrumbs
# ---------------------------------------------------------------------------

def test_log_breadcrumb_writes_json_line(isolated_dir):
    diagnostics.log_breadcrumb("op_test", floors=2, name="andamio")
    path = isolated_dir / "breadcrumbs.jsonl"
    assert path.exists()
    line = path.read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["op"] == "op_test"
    assert rec["floors"] == 2
    assert rec["name"] == "andamio"
    assert "ts" in rec  # timestamp presente


def test_log_breadcrumb_appends_multiple(isolated_dir):
    diagnostics.log_breadcrumb("op_a")
    diagnostics.log_breadcrumb("op_b")
    diagnostics.log_breadcrumb("op_c")
    crumbs = diagnostics.read_breadcrumbs()
    assert [c["op"] for c in crumbs] == ["op_a", "op_b", "op_c"]


def test_log_breadcrumb_handles_non_json_values(isolated_dir):
    """Valores no serializables se convierten con repr() sin lanzar."""
    class Weird:
        def __repr__(self):
            return "<Weird>"
    diagnostics.log_breadcrumb("op", obj=Weird(), n=5)
    crumbs = diagnostics.read_breadcrumbs()
    assert len(crumbs) == 1
    assert crumbs[0]["obj"] == "<Weird>"
    assert crumbs[0]["n"] == 5


def test_log_breadcrumb_never_raises(isolated_dir, monkeypatch):
    """Si el FS falla, no debe propagar — el addon nunca debe romperse
    por culpa del logging."""
    def boom(*a, **kw):
        raise OSError("disco lleno")
    monkeypatch.setattr("builtins.open", boom)
    diagnostics.log_breadcrumb("op")  # no debe lanzar


def test_read_breadcrumbs_returns_empty_when_file_missing(isolated_dir):
    assert diagnostics.read_breadcrumbs() == []


def test_read_breadcrumbs_respects_n_last(isolated_dir):
    for i in range(20):
        diagnostics.log_breadcrumb("op", i=i)
    last5 = diagnostics.read_breadcrumbs(n_last=5)
    assert len(last5) == 5
    assert [c["i"] for c in last5] == [15, 16, 17, 18, 19]


def test_read_breadcrumbs_handles_corrupt_lines(isolated_dir):
    """Líneas que no parsean JSON se devuelven como {raw: ...}."""
    path = isolated_dir / "breadcrumbs.jsonl"
    path.write_text(
        '{"ts":"2026-05-01","op":"good"}\n'
        'no soy json válido\n'
        '{"ts":"2026-05-02","op":"good2"}\n',
        encoding="utf-8",
    )
    crumbs = diagnostics.read_breadcrumbs()
    assert crumbs[0]["op"] == "good"
    assert "raw" in crumbs[1]
    assert crumbs[2]["op"] == "good2"


def test_clear_breadcrumbs_removes_file(isolated_dir):
    diagnostics.log_breadcrumb("op")
    assert (isolated_dir / "breadcrumbs.jsonl").exists()
    diagnostics.clear_breadcrumbs()
    assert not (isolated_dir / "breadcrumbs.jsonl").exists()


def test_clear_breadcrumbs_idempotent(isolated_dir):
    diagnostics.clear_breadcrumbs()
    diagnostics.clear_breadcrumbs()  # no error


# ---------------------------------------------------------------------------
# Rotación
# ---------------------------------------------------------------------------

def test_rotate_keeps_tail_aligned_to_newline(isolated_dir, monkeypatch):
    """Al exceder MAX_BREADCRUMB_BYTES, el log se reduce a la cola
    KEEP_BREADCRUMB_BYTES recortada al primer salto de línea."""
    monkeypatch.setattr(diagnostics, "MAX_BREADCRUMB_BYTES", 200)
    monkeypatch.setattr(diagnostics, "KEEP_BREADCRUMB_BYTES", 100)
    for i in range(50):
        diagnostics.log_breadcrumb("op_test_rotation", index=i,
                                    pad="x" * 30)
    path = isolated_dir / "breadcrumbs.jsonl"
    size = path.stat().st_size
    assert size <= 200 + 250  # tras el siguiente write puede crecer un poco
    crumbs = diagnostics.read_breadcrumbs()
    assert len(crumbs) >= 1
    # Cada entrada debe parsear como JSON (alineación a salto de línea OK)
    for c in crumbs:
        assert "op" in c or "raw" in c


# ---------------------------------------------------------------------------
# breadcrumb_op context manager
# ---------------------------------------------------------------------------

def test_breadcrumb_op_logs_start_and_end_on_success(isolated_dir):
    with diagnostics.breadcrumb_op("my_op", floors=3):
        time.sleep(0.001)
    crumbs = diagnostics.read_breadcrumbs()
    assert [c["op"] for c in crumbs] == ["my_op.start", "my_op.end"]
    assert crumbs[0]["floors"] == 3
    assert "dur_ms" in crumbs[1]


def test_breadcrumb_op_logs_exception_and_reraises(isolated_dir):
    with pytest.raises(ValueError, match="boom"):
        with diagnostics.breadcrumb_op("my_op"):
            raise ValueError("boom")
    crumbs = diagnostics.read_breadcrumbs()
    ops = [c["op"] for c in crumbs]
    assert ops == ["my_op.start", "my_op.exception"]
    assert crumbs[1]["exc_type"] == "ValueError"
    assert crumbs[1]["exc_msg"] == "boom"
    assert "tb" in crumbs[1]


def test_breadcrumb_op_truncates_long_traceback(isolated_dir):
    """El traceback se recorta a 2 KB para que el log no explote."""
    def deep(n):
        if n <= 0:
            raise RuntimeError("x" * 10000)
        deep(n - 1)
    with pytest.raises(RuntimeError):
        with diagnostics.breadcrumb_op("deep_op"):
            deep(50)
    crumbs = diagnostics.read_breadcrumbs()
    tb = crumbs[-1]["tb"]
    assert len(tb) <= 2000


# ---------------------------------------------------------------------------
# system_info / export_diagnostic_text
# ---------------------------------------------------------------------------

def test_system_info_has_required_keys():
    info = diagnostics.system_info()
    assert "platform" in info
    assert "python" in info
    assert "blender" in info
    assert "pid" in info
    assert isinstance(info["pid"], int)


def test_export_diagnostic_text_without_scene(isolated_dir):
    """Sin scene, el informe omite props/escena pero incluye el resto."""
    diagnostics.log_breadcrumb("op_a", x=1)
    diagnostics.log_breadcrumb("op_b", x=2)
    text = diagnostics.export_diagnostic_text(scene=None)
    assert "INFORME DE DIAGNÓSTICO" in text
    assert "[Sistema]" in text
    assert "[Breadcrumbs" in text
    assert "op_a" in text
    assert "op_b" in text
    # Faulthandler section presente
    assert "Faulthandler" in text


def test_export_diagnostic_text_handles_empty_log(isolated_dir):
    text = diagnostics.export_diagnostic_text(scene=None)
    assert "[Breadcrumbs" in text
    assert "(sin entradas" in text


# ---------------------------------------------------------------------------
# snapshot_props (dummy props sin bpy)
# ---------------------------------------------------------------------------

class _DummyPathPoint:
    def __init__(self, obj):
        self.obj = obj


class _DummyVec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _DummyMatrix:
    def __init__(self, x, y, z):
        self.translation = _DummyVec(x, y, z)


class _DummyObj:
    def __init__(self, name, x, y, z):
        self.name = name
        self.matrix_world = _DummyMatrix(x, y, z)


class _DummyProps:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_snapshot_props_extracts_known_keys():
    props = _DummyProps(
        floor_count=3, floor_height=2.0, scaffold_depth=0.732,
        bay_length_catalog="LAYHER", auto_update=True,
        path_points=[],
    )
    snap = diagnostics.snapshot_props(props)
    assert snap["floor_count"] == 3
    assert snap["floor_height"] == 2.0
    assert snap["bay_length_catalog"] == "LAYHER"
    assert snap["auto_update"] is True
    assert snap["path_points"] == []


def test_snapshot_props_includes_path_points():
    p1 = _DummyPathPoint(_DummyObj("Empty.001", 1.0, 2.0, 0.0))
    p2 = _DummyPathPoint(_DummyObj("Empty.002", 5.0, 2.0, 0.0))
    props = _DummyProps(floor_count=2, path_points=[p1, p2])
    snap = diagnostics.snapshot_props(props)
    assert snap["path_points"] == [
        ["Empty.001", 1.0, 2.0, 0.0],
        ["Empty.002", 5.0, 2.0, 0.0],
    ]


def test_snapshot_props_handles_missing_attr_silently():
    """Una versión del addon puede no tener todas las props; se omiten."""
    props = _DummyProps(floor_count=2, path_points=[])
    snap = diagnostics.snapshot_props(props)
    assert "floor_count" in snap
    assert "scaffold_depth" not in snap   # no estaba en el dummy


def test_snapshot_props_handles_none_path_obj():
    p = _DummyPathPoint(obj=None)
    props = _DummyProps(floor_count=2, path_points=[p])
    snap = diagnostics.snapshot_props(props)
    assert snap["path_points"] == [None]


# ---------------------------------------------------------------------------
# enable_faulthandler (smoke)
# ---------------------------------------------------------------------------

def test_enable_faulthandler_creates_log_and_is_idempotent(isolated_dir):
    p1 = diagnostics.enable_faulthandler()
    p2 = diagnostics.enable_faulthandler()
    assert p1 == p2
    assert (isolated_dir / "faulthandler.log").exists()
    diagnostics.disable_faulthandler()  # cleanup


def test_disable_faulthandler_idempotent(isolated_dir):
    diagnostics.disable_faulthandler()
    diagnostics.disable_faulthandler()  # sin error
