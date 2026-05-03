"""Modelo FEM puro Python (sin dependencia de bpy).

Define las dataclasses que representan un grafo de nodos y barras junto con
materiales, secciones, apoyos y cargas. extract_model.py rellena un `Model`
desde la geometría de Blender; solver.py lo traduce a PyNite.

Convenciones de unidades (SI estricto):
    - longitudes en m
    - fuerzas en N
    - momentos en N·m
    - tensiones / módulos en Pa
    - densidades en kg/m³
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Materiales y secciones — value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Material:
    name: str
    E: float                # módulo de Young (Pa)
    G: float                # módulo de cizalla (Pa)
    nu: float               # coeficiente de Poisson
    rho: float              # densidad (kg/m³)
    fy: float               # límite elástico (Pa)
    fu: float = 0.0         # resistencia última (Pa); 0 = no especificado


@dataclass(frozen=True)
class Section:
    name: str
    A: float                # área (m²)
    Iy: float               # inercia eje fuerte (m⁴)
    Iz: float               # inercia eje débil (m⁴)
    J: float                # constante de torsión (m⁴)
    Wel: float = 0.0        # módulo elástico (m³); 0 = no especificado
    Wpl: float = 0.0        # módulo plástico (m³); 0 = no especificado
    i: float = 0.0          # radio de giro (m); 0 = no especificado
    eu_class: int = 0       # clase EN 1993-1-1 (1..4); 0 = no clasificada


# ---------------------------------------------------------------------------
# Catálogo mínimo (Fase 1) — se ampliará en materials.py / sections.py (Fase 2)
# ---------------------------------------------------------------------------

S235JR = Material(
    name="S235JR",
    E=210e9,
    G=210e9 / (2.0 * (1.0 + 0.3)),   # ≈ 80.77 GPa
    nu=0.3,
    rho=7850.0,
    fy=235e6,
    fu=360e6,
)


def _chs_properties(D: float, t: float) -> tuple[float, float, float, float]:
    """Propiedades de un perfil tubular circular hueco (CHS) puro.

    Devuelve (A, I, J, Wel) — la sección es bisimetríca, por lo que Iy = Iz = I.
    """
    d = D - 2.0 * t
    A = math.pi / 4.0 * (D * D - d * d)
    I = math.pi / 64.0 * (D ** 4 - d ** 4)
    J = 2.0 * I                          # tubo circular cerrado de pared fina
    Wel = I / (D / 2.0)
    return A, I, J, Wel


_A_CHS, _I_CHS, _J_CHS, _W_CHS = _chs_properties(0.0483, 0.0032)

CHS_48_3x3_2 = Section(
    name="CHS_48.3x3.2",
    A=_A_CHS,
    Iy=_I_CHS,
    Iz=_I_CHS,
    J=_J_CHS,
    Wel=_W_CHS,
    Wpl=_W_CHS * 1.27,                  # factor de forma típico CHS ≈ 1.27
    i=math.sqrt(_I_CHS / _A_CHS),
    eu_class=1,                          # D/t = 15.09 < 50ε² → clase 1 con S235JR
)


# ---------------------------------------------------------------------------
# Topología
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Node:
    id: str
    x: float
    y: float
    z: float


@dataclass
class Member:
    id: str
    i_node: str
    j_node: str
    section: str
    material: str
    member_type: str             # "pole" | "ledger" | "brace" | "tie"
    # Releases por extremo: (FX, FY, FZ, MX, MY, MZ) — True = liberado.
    # En Fase 1 se dejan todos a False (continuos); Fase 4 modelará uniones reales.
    release_i: tuple = (False, False, False, False, False, False)
    release_j: tuple = (False, False, False, False, False, False)


@dataclass
class Support:
    node: str
    DX: bool = False
    DY: bool = False
    DZ: bool = False
    RX: bool = False
    RY: bool = False
    RZ: bool = False


@dataclass
class NodalLoad:
    node: str
    direction: str               # "FX" | "FY" | "FZ" | "MX" | "MY" | "MZ"
    magnitude: float             # N o N·m
    case: str = "D"              # caso de carga (D, L, W, ...)


@dataclass
class DistributedLoad:
    """Carga lineal trapezoidal aplicada a una barra.

    Convención PyNite: `direction` en mayúsculas → ejes globales del modelo,
    en minúsculas → ejes locales de la barra. En este addon usamos siempre
    globales para peso propio y servicio (FZ negativa = gravedad).

    `w1` / `w2` son magnitudes lineales en N/m (positivas o negativas).
    `x1` / `x2` son posiciones a lo largo del eje local x desde el extremo i;
    None significa "extremo de la barra".
    """
    member: str
    direction: str               # "FX" | "FY" | "FZ" | "Fx" | "Fy" | "Fz"
    w1: float                    # N/m en el inicio del tramo cargado
    w2: float                    # N/m en el final del tramo cargado
    x1: Optional[float] = None
    x2: Optional[float] = None
    case: str = "D"


# ---------------------------------------------------------------------------
# Contenedor
# ---------------------------------------------------------------------------

@dataclass
class Model:
    nodes: dict[str, Node] = field(default_factory=dict)
    members: dict[str, Member] = field(default_factory=dict)
    materials: dict[str, Material] = field(default_factory=dict)
    sections: dict[str, Section] = field(default_factory=dict)
    supports: list[Support] = field(default_factory=list)
    nodal_loads: list[NodalLoad] = field(default_factory=list)
    distributed_loads: list[DistributedLoad] = field(default_factory=list)

    # ---- materiales / secciones ----------------------------------------------
    def add_material(self, mat: Material) -> None:
        self.materials[mat.name] = mat

    def add_section(self, sec: Section) -> None:
        self.sections[sec.name] = sec

    # ---- nodos --------------------------------------------------------------
    def add_node(self, x: float, y: float, z: float, id: Optional[str] = None) -> str:
        if id is None:
            id = f"N{len(self.nodes) + 1}"
        if id in self.nodes:
            raise ValueError(f"Nodo duplicado: {id}")
        self.nodes[id] = Node(id, x, y, z)
        return id

    def find_node(self, x: float, y: float, z: float, tol: float = 1e-3) -> Optional[str]:
        """Devuelve el id del nodo ya existente dentro de `tol` (m), o None."""
        for nid, n in self.nodes.items():
            if (abs(n.x - x) <= tol
                    and abs(n.y - y) <= tol
                    and abs(n.z - z) <= tol):
                return nid
        return None

    def get_or_create_node(self, x: float, y: float, z: float, tol: float = 1e-3) -> str:
        nid = self.find_node(x, y, z, tol)
        if nid is not None:
            return nid
        return self.add_node(x, y, z)

    # ---- barras -------------------------------------------------------------
    def add_member(
        self,
        i_node: str,
        j_node: str,
        section: str,
        material: str,
        member_type: str,
        id: Optional[str] = None,
    ) -> str:
        if id is None:
            id = f"M{len(self.members) + 1}"
        if id in self.members:
            raise ValueError(f"Barra duplicada: {id}")
        if i_node not in self.nodes or j_node not in self.nodes:
            raise ValueError(f"Nodos {i_node}/{j_node} no existen")
        if section not in self.sections:
            raise ValueError(f"Sección {section} no registrada")
        if material not in self.materials:
            raise ValueError(f"Material {material} no registrado")
        self.members[id] = Member(id, i_node, j_node, section, material, member_type)
        return id

    # ---- apoyos / cargas ----------------------------------------------------
    def add_support(self, node: str, **flags) -> None:
        if node not in self.nodes:
            raise ValueError(f"Nodo {node} no existe")
        self.supports.append(Support(node=node, **flags))

    def add_nodal_load(self, node: str, direction: str, magnitude: float, case: str = "D") -> None:
        if node not in self.nodes:
            raise ValueError(f"Nodo {node} no existe")
        if direction not in ("FX", "FY", "FZ", "MX", "MY", "MZ"):
            raise ValueError(f"Dirección inválida: {direction}")
        self.nodal_loads.append(NodalLoad(node, direction, magnitude, case))

    def add_distributed_load(
        self,
        member: str,
        direction: str,
        w1: float,
        w2: Optional[float] = None,
        *,
        x1: Optional[float] = None,
        x2: Optional[float] = None,
        case: str = "D",
    ) -> None:
        """Añade una carga lineal a una barra.

        Si `w2` es None se asume uniforme (`w2 = w1`). Direcciones válidas:
        Fx/Fy/Fz (locales) o FX/FY/FZ (globales). Para peso propio y cargas
        de servicio se usa habitualmente FZ negativa.
        """
        if member not in self.members:
            raise ValueError(f"Barra {member} no existe")
        if direction not in ("Fx", "Fy", "Fz", "FX", "FY", "FZ"):
            raise ValueError(f"Dirección inválida: {direction}")
        if w2 is None:
            w2 = w1
        self.distributed_loads.append(
            DistributedLoad(member, direction, w1, w2, x1, x2, case)
        )

    # ---- subdivisión --------------------------------------------------------
    def split_member(self, member_id: str, n: int) -> list[str]:
        """Subdivide una barra en `n` sub-barras alineadas y equiespaciadas.

        Crea `n-1` nodos intermedios y reemplaza la barra original por `n`
        nuevas. Las release del original se preservan únicamente en los
        extremos exteriores: las uniones internas son siempre continuas.

        Devuelve la lista de ids de las nuevas barras (en orden i→j).
        Errores si la barra ya tiene cargas distribuidas asignadas: el
        caller debe subdividir antes de aplicar cargas para evitar
        ambigüedades de re-mapeo.
        """
        if n < 1:
            raise ValueError("n debe ser ≥ 1")
        if n == 1:
            return [member_id]
        if member_id not in self.members:
            raise ValueError(f"Barra {member_id} no existe")
        for dl in self.distributed_loads:
            if dl.member == member_id:
                raise ValueError(
                    f"Barra {member_id} tiene cargas distribuidas; "
                    "subdivide antes de aplicar cargas"
                )

        orig = self.members.pop(member_id)
        ni = self.nodes[orig.i_node]
        nj = self.nodes[orig.j_node]
        new_ids: list[str] = []

        prev = orig.i_node
        for k in range(1, n):
            t = k / n
            x = ni.x + t * (nj.x - ni.x)
            y = ni.y + t * (nj.y - ni.y)
            z = ni.z + t * (nj.z - ni.z)
            mid_id = self.add_node(x, y, z, id=f"{member_id}_n{k}")
            sub_id = f"{member_id}_s{k}"
            self.members[sub_id] = Member(
                id=sub_id,
                i_node=prev,
                j_node=mid_id,
                section=orig.section,
                material=orig.material,
                member_type=orig.member_type,
                release_i=orig.release_i if k == 1 else (False,) * 6,
                release_j=(False,) * 6,
            )
            new_ids.append(sub_id)
            prev = mid_id

        last_id = f"{member_id}_s{n}"
        self.members[last_id] = Member(
            id=last_id,
            i_node=prev,
            j_node=orig.j_node,
            section=orig.section,
            material=orig.material,
            member_type=orig.member_type,
            release_i=(False,) * 6,
            release_j=orig.release_j,
        )
        new_ids.append(last_id)
        return new_ids

    # ---- estadísticas -------------------------------------------------------
    def stats(self) -> dict:
        by_type: dict[str, int] = {}
        for m in self.members.values():
            by_type[m.member_type] = by_type.get(m.member_type, 0) + 1
        return {
            "nodes": len(self.nodes),
            "members": len(self.members),
            "members_by_type": by_type,
            "supports": len(self.supports),
            "nodal_loads": len(self.nodal_loads),
            "distributed_loads": len(self.distributed_loads),
        }
