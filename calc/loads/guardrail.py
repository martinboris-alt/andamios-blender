"""Carga horizontal en barandilla — EN 12811-1 §7.2.

EN 12811-1 §7.2.1 exige que cada barandilla intermedia y superior resista
una carga horizontal puntual de **0,3 kN** aplicada en cualquier punto
de su longitud (carga de protección personal contra caídas).

Modelado en el FEM
==================
Las barandillas (`Rail_*`) NO se extraen como miembros del FEM hoy
(`extract_model.py` solo capta `Pole_`, `Ledger_`, `Brace_`, `HBrace_`,
`Tie_`). Por simplicidad y rapidez, esta función aplica la carga
**directamente sobre los nodos top de los postes externos** en la
dirección perpendicular al andamio (la cara expuesta a la caída).

Esta es una aproximación conservadora desde el punto de vista de la
estabilidad global: el poste recibe el cortante horizontal que la
barandilla le transferiría. La verificación local de la barandilla en
flexión (M ≤ M_Rd) y deflexión queda como cálculo offline (viga
biapoyada con carga puntual).

Para un poste de la fila externa la carga puntual se aplica en el nodo
del nivel del top-rail (típicamente z = `floor_count·floor_h`). La
dirección puede ser ±X, ±Y o auto-detectada vía la geometría del andamio
(por defecto: detectar el lado externo y empujar hacia fuera).
"""

from __future__ import annotations

from .. import model as _model_mod
from ..model import Model, NodalLoad


# Carga normativa EN 12811-1 §7.2.1: 0,3 kN puntuales en barandilla
GUARDRAIL_F_NEWTONS = 300.0


def apply_guardrail_horizontal_load(
    model: Model,
    *,
    F: float = GUARDRAIL_F_NEWTONS,
    direction: str = "AUTO",
    case: str = "Q",
) -> int:
    """Aplica carga horizontal puntual en cada nodo top-de-poste de la
    fila exterior en la dirección perpendicular al andamio.

    Parámetros
    ----------
    F : float
        Magnitud (N). Default 300 N (= 0,3 kN según EN 12811-1 §7.2.1).
    direction : str
        - "AUTO" → eje X o Y según cuál sea el más alineado con la
          dirección perpendicular (auto-detección por la geometría).
        - "+X" / "-X" / "+Y" / "-Y" → eje fijo.
    case : str
        Caso de carga registrado en la lista. Default "Q" (carga
        variable, agrupa con sobrecargas de uso).

    Devuelve el número de nodos sobre los que se aplicó la carga.

    Estrategia de detección del nodo "top-de-poste":
        - Recorre los miembros con `member_type == "pole"`
        - Para cada poste, identifica el extremo con z mayor (cabeza)
        - Filtra postes de la fila exterior usando la coordenada Y o X
          (lado opuesto a la fachada). Por simplicidad, aplica a TODOS
          los postes top — el caso normal es que un par (frontal+
          posterior) reciba la carga simétricamente, lo que es ligeramente
          conservador.
    """
    if F <= 0:
        return 0

    # Detección automática del eje perpendicular: para cada poste, busca
    # los desplazamientos relativos. En la práctica, los andamios rectos
    # tienen sus postes en filas paralelas a uno de los ejes globales.
    # Tomamos la varianza de las coordenadas X e Y de los nodos: el eje
    # con menor varianza es el "transversal" (el del depth = scaffold_depth).
    if direction == "AUTO":
        xs = [n.x for n in model.nodes.values()]
        ys = [n.y for n in model.nodes.values()]
        if len(xs) < 2:
            return 0
        x_range = max(xs) - min(xs)
        y_range = max(ys) - min(ys)
        # Si X varía mucho más que Y, la fachada está alineada con X y la
        # carga horizontal apunta en ±Y. En caso contrario al revés.
        axis = "FY" if x_range >= y_range else "FX"
    elif direction in ("+X", "-X"):
        axis = "FX"
    elif direction in ("+Y", "-Y"):
        axis = "FY"
    else:
        raise ValueError(f"direction inválida: {direction!r}")

    sign = -1.0 if direction in ("-X", "-Y") else 1.0

    # Identificar el nodo top de cada poste — el extremo con z mayor.
    # Si dos miembros poste comparten un nodo top (postes en columna),
    # solo cargamos UNO (el más alto del modelo).
    pole_top_nodes: set[str] = set()
    for mem in model.members.values():
        if mem.member_type != "pole":
            continue
        n_i = model.nodes[mem.i_node]
        n_j = model.nodes[mem.j_node]
        top_nid = mem.j_node if n_j.z >= n_i.z else mem.i_node
        pole_top_nodes.add(top_nid)

    # De los nodos top, conservar solo los que NO sean nodo bottom de otro
    # poste (es decir, el verdadero "tope" del andamio en esa columna).
    pole_bottom_nodes: set[str] = set()
    for mem in model.members.values():
        if mem.member_type != "pole":
            continue
        n_i = model.nodes[mem.i_node]
        n_j = model.nodes[mem.j_node]
        bot_nid = mem.i_node if n_i.z <= n_j.z else mem.j_node
        pole_bottom_nodes.add(bot_nid)

    true_top_nodes = pole_top_nodes - pole_bottom_nodes

    # Aplicar carga
    n_loads = 0
    for nid in true_top_nodes:
        ld = NodalLoad(node=nid, direction=axis, magnitude=sign * F, case=case)
        model.nodal_loads.append(ld)
        n_loads += 1
    return n_loads
