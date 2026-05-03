"""Configuración de releases por tipo de miembro.

En andamios reales no todas las uniones son rígidas: las cruces (braces) y
los anclajes (ties) trabajan típicamente en axil puro porque la cuña no
desarrolla momento significativo en esa configuración. Los travesaños
(ledgers) y los postes (poles) sí transmiten momento a través de la roseta
+ cabeza M.

Este módulo aplica esa configuración masivamente sobre un `Model` ya
extraído de la geometría, sustituyendo el `release_i` / `release_j` por
defecto (False×6 — totalmente continuo) por la combinación adecuada al
tipo de miembro.

Convención del Member.release_(i|j) tuple:
    (D_x, D_y, D_z, R_x, R_y, R_z)         True = liberado

Configuraciones disponibles:
    "rigid"   → (False, False, False, False, False, False)
    "pinned"  → libera momentos R_y y R_z (mantiene axil + cortantes y torsor)
    "axial"   → libera adicionalmente torsor (R_x); útil para diagonales y
                anclajes donde la barra no transmite ni torsión.
"""

from __future__ import annotations

from .model import Model


_RELEASE_PRESETS: dict[str, tuple[bool, bool, bool, bool, bool, bool]] = {
    "rigid":  (False, False, False, False, False, False),
    "pinned": (False, False, False, False, True,  True),
    "axial":  (False, False, False, True,  True,  True),
}


def set_releases_by_type(
    model: Model,
    *,
    pole: str = "rigid",
    ledger: str = "rigid",
    brace: str = "pinned",
    tie: str = "pinned",
) -> dict[str, int]:
    """Aplica configuración de releases a todas las barras de cada tipo.

    Devuelve un dict {tipo: n_barras_modificadas}.
    """
    config: dict[str, str] = {
        "pole":   pole,
        "ledger": ledger,
        "brace":  brace,
        "tie":    tie,
    }
    for mtype, preset in config.items():
        if preset not in _RELEASE_PRESETS:
            raise ValueError(
                f"Preset {preset!r} desconocido para {mtype}; "
                f"opciones: {list(_RELEASE_PRESETS)}"
            )

    counts: dict[str, int] = {}
    for mem in model.members.values():
        if mem.member_type not in config:
            continue
        rel = _RELEASE_PRESETS[config[mem.member_type]]
        mem.release_i = rel
        mem.release_j = rel
        counts[mem.member_type] = counts.get(mem.member_type, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# K_φ semi-rígido — factor K efectivo de pandeo
# ---------------------------------------------------------------------------

# El solver lineal (PyNite) no soporta nativamente rigideces rotacionales en
# extremos de barra. La aproximación consagrada en EN 1993-1-1 Anexo E para
# pórticos arriostrados es transformar el K_φ del nudo en un factor K
# efectivo de pandeo y pasarlo como L_cr al chequeo a compresión:
#
#     K = (1 + 0,145·(η_1+η_2) − 0,265·η_1·η_2)
#         / (2 − 0,364·(η_1+η_2) − 0,247·η_1·η_2)
#
# donde η_i = K_C / (K_C + K_φ_i), K_C = E·I / L (rigidez de la columna).
#
# Casos límite (verificados por test):
#   K_φ → ∞ (rígido)  → η → 0   → K → 1/2 = 0,5
#   K_φ → 0 (pinned) → η → 1    → K → (1 + 0,145·2 − 0,265) / (2 − 0,728 − 0,247) = 1,025 / 1,025 = 1,0
# Entre medias, el factor varía suavemente. Para Layher Allround (K_φ=80
# kN·m/rad) sobre poste CHS Ø48,3×3,2 (E·I=24,3 kN·m²) y L=2 m:
#   K_C = 12,15; η = 0,132; K ≈ 0,54


def effective_buckling_factor_K(
    L: float,
    EI: float,
    K_phi_top: float,
    K_phi_bot: float,
) -> float:
    """Factor K efectivo de pandeo según EN 1993-1-1 Anexo E para pórtico
    arriostrado (sin desplazamiento lateral).

    Parámetros:
        L          longitud geométrica de la columna (m)
        EI         rigidez flexional E·I (N·m² o kN·m², coherente con K_φ)
        K_phi_top  rigidez rotacional del nudo superior (mismas unidades)
        K_phi_bot  rigidez rotacional del nudo inferior

    Devuelve K ∈ [0,5; 1,0]. Para `K_phi → ∞` da 0,5 (rígido perfecto);
    para `K_phi → 0` da 1,0 (rótula perfecta). Si `L<=0` o `EI<=0`,
    devuelve 1,0 (degenerado, asumimos pinned conservador).
    """
    if L <= 0 or EI <= 0:
        return 1.0
    K_C = EI / L
    # η = K_C / (K_C + K_phi); con K_phi muy grande, η→0 (rígido)
    # con K_phi → 0, η → 1 (rótula)
    eta_1 = K_C / (K_C + K_phi_top) if K_phi_top > 0 else 1.0
    eta_2 = K_C / (K_C + K_phi_bot) if K_phi_bot > 0 else 1.0
    num = 1.0 + 0.145 * (eta_1 + eta_2) - 0.265 * eta_1 * eta_2
    den = 2.0 - 0.364 * (eta_1 + eta_2) - 0.247 * eta_1 * eta_2
    if den <= 0:
        return 1.0
    K = num / den
    # Clamp al rango teórico [0,5; 1,0]
    return max(0.5, min(1.0, K))


def compute_pole_lcr_overrides(
    model: Model,
    *,
    K_phi: float,
) -> dict[str, float]:
    """Calcula `L_cr` por poste aplicando K_φ semi-rígido en ambos
    extremos. Ignora postes con `member_type != 'pole'` y barras de
    longitud nula.

    Devuelve dict {member_id → L_cr_metros} listo para pasar como
    `L_cr_overrides` a `run_all_checks`. Si `K_phi` ≤ 0, devuelve dict
    vacío (caller debe usar L_cr_factor por defecto).

    Asume el mismo K_φ en top y bot (válido cuando el poste atraviesa
    rosetas idénticas a ambos lados — el caso normal Layher Allround).
    """
    if K_phi <= 0:
        return {}
    out: dict[str, float] = {}
    for mid, mem in model.members.items():
        if mem.member_type != "pole":
            continue
        n_i = model.nodes[mem.i_node]
        n_j = model.nodes[mem.j_node]
        dx = n_j.x - n_i.x
        dy = n_j.y - n_i.y
        dz = n_j.z - n_i.z
        L = (dx*dx + dy*dy + dz*dz) ** 0.5
        if L <= 0:
            continue
        sec = model.sections[mem.section]
        mat = model.materials[mem.material]
        # Para CHS la sección es bisimétrica (Iy = Iz). Usamos Iy.
        EI = mat.E * sec.Iy
        K = effective_buckling_factor_K(L, EI, K_phi, K_phi)
        out[mid] = K * L
    return out
