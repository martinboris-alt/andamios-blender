# Auditoría — Incoherencias del addon explicado a un novato

> Versión auditada: **0.7.12** · Fecha: 2026-05-02
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

## 2 · `bay_length_catalog` con tres valores ambiguos 🟠 [both]

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

---

## 3 · `pole_length_catalog` y `bay_length_catalog` 🟠 [doc]

Hay **DOS catálogos distintos** en el panel:
- `bay_length_catalog` — catálogo de longitudes de **vanos** (largo entre postes)
- `pole_length_catalog` — catálogo de longitudes de **piezas de poste** (cómo se segmenta el tubo vertical)

Un novato verá "Catálogo de longitudes" y "Catálogo postes" sin entender
que se aplican a dos cosas distintas (horizontal vs vertical).

**Fix propuesto [doc]:** renombrar etiquetas en el panel:
- `"Catálogo de longitudes"` → `"Catálogo vanos (horizontal)"`
- `"Catálogo postes"` → `"Catálogo postes (vertical)"`

---

## 4 · "Diagonales horizontales (plano)" 🟠 [both]

**Confusión:** el toggle `add_horizontal_braces` se llama "Diagonales
horizontales (plano)". Para un novato suena contradictorio: ¿una diagonal
horizontal? ¿En qué plano?

Se refiere a una **diagonal en el plano del deck** (rigidiza torsión).
Pero "plano" en castellano puede significar "alzado" o "plana" u "horizontal".

**Fix propuesto [code]:** renombrar a:
`"Cruces en planta (rigidizan torsión)"` o
`"Diagonales en plano del piso"`.

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

## 8 · Botón "Diagnóstico" en panel principal 🔴 [code]

**Confusión:** el panel principal tiene una sección "Diagnóstico" con
botón "Exportar informe". El nombre puede confundir con
**"Comprobar modelo"** del cálculo (que también valida geometría) o con
"Diagnóstico narrativo de fallos" (que aparece tras `calc_run`).

**Fix propuesto [code]:** renombrar la sección a
`"Reporte de errores"` y el botón a
`"Exportar log para depurar"`. Aclara que se usa solo cuando Blender
ha fallado / se ha cerrado.

---

## 9 · Clases de servicio Q1..Q6 sin explicación inline 🟠 [doc]

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

---

## 10 · Combinación de cargas con códigos crípticos 🔴 [doc]

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

## 17 · Indicador de escalera "P0/P1" confunde con path_points 🟡 [code]

**Confusión:** en el modo manual de escaleras, cada slot tiene un campo
"Pos" que es un slider 0..1 y un "Indicador" que es un Empty visible.
Estos empties también se llaman P0, P1... como los path_points
principales.

**Fix [code]:** prefijar los indicadores de escalera con `LdrInd_` para
no confundir con los path_points (que son `P0`, `P1`...).

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

### 🔴 CRÍTICAS (3)
- **#1 Plataforma vs bandeja** — clarificar conceptualmente con animación
- **#8 "Diagnóstico" botón ambiguo** — renombrar para no confundir con cálculo
- **#10 Combinaciones ULS/SLS crípticas** — traducir nombres del enum

### 🟠 MEDIAS (8)
- #2, #3, #4 nombres de catálogos / toggles confusos
- #7 auto-update sin avisar costes
- #9 Q1-Q6 sin descripción inline
- #13, #14 patrones de cruces sin tooltip visual
- #16, #19 catálogos / botones sin contexto

### 🟡 BAJAS (6)
- #5, #6, #11, #12, #15, #17, #20 microcopia y tooltips

---

## Acciones recomendadas

1. **[code]** Fix #8 (renombrar "Diagnóstico" → "Reporte de errores") y
   #10 (descripciones inline en combos)
2. **[code]** Mostrar descripción del Q seleccionado bajo el dropdown (#9)
3. **[doc]** Animaciones comparativas para #2, #13, #14
4. **[doc]** Tooltips/descripciones en panel para #4, #6, #7, #11, #12, #14, #19
5. **[doc]** Sección "Glosario visual" en el tutorial: hover en término →
   imagen al lado
