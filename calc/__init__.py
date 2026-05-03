"""Módulo de cálculo estructural del addon de andamios.

Estructura:
    - model.py            dataclasses puro Python (Node, Member, Material, Section, …).
    - extract_model.py    recorre la geometría de Blender y devuelve un Model.
    - solver.py           wrapper sobre PyNiteFEA para análisis lineal elástico.
    - materials.py        catálogo extensible (S235JR, S275JR, S355JR).
    - sections.py         catálogo CHS extensible (Ø48,3×3,2 / Ø48,3×4,0 / Ø60,3×3,2).
    - loads/              peso propio, servicio EN 12811-1, viento EN 1991-1-4,
                          imperfecciones EN 1993-1-1.
    - combinations.py     combinaciones EN 1990 §6.10 (ULS) + 6.14a/6.15a/6.16a (SLS).
    - releases.py         configuración de releases por tipo de miembro.
    - checks/             comprobaciones EN 1993-1-1 §6 (sección + pandeo +
                          interacción), EN 12811-1 (servicio) y EN 74 (uniones).
    - viewport.py         coloreado verde→rojo del viewport por utilización.
    - report.py           generación de informe HTML del cálculo.
    - ui.py               panel "Cálculo estructural" para Blender.
    - tests/              validación contra resultados analíticos.

`solver.py` y `model.py` no dependen de bpy: los tests corren fuera de Blender.
"""

from .model import (
    Material,
    Section,
    Node,
    Member,
    Support,
    NodalLoad,
    DistributedLoad,
    Model,
    S235JR,
    CHS_48_3x3_2,
)
from .materials import MATERIALS, S275JR, S355JR, get_material, register_material
from .sections import (
    SECTIONS,
    CHS_48_3x4_0,
    CHS_60_3x3_2,
    classify_chs,
    get_section,
    make_chs_section,
    register_section,
)
from .combinations import (
    sls_characteristic,
    sls_frequent,
    sls_quasi_permanent,
    standard_combos,
    uls_eq_6_10,
)
from .releases import set_releases_by_type
from .checks import (
    MemberCheckResult,
    SectionCheck,
    check_deflection_limit,
    check_joint,
    check_section_resistances,
    run_all_checks,
)
from .report import generate_html_report, write_html_report

__all__ = [
    # Tipos
    "Material",
    "Section",
    "Node",
    "Member",
    "Support",
    "NodalLoad",
    "DistributedLoad",
    "Model",
    # Catálogo de materiales
    "MATERIALS",
    "S235JR",
    "S275JR",
    "S355JR",
    "get_material",
    "register_material",
    # Catálogo de secciones
    "SECTIONS",
    "CHS_48_3x3_2",
    "CHS_48_3x4_0",
    "CHS_60_3x3_2",
    "classify_chs",
    "get_section",
    "make_chs_section",
    "register_section",
    # Combinaciones
    "uls_eq_6_10",
    "sls_characteristic",
    "sls_frequent",
    "sls_quasi_permanent",
    "standard_combos",
    # Releases
    "set_releases_by_type",
    # Checks
    "MemberCheckResult",
    "SectionCheck",
    "check_deflection_limit",
    "check_joint",
    "check_section_resistances",
    "run_all_checks",
    # Report
    "generate_html_report",
    "write_html_report",
]
