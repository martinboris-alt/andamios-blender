"""Tests del módulo calc.deformed (geometría deformada tipo ANSYS).

La construcción/limpieza de las colecciones depende de bpy y se valida
en el smoke test de Blender. Aquí cubrimos `_displacement_to_bucket`
(función pura) y `store_tube_displacements` con un fake de bpy.
"""

from __future__ import annotations

import sys
import types

import pytest

from calc import S235JR, CHS_48_3x3_2, Model
from calc.solver import solve


def _stub_bpy_for_store():
    """Crea un módulo bpy mínimo con `bpy.data.objects` indexable por nombre.
    Cada objeto fake tiene `.type`, `.name`, `.bound_box`, `.matrix_world` y
    soporta __setitem__ para custom props.
    """
    if "bpy" in sys.modules:
        # Si ya está stubeado en otro test, lo reseteamos
        del sys.modules["bpy"]

    class _FakeObj:
        def __init__(self, name, mesh=True):
            self.name = name
            self.type = "MESH" if mesh else "EMPTY"
            self._props = {}
        def __setitem__(self, k, v):
            self._props[k] = v
        def __getitem__(self, k):
            return self._props[k]
        def __contains__(self, k):
            return k in self._props
        def get(self, k, default=None):
            return self._props.get(k, default)

    class _FakeData:
        def __init__(self):
            self.objects = {}
        def add(self, obj):
            self.objects[obj.name] = obj

    bpy_mod = types.ModuleType("bpy")
    bpy_mod.data = _FakeData()
    sys.modules["bpy"] = bpy_mod
    return bpy_mod, _FakeObj


def test_store_tube_displacements_writes_six_floats_per_object():
    """Cada miembro debe recibir 6 valores (dx, dy, dz)_i + (dx, dy, dz)_j."""
    bpy, FakeObj = _stub_bpy_for_store()
    # Crear objetos para los miembros del modelo
    bpy.data.add(FakeObj("Pole_F0_0"))
    bpy.data.add(FakeObj("Pole_F0_1"))

    # Modelo simple con 1 miembro y resultado mock
    L = 3.0
    m = Model()
    m.add_material(S235JR); m.add_section(CHS_48_3x3_2)
    m.add_node(0, 0, 0, id="A")
    m.add_node(0, 0, L, id="B")
    m.add_member("A", "B", CHS_48_3x3_2.name, S235JR.name, "pole",
                 id="M_Pole_F0_0")
    m.add_support("A", DX=True, DY=True, DZ=True, RX=True, RY=True, RZ=True)
    m.add_nodal_load("B", "FX", 1000.0)
    res = solve(m, check_statics=False)

    # Necesitamos importar deformed DESPUÉS del stub
    if "calc.deformed" in sys.modules:
        del sys.modules["calc.deformed"]
    from calc.deformed import store_tube_displacements, CUSTOM_PROP_DISP

    n = store_tube_displacements(m, res)
    assert n == 1
    obj = bpy.data.objects["Pole_F0_0"]
    disp = list(obj[CUSTOM_PROP_DISP])
    assert len(disp) == 6
    # i_node está en A (apoyo) → desplazamiento ~0
    assert all(abs(v) < 1e-6 for v in disp[:3])
    # j_node está en B (libre) → desplazamiento no nulo
    assert any(abs(v) > 1e-6 for v in disp[3:])


def test_displacement_to_bucket_uses_pipeline_thresholds():
    """`_displacement_to_bucket` debe coincidir con `deflection_ratio_to_bucket`."""
    if "calc.deformed" in sys.modules:
        del sys.modules["calc.deformed"]
    # Restablecer bpy a estado conocido (no necesario para esta función pero
    # mantiene aislamiento entre tests)
    _stub_bpy_for_store()
    from calc.deformed import _displacement_to_bucket
    from calc.pipeline import deflection_ratio_to_bucket

    # Ejemplo: L=2 m, δ=4 mm → ratio = 0.002 = 1/500 → bucket 1
    bucket_dir = _displacement_to_bucket(0.004, 2.0)
    bucket_ref = deflection_ratio_to_bucket(0.004 / 2.0)
    assert bucket_dir == bucket_ref


def test_displacement_to_bucket_handles_zero_length():
    if "calc.deformed" in sys.modules:
        del sys.modules["calc.deformed"]
    _stub_bpy_for_store()
    from calc.deformed import _displacement_to_bucket
    assert _displacement_to_bucket(0.01, 0.0) == 0
