"""Wrapper sobre PyNiteFEA para análisis lineal elástico.

Todas las dependencias con PyNite están aisladas en este archivo: si
mañana cambiamos a OpenSeesPy o a un solver propio, sólo se reescribe
`solve()`. El resto del paquete habla con `Model` (puro Python).

Convención PyNite: el package se importa con `from Pynite import ...`
aunque el paquete pip se llame `PyNiteFEA`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .model import Model


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass
class NodeResult:
    DX: float
    DY: float
    DZ: float
    RX: float
    RY: float
    RZ: float
    RxnFX: float = 0.0
    RxnFY: float = 0.0
    RxnFZ: float = 0.0
    RxnMX: float = 0.0
    RxnMY: float = 0.0
    RxnMZ: float = 0.0


@dataclass
class MemberResult:
    """Esfuerzos extremos por barra (envolventes a lo largo del eje local).

    Convención del addon — **tracción positiva** (estándar EN 1993):
        - axial_max: máximo axil con signo (>0 → max tracción)
        - axial_min: mínimo axil con signo (<0 → max compresión)
        - shear_y, shear_z: máximo |cortante| local
        - moment_y, moment_z: máximo |momento| local
        - torque_max: máximo |torsor| local

    Nota: PyNite usa internamente convención **compresión positiva**, por lo
    que el wrapper invierte el signo de los axiles al construir este objeto.
    """
    axial_max: float
    axial_min: float
    shear_y_max: float
    shear_z_max: float
    moment_y_max: float
    moment_z_max: float
    torque_max: float
    length: float


@dataclass
class Results:
    nodes: dict[str, NodeResult] = field(default_factory=dict)
    members: dict[str, MemberResult] = field(default_factory=dict)
    combo: str = ""
    pynite_model: object = None        # FEModel3D — acceso de bajo nivel
    pdelta: bool = False               # True si se ejecutó analyze_PDelta


# ---------------------------------------------------------------------------
# Construcción del modelo PyNite
# ---------------------------------------------------------------------------

def build_pynite_model(model: Model, combos: Optional[dict] = None):
    """Convierte un `Model` puro a `FEModel3D` y registra apoyos, cargas y combos.

    Parameters
    ----------
    combos : dict[str, dict[str, float]] | None
        Diccionario de combinaciones {nombre: {caso: factor, ...}}.
        Si es None se registra una combinación trivial 'ULS' con D=1.
    """
    from Pynite import FEModel3D
    fem = FEModel3D()

    for mat in model.materials.values():
        fem.add_material(mat.name, mat.E, mat.G, mat.nu, mat.rho)

    for sec in model.sections.values():
        fem.add_section(sec.name, sec.A, sec.Iy, sec.Iz, sec.J)

    for n in model.nodes.values():
        fem.add_node(n.id, n.x, n.y, n.z)

    for m in model.members.values():
        fem.add_member(m.id, m.i_node, m.j_node, m.material, m.section)
        # Releases (Fase 1: todos a False; quedan listos para fases posteriores)
        if any(m.release_i) or any(m.release_j):
            fem.def_releases(
                m.id,
                Dxi=m.release_i[0], Dyi=m.release_i[1], Dzi=m.release_i[2],
                Rxi=m.release_i[3], Ryi=m.release_i[4], Rzi=m.release_i[5],
                Dxj=m.release_j[0], Dyj=m.release_j[1], Dzj=m.release_j[2],
                Rxj=m.release_j[3], Ryj=m.release_j[4], Rzj=m.release_j[5],
            )

    for s in model.supports:
        fem.def_support(s.node, s.DX, s.DY, s.DZ, s.RX, s.RY, s.RZ)

    for ld in model.nodal_loads:
        fem.add_node_load(ld.node, ld.direction, ld.magnitude, case=ld.case)

    for dl in model.distributed_loads:
        fem.add_member_dist_load(
            dl.member, dl.direction, dl.w1, dl.w2,
            x1=dl.x1, x2=dl.x2, case=dl.case,
        )

    if combos is None:
        combos = {"ULS": {"D": 1.0}}
    for cname, factors in combos.items():
        fem.add_load_combo(cname, factors)

    return fem


# ---------------------------------------------------------------------------
# Análisis
# ---------------------------------------------------------------------------

def solve(
    model: Model,
    *,
    combos: Optional[dict] = None,
    combo: Optional[str] = None,
    check_statics: bool = True,
    log: bool = False,
    use_pdelta: bool = False,
    pdelta_max_iter: int = 30,
) -> Results:
    """Ejecuta análisis y devuelve resultados para `combo`.

    Por defecto análisis lineal elástico de primer orden. Si
    `use_pdelta=True` ejecuta análisis P-Delta (segundo orden geométrico)
    iterativo de PyNite — captura la amplificación de momentos por el
    desplome de la cúspide en torres esbeltas. Más lento (~2-5×) pero
    requerido por EN 1993-1-1 §5.2 cuando el factor crítico α_cr ≤ 10.

    Si P-Δ no converge (sistema inestable bajo la combinación dada),
    PyNite lanza `ValueError`; aquí lo reempaquetamos como
    `RuntimeError` con mensaje accionable para el usuario.

    Si `combo` es None, se usa la primera combinación de `combos` (o 'ULS'
    cuando se aplica el default).
    """
    fem = build_pynite_model(model, combos)
    if use_pdelta:
        import math
        import warnings
        try:
            with warnings.catch_warnings(record=True) as w_list:
                warnings.simplefilter("always")
                fem.analyze_PDelta(
                    log=log,
                    check_stability=True,
                    max_iter=pdelta_max_iter,
                    sparse=True,
                )
            # PyNite a veces no eleva ValueError ante matriz singular; emite
            # MatrixRankWarning y devuelve NaN. Tratamos ambos como inestabilidad.
            singular_warned = any(
                "singular" in str(w.message).lower() for w in w_list
            )
            if not singular_warned:
                # Verificar NaN en cualquier nodo (matriz singular silenciosa)
                first_combo = combo or next(iter(fem.load_combos.keys()))
                for node in fem.nodes.values():
                    if any(math.isnan(getattr(node, attr)[first_combo])
                           for attr in ("DX", "DY", "DZ")):
                        singular_warned = True
                        break
            if singular_warned:
                raise ValueError("matriz de rigidez singular en P-Delta")
        except ValueError as e:
            raise RuntimeError(
                "Análisis P-Delta no convergió: el andamio es inestable "
                "bajo esta combinación de cargas (vuelco o pandeo global). "
                "Añade anclajes a fachada, reduce la altura, o usa secciones "
                f"más rígidas. Detalle interno: {e}"
            ) from e
    else:
        fem.analyze(check_statics=check_statics, log=log)

    if combo is None:
        if combos is None:
            combo = "ULS"
        else:
            combo = next(iter(combos.keys()))

    res = Results(combo=combo, pynite_model=fem, pdelta=use_pdelta)

    for nid, node in fem.nodes.items():
        res.nodes[nid] = NodeResult(
            DX=node.DX[combo],
            DY=node.DY[combo],
            DZ=node.DZ[combo],
            RX=node.RX[combo],
            RY=node.RY[combo],
            RZ=node.RZ[combo],
            RxnFX=node.RxnFX[combo],
            RxnFY=node.RxnFY[combo],
            RxnFZ=node.RxnFZ[combo],
            RxnMX=node.RxnMX[combo],
            RxnMY=node.RxnMY[combo],
            RxnMZ=node.RxnMZ[combo],
        )

    for mid, mem in fem.members.items():
        # PyNite usa compresión-positivo; invertimos para tracción-positivo.
        py_max = mem.max_axial(combo)
        py_min = mem.min_axial(combo)
        res.members[mid] = MemberResult(
            axial_max=-py_min,
            axial_min=-py_max,
            shear_y_max=max(abs(mem.max_shear("Fy", combo)), abs(mem.min_shear("Fy", combo))),
            shear_z_max=max(abs(mem.max_shear("Fz", combo)), abs(mem.min_shear("Fz", combo))),
            moment_y_max=max(abs(mem.max_moment("My", combo)), abs(mem.min_moment("My", combo))),
            moment_z_max=max(abs(mem.max_moment("Mz", combo)), abs(mem.min_moment("Mz", combo))),
            torque_max=max(abs(mem.max_torque(combo)), abs(mem.min_torque(combo))),
            length=mem.L(),
        )

    return res
