# Auditoría — Incoherencias del addon explicado a un novato

> Versión auditada: **0.7.12** · Fecha: 2026-05-02
> **Re-auditado: 2026-05-03 (v0.7.13)** — varios fixes ya estaban en código sin
> que el documento se actualizara; los marcamos ✅. Ver "Estado de los fixes"
> al final.
> Misión: detectar puntos donde un usuario sin formación de andamios o de
> Blender se traba al intentar entender qué hace cada control.

Cada incidencia está clasificada por **severidad**:
- 🔴 **CRÍTICA** — bloquea el entendimiento del flujo principal
- 🟠 **MEDIA** — fricción real, causa errores recurrentes
- 🟡 **BAJA** — mejora de pulido, no bloquea

Y por **tipo de fix**:
- `[code]` requiere modificar el `.py`
- `[doc]` se arregla en el tutorial / tooltip
- `[both]` ambos

---

## 1 · Plataforma vs bandeja vs deck 🔴 [doc]

**Confusión:** el panel mezcla tres palabras para conceptos relacionados pero
distintos.

| Término | Qué es | Dónde aparece |
|---|---|---|
| **Plataforma** | Todo el suelo de un piso (= 1 deck) | Toggle `add_decks`, color `color_plataformas` |
| **Bandeja** | Pieza individual rectangular que cubre parte del ancho | Props `deck_planks_count`, `deck_plank_width`, panel "Material bandeja" |
| **Deck** | El conjunto plataforma + sus bandejas | Solo en código (`add_decks`, `deck_*`) |

Un novato no sabe que **una plataforma = N bandejas paralelas**. Resuelto en
el tutorial v3 con la sección "Plataformas y bandejas" + tooltip pero el
panel sigue mezclando los dos términos sin explicación in-line.

**Fix propuesto [doc]:** añadir un tooltip en el toggle "Plataformas":
*"Una plataforma es el suelo de un piso, formado por bandejas paralelas.
El número y ancho de las bandejas se configura abajo."*

---

## 2 · `bay_length_catalog` con tres valores ambiguos ✅ [code, v0.7.13]

**Confusión:** el dropdown de "Catálogo de longitudes" tiene tres opciones
con nombres genéricos:
- **GENERIC** → "Genérico" — múltiplos de 0,5 m (1,0 / 1,5 / 2,0 / 2,5 / 3,0)
- **LAYHER** → "Layher Allround" — catálogo real Layher
- **UNIFORM** → "Uniforme" — divide el tramo en N partes iguales

Para un novato, **"GENERIC" suena a "valor por defecto"** y "UNIFORM"
también. La diferencia entre los tres no es obvia hasta que ves el resultado.

**Fix propuesto [code]:** renombrar internamente:
- `GENERIC` → `STANDARD` o `MIXTO_50CM` (nombre que sugiere "múltiplos de 50 cm")
- `LAYHER` → `LAYHER_ALLROUND` (más explícito)
- `UNIFORM` → `IGUALES` (en español, más directo)

Coste: cambiar enum + actualizar `_BAY_LENGTH_CATALOGS` + presets que
referencian los códigos.

**Fix temporal [doc]:** animación comparativa lado-a-lado de los 3 modos
sobre un mismo tramo de 7 m.

**Fix aplicado v0.7.13:** se preservan los códigos del enum (`GENERIC`/
`LAYHER`/`UNIFORM`) para no romper .blend guardados, pero se renombran
los **labels visibles** + descripciones:
- "Genérico" → **"Mixto múltiplos 0,5 m"**
- "Layher Allround" → **"Layher Allround (catálogo real)"**
- "Uniforme" → **"Iguales (divide en N partes)"**
+ etiqueta del prop a "Catálogo vanos (horizontal)" (cierra también #3).

---

## 3 · `pole_length_catalog` y `bay_length_catalog` ✅ [code, v0.7.13]

Hay **DOS catálogos distintos** en el panel:
- `bay_length_catalog` — catálogo de longitudes de **vanos** (largo entre postes)
- `pole_length_catalog` — catálogo de longitudes de **piezas de poste** (cómo se segmenta el tubo vertical)

Un novato verá "Catálogo de longitudes" y "Catálogo postes" sin entender
que se aplican a dos cosas distintas (horizontal vs vertical).

**Fix propuesto [doc]:** renombrar etiquetas en el panel:
- `"Catálogo de longitudes"` → `"Catálogo vanos (horizontal)"`
- `"Catálogo postes"` → `"Catálogo postes (vertical)"`

**Fix aplicado v0.7.13:** las dos etiquetas se renombraron exactamente como
se proponía. Los labels de los items de `pole_length_catalog` también se
hicieron explícitos ("Uniforme (longitud fija)", "Mixto múltiplos 0,5 m",
"Layher Allround (catálogo real)").

---

## 4 · "Diagonales horizontales (plano)" ✅ [code, v0.7.13]

**Confusión:** el toggle `add_horizontal_braces` se llama "Diagonales
horizontales (plano)". Para un novato suena contradictorio: ¿una diagonal
horizontal? ¿En qué plano?

Se refiere a una **diagonal en el plano del deck** (rigidiza torsión).
Pero "plano" en castellano puede significar "alzado" o "plana" u "horizontal".

**Fix propuesto [code]:** renombrar a:
`"Cruces en planta (rigidizan torsión)"` o
`"Diagonales en plano del piso"`.

**Fix aplicado v0.7.13:** label cambiado a **"Cruces en planta (rigidizan
torsión)"** + descripción ampliada con la palabra clave "racking" y la
analogía visual ("vistas desde arriba forman aspas").

---

## 5 · `closed_loop` 🟡 [doc]

El toggle "Trayectoria cerrada" sin más explicación deja al novato
preguntando qué pasa exactamente. **Fix [doc]:** ya cubierto en tutorial v3
con la receta "Torre", pero añadir descripción al tooltip:
*"Conecta el último punto con el primero — útil para torres rectangulares
o anillos cerrados."*

---

## 6 · `use_terrain_z` y `base_z` 🟡 [doc]

Un novato no sabe qué es "Z" (eje vertical en Blender). Las props se
llaman:
- `base_z` → "Z base (m)"
- `use_terrain_z` → "Terreno irregular"

**Fix propuesto [doc]:** añadir tooltip a "Z base":
*"Altura del pie del andamio sobre el origen de Blender. Si tu obra
tiene desniveles, activa 'Terreno irregular' y el addon nivelará
automáticamente con husillos de longitud variable."*

---

## 7 · "Auto-update" sin explicación de costes 🟠 [doc]

**Confusión:** el toggle "Auto-actualizar al mover la trayectoria" no
avisa de que **regenerar puede tardar varios segundos** en andamios
grandes. Un usuario que activa auto-update y mueve un empty puede
pensar que Blender se ha colgado.

**Fix [doc]:** añadir tooltip:
*"Regenera el andamio cada vez que cambies un valor. Recomendado
mientras exploras parámetros. **Desactivar** en andamios grandes
(&gt; 50 vanos) o cuando estás conforme con el diseño."*

---

## 8 · Botón "Diagnóstico" en panel principal ✅ [code, ya resuelto antes de v0.7.13]

**Confusión:** el panel principal tiene una sección "Diagnóstico" con
botón "Exportar informe". El nombre puede confundir con
**"Comprobar modelo"** del cálculo (que también valida geometría) o con
"Diagnóstico narrativo de fallos" (que aparece tras `calc_run`).

**Fix propuesto [code]:** renombrar la sección a
`"Reporte de errores"` y el botón a
`"Exportar log para depurar"`. Aclara que se usa solo cuando Blender
ha fallado / se ha cerrado.

**Estado real (verificado 2026-05-03 en `andamios_addon.py:3055-3060`):** ya
hecho. La sección dice **"Reporte de errores"** (icono CONSOLE) con sub-label
**"(Solo para depurar fallos)"** + botón **"Exportar log"** (icono TEXT) +
botón papelera. La auditoría se redactó antes de aplicarse el fix.

---

## 9 · Clases de servicio Q1..Q6 sin explicación inline ✅ [code, ya resuelto antes de v0.7.13]

**Confusión:** el dropdown "Tipo de uso" muestra Q1, Q2, Q3, Q4, Q5, Q6
sin más. Un novato no sabe qué significa cada uno.

Sin embargo el código YA tiene descripciones legibles
(`SERVICE_DESCRIPTION` en `pipeline.py`) que **no se muestran en el panel**.

**Fix propuesto [code]:** mostrar la descripción del Q seleccionado bajo
el dropdown:

```
Tipo de uso: [Q3 ▼]
   "Uso general (≈ 4 trabajadores con herramienta, 200 kg/m²)"
```

**Estado real (verificado 2026-05-03 en `calc/ui.py:1101-1109`):** ya hecho.
Bajo el dropdown se renderiza `f"   ↳ {q_desc}"` con icono INFO, leyendo
de `SERVICE_DESCRIPTION` en `calc/pipeline.py`. Ejemplo: con Q3 seleccionado
aparece **"↳ uso general (≈200 kg/m², ≈4 trabajadores con herramienta)"**.

---

## 10 · Combinación de cargas con códigos crípticos ✅ [code, ya resuelto antes de v0.7.13]

**Confusión:** el dropdown "Combinación a comprobar" muestra:
- `ULS_LeadL`
- `ULS_LeadW`
- `SLS_RARE`
- `SLS_FREQ`
- `SLS_QUASI`

Un novato no entiende **nada** de esto. ULS / SLS, "Lead", "RARE", etc.

**Fix propuesto [doc]:** poner descripción legible:
- `ULS_LeadL` → "ULS · uso dominante (más típico)"
- `ULS_LeadW` → "ULS · viento dominante"
- `SLS_RARE` → "SLS · raro (deflexión max)"
- `SLS_FREQ` → "SLS · frecuente (deflexión normal)"

Coste: traducir los items del enum del panel.

**Estado real (verificado 2026-05-03 en `andamios_addon.py:2454-2480`):** ya
hecho. Los 6 items tienen labels legibles ("Resistencia — uso dominante",
"Resistencia — viento dominante", "Resistencia — levantamiento por viento",
"Servicio — deformación característica/frecuente/casi-permanente") y cada
uno con descripción larga (tooltip) que explica el caso. La auditoría se
redactó antes del fix.

---

## 11 · Generar / Actualizar 🟡 [doc]

Un novato puede no saber **cuándo pulsar el botón**:
- ¿Cada vez que cambio un valor?
- ¿Una sola vez?
- ¿Por qué a veces se ve un punto rojo en el botón?

**Fix [doc]:** ya cubierto en quickstart pero añadir microcopia:
*"Pulsa cada vez que cambies un parámetro. O activa Auto-actualizar
arriba para que sea automático."*

---

## 12 · "Husillo" no se explica 🟡 [doc]

Aparece en "Husillo de base (m)". Un novato no sabe qué es un husillo
(pie regulable de altura). El tutorial v3 lo tiene en glosario pero el
panel no lo enlaza.

**Fix [doc]:** tooltip — *"Pie regulable bajo cada poste. Permite nivelar
el andamio sobre suelos irregulares."*

---

## 13 · Subdivisión cruces — concepto avanzado sin contexto 🟠 [doc]

**Confusión:** el dropdown "Subdivisión cruces" tiene NONE / HALF / QUARTER.
Un novato no entiende qué subdivide ni para qué sirve sin un ejemplo
visual.

**Fix [doc]:** **animación comparativa NONE/HALF/QUARTER** lado-a-lado
en el tutorial. Ya tenemos `anim_brace_cycle.webp`. Asegurar que se
referencia correctamente en la sección "Cruces y barandilla".

---

## 14 · Brace pattern FRONT/BACK/BOTH/ALT 🟠 [doc]

El dropdown "Patrón cruces" tiene 4 opciones cuyos nombres traducidos
("Solo frontal", "Solo posterior", "Ambas caras", "Alternadas") **no
explican qué cara es frontal**. Para un novato, ¿cuál es la cara frontal
de su andamio?

**Convención del addon:** la cara FRONT es la primera (la que toca el
usuario al colocar los empties). La cara BACK es la opuesta (más cerca
de la fachada). Esto **no está documentado en el panel**.

**Fix [doc]:** tooltip en el dropdown:
*"Frontal = cara exterior (donde están los path_points). Posterior
= cara interior (más cerca de la fachada o del muro a estabilizar)."*

---

## 15 · Anclaje vs Tie inconsistente 🟡 [doc]

El código mezcla:
- "Anclajes a fachada" (panel) ✓
- `add_ties` (prop) — tie en inglés
- `Tie_*` (prefijo de objetos)
- "Anclajes" (collection)

Para un novato hispanohablante, "Tie_F2_03" en el outliner es críptico.
**Fix [doc]:** explicación de prefijos en el tutorial. **Fix [code]
opcional:** renombrar prefijos a "Anclaje_*" — pero es invasivo.

---

## 16 · Bandeja: catálogo Ringlock EU oculto 🟠 [doc]

**Confusión:** existe una sección "Catálogo de bandejas" en el panel con
filtros (ancho/clase/material) y selector. **No queda claro para un
novato si esto AFECTA al andamio que genera o solo es informativo.**

Mirando el código, parece que es un catálogo de referencia que ayuda al
auto-cubrir y la auditoría, pero **no se usa directamente en la
generación principal** (que va por `deck_planks_count` × `deck_plank_width`).

**Fix [doc]:** clarificar en el tutorial:
*"El catálogo de bandejas Ringlock EU es una referencia para la
**auditoría** y la herramienta **Auto-cubrir bandejas**. La generación
del andamio principal usa los valores `deck_planks_count` y
`deck_plank_width` del panel."*

---

## 17 · Indicador de escalera "P0/P1" confunde con path_points ✅ [code, ya resuelto antes de v0.7.13]

**Confusión:** en el modo manual de escaleras, cada slot tiene un campo
"Pos" que es un slider 0..1 y un "Indicador" que es un Empty visible.
Estos empties también se llaman P0, P1... como los path_points
principales.

**Fix [code]:** prefijar los indicadores de escalera con `LdrInd_` para
no confundir con los path_points (que son `P0`, `P1`...).

**Estado real (verificado 2026-05-03 en `andamios_addon.py:2562-2568`):** los
indicadores ya se nombran como `Andamio_LadderHandle_NN` (no `P0/P1`), con
lo que el conflicto está resuelto aunque con un prefijo distinto al
propuesto. La auditoría se redactó antes de aplicarse el fix.

---

## 18 · Color "Anclajes" pero hay colección "Anclajes" 🟡 [code]

Hay una colección llamada "Anclajes" (donde van los Tie_*) y un color
configurable "Color anclajes". Coherente. ✓ — sin acción.

---

## 19 · Botón "Auditoría bandejas" sin contexto previo 🟠 [doc]

**Confusión:** el panel principal tiene un botón "Auditoría bandejas"
que reporta a la **consola del sistema** un texto largo. Un novato
puede no saber dónde mirar el resultado.

**Fix [doc]:** tooltip o microcopia:
*"Reporta al panel + consola del sistema (Window → Toggle System Console
en Windows) la utilización de cada bandeja según EN 12811-1."*

---

## 20 · "Restaurar colores" y "Revertir auto-corrección" 🟡 [doc]

Dos botones distintos en el panel de cálculo, ambos relacionados con
"deshacer" — pero uno deshace los colores del viewport (post-calc) y el
otro deshace los cambios de props que hizo el auto-fix.

**Fix [doc]:** ya documentado en tutorial v3 sección 15 / 16. Mantener.

---

## Resumen priorizado

### 🔴 CRÍTICAS (3) — 3/3 resueltas ✅
- ✅ **#8 "Diagnóstico" botón ambiguo** — ya renombrado a "Reporte de errores"
- ✅ **#10 Combinaciones ULS/SLS crípticas** — items ya con labels legibles
- ✅ **#1 Plataforma vs bandeja** — bloque conceptual + tabla en TUTORIAL §7 (v0.7.13)

### 🟠 MEDIAS (8) — 8/8 resueltas ✅
- ✅ **#2 catálogos ambiguos** — labels visibles renombrados (v0.7.13)
- ✅ **#3 dos catálogos sin distinguir** — etiquetas (horizontal)/(vertical) (v0.7.13)
- ✅ **#4 "Diagonales horizontales (plano)"** — renombrado a "Cruces en planta…" (v0.7.13)
- ✅ **#9 Q1-Q6 sin descripción inline** — descripción ya se muestra
- ✅ **#7 auto-update sin avisar costes** — aviso de coste en TUTORIAL §4.5 (v0.7.13)
- ✅ **#13 subdivisión cruces sin contexto** — referencia a `anim_subdivisions_zoom.webp` en §8.2 (v0.7.13)
- ✅ **#14 patrón cruces FRONT/BACK sin tooltip** — bloque "convención del addon" + ref a `anim_brace_cycle.webp` en §8.2 (v0.7.13)
- ✅ **#16 catálogo Ringlock sin contexto** — nota explícita en §7.3 ("herramienta de referencia, no afecta a generación") (v0.7.13)
- ✅ **#19 botón "Auditoría bandejas" sin contexto** — nota sobre dónde mira el resultado (consola + panel) en §7.3 (v0.7.13)

### 🟡 BAJAS (7) — 7/7 resueltas ✅
- ✅ **#17 Indicador escalera "P0/P1"** — ya nombrado `Andamio_LadderHandle_NN`
- ✅ **#5 closed_loop** — tooltip ampliado en §5.1 (v0.7.13)
- ✅ **#6 use_terrain_z + base_z** — bloque "qué es Z" + explicación husillo en §6.4 (v0.7.13)
- ✅ **#11 Generar/Actualizar** — microcopia "¿cuándo pulsarlo?" en §4.4 (v0.7.13)
- ✅ **#12 husillo** — definición inline + glosario visual §19.5 (v0.7.13)
- ✅ **#15 anclaje vs tie** — sección 10.3 "Prefijos en el outliner — qué significa cada nombre" (v0.7.13)
- ✅ **#20 dos botones de "deshacer"** — tabla comparativa "Restaurar colores" vs "Revertir auto-corrección" en §15 (v0.7.13)
- ✅ **#18 Color "Anclajes"** — ya estaba ✓ sin acción (sin cambios)

---

## Estado de los fixes (snapshot 2026-05-03 / v0.7.13)

**Resueltos en código (7 issues):** #2, #3, #4, #8, #9, #10, #17. De estos,
#8/#9/#10/#17 estaban resueltos **antes** de la sesión 2026-05-03 (la
auditoría 2026-05-02 no estaba al día); #2/#3/#4 se resolvieron **en**
2026-05-03 cambiando los labels visibles del enum sin tocar las claves
internas para preservar la compatibilidad con .blend guardados.

**Resueltos en documentación (13 issues, Fase G — TUTORIAL.md, v0.7.13):**
#1, #5, #6, #7, #11, #12, #13, #14, #15, #16, #19, #20. Todos cerrados con
microcopia inline + nueva sección §10.3 (prefijos del outliner) + nueva
sección §19 (Glosario visual) que asocia cada concepto con su asset
existente en `tutorial/assets/`.

**Total resueltos:** 20/20 issues identificados originalmente. La auditoría
2026-05-02 se cierra completa con el release v0.7.13.

## Próxima auditoría (a hacer en futura sesión)

Re-auditar el addon con un usuario novato real (o simulado) sobre la
v0.7.13 para detectar la siguiente capa de fricciones. Posibles focos:
- El sub-panel "Auto-corrección" — flujo aún confuso para quien no entiende
  la diferencia entre re-diseñar y re-comprobar.
- La sección "Colores" — 10 sliders sin agrupación visual.
- El catálogo de presets de fabricante — ¿cuál elijo si no conozco Layher?
- El visor 3D del tutorial HTML (`tutorial/index.html`) — pendiente de
  cubrir con tooltips equivalentes en la web.
