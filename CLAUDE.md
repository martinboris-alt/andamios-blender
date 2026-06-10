# CLAUDE.md — Guía rápida para asistentes de IA

> Este archivo se carga automáticamente al inicio de cada sesión de Claude Code
> en este repo. Mantenlo conciso. Para detalle de usuario está [README.md](README.md);
> para histórico de versiones [DEVELOPMENT.md](DEVELOPMENT.md); para limitaciones
> conocidas [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Qué es esto

Addon de Blender que genera andamios multidireccionales paramétricos a partir
de empties y los verifica estructuralmente según Eurocódigos. Es un único repo,
sin monorepo: el addon vive en `andamios_addon.py` y el módulo de cálculo en
`calc/`. Versión actual en `bl_info.version`; releases canónicas en GitHub.

## Layout

```
andamios_addon.py       # Addon completo en UN solo archivo (~148 KB, 13 operadores, 1 panel raíz)
tutorial_guide.py       # Tutorial guiado in-Blender (overlay)
build_release.py        # Empaqueta -> andamios.zip
calc/                   # Módulo FEM independiente de bpy
  ├── model.py          # Dataclasses Pure-Python (Node, Member, Material, Section, ...)
  ├── catalogs.py       # Catálogos multi-fabricante (Layher/PERI/ULMA/Doka) — fuente única dimensional
  ├── extract_model.py  # bpy -> Model (única pieza de calc/ que toca bpy)
  ├── solver.py         # Wrapper PyNiteFEA
  ├── pipeline.py       # Orquesta extract -> solve -> check
  ├── checks/           # EN 1993-1-1, EN 12811, EN 74 joints
  ├── loads/            # peso propio, servicio, viento, imperfecciones, barandilla
  ├── ui.py             # Panel "Cálculo estructural" (toca bpy)
  ├── viewport.py / deformed.py / cad_*.py / report.py / bom.py / screenshots.py
  └── tests/            # ~25 archivos pytest, 434 tests
i18n/translations.py    # Solo en_US registrado; ES es la fuente in-code
.github/workflows/release.yml  # CI: build + tests + tag
tutorial/               # Manual HTML interactivo (Three.js, autocontenido)
```

**Archivos `.bak.py` y `mcp-*` / `mechanicalpro-master*` en raíz son artefactos
históricos** — están en `.gitignore` y **no se tocan**.

## Comandos esenciales

```bash
# Tests (usa el Python embebido de Blender porque algunos importan bpy)
/snap/blender/current/5.1/python/bin/python3.13 -m pytest calc/tests/ -q
# Esperado: 434 passed

# Build del zip instalable
python build_release.py
# Genera andamios.zip en raíz; estructura interna: andamios/__init__.py + andamios/calc/
```

No hay `pyproject.toml` ni `setup.py`: las dependencias de `calc/` están en
[`calc/requirements.txt`](calc/requirements.txt) (PyNiteFEA principalmente).

## Convenciones del proyecto

### Arquitectura
- **`andamios_addon.py` es deliberadamente monolítico.** No partir en módulos
  sin pedir confirmación: los operadores, panels y propiedades referenciados
  por nombre (`bl_idname`) son frágiles a la refactorización y rompen escenas
  guardadas.
- **`calc/` no debe importar `bpy`** salvo en `extract_model.py` y `ui.py`
  (los únicos puentes con Blender). Esta separación es la que permite que los
  tests corran fuera de Blender. Si tocas `calc/`, mantén el aislamiento.
- **Nombres canónicos** que aparecen en código y escenas:
  - Colección: `Scaffold` (constante `SCAFFOLD_COLLECTION`)
  - Tube diameter: `0.0489` m (EN 39 / EN 12810)
  - Sistema: `Ringlock_EU` (compatible Layher, PERI, ULMA, Doka)

### Estilo bpy
- Operadores deben tener `bl_options = {'REGISTER', 'UNDO'}` salvo justificación.
- Operadores que actúan sobre selección deben definir `poll()` que valide
  `context.active_object` y modo (`OBJECT` vs `EDIT`).
- Preferir `bpy.data.*` sobre `bpy.ops.*` en lógica interna; `bpy.ops` solo
  para acciones de usuario o cuando no hay alternativa.
- Mensajes de UI van por `iface_(...)` para que i18n los recoja.

### Tests
- Cubren el módulo `calc/` (no UI Blender). Si añades funcionalidad de cálculo,
  añade tests; el suite no debería bajar de 434.
- Patrón: `test_<modulo>.py`. Validan contra resultados analíticos cuando es
  posible (ver `test_viga_apoyada.py`, `test_portico_simple.py`).

### Normativa
Las decisiones de cálculo están atadas a normas. Cuando dudes, **busca la
referencia EN en el código** (e.g. `# EN 1993-1-1 §6.3.1` o `# EN 12811-1 §6.2`).
No reinventar fórmulas: si el solver da algo raro, primero verifica que la
fórmula coincide con la norma citada.

Normas que toca este código:
- **EN 1993-1-1** — diseño acero (sección, pandeo, interacción flexo-compresión)
- **EN 12811-1/2/3** — andamios de servicio (deflexiones, clases Q1-Q6)
- **EN 1991-1-4** — viento (zonas A/B/C españolas, terrenos 0-IV)
- **EN 1990** — combinaciones (eq. 6.10, 6.14a/6.15a/6.16a)
- **EN 74** — uniones tubo-acoplador
- **UNE-EN ISO 129-1** — acotación en planos CAD

## Cosas que NO hay que hacer

- ❌ **Renombrar operadores existentes** (`bl_idname`): rompe escenas guardadas
  y el tutorial guiado.
- ❌ **Tocar `andamios_addon_v0.4.1.bak.py`** o cualquier `*.bak.py`: son
  snapshots de referencia para regresiones, no código vivo.
- ❌ **Bajar la versión mínima de Blender** sin discutirlo — `bl_info["blender"]`
  fija el mínimo que carga el addon, pero la API target real es 5.1+ (ver README).
- ❌ **Mockear el solver en tests de FEM**. Los tests deben ejercitar PyNiteFEA
  real contra resultados analíticos. Mockear ha enmascarado bugs de signo en
  el pasado.
- ❌ **Asumir que `context.active_object` no es None** — siempre validar.
- ❌ **Activar P-Δ por defecto** — es opt-in deliberado (lento, ~2-5×).
- ❌ **Editar `i18n/translations.py` a mano para añadir idiomas nuevos** sin
  consultar: el flujo decidido es solo ES (fuente in-code) + en_US registrado.

## Cómo se hace una release

1. Bump `bl_info["version"]` en `andamios_addon.py`.
2. Actualiza `DEVELOPMENT.md` con notas de la versión.
3. Ejecuta `pytest calc/tests/ -q` — debe pasar todo.
4. `git commit && git tag v0.X.Y && git push --tags`.
5. El workflow `.github/workflows/release.yml` construye el zip y crea la GitHub
   Release. Verifica que el zip resultante instala limpio en Blender 5.1.

## Documentos a leer ANTES de tocar áreas concretas

| Si vas a tocar... | Lee primero |
|---|---|
| Geometría / generación / UI principal | [README.md](README.md) §"Funcionalidades" |
| Algo que falla raro | [KNOWN_ISSUES.md](KNOWN_ISSUES.md) — puede estar identificado |
| Comprobaciones FEM | [calc/__init__.py](calc/__init__.py) (mapa) y la norma EN citada en el módulo |
| Release o packaging | [build_release.py](build_release.py) |
| i18n | [i18n/__init__.py](i18n/__init__.py) y memoria de proyecto sobre i18n cerrado |
| Histórico de decisiones | [DEVELOPMENT.md](DEVELOPMENT.md) |

## Stack y entornos

- **Blender 5.1+** (Python embebido 3.13)
- **PyNiteFEA** (auto-instalada en `register()` si falta — ver función `_ensure_pynite` en addon)
- **Tests**: pytest (sin frameworks adicionales)
- **CI**: GitHub Actions (`release.yml`)
- **Sin Node, sin bundlers, sin DB.**
