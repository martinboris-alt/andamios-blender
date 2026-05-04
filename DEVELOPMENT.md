# Andamios A→Polilínea — Documentación de desarrollo

Documento maestro para reconstruir el addon desde cero. Versión 0.2.x (abril 2026).

---

## 1. Objetivo

Addon de Blender en Python que **genera de forma procedural** un andamio paramétrico a lo largo de una **polilínea 3D** definida por empties. Soporta esquinas con cálculo geométrico exacto, plataformas estandarizadas, escaleras inclinadas con trampillas, regeneración automática y, en el roadmap, un módulo de cálculo estructural según Eurocódigo.

Ubicación: `Escritorio/addon para crear andamios/andamios_addon.py`.

---

## 2. Estructura del archivo

Un único archivo Python (`andamios_addon.py`). Secciones en orden:

1. `bl_info` y constantes (`SCAFFOLD_COLLECTION`, `TUBE_DIAM`, `PLANK_THICKNESS`, `TOEBOARD_HEIGHT`).
2. **Helpers de geometría**: `_ensure_collection`, `_clear_collection`, `_make_tube`, `_make_box`, `_make_quad_plank`, `_ladder`, `_make_trapdoor_lid`, `_make_hinge_marker`.
3. **Materiales**: `_MATERIAL_COLORS`, `_get_category_material`, `_apply_category_materials`.
4. **Generador**: `_path_objects`, `_compute_path_geometry`, `generate_scaffold`, `_format_summary`.
5. **Auto-update handler**: `_auto_deferred_regen`, `_auto_on_depsgraph`, `_auto_register`, `_auto_unregister`, `_on_auto_update_toggle`, globals `_AUTO_BUSY`, `_AUTO_PENDING`, `_AUTO_LAST`.
6. **Properties**: `ANDAMIOS_PathPoint`, `ANDAMIOS_Props`.
7. **Operadores**: `ANDAMIOS_OT_path_add`, `ANDAMIOS_OT_path_remove`, `ANDAMIOS_OT_path_move`, `ANDAMIOS_OT_generate`, `ANDAMIOS_OT_clear`, `ANDAMIOS_OT_export_bom`.
8. **UI**: `ANDAMIOS_UL_path`, `ANDAMIOS_PT_panel`.
9. `register()` / `unregister()` y bloque `__main__`.

Cuando crezca lo suficiente, refactorizar en paquete con módulos separados (geometry, ladders, decks, props, ops, ui, materials, auto_update). Por ahora, archivo monolítico para facilitar la edición.

---

## 3. Constantes globales

```python
SCAFFOLD_COLLECTION = "Scaffold"   # nombre de la colección raíz
TUBE_DIAM = 0.0489                 # 48.3 mm tubo estándar de andamio
PLANK_THICKNESS = 0.04             # grosor bandeja
PLANK_WIDTH = 0.32                 # ancho bandeja (DEPRECATED, ver props.deck_plank_width)
TOEBOARD_HEIGHT = 0.15             # altura rodapié
```

Nombres de sub-colecciones (mismas que las claves de `_MATERIAL_COLORS`):

| Sub-colección | Contenido | Color |
|---|---|---|
| Postes | Tubos verticales en cada nodo | Azul acero `(0.20, 0.45, 0.85)` |
| Travesaños | Tubos longitudinales y transversales por planta | Azul claro `(0.40, 0.65, 0.95)` |
| Plataformas | Bandejas (1..N por vano) + decks de esquina | Marrón madera `(0.55, 0.35, 0.15)` |
| Cruces | Diagonales de arriostramiento alternando bays/plantas | Naranja `(0.95, 0.45, 0.10)` |
| Escaleras | Rieles + peldaños, una por bay/planta | Rojo `(0.85, 0.15, 0.15)` |
| Barandillas | Top + mid + rodapiés (front + back) | Amarillo seguridad `(1.00, 0.85, 0.00)` |
| Trampillas | Lid (tapa) + 2 hinge markers por hueco | Verde `(0.20, 0.70, 0.30)` |

---

## 4. Modelo de datos

### 4.1 Trayectoria (polilínea)

`ANDAMIOS_PathPoint(PropertyGroup)` envuelve un `PointerProperty(type=bpy.types.Object)`. Se requiere envolver en un PropertyGroup porque `CollectionProperty` no acepta `PointerProperty` a `bpy.types.Object` directamente.

```python
class ANDAMIOS_PathPoint(PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object, name="Punto")
```

`ANDAMIOS_Props` mantiene `path_points: CollectionProperty(type=ANDAMIOS_PathPoint)` y un `active_path_index: IntProperty` para la UIList.

### 4.2 Properties principales

| Propiedad | Tipo | Default | Rango | Significado |
|---|---|---|---|---|
| `path_points` | Collection | `[]` | — | Vértices de la polilínea (mín. 2) |
| `active_path_index` | Int | 0 | ≥0 | Índice activo en la UIList |
| `floor_count` | Int | 2 | 1–20 | Nº de plantas |
| `floor_height` | Float | 2.0 m | 1.0–4.0 | Altura por planta |
| `scaffold_depth` | Float | 0.732 m | 0.3–2.0 | Profundidad bay (perp) |
| `section_length` | Float | 2.5 m | 0.5–4.0 | Longitud objetivo de cada vano |
| `base_z` | Float | 0.0 m | — | Z del pie del andamio |
| `add_decks` | Bool | True | — | Generar bandejas |
| `deck_planks_count` | Int | 3 | 1–6 | Nº de bandejas por vano |
| `deck_plank_width` | Float | 0.32 m | 0.15–0.50 | Ancho estandarizado de bandeja |
| `guardrails` | Bool | True | — | Barandillas + rodapié |
| `add_braces` | Bool | True | — | Cruces diagonales |
| `add_ladders` | Bool | True | — | Escaleras + trampillas |
| `ladder_every` | Int | 3 | 1–20 | Una escalera cada N vanos |
| `ladder_length` | Float | 2.5 m | 1.5–5.0 | Longitud estándar de escalera (la inclinación se calcula) |
| `auto_update` | Bool | False | — | Regenerar al mover los puntos (toggle con callback) |
| `last_summary` | String | "" | — | Texto del resumen mostrado en el panel |

### 4.3 Pipeline de generación

```
generate_scaffold(props, context)
  ├─ _compute_path_geometry(props)
  │     → P, forwards, perps, seg_lens, front_corners, back_corners
  ├─ Calcular bays por segmento (seg_bays[i] = ceil(seg_len[i] / section_length))
  ├─ Construir nodes_front[], nodes_back[], bay_segment[], is_corner[]
  ├─ _clear_collection("Scaffold") y crear sub-colecciones
  ├─ Calcular tilt_dx = sqrt(L²-h²) y _ladder_dirn helper (lean direction zig-zag opcional, hoy +1 fijo)
  ├─ 1) Postes en cada nodo (front + back)
  ├─ 2) Por planta f en 1..floor_count:
  │     ├─ Travesaños longitudinales (front + back, por bay)
  │     ├─ Travesaños transversales (front-back en cada nodo)
  │     ├─ Bandejas (sólido o pierced) y deck de esquina
  │     └─ Barandillas top + mid + rodapiés (front + back)
  ├─ 3) Cruces diagonales (alternando bays/plantas en el front row)
  ├─ 4) Escaleras inclinadas (1 por bay/planta) con tapa + hinge markers
  └─ 5) _apply_category_materials(root)
  → return stats dict
```

---

## 5. Geometría: polilínea con esquinas

### 5.1 Convención del lado

`perp = Vector((-fwd.y, fwd.x, 0)).normalized()` ⇒ "perp" apunta a la izquierda del avance (+90° CCW). El andamio se construye sobre el lado **+perp** del recorrido (cara opuesta al edificio si recorres en sentido horario).

### 5.2 Esquinas — fórmula de la bisectriz

En cada vértice interior `Pi`, la posición del **poste trasero** se calcula con:

```python
n1, n2 = perps[i-1], perps[i]
cos_a = forwards[i-1] · forwards[i]
cos_half = sqrt((1 + cos_a) / 2)            # mitad del ángulo de giro
bis = (n1 + n2).normalized()
back_corner_i = Pi + bis * (depth / cos_half)
```

Esto garantiza distancia perpendicular = `depth` desde **ambos** segmentos adyacentes simultáneamente. Verificación: para giro 90°, `cos(45°) ≈ 0.707`, `depth/cos_half ≈ depth·√2`, offset diagonal en NE/SE/SW/NW.

Endpoints (`i=0` o `i=n_segs`): solo offset perpendicular del segmento adyacente único.

### 5.3 Subdivisión de segmentos

Para segmento `i` de longitud `L_i`:

```python
bay_count_i = max(1, ceil(L_i / section_length))
bay_len_i = L_i / bay_count_i
```

Cada bay intermedio se calcula por **interpolación lineal** entre `front_corners[i]` y `front_corners[i+1]` (y entre los back_corners). Como ambos endpoints están a distancia perpendicular `depth` del segmento, los nodos intermedios también lo están (la línea que une dos puntos a la misma distancia perpendicular de un segmento es paralela a él).

### 5.4 Nodos y bays globales

Tras construir `nodes_front[]` y `nodes_back[]` (longitud `n_nodes = sum(bay_count_i) + 1`):

- `n_bays = n_nodes - 1`
- `bay_segment[k]` = índice del segmento de la polilínea al que pertenece el bay `k`
- `is_corner[k]` = `True` si el nodo `k` corresponde a un vértice de la polilínea (incluyendo endpoints)

Un nodo "corner" siempre lleva un poste con sufijo `_FC_`/`_BC_` en lugar de `_F_`/`_B_`.

---

## 6. Bandejas (decks) estandarizadas

### 6.1 Vano normal

`N = props.deck_planks_count` bandejas centradas en el bay (perp), cada una con ancho `props.deck_plank_width`. La perpendicular de cada plank `k`:

```python
plank_perp = -N*plank_w/2 + (k + 0.5) * plank_w
```

Si `[plank_perp ± plank_w/2]` excede `[-depth/2, +depth/2]`, la bandeja se omite (sin clipping a ancho no estándar).

Cada bandeja: `_make_box(center, (bay_len-0.01, plank_w-0.005, PLANK_THICKNESS), ..., rotation_z=yaw)`.

### 6.2 Vano con trampilla (pierced)

Para cada plank `k`, si su rango perp solapa con el hueco (`[hyL, hyR]`), se parte en 2 segmentos:

- `_a`: forward `[-bay_len/2, hxL]`
- `_b`: forward `[hxR, +bay_len/2]`

Si no solapa, plank completo. Esto evita bandejas no estándar y mantiene la regla "cada bandeja es estandarizada".

### 6.3 Deck de esquina

En cada vértice interior se añade un cuadrilátero con `_make_quad_plank` que rellena la zona triangular/cuadrilateral entre los dos bays adyacentes. Vertices:

- A = `nodes_front[k]` (= `Pi`)
- B = A + `perps[seg_in] * depth`
- C = `nodes_back[k]` (offset bisectriz)
- D = A + `perps[seg_out] * depth`

Para 90° forma un cuadrado de `depth × depth`; para otros ángulos, un cuadrilátero general convexo.

---

## 7. Trampillas y escaleras

### 7.1 Geometría inclinada con longitud estándar

`tilt_dx = sqrt(L² - floor_h²)` donde `L = props.ladder_length`. Inclinación = `asin(floor_h / L)`.

Ejemplos:
- `L=2.5`, `h=2` → `tilt_dx=1.5` m, ángulo ≈ 53° (más tendido)
- `L=2.2`, `h=2` → `tilt_dx≈0.92` m, ángulo ≈ 65°
- `L=3.0`, `h=2` → `tilt_dx≈2.24` m, ángulo ≈ 42°

### 7.2 Posicionamiento

Para cada bay `i ∈ ladder_bays` y cada planta `f_idx ∈ [0, floor_count)`:

```python
d = _ladder_dirn(f_idx)   # actualmente +1 fijo (sin zig-zag)
bot_xy = bay_center - fwd * (d * tilt_dx/2)
top_xy = bay_center + fwd * (d * tilt_dx/2)
```

`side_axis = perps[seg]` ⇒ rieles separados en perp, **peldaños transversales** al recorrido (cruzando el bay de delante atrás).

### 7.3 Trampilla apilada (no zig-zag)

`_ladder_dirn(n) = 1.0` siempre. Las trampillas de todas las plantas quedan en el mismo `forward x` (apiladas). Esto puede revisarse a una versión zig-zag en el futuro cambiando solo la función `_ladder_dirn`.

### 7.4 Hueco y bisagra

Para `dirn = +1`:
- `free_edge_x = +tilt_dx/2` (donde llega el riel superior)
- `hinge_local_x = free_edge_x - h_a` (al -fwd del hueco)
- `hole_cx = (free_edge_x + hinge_local_x) / 2 = +(tilt_dx-h_a)/2`
- Hueco `[hxL, hxR] = [hinge_local_x, free_edge_x]` con anchura `h_a`

La bisagra está al lado **opuesto** a la inclinación de la escalera (regla: "tapa abre opuesta a la subida"). Cuando se abre 85°, el borde libre se aleja del operario que sube. `LADDER_GRIP_EXT = 0.0` ⇒ los rieles **no sobresalen** del nivel del deck (para que la tapa pueda cerrar).

### 7.5 Marcadores de bisagra

Dos cilindros cortos (knuckles) en el eje de la bisagra, a ±30 % del lado largo. Indican visualmente la dirección de apertura del lid.

---

## 8. Barandillas y rodapiés

### 8.1 Barandillas

Por planta: dos rieles horizontales en la fila front y dos en la back, a alturas `z + 0.5 m` (mid) y `z + 1.0 m` (top). Diámetro `TUBE_DIAM × 0.85` (más finos que los travesaños).

### 8.2 Rodapiés

Al pie de cada planta (entre el deck y la altura `TOEBOARD_HEIGHT`): cajas finas de 0.025 m de espesor, longitud **completa = bay_len** (sin restar 0.05). El back rodapié usa `back_len = ‖nodes_back[i+1] - nodes_back[i]‖` y `back_yaw = atan2(back_dir.y, back_dir.x)` para seguir la línea trasera (que en esquinas tiene un kink debido a la bisectriz).

Esto cierra los gaps de 5 cm en las esquinas que aparecían con la versión anterior.

---

## 9. Auto-update

### 9.1 Handler

`_auto_on_depsgraph(scene, depsgraph)` registrado en `bpy.app.handlers.depsgraph_update_post`. Lógica:

1. Si `_AUTO_BUSY` o `_AUTO_PENDING` → ignorar (re-entrancia).
2. Si `props.auto_update` False → ignorar.
3. Calcular `_path_signature(props)` (tuple de posiciones de todos los path_points).
4. Si la firma no cambió → ignorar.
5. Marcar `_AUTO_PENDING = True` y registrar timer `bpy.app.timers.register(_auto_deferred_regen, 0.0)`.

### 9.2 Timer diferido

`_auto_deferred_regen()` se ejecuta en el siguiente tick (no dentro del handler, donde modificar `bpy.data` es arriesgado). Dentro pone `_AUTO_BUSY = True`, llama `generate_scaffold`, escribe `last_summary` y libera el flag.

### 9.3 Toggle callback

Cuando el usuario activa/desactiva `auto_update`, se invoca `_on_auto_update_toggle(self, context)` que resetea `_AUTO_LAST` y, si se activó con ≥2 puntos, dispara una regeneración inmediata.

### 9.4 Limpieza de handlers obsoletos

Recargar el addon (exec del archivo) deja handlers viejos enganchados. Para limpiar manualmente:

```python
for h in list(bpy.app.handlers.depsgraph_update_post):
    if getattr(h, "__name__", "") == "_auto_on_depsgraph":
        bpy.app.handlers.depsgraph_update_post.remove(h)
```

---

## 10. UI

### 10.1 Panel `ANDAMIOS_PT_panel`

Sidebar `View3D > Andamios`. Secciones:

1. **Trayectoria (polilínea)**: UIList con +/- /↑/↓ y botón "cursor" para crear empty en la posición del cursor 3D. `Z base`.
2. **Dimensiones**: section_length, scaffold_depth, floor_count, floor_height.
3. **Componentes**: add_decks (+ deck_planks_count + deck_plank_width), guardrails, add_braces, add_ladders (+ ladder_every + ladder_length).
4. **Botones**: Generar/Actualizar (icon `FILE_REFRESH`), Borrar, Exportar BOM (CSV).
5. **Auto-actualizar al mover la trayectoria** (icon `AUTO`).
6. **Resumen** (si hay): texto multi-línea con stats.

### 10.2 UIList `ANDAMIOS_UL_path`

Cada entrada: label `Pn` (icon `EMPTY_AXIS`) + prop `obj` (PointerProperty selector).

---

## 11. Operadores

| `bl_idname` | Clase | Función |
|---|---|---|
| `andamios.path_add` | `ANDAMIOS_OT_path_add` | Añade un slot a la polilínea. Con `at_cursor=True`, crea un empty en el cursor 3D y lo enlaza. |
| `andamios.path_remove` | `ANDAMIOS_OT_path_remove` | Elimina el slot activo. |
| `andamios.path_move` | `ANDAMIOS_OT_path_move` | Reordena el slot activo (UP/DOWN). |
| `andamios.generate` | `ANDAMIOS_OT_generate` | Llama `generate_scaffold`, captura excepciones, escribe `last_summary`. |
| `andamios.clear` | `ANDAMIOS_OT_clear` | Borra la colección `Scaffold`. |
| `andamios.export_bom` | `ANDAMIOS_OT_export_bom` | CSV con conteos por sub-colección (modal con file dialog). |

Helpers internos: `_new_empty(name, location, scene_collection)`, `_next_point_name(props)`.

---

## 12. Helpers de geometría (función a función)

### `_ensure_collection(name, parent=None)`
Crea/obtiene una `bpy.types.Collection` con el nombre dado y la enlaza bajo `parent` (default = `scene.collection`).

### `_clear_collection(name)`
Recursivo. Elimina sub-colecciones, objetos y la propia colección. **Bug-fix histórico**: la versión 0.1 hacía `bpy.data.collections.remove(child)` después de la llamada recursiva, generando `ReferenceError: StructRNA of type Collection has been removed`. Solución: dejar que la recursión limpie cada hijo y el bucle del padre solo itera.

### `_make_tube(p1, p2, diameter, name, coll)`
Crea un cilindro entre dos puntos del mundo. 12 segmentos. Usa quaternion para alinear `+Z` local con la dirección. Si `length < 1e-6`, retorna `None`.

### `_make_box(center, size, name, coll, rotation_z=0)`
Caja rectangular. Crea cubo unidad, escala con `bmesh.ops.scale`, rota en `Z` con `rotation_euler`.

### `_make_quad_plank(quad_xy, name, coll, thickness, z_top)`
Plank de 4 vértices arbitrarios (proyección XY) con grosor vertical. Usado para decks de esquina.

### `_ladder(p_bot, p_top, width, rung_count, name, coll, side_axis=None)`
Crea 2 rieles + N peldaños entre dos puntos del mundo. `side_axis` define la dirección del eje sobre el que se separan los rieles (perpendicular al eje de subida). Si `None`, calcula automáticamente.

### `_make_trapdoor_lid(hinge_world, hinge_dir_xy, away_dir_xy, length, width, thickness, open_angle_rad, name, coll)`
Crea una tapa rectangular con una rotación pre-aplicada al mesh: la tapa nace en su posición abierta. `obj.location = hinge_world`. Para cerrarla, se podría rotar el objeto ±open_angle (no implementado como animación).

### `_make_hinge_marker(hinge_world, hinge_axis_xy, lid_length, name, coll)`
Dos cilindros cortos (60 mm × 35 mm Ø) en el eje de la bisagra a ±30 % del lado largo. Visibles para indicar dirección de apertura.

---

## 13. Materiales y colores

Diccionario `_MATERIAL_COLORS` mapea cada nombre de sub-colección a un color RGBA. `_get_category_material(category)` crea/obtiene un `bpy.data.materials` llamado `"Andamio_<categoria>"` con `diffuse_color` y `BSDF.Base Color` actualizados. `_apply_category_materials(root)` lo asigna a todos los objetos de cada sub-colección al final de `generate_scaffold`.

Los materiales se reutilizan entre regeneraciones; cambiar `_MATERIAL_COLORS` y volver a generar actualiza todas las piezas.

Para verlo en el viewport:
```python
sp.shading.type = 'SOLID'
sp.shading.color_type = 'MATERIAL'
```

---

## 14. Decisiones de diseño (log)

### Decisión 1: empties como vértices de polilínea (no Curve)
**Justificación**: en andamios reales las esquinas son rectas, no arcos. Un objeto Curve añade complejidad sin valor. Los empties son fáciles de mover puntualmente y trabajar con el handler de `depsgraph_update_post`.

### Decisión 2: bisectriz exacta en esquinas (no perp simple)
**Justificación**: usar `depth` perpendicular al segmento entrante deja un gap en el saliente. La fórmula de bisectriz garantiza distancia perpendicular `depth` a ambos segmentos.

### Decisión 3: timer diferido para auto-update
**Justificación**: modificar `bpy.data` dentro de un handler `depsgraph_update_post` es inestable. El timer mueve la regeneración al siguiente tick, donde es seguro.

### Decisión 4: zig-zag descartado para escaleras
**Justificación**: el usuario probó zig-zag (escaleras alternando dirección) pero pidió volver a apilar las trampillas. Con zig-zag, la base de la escalera N+1 queda exactamente sobre el hueco que la siguiente cierra ⇒ violación de la regla de seguridad. Apilar deja todas las trampillas en el mismo XY del bay.

### Decisión 5: rieles sin extensión sobre el deck
**Justificación**: el usuario indicó que los rieles no deben sobresalir para que la tapa pueda cerrar. `LADDER_GRIP_EXT = 0.0`. La pérdida de "agarre" se asume aceptable: el operario usa los rieles laterales del andamio.

### Decisión 6: bandejas estandarizadas vs single-box
**Justificación**: una caja única no representa la realidad (las bandejas son piezas estandarizadas que se colocan adyacentes). Refactor: N bandejas centradas en perp con ancho fijo. Si solapan con un hueco, se parten en 2 segmentos forward, sin perder ancho estándar.

### Decisión 7: rodapié = bay_len completo (sin restar 5 cm)
**Justificación**: la versión 0.1 restaba 5 cm para clearance del poste. Esto generaba un gap visible en esquinas. Solución: longitud completa, asumiendo intersección visual mínima con el poste (de Ø49 mm).

### Decisión 8: longitud de escalera estandarizada → tilt variable
**Justificación**: andamio real usa escaleras de longitud fija; el ángulo varía según la altura entre plantas. Calcular `tilt_dx = sqrt(L² - h²)` desde `props.ladder_length` y `props.floor_height`.

### Decisión 9: monolítico hasta superar ~1500 LOC
**Justificación**: refactorizar a paquete antes de tiempo añade fricción. El archivo único cabe en una pestaña del editor y permite búsqueda rápida.

---

## 15. Roadmap

### Geometría (corto plazo)
- [x] Polilínea con N puntos
- [x] Esquinas con bisectriz
- [x] Trampillas + escaleras inclinadas + tapas
- [x] Bisagras visibles indicando dirección de apertura
- [x] Bandejas estandarizadas (N planks por vano)
- [x] Rodapiés sin gap en esquinas
- [ ] Bandejas con longitud estandarizada (snap a 1.5/2.0/2.5/3.0 m + pieza de compensación)
- [ ] Rodapié dedicado para corner deck (cubre el perímetro de la pieza de esquina)
- [ ] Ladders en zig-zag opcional (toggle en props)
- [ ] Polilínea cerrada (loop)

### Estructural (medio plazo)
Ver sección 16.

### Misc (largo plazo)
- [ ] BOM más detallado (longitudes, no solo conteos)
- [ ] Soporte para anclajes a fachada (ties con coaccion)
- [ ] Husillos de base con altura variable
- [ ] Mallas/lonas como objetos con coeficiente φ para viento

---

## 16. Módulo de cálculo estructural (futuro)

Sub-carpeta `calc/` paralela a `andamios_addon.py`.

**Decisiones tomadas**:
- Solver: PyNite (`pip install PyNiteFEA`), wrapper `solver.py` permite cambio a OpenSeesPy.
- Anejo Nacional: España por defecto; configurable.
- Tipo prioritario: andamio de fachada multidireccional (EN 12810).
- Catálogo: genérico con valores conservadores; extensible vía dict de fabricantes.

**Estructura**:
```
calc/
├── __init__.py
├── extract_model.py     # geometría addon → grafo nodos/barras
├── materials.py         # S235JR, S355: fy, fu, E, G, ν, ρ
├── sections.py          # CHS Ø48.3×3.2: A, I, Wel, Wpl, i, clase
├── joints.py            # Cφ por tipo de unión, EN 74 capacities
├── loads/
│   ├── self_weight.py
│   ├── service_load.py  # clases EN 12811-1
│   ├── wind.py          # EN 1991-1-4
│   ├── snow.py
│   └── imperfections.py
├── combinations.py      # 6.10 EN 1990
├── solver.py            # wrapper PyNite
├── checks/
│   ├── en1993_1_1.py    # 6.2 + 6.3.1 + 6.3.3
│   ├── en12811.py
│   └── joints.py        # EN 74
├── viewport.py          # gradiente verde/amarillo/rojo
├── report.py            # HTML jinja2 → opcional PDF
├── ui.py                # panel "Cálculo"
└── tests/
    ├── test_portico_simple.py
    └── test_pieper_kohler.py
```

**Plan por fases**:
1. `extract_model.py` + `solver.py` (lineal) + test pórtico isostático.
2. `materials.py` + `sections.py` + cargas G y Q.
3. Viento EN 1991-1-4 + imperfecciones + combinaciones.
4. Comprobaciones EN 1993 + EN 12811 + EN 74.
5. Viewport + report HTML + UI panel + validación con ejemplo de bibliografía.

---

## 17. Cómo recrear desde cero

1. Crear `andamios_addon.py` con `bl_info` (Blender 3.0+, category Add Mesh).
2. Definir `ANDAMIOS_PathPoint(PropertyGroup)` con `obj: PointerProperty(type=bpy.types.Object)`.
3. Definir `ANDAMIOS_Props(PropertyGroup)` con todas las properties de §4.2.
4. Implementar helpers de geometría (§12).
5. Implementar `_compute_path_geometry` (§5).
6. Implementar `generate_scaffold` siguiendo el pipeline de §4.3.
7. Añadir auto-update con timer diferido (§9).
8. Implementar operadores (§11) y panel (§10).
9. Implementar materiales (§13).
10. `register()` con `_auto_register()`, `unregister()` con `_auto_unregister()`.
11. Bloque `if __name__ == "__main__": register()` para `Run Script` desde el editor de texto de Blender.

Validación mínima:
- Crear 4 empties en (0,0,0), (8,0,0), (8,-6,0), (0,-6,0).
- Añadirlos a `path_points`.
- Generar.
- Verificar 11 vanos, 2 esquinas, postes en (0,0), (8,0), (8,-6), (0,-6) front y (0,0.732), (8.732,0.732), (8.732,-6.732), (0,-6.732) back.

---

## 18. Convenciones del código

- Nombres de variables locales en deck-local frame: `xL`, `xR`, `yL`, `yR` (bay), `hxL`, `hxR`, `hyL`, `hyR` (hueco).
- Sufijos de objeto: `_F` front-row pole intermedio, `_FC` front-row corner pole, `_B` back-row pole, `_BC` back-row corner pole, `_p<k>` plank index `k` (sólido), `_p<k>a`/`_p<k>b` segmentos de plank partido.
- Trapdoor: `Lid_F<f>_<bay:03d>` para la tapa, `Hinge_F<f>_<bay:03d>_L`/`_R` para los knuckles.
- Coords del cúmulo deck-local: `forward = +x`, `perp = +y`, `up = +z`.
- `bay_center` (en world) siempre apunta al centro geométrico del rectángulo del deck.

---

## 19. Glosario

| Término | Definición |
|---|---|
| **Vano (bay)** | Tramo entre dos postes consecutivos a lo largo de la polilínea |
| **Tramo (segment)** | Recta entre dos vértices consecutivos de la polilínea |
| **Front row** | Fila de postes pegada a la trayectoria (`perp = 0` en deck-local) |
| **Back row** | Fila de postes a `depth` del front row (`perp = depth` en deck-local) |
| **Bandeja (plank)** | Plataforma estandarizada (típico 0.32 m de ancho) |
| **Trampilla** | Hueco en el deck por el que pasa la escalera |
| **Lid (tapa)** | Plank con bisagra que cubre la trampilla |
| **Borde de cierre / free edge** | Lado del lid opuesto a la bisagra (donde llega el riel de la escalera) |
| **Hinge edge** | Lado del lid donde está la bisagra |
| **Knuckle** | Cilindro corto que representa una sección de la bisagra |
| **Tilt_dx** | Distancia horizontal recorrida por la escalera al subir un piso |
| **Bisectriz** | Vector que divide en dos partes iguales el ángulo entre dos segmentos consecutivos en una esquina |

---

## 20. Errores conocidos / cuidados

- **Recargar el addon vía `exec`** deja handlers viejos. Limpieza manual necesaria (§9.4).
- **`PointerProperty` a Object dentro de un `CollectionProperty`**: requiere envolver en un `PropertyGroup` (`ANDAMIOS_PathPoint`).
- **`bpy.ops.view3d.view_selected`** dentro de un `temp_override` mueve el viewport. Si los empties están seleccionados al hacerlo, NO se mueven (la op solo cambia la cámara), pero a veces el usuario los mueve manualmente entre llamadas MCP y la geometría regenerada cambia.
- **`floor_count = 5`** con `LADDER_LENGTH = 2.5` y `bay_len = 2.0` deja la base de la escalera N+1 en el borde del hueco que cierra. Considérese ajustar `ladder_length` a 2.2 para más holgura.
- **Anchura de bandejas**: con `depth = 0.732` solo caben 2 bandejas de 0.32 m. Para 3 bandejas (1 m de paso), aumentar `scaffold_depth` a ~1.10 m.
- **Trampilla sobre esquinas**: si `bay 0` cae en una esquina y `ladder_every = 1`, la geometría del hueco puede degenerar (corner deck + hueco no encajan limpiamente). Mantener `ladder_every ≥ 3` por ahora.

---

## 21. Puntos de mejora geométrica pendientes

Lista exhaustiva de detalles por pulir. Severidad: **C** cosmético, **F** funcional, **S** seguridad, **E** estructural. Esfuerzo: **S** pequeño (≤1 día), **M** medio (≤1 semana), **L** grande (>1 semana).

### 21.1 Postes

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 1 | C/S | M | Postes son cilindros continuos. Reales = segmentos de 1/2/3/4 m con manguito de empalme | ✅ **v0.2.7** — `_emit_pole_stack` con segmentación + manguito Ø115% a cada empate. Prop `pole_segment_length` (0 = continuo) |
| 2 | F | M | Falta **husillos de base** (jack base con plato) | ✅ **v0.2.4** — `_make_jack_base` + `props.jack_height` |
| 3 | C/S | M | Sin **acoples** en nodos (cup-lock, ringlock, wedge) | ✅ **v0.2.7** — `_make_rosette` Ø130 mm × 10 mm en cada nodo × planta. Sub-collección `Acoples`. Prop `add_rosettes` |

### 21.2 Travesaños

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 4 | F | L | Longitudes **no estandarizadas** (travesaños) | ✅ **v0.2.5** — Catálogo configurable (GENERIC/LAYHER/UNIFORM) + DP en `_bay_lengths_for_segment` con compensación al final |
| 5 | F | M | **Travesaño transversal en esquina** tiene longitud `depth/cos(α/2)` (no estándar) | ✅ **v0.2.6** — Etiquetado `Ledger_TC_*` y contado en `stats['corner_ledgers']` para BOM |
| 6 | S | S | Travesaños no se "apoyan" en los acoples (flotan entre postes) | ✅ **v0.3.7** (parcial) — Rosetas son ahora children del segment del poste que las contiene. Se mueven/seleccionan/duplican como pieza modular |

### 21.3 Bandejas

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 7 | F | L | Longitud **no estandarizada** (bandejas) | ✅ **v0.2.5** — Heredada del catálogo (cada bandeja = bay_len, ahora estándar excepto la compensación) |
| 8 | C/S | S | Si `depth` no es múltiplo de `plank_width`, hay **hueco perp** entre última bandeja y back row | Clampar `plank_count` a `floor(depth/plank_w)` o llenar con bandeja parcial |
| 9 | F | M | **Corner deck es un único cuadrilátero** (representa la "corner platform" de catálogo) | ✅ **v0.2.6** — Renombrado `Corner_Plank_*`, prop `add_corner_planks`, sentado +5 mm sobre el ledger transversal |
| 10 | C/S | S | Bandejas **atraviesan los travesaños transversales** | ✅ **v0.2.7** — Z subida en `+TUBE_DIAM/2` para descansar sobre el tubo |

### 21.4 Trampillas

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 11 | C/S | S | `LID_OPEN_DEG = 85°` constante | ✅ **v0.2.4** — `props.lid_open_deg` |
| 12 | C/S | S | Sin **manija/tirador** en borde libre | ✅ **v0.2.9** — Helper `_make_lid_handle` con U‑shape (2 postes + barra horizontal) en el free edge |
| 13 | F/S | M | Trampillas en **vanos contiguos a esquina** pueden degenerar (bay_len corto) | Excluir corner-adjacent indices de `ladder_bays` o re-validar geometría |
| 14 | C/S | S | Knuckles de bisagra son simbólicos, sin pieza visual de unión a la deck | ✅ **v0.2.9** — Pin pasador (cilindro Ø20%TUBE × 85% lid_length) entre los knuckles |

### 21.5 Escaleras

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 15 | C/S | S | Sin **pie de apoyo** (base plate o peana) | ✅ **v0.2.4** — Pie 0.20×0.20×0.02 m bajo cada riel |
| 16 | S | S | Si `bay_len < tilt_dx`, base **sale del bay** | ✅ **v0.2.4** — Warning en panel cuando `tilt_dx > section_length-0.1` |
| 17 | C/S | S | Peldaños equidistantes de extremo a extremo (deberían estar a ≥0.15 m de cada extremo) | ✅ **v0.2.4** — Clearance 0.15 m en cada extremo |
| 18 | C/S | S | `LADDER_WIDTH = 0.42` constante | ✅ **v0.2.4** — `props.ladder_width` |
| 19 | F | M | Sin **pasamanos lateral** ni descanso de planta | ✅ **v0.7.15** — Helper `_ladder_handrail` añade tubo paralelo al riel a 0,9 m (configurable) + 2 postes verticales en extremos. Toggle `add_ladder_handrail`. Descanso de planta queda fuera de scope (lo cubre la propia plataforma de la planta superior con su trampilla) |

### 21.6 Barandillas y rodapiés

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 20 | F/S | S | **Rodapié back en esquina** sigue la bisectriz con un kink — falta una pieza de remate de esquina | ✅ **v0.2.4** — Pieza `Toe_C_F<f>_<k>` rotada al ángulo de la bisectriz |
| 21 | C/S | S | Barandillas en esquina terminan a tope sin pieza de remate | ✅ **v0.3.5** — `Rail_C_<mid|top>_F<f>_<k>_<F|B>` corner rail caps en cada esquina × planta × row × altura |
| 22 | F/S | M | **Barandillas transversales de extremo** ausentes en P0 y Pn | ✅ **v0.2.7** — `Rail_E_<top|mid>_F<f>_<end_idx>` cierra ambos extremos del andamio |

### 21.7 Cruces (diagonales)

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 23 | F/S | S | Diagonales se generan en bays con escalera ⇒ pueden **colisionar** | ✅ **v0.2.7** — `if i in ladder_bays: continue` en el bucle de cruces |
| 24 | E | M | Sin **diagonales horizontales** en plano (rigidizadores en planta) | ✅ **v0.3.6** — Toggle `add_horizontal_braces` + `h_brace_every_floors` + `h_brace_every_bays`. Diagonal en plano del deck a floor z, de `nodes_front[i]` a `nodes_back[i+1]`. Skip ladder/compensation bays |
| 25 | E | L | Diagonales solo en front row. Real: alternan front/back, a veces transversales | ✅ **v0.4.0** — EnumProperty `brace_pattern` con 4 modos: FRONT (solo cara frontal, default), BACK (solo posterior), BOTH (ambas), ALT (alternando front/back cada 4 vanos). Helper `_emit_brace` con caps wedge. Naming `Brace_F<f>_<bay>_F` o `_B` |

### 21.8 Anclajes a fachada

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 26 | E | M | **Ausentes**. Necesarios para EN 12810 y para anular el vuelco en el cálculo estructural | ✅ **v0.2.4** — Sub-collección `Anclajes`, props `add_ties` + `tie_every_bays/floors` + `tie_length` |

### 21.9 Trayectoria

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 27 | F | M | Polilínea **abierta** únicamente. Sin loop cerrado (P0 = Pn) | ✅ **v0.2.9** — Toggle `props.closed_loop`. En cerrado: todos los vértices son interiores con bisectriz, no hay end‑rails, segmento de cierre P_n→P_0 |
| 28 | F | M | **Z proyectada a `base_z`** (el código aplana todos los puntos). Sin Z variable | ✅ **v0.3.0** — Toggle `use_terrain_z`. Cada empty conserva su Z (= cota del terreno). `ref_z = max(P.z) + jack_height`, andamio nivelado, husillos de longitud individual por poste |
| 29 | C | S | Ángulos muy obtusos (>170°) → bisector pequeño. Ya hay clamp pero sin warning | Avisar en panel cuando `cos_half < 0.1` |

### 21.10 Materiales y UI

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 30 | C | S | Colores no configurables desde panel | ✅ **v0.3.5** — 10 `FloatVectorProperty(subtype=COLOR)` en `ANDAMIOS_Props`, sección "Colores" en grid 2 columnas. `_apply_category_materials` toma valores de las props |
| 31 | F | M | Sin **presets de fabricante** (Layher 73/109, ULMA, Peri) | ✅ **v0.2.9** — EnumProperty `preset` con CUSTOM/LAYHER_73/LAYHER_109/GENERIC_1M/NARROW. Aplica depth + planks + catálogo en una pasada usando `_AUTO_SUPPRESS` |
| 32 | C | S | Sin **validaciones con warnings** en el panel | ✅ **v0.2.4** — Warnings en panel para depth/plank_count y tilt_dx/bay_len |

### 21.11 Performance

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 33 | F | M | Cada regen reconstruye TODO. Sin caching | ✅ **v0.4.1** — Cambios de color usan callback `_on_color_change` que solo refresca materiales (3.3 ms vs 10.6 s para regen completo, ~3000× más rápido) |
| 34 | F | L | Postes y travesaños son meshes únicos | ✅ **v0.4.1** — `_TUBE_MESH_CACHE` y `_BOX_MESH_CACHE` con clave (length/size, diam, coll). 843 objetos comparten 329 meshes (61% reducción). Cleared al inicio de cada regen para evitar refs huérfanas |

### 21.12 Auto-update

| # | Sev | Esf | Detalle | Pista de implementación |
|---|---|---|---|---|
| 35 | F | S | Solo escucha `path_points`. Cambios de **propiedades** (floor_count, ladder_length, etc.) **no disparan** regen | ✅ **v0.2.9** — `_on_prop_change_regen` añadido a 25 propiedades geométricas. Flag `_AUTO_SUPPRESS` evita regens múltiples durante presets |

---

### 21.13b Rosetas a altura de barandilla

| # | Sev | Esf | Detalle | Estado |
|---|---|---|---|---|
| 37 | C | S | Rosetas solo a nivel de plataforma; faltaban en mid + top rail | ✅ **v0.3.0** — `rail_offsets` con (0.0=L, 0.5=M, 1.0=T). 3 alturas por planta cuando `guardrails` está activo |

### 21.14 Modo manual de posicionamiento de escaleras

| # | Sev | Esf | Detalle | Estado |
|---|---|---|---|---|
| 36 | F | M | **Posición manual de cada escalera con slider y snap al vano más cercano** | ✅ **v0.2.8** — `ANDAMIOS_LadderSlot` (CollectionProperty) + UIList con slider 0..1 + snap por distancia acumulada al centro del bay. Toggle `use_manual_ladders`. Auto-update reactivo al mover el slider |

### 21.13 Priorización sugerida

**Fase A — críticos para realismo de fabricante (1-2 semanas)**
- #4, #7 — Longitudes estandarizadas (travesaños y bandejas)
- #2 — Husillos de base
- #5, #9 — Piezas de esquina dedicadas (travesaño transversal + corner deck)
- #20 — Rodapié de esquina con remate
- #26 — Anclajes a fachada (necesario para el módulo estructural)

**Fase B — calidad visual y seguridad (1 semana)**
- #1, #3 — Postes segmentados + acoples
- #10 — Bandejas posadas sobre travesaños
- #15, #17 — Pie de apoyo escalera + distribución peldaños
- #22 — Barandillas transversales de extremo
- #23 — Cruces que no chocan con escaleras
- #32 — Validaciones con warnings

**Fase C — funcionalidad avanzada (2-3 semanas)**
- #11, #12, #14 — Detalles trampillas (ángulo configurable, manija, knuckles realistas)
- #19 — Pasamanos lateral en escaleras
- #27, #28 — Polilínea cerrada + Z variable
- #31 — Presets de fabricante
- #35 — Auto-update por cambio de propiedades

**Fase D — performance y refinamiento estructural (variable)**
- #6, #21 — Vinculación visual con acoples / remates
- #24, #25 — Diagonales horizontales y patrón completo
- #33, #34 — Caching e instancing
- #30 — Colores configurables

---

## 22. Versiones

> **Nota (2026-05-03):** las entradas v0.7.5 → v0.7.13 fueron reconstruidas a posteriori
> tras detectar que el código avanzó hasta v0.7.13 sin actualizar esta tabla. Las anclas
> firmes son v0.7.7 (citada en `tests/test_cad_overlays.py` como "Regresión v0.7.7"),
> v0.7.10 (citada en `TUTORIAL.md §8.2` como "brace_subdivision v0.7.10+"), v0.7.12
> (citada en `TUTORIAL.md §12.2` como "El validador v0.7.12+") y v0.7.13 (commit
> "Initial public release"). El orden interno del resto se reconstruye del código.

| Versión | Hito |
|---|---|
| 0.7.15 | **Pasamanos lateral en escaleras (Fase J — cierre §21.5 #19)**: último item geométrico abierto del checklist §21. Las escaleras Layher Allround reales incluyen un tubo elevado paralelo a un lado de la escalera para que el trabajador se agarre durante el ascenso (pieza Steigleiterschutzgeländer). Hasta v0.7.14 las escaleras eran sólo rieles + peldaños + pie + trampilla; faltaba este elemento de protección personal exigido implícitamente por EN 12811-1 §7.2 (carga horizontal de 0,3 kN en cualquier punto de un agarre de trabajador). (1) Helper nuevo `_ladder_handrail(p_bottom, p_top, side_axis, width, height, name, coll)` que genera 3 piezas: 1 tubo `{name}_handrail` paralelo al riel `_rail_a` desplazado +Z·height (0,90 m default), y 2 verticales cortos `_handrail_post_bot` / `_handrail_post_top` que conectan el riel principal con el pasamanos en los extremos. Mismo grosor (TUBE_DIAM·0,6) que los rieles para coherencia visual. (2) Props nuevas: `add_ladder_handrail: BoolProperty(default=True)` y `ladder_handrail_height: FloatProperty(default=0.90, min=0.70, max=1.20)` con descripción ergonómica. (3) Bucle de generación: tras `_ladder(...)` y antes del `# Foot plate`, llamada condicional a `_ladder_handrail` reutilizando `prp` (mismo side_axis que la escalera) y `LADDER_WIDTH`. Las piezas heredan el prefijo `Ladder_{i:03d}_F{f_idx}_handrail*` para que el outliner las agrupe junto a su escalera. (4) Panel: el sub-bloque "Escaleras" añade dos filas — toggle "Pasamanos lateral (escalera)" + slider "Altura pasamanos (m)" condicionalmente activos según `add_ladders` y `add_ladder_handrail`. (5) Compatibilidad BOM/CAD verificada: `category_for_name` filtra `Ladder_*_handrail*` como sub-pieza (no infla el conteo de escaleras ensambladas — sólo `_rail_a` cuenta como representativo); `kind_for_object_name` también las omite (markers funcionales sólo se dibujan para `_rail_a`). 6 tests nuevos parametrizados (3 en `test_bom.py` + 3 en `test_cad_overlays.py`) cubren los 3 prefijos. **Smoke**: U-shape con 4 escaleras genera 12 nuevas piezas (3 por escalera) sin afectar el conteo de "ladder" en BOM (sigue siendo 4). **434/434 PASSED**. |
| 0.7.14 | **Análisis P-Δ (2º orden geométrico, EN 1993-1-1 §5.2)**: cierra el primer "limitante real" declarado en el README ("sin P-Δ, conservador para andamios típicos pero subestima ~10-20 % en torres muy esbeltas >15 m sin anclajes"). Implementación opt-in que aprovecha el `analyze_PDelta` nativo de PyNiteFEA — no se reinventa el bucle iterativo. (1) `solver.py::solve()` añade params `use_pdelta: bool = False` (default OFF para no cambiar el comportamiento de los 421 tests previos) y `pdelta_max_iter: int = 30`. Si `use_pdelta=True` llama a `fem.analyze_PDelta(check_stability=True, max_iter=…, sparse=True)` en vez de `fem.analyze(...)`. (2) Detección robusta de inestabilidad: PyNite es inconsistente sobre singularidad — a veces eleva `ValueError`, a veces sólo emite `MatrixRankWarning` y devuelve NaN, a veces converge a una rama post-bifurcación con flecha de signo invertido. El wrapper captura los tres casos: `warnings.catch_warnings(record=True)` para los warnings + verificación explícita de `math.isnan` en los DOFs traslacionales tras la convergencia. Cualquiera de los dos dispara `RuntimeError` con mensaje accionable: "Análisis P-Delta no convergió: el andamio es inestable... Añade anclajes a fachada, reduce la altura, o usa secciones más rígidas." (3) Nuevo flag `Results.pdelta: bool` que refleja el modo del análisis ejecutado, propagado a downstream (informe). (4) `pipeline.py::build_and_solve()` lee `options["use_pdelta"]` (default False) y lo pasa a `solve()`. Docstring del pipeline actualizada con la nueva clave. (5) `andamios_addon.py` añade `BoolProperty calc_use_pdelta` con descripción larga citando EN 1993-1-1 §5.2 y el criterio α_cr ≤ 10. (6) `calc/ui.py` añade caja "Avanzado" colapsable al sub-panel "Cargas y combinación" con el toggle + leyenda condicional ("↳ Captura desplome — más lento, requerido en torres esbeltas"). (7) `calc/report.py` añade fila "Tipo de análisis" en el resumen ejecutivo: si P-Δ está activo, dice "**2º orden geométrico (P-Δ)** — la rigidez se actualiza iterativamente con la posición deformada de los postes. Captura la amplificación de momentos por desplome de la cúspide. Recomendado por EN 1993-1-1 §5.2 cuando α_cr ≤ 10."; si no, dice "Lineal de 1<sup>er</sup> orden" con sugerencia de activar P-Δ en torres esbeltas. (8) `calc/tests/test_pdelta.py` (7 tests): switching default OFF / explícito ON, P-Δ con axial=0 coincide con lineal, **validación cuantitativa contra fórmula de Euler** δ_pd/δ_lin ≈ 1/(1−N/N_cr) en voladizo CHS Ø48,3×3,2 con axil = 0,3·N_cr (error < 10 %), monotonía amplificación crece con axial (10 %/30 %/50 % de N_cr), comportamiento post-crítico (N=1,5·N_cr → flecha de signo opuesto, manifestación de la rama post-bifurcación), error message accionable ante singularidad (modelo sin soportes → matriz singular silenciosa → wrapper la detecta vía warning + isnan y eleva `RuntimeError` con texto que menciona anclajes/altura/secciones). **Smoke**: voladizo 3 m con axil=2000 N (≈ 0,3·N_cr) + lateral=200 N → δ_lin=0,148 mm vs δ_pd=0,210 mm, amplificación numérica 1,42 vs Euler 1,43. **428/428 PASSED**. |
| 0.7.13 | **Apertura pública del repositorio**: primera release pública del addon como repo independiente bajo licencia MIT. (1) `README.md` reescrito con quickstart en 5 pasos, listado de funcionalidades agrupadas (Geometría / FEM / Exportación / UX), badges de tests/Blender/licencia, enlace a la landing `mechanicalpro.vercel.app/andamios` y CTA de feedback. (2) `LICENSE` MIT añadida con copyright a nombre del autor; aviso explícito de que las normativas EN 1993, EN 12811, EN 1991-1-4 referenciadas pertenecen a CEN/AENOR y los valores Layher son orientativos (usar ETA en producción). (3) Estructura de repo limpiada: `mechanicalpro-master/` (landing Next.js) y `tutorial/` (manual HTML interactivo) explicitados en el árbol. (4) Sección "Limitaciones conocidas" lista lo que el addon **no** hace (sin P-Δ, sin sismo, voladizos parciales, sólo Layher Allround calibrado para K_φ y joints). (5) `bl_info["version"]` actualizado a (0,7,13) — la versión 0.7.12 quedó como "auditoría interna" antes del release público. **Smoke test**: el repo se clona limpio y `pytest calc/tests/ -q` pasa 421/421 sin tocar dependencias adicionales más allá de PyNiteFEA. |
| 0.7.12 | **Validador previo al cálculo (sanity-check pre-FEM)**: el solver puede tardar minutos o colgar Blender en modelos mal configurados; un linter rápido del modelo evita perder tiempo. (1) Nuevo módulo `calc/validator.py` con dataclass `ValidationIssue(level, code, message, suggestion)` y propiedad `is_blocking` (level=ERROR). (2) `validate_model(model)` (puro, sin bpy) emite `E1` (sin nodos), `E2` (sin miembros), `E3` (sin material), `W1` (sin soportes), `W2` (poste muy esbelto), `W3` (releases incoherentes), `W4` (cargas faltantes). (3) `validate_scene(scene)` (requiere bpy) emite `E10` (sin props andamios), `E11` (path < 2 puntos), `E12` (path con None), `E13` (sin colección Scaffold), `W10` (h > 8 m sin anclajes), `W11` (planta con < 2 plantas), `W12` (profundidad anormal), `W13` (bandejas no encajan en depth), `W14` (planta < 1,5 m). (4) `summarize_issues(issues)` devuelve `(n_errors, n_warnings, n_infos, status_text)` para el panel. (5) Operador `ANDAMIOS_OT_calc_validate` (`andamios.calc_validate`) llama al validador, persiste el resumen en `scene["calc_validation_summary"]` con timestamp y enseña semáforo en el panel: ✓ Limpio / ⚠ N warnings / ✗ N errors. (6) Sub-panel `ANDAMIOS_PT_calc_run` muestra el botón "Comprobar modelo" (icono CHECKMARK) por encima de "Ejecutar cálculo"; la lista de issues se despliega bajo el botón con icono por severidad. (7) `cad_plan.build_validation_summary(scene)` extrae el dict para renderizar el cajetín del plano CAD con util_max + delta_max_mm + n_failed/n_total + combo + service + zona viento (status: ANDAMIO SEGURO / MARGEN AJUSTADO / NO CUMPLE). (8) `tests/test_validator.py` (14 tests) cubre validate_model con todos los códigos E1-E3/W1-W4, summarize_issues, is_blocking. (9) `tests/test_validation_frame.py` (6 tests) prueba el flujo completo sobre el pórtico isostático. **Sumando los 49 tests acumulados v0.7.5–v0.7.12**: 421/421 PASSED. |
| 0.7.11 | **Tutorial HTML interactivo + landing del producto**: paquete divulgativo para usuarios sin Blender previo. (1) Carpeta `tutorial/` con `index.html` autocontenido (sin servidor) — manual interactivo con quickstart en 5 minutos, 5 recetas (recto / L / U / torre cerrada / 4 plantas con anclajes), referencia de cada control del panel, glosario de términos de andamiaje y visor 3D Three.js para los GLB del flagship. (2) `tutorial/build.py` (más `build_animations.py`, `build_promo.py`, `make_promo.py`) automatiza la regeneración de assets desde Blender headless: PNGs ortográficos + isométricos por receta, animaciones WebP comparativas (subdivisión cruces, patrón FRONT/BACK/BOTH/ALT, plantas), exports GLB del andamio flagship. (3) `tutorial/test_promo.py` y `test_render.py` validan que el pipeline de assets compila sin errores. (4) Carpeta `mechanicalpro-master/` (Next.js 14 + Tailwind) con landing en `mechanicalpro.vercel.app/andamios`: hero con vídeo de demo, ficha técnica, CTA al repo de GitHub. **Smoke**: `tutorial/index.html` se abre en cualquier navegador moderno y carga los assets locales sin pedir red. |
| 0.7.10 | **Subdivisión zigzag de cruces (NONE / HALF / QUARTER)**: las cruces standard Layher de 2,07×2 m miden ~2,9 m, son piezas pesadas y ocupan dos roset (esquina-a-esquina). En obra es habitual sustituirlas por sub-cruces ancladas a rosetas intermedias. (1) Nueva `EnumProperty brace_subdivision` con 3 modos: `NONE` (default, una diagonal esquina-a-esquina ~2,9 m), `HALF` (dos sub-cruces ancladas a la roseta de media altura, patrón en N, ~2,3 m, 2× cruces), `QUARTER` (cuatro sub-cruces ancladas a rosetas cada 0,5 m, ~2,1 m, 4× cruces; recomendado solo en torres ≥ 15 m). (2) Constante `_SUBDIVS_MAP = {'NONE': 1, 'HALF': 2, 'QUARTER': 4}` y bucle interno `for k in range(subdivs)` que llama a `_emit_brace` con sufijo `_s<k>` cuando subdivs>1. (3) `_emit_brace_set(node_a, node_b, base_z, name_prefix)` factoriza la generación de la pila de sub-diagonales (puntos intermedios = `lerp(a, b, k/subdivs)` por roseta). (4) Sub-panel del UI muestra el dropdown bajo "Patrón cruces". (5) Tests cubren la regresión de count: subdivs=2 produce 2× barras frente a NONE; subdivs=4 produce 4×. **Documentado en TUTORIAL §8.2** con anim comparativa NONE/HALF/QUARTER. |
| 0.7.9 | **Tutorial guiado in-Blender (overlay GPU + state machine)**: wizard estilo Illustrator que enseña al novato a generar su primer andamio sin salir de Blender. (1) Nuevo módulo `tutorial_guide.py` (684 LOC). Operador modal `ANDAMIOS_OT_tutorial_start` que registra draw handler de viewport + timer y procesa eventos sin bloquear la UI. (2) `TutorialState` singleton mantiene el paso actual y los contadores iniciales (nº de empties, nº de path_points, presencia de Scaffold) para detectar progreso automáticamente. (3) **6 pasos**: WELCOME → CREATE_E1 → CREATE_E2 → ASSIGN_PATH → GENERATE → DONE. Detección automática: CREATE_E1/E2 cuentan empties en escena, ASSIGN_PATH comprueba `len(path_points) >= 2 con obj != None`, GENERATE comprueba colección Scaffold con objetos. (4) `_draw_overlay()` pinta caja flotante con título + instrucción + flecha pulsante usando `gpu` (rectángulos translúcidos) + `blf` (texto). (5) Operadores manuales `tutorial_next` / `tutorial_skip` para avance forzado. (6) `register()` integra el tutorial en el panel principal del addon (botón "Iniciar tutorial guiado" en la cabecera). El tutorial es independiente del módulo de cálculo: si PyNiteFEA no está instalado, sigue funcionando. (7) `unregister()` limpia el draw handler y el timer para evitar zombies en reload. **Limitaciones documentadas**: el overlay solo se pinta sobre el viewport 3D; los controles nativos del panel se highlight con `alert=True` pero no se "pulsan solos". |
| 0.7.8 | **CAD: etiquetas de tramo en planta + cajetín con resumen del último cálculo**: el lector del plano necesita poder navegar entre la vista general y los detalles por tramo, y ver de un vistazo si el cálculo dio OK/marginal/NO. (1) Nuevo helper `_draw_tramo_labels(transform, frames)` en `cad_plan.py` que pinta una caja blanca semi-opaca con borde azul ISO y texto "TRAMO A-B" / "TRAMO B-C" en el midpoint XY de cada tramo de la polilínea, usando el mismo `transform` del `_draw_view` de la planta. Sirve como índice visual hacia las hojas de detalle. (2) Helpers `extract_floor_heights(scene)` y `extract_pole_levels(lines_3d, axis)` para que el cajetín pueda mostrar las plantas + las coordenadas de eje sin reabrir Blender. (3) `build_validation_summary(scene)` lee custom props del último cálculo (`calc_status_level`, `calc_status_worst`, `calc_status_n_total/n_failed`, `calc_defl_worst_disp_m`, props.calc_combo/service_class/wind_zone) y compone dict con `status_text` ("✓ ANDAMIO SEGURO" / "⚠ MARGEN AJUSTADO" / "✗ NO CUMPLE") + `details` formateados. (4) `_build_overview_sheet` y `_build_single_sheet` añaden un bloque "VALIDACIÓN ESTRUCTURAL" en el cajetín cuando hay summary; rojo/amarillo/verde por status. (5) Si el usuario aún no ha calculado, el bloque se omite (no aparece "?" en el plano). |
| 0.7.7 | **Fix de regresión: plataformas como `plank` sin marker dedicado**: tras v0.7.4 detectado que el helper `kind_for_object_name` clasifica las bandejas como `plank`, pero `_MARKER_STYLE` ya no incluye `plank` (los rectángulos marrones saturaban la planta y se quitaron tras feedback). El consumer `_draw_top_markers` hacía `_MARKER_STYLE[kind]` directo → `KeyError` en plantas con bandejas regulares. (1) `_draw_top_markers` filtra `kind in _MARKER_STYLE` antes del lookup. (2) `kind_for_object_name` mantiene `plank` para uso interno (auditoría, BOM), pero los markers solo se dibujan para `trapdoor` (T verde), `ladder` (E rojo), `tie` (▲ rojo). (3) Test de regresión en `tests/test_cad_overlays.py::test_plank_classified_but_skipped_in_marker_style` confirma `assert "plank" not in _MARKER_STYLE` y que `_draw_top_markers([{"kind": "plank", ...}])` devuelve `""` sin lanzar. **Lección**: extraer la dependencia kind→style como un dict y filtrar `in` antes de indexar evita la fragilidad de "todo registrado siempre tiene marker". |
| 0.7.6 | **K_φ semi-rígido en uniones (EN 1993-1-1 Anexo E)**: las uniones roseta-tubo Layher Allround no son ni rótulas perfectas ni empotramientos rígidos; tienen rigidez rotacional finita K_φ ≈ 80–120 kN·m/rad. Tratarlas como rótula es muy conservador (subestima capacidad), tratarlas como empotrado es inseguro. (1) Nuevas funciones en `calc/releases.py`: `effective_buckling_factor_K(L, EI, K_phi_top, K_phi_bot)` aplica la fórmula del Anexo E de EN 1993-1-1 para pórticos arriostrados — calcula η_i = K_C / (K_C + K_φ_i) donde K_C = E·I/L, y devuelve K ∈ [0,5; 1,0] según rigidez de los nudos. Para K_φ → ∞ devuelve 0,5 (rígido), para K_φ → 0 devuelve 1,0 (rótula). (2) `compute_pole_lcr_overrides(model, K_phi)` recorre los miembros tipo `pole`, calcula K efectivo nudo a nudo y devuelve dict `{member_id: L_cr}` con `L_cr = K · L`. Ledgers/braces/ties ignorados (ya tienen su propio régimen). (3) Pipeline `build_and_solve` consume el dict de overrides y lo pasa a la verificación de pandeo en `checks/en1993_1_1.py` para usar `L_cr` específico por miembro en lugar del genérico `L`. (4) `tests/test_kphi.py` (10 tests): casos límite (K_φ→∞ da 0,5, K_φ→0 da 1,0), valor Layher Allround real (K_φ=80 kN·m/rad sobre L=2 m da K≈0,77), L<=0/EI<=0 fallback seguro, dict de overrides solo contiene postes. **Impacto típico**: en torres Layher de 4 plantas el util de pandeo de los postes baja del 0,68 (rótula) al 0,52 (semi-rígido), liberando un 20–25 % de capacidad real. |
| 0.7.5 | **Carga horizontal en barandilla (EN 12811-1 §7.2.1)**: la normativa exige que cada barandilla intermedia y superior resista 0,3 kN puntuales aplicados en cualquier punto de su longitud (carga de protección personal contra caídas). Hasta v0.7.4 esta carga no se modelaba. (1) Nuevo módulo `calc/loads/guardrail.py` con constante `GUARDRAIL_F_NEWTONS = 300.0` y función `apply_guardrail_horizontal_load(model, *, F=300, direction="AUTO", case="Q")`. Como las barandillas (`Rail_*`) no se extraen como miembros del FEM (solo `Pole_/Ledger_/Brace_/HBrace_/Tie_`), la carga se aplica como **NodalLoad** sobre los nodos top de los postes externos en la dirección perpendicular al andamio (transferencia conservadora del cortante que la barandilla pasaría al poste). (2) Modo `direction="AUTO"`: detecta el lado externo del andamio analizando la geometría (cara expuesta a caída) y aplica ±X o ±Y según corresponda. Modos manuales `+X / -X / +Y / -Y` para casos especiales. (3) La verificación local de la barandilla en flexión (M ≤ M_Rd, viga biapoyada con carga puntual) queda como cálculo offline — documentado en docstring. (4) Pipeline `build_and_solve` invoca la función entre la aplicación de cargas Q y la composición de combinaciones, de modo que la carga entra en `ULS_LeadL` y `ULS_LeadW`. (5) `tests/test_guardrail_load.py` (13 tests): aplicación a modelo sintético, dirección AUTO/manual, magnitud por defecto 300 N, contador de cargas devuelto, idempotencia (re-aplicar no duplica), `case="Q"` correcto. **Smoke test**: en un andamio de 5 vanos × 2 plantas, el módulo añade 6 cargas (3 nodos top × 2 caras externas); el cortante en la base aumenta ~2 % y aparece en el reporte como contribución al combo ULS_LeadW. |
| 0.7.4 | **Etiquetado funcional + Norte en planta**: el plano CAD ahora cumple el último item del checklist normativo (antipatrón H del prompt acotación: plataformas/trampillas/escaleras/anclajes dibujados pero sin identificar). (1) Refactor `_draw_view` para que devuelva el `transform = (x_off, y_off, scale)` como 4º elemento de la tupla — los callsites que no lo necesitan usan `_`; los sheet builders de la planta lo retienen para superponer markers en las mismas coords. (2) Helper puro `kind_for_object_name(name)` clasifica un objeto del Scaffold por kind funcional ∈ {plank, trapdoor, ladder, tie} a partir del prefijo (Deck_/Plank_/Corner_Plank_, Lid_/Trapdoor_, Ladder_*_rail_a, Tie_), descartando postes/ledgers/rails/braces/husillos/rosetas y sub-piezas duplicadas (Ladder_*_rail_b, Ladder_*_step_*, Hinge_, LidHandle_). (3) Helper `extract_functional_elements_3d(scene)` recorre la colección Scaffold y produce dicts `{kind, x, y, z, label, name}` con el centroide del bbox local llevado a mundo (más estable que matrix.translation cuando el origen del mesh no está centrado). (4) `_MARKER_STYLE` define color/label por kind: plank rectángulo marrón sin etiqueta, trapdoor cuadrado verde con "T" blanca centrada, ladder rectángulo rojo con "E", tie triángulo rojo apuntando hacia arriba. (5) `_draw_top_markers(transform, elements)` superpone markers SVG sobre la planta usando `project_world_to_svg` con el mismo transform que `_draw_view`. (6) `_draw_north(rect, position)` flecha de Norte en círculo blanco con borde azul ISO en cualquiera de las 4 esquinas (default `bottom-right`); asume `+Y mundo = Norte` por convención del addon (la fachada está en y=0 y el andamio crece hacia +Y interior). Como SVG invierte Y al pintar, la flecha hacia arriba corresponde a +Y mundo. (7) `_draw_top_overlays(rect, transform, elements)` combina markers + Norte; siempre pinta Norte aunque transform=None o no haya elementos funcionales. (8) `_build_single_sheet` y `_build_overview_sheet` reciben nuevo param `functional_elements_3d`; tras el `_draw_view` de la planta llaman a `_draw_top_overlays`. (9) `generate_cad_sheets` propaga el param. (10) Operador `andamios.calc_cad_export` extrae los elementos vía `extract_functional_elements_3d(scene)` y los pasa al API. (11) `tests/test_cad_overlays.py` — 40 tests pytest: kind_for_object_name parametrizado con 7 nombres válidos (plank/trapdoor/ladder/tie cubriendo los 7 prefijos del addon) + 12 nombres a descartar (postes/ledgers/rails/braces/husillos/rosetas, Ladder_*_rail_b/step_, Hinge_/LidHandle_); _draw_top_markers vacío sin transform/elementos, plank rect sin texto, trapdoor con "T", ladder con "E", tie polygon, kind desconocido skip seguro, múltiples elementos suman 3 rect + 1 polygon + 2 textos, position usa el transform correctamente con cy del polygon ±offsets; _draw_north con circle + "N" + polygon, las 4 esquinas, dentro del rect; combinación markers+Norte. **Smoke test U-shape**: 18 planks + 4 escaleras + 4 trampillas detectadas, "T" y "E" presentes en el HTML, marrón de plank aparece 36 veces (2 ocurrencias por plank: stroke+fill), Norte en cada hoja con planta. **372/372 PASSED**. |
| 0.7.3 | **CAD multi-hoja con isometría + partición por tramos**: el alzado frontal global de un andamio en U/L se aplastaba al mezclar todos los tramos rectos en el mismo eje X. Refactor para producir 1 hoja por tramo recto cuando la polilínea tiene ≥ 2 segmentos. (1) Nuevo módulo puro `calc/cad_views.py`: `iso_project((x,y,z))` axonometría 30°/30° con +Z arriba (cos30·(x−y), z−sin30·(x+y)); `SegmentFrame` (origin/end/ex_xy/length) + `segment_frames(path_points)` que descarta tramos verticales (postes); `split_lines_by_segments` reparte cada línea al tramo cuyo eje pasa más cerca del midpoint XY (con penalización fuera del intervalo [0, length]); `project_lines_to_segment(lines, frame)` produce el alzado frontal local; `segment_label(i, n)` → "A-B", "B-C". (2) `calc/cad_plan.py` ampliado con `_draw_iso_view(rect, lines_3d)` (vista esquemática con grosores 70 % de las orto, sin cotas) y `_draw_legend(rect, segment_labels)` con muestras por categoría + lista de tramos. (3) Nueva API `generate_cad_sheets(...)` devuelve `list[str]`: 1 hoja con alzado+planta+iso+leyenda+BOM si la polilínea tiene 0-1 tramo; o overview (planta+iso+leyenda+BOM+cajetín) + 1 hoja por tramo (alzado local + cota a ejes + cajetín mini con datos del tramo) si hay ≥ 2. (4) `wrap_sheets_in_html` reemplaza `wrap_in_html` con `page-break-after: always` entre hojas para impresión continua a PDF. (5) `generate_cad_svg` / `wrap_in_html` siguen como wrappers delgados (compatibilidad). (6) Operador `andamios.calc_cad_export` pasa `path_points_3d=ref_points` al nuevo API; el report al usuario indica el número de hojas. (7) `tests/test_cad_views.py` — 30 tests pytest: iso_project (origen→origen, ejes Z/X/Y, diagonal X=Y colapsa horizontal, bbox de cubo unidad); segment_frames (single horizontal, vertical descartado, U-shape produce 3, diagonal a 45° normalizado); project (punto sobre eje da arc length, perp se descarta, z preservado, origen offset); perp_distance (zero on axis, ignora Z, perp offset, fuera de intervalo penaliza); split_lines (path vacío → 1 bucket, L-shape asigna correcto, esquina cae en uno solo, preserva count en U-shape con 13 líneas); project_lines (formato tuple, default category, dirección Y); segment_label A-B/B-C/C-D + zero. **Smoke test U-shape (4 path points)**: 4 hojas / 142 KB con marcadores VISTA GENERAL + TRAMO A-B/B-C/C-D + ISOMETRÍA + LEYENDA presentes. **Smoke test recto (2 path points)**: 1 hoja sin "TRAMO". **332/332 PASSED**. |
| 0.7.2 | **Sistema de diagnóstico de crashes**: el usuario reportó que Blender se cierra de golpe tras varias regeneraciones; un segfault mata el proceso antes que cualquier try/except, así que hay que persistir eagerly a disco antes de cada operación. (1) Nuevo módulo `calc/diagnostics.py`: `enable_faulthandler()` apunta `~/.config/andamios/faulthandler.log` (captura SIGSEGV/SIGABRT/SIGFPE con traza Python all_threads); `log_breadcrumb(op, **fields)` JSONL append-only en `breadcrumbs.jsonl` con rotación 256→128 KB alineada a salto de línea, best-effort sin lanzar; `breadcrumb_op` context manager registra `<op>.start` / `<op>.end` / `<op>.exception` con dur_ms y traceback recortado a 2 KB; `snapshot_props(props)` extrae 22 props JSON-able + path_points como `[name, x, y, z]`; `snapshot_scene(scene)` cuenta objetos del Scaffold; `export_diagnostic_text(scene)` compone `.txt` con sysinfo + props + breadcrumbs + faulthandler tail. (2) Integración en `andamios_addon.py`: `register()` activa faulthandler antes de cualquier otra cosa que pueda romper + log "addon_register" con versión; operador `ANDAMIOS_OT_generate` envuelto en `breadcrumb_op("manual_generate", n_path, floors, catalog)`; `_auto_deferred_regen` envuelto en `breadcrumb_op("auto_regen")`; `_auto_on_depsgraph` registra cada disparo. (3) Operadores `ANDAMIOS_OT_diag_export` (FileSelect → escribe `.txt` legible) y `ANDAMIOS_OT_diag_clear` (papelera). (4) Botón "Diagnóstico → Exportar informe / 🗑" en el panel principal. (5) `tests/test_diagnostics.py` — 22 tests pytest aislados con `monkeypatch` de `diagnostic_dir`: log JSON-line, append múltiple, valores no-JSON con repr, OSError no propaga, read empty/n_last/corrupt lines, clear idempotente, rotación alineada a `\n`, breadcrumb_op start/end/exception/traceback truncado, snapshot_props con path_points/None/missing, system_info, export sin scene, faulthandler idempotente. **Smoke test Blender headless**: `andamios.generate` registra `manual_generate.start` (n_path=2 floors=2 catalog=GENERIC) + `manual_generate.end` (dur_ms=7); informe de 1.5 KB legible. **302/302 PASSED**. |
| 0.1.0 | A→B simple, propiedades, panel básico |
| 0.1.1 | Auto-update con timer diferido |
| 0.2.0 | Polilínea con N puntos, esquinas con bisectriz |
| 0.2.1 | Trampillas con tapa y bisagras visibles |
| 0.2.2 | Escaleras transversales, longitud estándar configurable |
| 0.2.3 | Bandejas estandarizadas, rodapiés de esquina sin gap |
| 0.2.4 | **Fase A/B parcial**: husillos de base, anclajes a fachada, rodapié de esquina, pie de escalera, distribución de peldaños, props expuestas (ladder_width, lid_open_deg), validaciones en panel |
| 0.2.5 | **Catálogo de longitudes estándar**: EnumProperty `bay_length_catalog` con GENERIC / LAYHER / UNIFORM. DP que encuentra la combinación óptima por tramo + compensación al final |
| 0.2.6 | **Cierre Fase A**: travesaño transversal de esquina (Ledger_TC), plataforma de esquina dedicada (Corner_Plank) con prop `add_corner_planks` |
| 0.2.7 | **Cierre Fase B**: postes segmentados con manguito (`pole_segment_length`), rosetas en cada nodo (`add_rosettes`), bandejas elevadas sobre travesaños, barandillas de extremo (`Rail_E_*`), cruces sin colisión con escaleras |
| 0.2.8 | **Posicionamiento manual de escaleras**: slider 0..1 por escalera con snap al centro del bay más cercano. Toggle `use_manual_ladders`. CollectionProperty + UIList + operadores add/remove |
| 0.2.9 | **Fase C parcial**: manija lid (U‑shape), pin de bisagra, presets fabricante (Layher 73/109/Genérico/Estrecho), polilínea cerrada (`closed_loop`), auto‑update reactivo a cambio de 25 props |
| 0.3.0 | **Terreno irregular**: toggle `use_terrain_z` con cálculo automático de longitud de husillo individual por poste para nivelar el andamio. Rosetas a 3 alturas por planta (ledger + mid rail + top rail) |
| 0.3.1 | **Fix alineación geométrica**: bandejas, lid hinge, corner_plank y ties usaban `z + offset` sin sumar `ref_z` → desfase visible en modo terreno y con `base_z != 0`. Corregido. **Pole top extension**: ampliada de +0.20 m a +1.05 m para que las barandillas top del piso final tengan poste de anclaje. Si `pole_segment_length > 0`, redondea hacia arriba al múltiplo más cercano (uso de pieza estándar) |
| 0.3.2 | **Fix ladder F0 sobre terreno**: la primera escalera (de suelo a piso 1) arranca en la cota interpolada del terreno bajo el bay center (`(ground_z_front[i] + ground_z_front[i+1])/2`) en lugar de la base nivelada del andamio. Las escaleras de plantas superiores siguen apoyando en `ref_z + f*floor_h` (deck nivelado) |
| 0.3.3 | **Cruces y rosetas integradas**: (1) rosetas también a nivel base (f=0) para que la primera diagonal tenga punto de anclaje; (2) cabeza/cap (Ø120% × 6 cm) en cada extremo de la diagonal representando el wedge head Layher; (3) skip diagonales en bays de compensación (longitud no estándar); (4) rosetas refactorizadas como **annulus** con agujero interno = `TUBE_DIAM` → el pilar pasa por dentro y se integra visualmente |
| 0.3.4 | **Indicadores en viewport para sliders de escalera**: cada `LadderSlot` tiene un empty (cono) que se mueve sobre la polilínea según el slider. Helper `_polyline_position_at_t` interpola por longitud acumulada (soporta closed_loop y use_terrain_z). Operadores `ladder_add` / `ladder_remove` crean/eliminan el empty automáticamente |
| 0.3.5 | **Fase D parcial**: (#21) corner rail caps front+back en mid y top; (#30) 10 colores configurables por categoría con FloatVectorProperty + sección "Colores" en el panel |
| 0.3.6 | **Fase D continúa**: (fix) rodapiés transversales en extremos abiertos (`Toe_E_F<f>_<end_idx>`); (#24) diagonales horizontales en plano del deck con cadencia configurable, skip de ladder/compensation bays |
| 0.3.7 | **Modularidad pole + rosetas**: cada segment del poste (cuando `pole_segment_length > 0`) ahora es padre de las rosetas que caen en su rango Z. El usuario puede seleccionar/mover un segment y sus rosetas viajan con él, simulando el ensamblaje real |
| 0.3.7.1 | **Hotfix**: las rosetas se apilaban en (0,0,0) por timing del depsgraph (matrix_world devuelve identity tras crear el objeto). Solucionado computando la matriz mundial del parent manualmente desde `seg_obj.location` y `seg_obj.rotation_quaternion` |
| 0.3.8 | **Catálogo de longitudes para postes**: nueva EnumProperty `pole_length_catalog` con UNIFORM/GENERIC/LAYHER. Reusa el DP `_bay_lengths_for_segment` para combinar piezas estándar de 0.5/1/1.5/2/3/4 m hasta cubrir la altura. Pole reaches exactamente el top rail (`pole_top_offset = 1.0` sin redondeo hacia arriba) → no más pole sobresaliente |
| 0.3.9 | **Rosetas cada `rosette_pitch`**: distribución uniforme cada 0.5 m (configurable) a lo largo de toda la altura del poste, no solo en alturas estructurales. Cualquier configuración encuentra anclaje. Cada poste de 4 m tiene 9 rosetas como Layher real |
| 0.4.0 | **Patrón cruces front+back**: EnumProperty `brace_pattern` con FRONT / BACK / BOTH / ALT. Helper `_emit_brace` factoriza la creación de tubo + caps. Suffix `_F` o `_B` en el name para distinguir cara |
| 0.4.1 | **Performance**: (#34) instancing de meshes vía cache por (length/size, diam, coll) → 61% reducción de mesh data; (#33) cambios de color usan callback ligero `_on_color_change` (3000× más rápido que regen completo) |
| 0.4.2 | **Ringlock EU — Fase 1 Catálogo**: constantes del sistema (LONGITUDINAL_MODULES, ROSETTE_PITCH_M, etc.), 22 bandejas precargadas en 5 familias (Steel 0.32/0.61, Alu+LVL 0.61, Aluminium 0.32, Trapdoor). Valores estructurales conservadores marcados `is_estimated=True`. Panel con filtros por ancho/clase/material y display de propiedades de la bandeja seleccionada. Backup creado en `andamios_addon_v0.4.1.bak.py` antes de tocar nada |
| 0.4.3 | **Ringlock EU — Fase 2 Integración**: helpers `_find_matching_deck` (DP de match por longitud+ancho+material), `deck_to_fem_loads` (cargas equivalentes a ledgers) y `deck_verify_self_bending` (verificación EN 12811-1). Cada plank regular generado recibe custom property `andamio_deck_id` apuntando al catálogo. Stats `deck_total_weight_kg` y `decks_unmatched`. Property `deck_material_pref`. El lid de las trampillas se vincula a la variante `Deck_Trapdoor_AluLVL_*` |
| 0.4.4 | **Ringlock EU — Fase 3 Auditoría/UI**: (1) helper `_audit_decks_in_scene()` recorre `Plataformas` + `Trampillas`, agrega peso, no-matches, OK/FAIL y peor utilización; (2) operador `ANDAMIOS_OT_deck_audit` (icono `VIEWZOOM`) reporta el resumen vía `self.report` y vuelca distribución detallada por id al system console + lo expone en `props.last_summary`; (3) panel: nuevo indicador de **hueco perpendicular** `(scaffold_depth − N×plank_w) × 1000 mm` con check `≤ DECK_GAP_MAX_MM (25 mm)` por EN 12811-1; (4) la verificación de flexión **ignora** los `andamio_deck_role == "trapdoor_lid"` para evitar doble conteo (el spec del lid apunta al trapdoor deck completo, ya verificado por las tiras del propio bay). Auditoría en escena U-shape 3 tramos / 2 plantas: LAYHER → 52 bandejas, 44 OK / 0 FAIL, peor util 0.838 |
| 0.4.5 | **Ringlock EU — Fase 4 Auto-cubrir**: (1) constante `RINGLOCK_DECK_WIDTHS = (0.19, 0.32, 0.61)`; (2) helper `_suggest_deck_cover(depth, tol_mm)` enumera todas las combinaciones `combinations_with_replacement` hasta `n_max=6` planks y elige la mejor por `(gap, no-uniforme, n)` con tolerancia EN 12811-1 de 25 mm; (3) operador `ANDAMIOS_OT_deck_auto_cover` (icono `SHADERFX`) aplica props si la mejor combinación es **uniforme y dentro de tolerancia**, regenera y reporta; si es **mixta** o fuera de tolerancia sólo lo reporta como warning sin mutar props; (4) sugerencia visible en panel cuando el hueco actual está fuera de tol y existe combinación válida; (5) **fix de precisión flotante**: las `FloatProperty` truncan 0.96 → 0.9599999785... → la condición `gap < 0` rechazaba `3×0.32` como overhang fantasma. Resuelto con `EPS_MM = 0.5` en la comprobación y `max(0, gap)` para mostrar. Casos verificados: 0.96 → 3×0.32, 0.64 → 2×0.32, 1.09 → mezcla 0.32+4×0.19 (warn), 0.30 → fuera de tol (warn). **Cierre del ciclo Ringlock EU (Fase 1-4)** |
| 0.5.0 | **FEM — Fase 1 (esqueleto)**: nuevo paquete `calc/` paralelo al addon. (1) `model.py` define dataclasses puro Python (`Material`, `Section`, `Node`, `Member`, `Support`, `NodalLoad`, `Model`) con catálogo mínimo S235JR + CHS Ø48,3×3,2 (A=4,534·10⁻⁴ m², I=1,158·10⁻⁷ m⁴, J=2I); el módulo NO importa bpy → tests fuera de Blender. (2) `extract_model.py` recorre `Postes/Travesaños/Cruces/Anclajes` dentro de `Scaffold`, reconstruye los extremos de cada tubo desde `obj.matrix_world` + `bound_box` (eje Z local con depth=L), filtra sub-piezas no estructurales (`_sleeve`, `_capA`, `_capB`, `_head`, `_rod`, `_handle`, `_pin`, `_bar`) y fusiona nodos por tolerancia 1 mm. Clasifica miembros por prefijo (Pole→pole, Ledger→ledger, Brace/HBrace→brace, Tie→tie). (3) `solver.py` wrapper sobre PyNiteFEA: `build_pynite_model()` traduce `Model`→`FEModel3D`, `solve()` ejecuta análisis lineal y devuelve `Results` (desplazamientos nodales, reacciones, envolventes axial/cortante/momento/torsor por barra). Releases stub para Fase 4. (4) `tests/test_portico_simple.py` — voladizo L=3 m, P=1000 N en punta: 4 tests pytest que verifican δ_z = -PL³/(3EI), M_emp = PL, R_z = P y DOFs nulos en el resto, todos < 0,5 % de error → 4/4 PASSED. (5) `requirements.txt` con `PyNiteFEA>=2.4`, `pytest>=8.0`, `numpy>=1.24`. Validado con la Python bundled de Blender 5.1 (Python 3.13) instalando con `pip install --user`. |
| 0.5.1 | **FEM — Fase 2 (catálogos + cargas)**: (1) `model.py` se amplía con `DistributedLoad` (carga lineal trapezoidal por barra: `direction`, `w1`, `w2`, `x1`, `x2`, `case`), `Model.add_distributed_load(member, direction, w1, w2=None, …)` y `Model.split_member(member_id, n)` que subdivide una barra en N sub-barras equiespaciadas preservando releases sólo en los extremos exteriores (rechaza barras ya cargadas para evitar ambigüedad de remapeo). `Section` recibe campos `i` (radio de giro) y `eu_class` (1..4 EN 1993-1-1). `Model.stats()` separa `nodal_loads` y `distributed_loads`. (2) `solver.py` traduce `model.distributed_loads` a `fem.add_member_dist_load(member, direction, w1, w2, x1, x2, case)`. (3) `materials.py` — catálogo `MATERIALS` con S235JR/S275JR/S355JR (E=210 GPa, ν=0,3, G=80,77 GPa, ρ=7850 kg/m³ por EN 1993-1-1 §3.2.6 + EN 1991-1-1 A.4; fy/fu por EN 10025-2 t≤16 mm); helpers `get_material` / `register_material`. (4) `sections.py` — catálogo `SECTIONS` con CHS Ø48,3×3,2 / Ø48,3×4,0 / Ø60,3×3,2; helper `make_chs_section(name, D, t, fy)` calcula A, I, J, Wel, Wpl=(D³−d³)/6, i=√(I/A), `classify_chs(D, t, fy)` aplica Tabla 5.2 EN 1993-1-1 (D/t ≤ 50ε² / 70ε² / 90ε² con ε²=235/fy_MPa). Los tres CHS son clase 1 con S235JR. (5) `calc/loads/` — `self_weight.apply_self_weight(model, g=9.81, case="D")` registra w=ρ·A·g en FZ negativa por barra; `service_load.apply_service_load(model, ledger_ids, klass="Q3", deck_width, n_ledgers_per_pair=2, case="L")` aplica Q1..Q6 EN 12811-1 Tabla 3 como w=q·b/n por ledger (caller pasa los ids; detección automática queda para Fase 3). (6) `tests/test_viga_apoyada.py` — viga simplemente apoyada AC, L=4 m, subdividida en N=4 sub-elementos: 6 tests pytest que verifican δ=−5qL⁴/(384EI), M=qL²/8, R=qL/2 con carga uniforme manual y con peso propio (ambos error 0,0000 % por exactitud nodal Bernoulli-Euler con vector consistente), valores correctos de `apply_self_weight` y `apply_service_load`, rechazo de subdivisión sobre barra cargada. **10/10 PASSED** (4 Fase 1 + 6 Fase 2). |
| 0.5.2 | **FEM — Fase 3 (viento + imperfecciones + combinaciones)**: (1) `calc/loads/wind.py` — modelo EN 1991-1-4 §4.3-§4.5: `roughness_factor(z, terrain)` con tabla `TERRAIN_PARAMS` 0/I/II/III/IV (z₀, z_min) y k_r=0,19·(z₀/z₀,II)^0,07; `turbulence_intensity` y `peak_velocity_pressure(z, terrain, v_b, c_o, k_l, rho_air)` con clamp z≥z_min; constantes `RHO_AIR=1,25` y `SPAIN_BASIC_WIND={"A":26, "B":27, "C":29}` (CTE DB-SE-AE Anejo D); `apply_wind_load(model, member_ids, *, diameter, c_f=1,3, terrain, v_b, direction="FX", case="W")` aplica carga lineal `w=c_f·q_p(z_mid)·D` evaluando q_p en el midpoint de cada barra. (2) `calc/loads/imperfections.py` — EN 1993-1-1 §5.3.2: `imperfection_angle(h, m=1)` calcula φ=φ₀·α_h·α_m con φ₀=1/200, α_h=clamp(2/√h, 2/3, 1), α_m=√(½(1+1/m)); `apply_horizontal_imperfection(model, vertical_loads, *, h, m=1, direction="FX", case="I")` añade NodalLoad horizontal H_i=φ·V_i (caller pasa el reparto de cargas verticales por nodo). (3) `calc/combinations.py` — EN 1990 §6.10 + §6.14a/6.15a/6.16a: defaults γ_G=1,35 / γ_Q=1,5 / ψ_0={"L":0,7,"W":0,6} / ψ_1={"L":0,7,"W":0,2} / ψ_2={"L":0,6,"W":0,0}; `uls_eq_6_10(include_uplift=True)` genera ULS_LeadL, ULS_LeadW y ULS_Uplift (γ_G,inf=1,0 con W=γ_Q·1,5); `sls_characteristic` / `sls_frequent` / `sls_quasi_permanent` con leading=L; `standard_combos()` devuelve el set ULS+SLS completo. Las imperfecciones (caso "I") se factorizan con γ_G en ULS y 1,0 en SLS por estar atadas al peso propio. (4) `tests/test_wind_imperfections.py` — 27 tests pytest: q_p(10,II,vb=26)=993,84 Pa contra cálculo manual; clamp z<z_min; α_h con clamp superior (h<4) e inferior (h≥9); α_m=√0,75 (m=2), √0,625 (m=4); aplicación correcta de imperfections y wind sobre Model; factores ULS/SLS contra defaults; **integración solver** — poste empotrado L=4 m con D+W+I bajo combo ULS_LeadW: reacción vertical = γ_G·q_self·L y horizontal = γ_Q·w_wind·L+γ_G·H_imperf con error <0,5 %. **37/37 PASSED** (4 Fase 1 + 6 Fase 2 + 27 Fase 3). |
| 0.5.3 | **FEM — Fase 4 (comprobaciones EN 1993 + EN 12811 + EN 74 + releases)**: (1) `calc/checks/en1993_1_1.py` — capacidades sección §6.2: `tension_resistance` (A·fy/γ_M0), `compression_resistance` (clase 1-3), `bending_resistance` (Wpl·fy clase 1-2 / Wel·fy clase 3), `shear_resistance` para CHS (A_v=2A/π por Eq. 6.22). Pandeo §6.3.1.2: tabla `ALPHA_BUCKLING` con curvas a₀/a/b/c/d, `non_dimensional_slenderness(section, material, L_cr)` usa `Section.i`, `chi_buckling(λ̄, curve="c")` aplica Eq. 6.49 con χ=1 para λ̄≤0,2. **Default curva c (α=0,49)** porque tubos de andamio son típicamente conformados en frío (Tabla 6.2). Interacción flexo-compresión §6.3.3: como CHS son bisimétricos (χ_y=χ_z) y sin LT-buckling, las Eq. 6.61/6.62 colapsan en `n + k_yy·m_y + k_zy·m_z ≤ 1` con k_zy=0,6·k_yy (Anexo B Tabla B.1, C_my=C_mz=0,9 conservador). `SectionCheck` dataclass agrega utilizaciones por chequeo y `worst()`. γ_M0=γ_M1=1,0 por defecto (recomendado §6.1, override en AN). (2) `calc/checks/en12811.py` — `check_deflection_limit(δ, L, limit_factor=1/100)` para δ ≤ L/100 (plataforma) y L/200 (viento); cargas mínimas barandillas §7.2.1 (300 N horizontal, 0,5 kN vertical). (3) `calc/checks/joints.py` — catálogo `JOINT_CAPACITIES` con `LAYHER_ALLROUND_M` (F_t=18 kN, F_c=70 kN, V=28 kN, M=9 kN·m, K_φ=80 kN·m/rad) y `LAYHER_ALLROUND_HEAVY` (+30 %); `check_joint(N, V, M, joint, gamma_M2=1,25)` con interacción cuadrática `(N/N_Rd)²+(V/V_Rd)²+M/M_Rd≤1` (γ_M2 EN 1993-1-8). (4) `calc/releases.py` — presets `rigid` / `pinned` (libera RY+RZ) / `axial` (libera RX+RY+RZ); `set_releases_by_type(model, *, pole="rigid", ledger="rigid", brace="pinned", tie="pinned")` aplica masivamente por `member_type`. **Default brace="pinned"** (no "axial") para evitar k22 singular en PyNite cuando una diagonal queda en plano. (5) `calc/checks/__init__.py` — pipeline `run_all_checks(model, results, *, L_cr_factor=1.0, L_cr_overrides, curve_by_type, …)` itera barras del modelo, mapea axial+momentos+cortantes a `check_section_resistances` y devuelve `dict[member_id → MemberCheckResult]`. (6) **Fix solver.py — convención axial**: PyNite reporta axil con compresión-positivo (verificado con voladizo a tracción explícita); el wrapper invierte el signo `axial_max=-py_min`, `axial_min=-py_max` para que `MemberResult` sea tracción-positivo (estándar EN 1993). (7) `tests/test_checks.py` — 30 tests pytest: capacidades sección contra fórmulas; χ contra cálculo manual para 5 curvas a λ̄=1,5; N_b,Rd L=2 m curva c ≈ 40 kN; interacción pura compresión = N_Ed/N_b,Rd; pura flexión sin axil = C_my·M/M_Rk; deflexión δ=L/100 → util=1; joint Layher en tracción pura → util=γ_M2=1,25; releases por tipo aplicados correctamente; **pipeline integrado** — voladizo CHS L=3 m / P=10 kN compresión: util compresión y pandeo coinciden con cálculo manual <1 %. **68/68 PASSED** (4 Fase 1 + 6 Fase 2 + 27 Fase 3 + 31 Fase 4). |
| 0.7.1 | **Plano CAD normativo UNE-EN ISO 129-1**: el plano ahora cumple las reglas básicas de un delineante experto (siguiendo `prompt_acotacion_andamios.md`) en vez de volcar cotas crudas. (1) Nuevo módulo puro `calc/cad_dim.py` con catálogos Layher modulares (`LAYHER_BAY_LENGTHS_M = (0.73, 1.09, 1.40, 1.57, 2.07, 2.57, 3.07)`, `LAYHER_FLOOR_HEIGHTS_M = (1.0, 1.5, 2.0)`, `LAYHER_POLE_LENGTHS_M`) y escalas normalizadas `(20, 50, 100, 200, 500)`. (2) `consolidate_coords(values_m, tol_mm=5)` fusiona montantes a < 5 mm en un único representante (resuelve antipatrón A: líneas duplicadas a < 1 mm) — redondeo a múltiplos de 5 mm. (3) `snap_to_modular(length, steps, tol_mm=10)` snapea longitudes a la modular más próxima si entra en tolerancia (evita cotas espurias 1973 / 1752 mm cuando lo correcto es 2070). (4) `build_segments(consolidated_coords)` produce lista de `Segment` con `modular`/`is_compensator`. (5) `group_chain(segments)` agrupa segmentos modulares idénticos consecutivos en `ChainGroup` con notación `"5 × 2070 = 10350"`. Compensadores nunca se agrupan. (6) `pick_normalized_scale(bbox_w, bbox_h, avail_w, avail_h)` elige la más fina de {1:20, 1:50, 1:100, 1:200, 1:500} que cabe; el alzado frontal manda la escala y planta + lateral comparten via `fixed_scale_denom`. (7) `axis_labels_alpha(n)` y `axis_labels_numeric(n)` generan A/B/C/.../AA/AB y 1/2/3/... (8) `prepare_dimension_chain` API completa: consolida + snap + agrupa → `DimensionChainSpec(coords_m, segments, groups, total_mm, has_compensators)`. (9) Reescritura de `cad_plan._draw_view`: tres cadenas jerárquicas — A EJES (notación abreviada con compensadores en rojo y etiqueta "compens.") + TOTAL (`"<total> mm"`, fuente 3.5, ext_above=2). Helpers `_draw_dim_chain` / `_draw_dim_chain_v` consumen los `ChainGroup`. (10) `_draw_axis_labels` dibuja burbujas blancas con borde azul ISO + letra/número (radio 3.5 mm, font 3.0). (11) Tipografía mejorada: título de vista 4.5 (≈ 5 mm en papel), cifras de cota 3.0 (≥ 2.5 mm normativos), separación entre cadenas ≥ 9 mm (cumple ISO 129-1 §5.4 ≥ 7 mm). (12) Etiqueta "Esc. 1:N" dentro de cada vista. Cajetín muestra la escala global del alzado frontal. (13) `tests/test_cad_dim.py` — 27 tests pytest: consolidación de duplicados, snap modular Layher parametrizado, redondeo a 5 mm, segmentos modulares + compensadores correctos, agrupación N×L=T (5 × 2070 = 10350), compensadores no agrupados, escala normalizada elige la más fina que cabe, etiquetas alfa con overflow (AA, AB), pipeline completo con duplicados a < 5 mm que se fusionan automáticamente. **Smoke test** sobre U-shape: plano de 101 KB con escala 1:50 detectada, globos de eje dibujados, compensadores etiquetados; los tests unitarios validan que la notación abreviada N×L=T aparece cuando hay crujías idénticas repetidas. **280/280 PASSED**. |
| 0.7.0 | **UI Refactor — sub-paneles colapsables**: el panel de Cálculo Estructural pasa de un único panel monolítico (8 secciones en columna) a 7 paneles jerárquicos colapsables nativos de Blender, mejorando la usabilidad considerablemente. (1) `ANDAMIOS_PT_calc` queda como **panel raíz** con sólo el workflow header (3 etapas). (2) `_SubPanelBase` mixin con `bl_parent_id="ANDAMIOS_PT_calc"` + `bl_space_type='VIEW_3D'` + `bl_region_type='UI'` + helpers `_has_design`/`_has_results` para los `poll()`. (3) **6 sub-paneles**: `ANDAMIOS_PT_calc_loads` (Cargas + combinación, abierto), `ANDAMIOS_PT_calc_run` (botones ejecutar/restaurar con `scale_y=1.3` para que destaque), `ANDAMIOS_PT_calc_results` (status + lista críticos, sólo si hay último cálculo), `ANDAMIOS_PT_calc_visualization` (modo color + deformada + localizar, sólo tras cálculo), `ANDAMIOS_PT_calc_autofix` (DEFAULT_CLOSED), `ANDAMIOS_PT_calc_export` (DEFAULT_CLOSED, los 3 export buttons agrupados). (4) `poll()` por sub-panel: loads/run/autofix/export requieren `_has_design`; results/visualization requieren `_has_results` (tras pulsar Ejecutar). Los sub-paneles que dependen del cálculo aparecen y desaparecen automáticamente. (5) Helpers `_draw_*` del panel raíz se reusan desde los sub-paneles vía `ANDAMIOS_PT_calc._draw_status(...)` y `ANDAMIOS_PT_calc._draw_failures_list(...)` — sin duplicación de código. (6) Orden de registro respeta `bl_parent_id`: panel raíz primero, sub-paneles después. **Smoke test Blender**: 7 paneles registrados en `bpy.types`; antes del cálculo poll() devuelve True para 4 paneles (loads/run/autofix/export) y False para 2 (results/visualization); tras `calc_run` los dos restantes pasan a True. **253/253 PASSED**. |
| 0.6.9 | **CAD: cotas mm + cadena entre puntos de referencia + validación**: el plano CAD ahora se cota como un plano técnico real, no sólo el bbox total. (1) `_format_mm(distance_m)` produce strings tipo `"5000 mm"` (sin decimales para ≥ 100 mm) — convención técnica. Reemplaza el formato anterior `"5.00 m"`. (2) `_chain_dim_h(svg_xs, y_dim, segment_labels)` y `_chain_dim_v` dibujan **cadena de cotas** entre puntos consecutivos: línea principal con flechas tipo polygon entre cada par + líneas auxiliares de extensión + etiqueta centrada. Los `_dim_line_h/_dim_line_v` también ganaron parámetro `ext_above`/`ext_right` para extension lines. (3) `_draw_view` acepta `chain_dim_x` y `chain_dim_y` (listas de coordenadas mundiales): produce 2 niveles de cota en cada vista — la cadena de segmentos a 7 mm del bbox + la cota total a 13 mm. (4) Helpers `extract_reference_points_3d(scene)` lee los empties del `path_points`, `extract_floor_heights(scene)` calcula niveles Z absolutos a partir de `base_z + i·floor_h`, `extract_pole_levels(lines, axis)` detecta los X/Y únicos donde hay postes. (5) `build_validation_summary(scene)` lee custom props del último `calc_run` y produce dict con level/status/details (`"util max 0.55 · δ máx 14 mm · 0/71 fallos · ULS_LeadL · Q3 · viento A"`). (6) `_title_block` extendido con parámetro `validation`: la última fila se pinta con fondo coloreado según level (verde/ámbar/rojo) + texto del status + detalles + título "VALIDACIÓN ESTRUCTURAL · EN 1993-1-1 + EN 12811-1". (7) `generate_cad_svg` recibe los nuevos params (reference_points_3d, floor_heights, pole_x_levels, pole_y_levels, validation) y los reparte por vistas: alzado frontal cota X de postes + Z de plantas; planta cota X+Y de postes y referencia; alzado lateral cota Y de postes + Z de plantas. (8) Operador `calc_cad_export` enlaza extract_reference_points_3d, extract_floor_heights, extract_pole_levels, build_validation_summary y los pasa al generate_cad_svg. **Smoke test U-shape** detecta 4 puntos de referencia + 7 niveles X de postes + 4 niveles Y + 2 niveles Z (1 planta de 2 m). El plano resultante (96 KB) muestra cota total + cadena de 6 segmentos en X del alzado y 3 en Y de la planta + caja VALIDACIÓN verde con util/δ/fallos. **253/253 PASSED**. |
| 0.6.8 | **Plano CAD vectorial estilo NX + rosetas en BOM**: (1) Nuevo módulo `calc/cad_plan.py` que genera SVG vectorial de hoja A3 horizontal (420×297 mm). Helpers puros: `paper_dims`, `project_to_view` (front/side/top), `bbox_of_lines`, `fit_in_rect` (calcula transform centrando con padding), `project_world_to_svg` (invierte Y porque SVG va arriba→abajo). Estilos por categoría: postes negro 0,8 mm, ledgers floor 0,6, rails gris 0,35, braces azul 0,55, ties rojo. Las plataformas/escaleras se omiten (no son tubos lineales). (2) Cotas dimensionales automáticas con `_dim_line_h`/`_dim_line_v` que dibujan línea con flechas tipo polygon en los extremos + etiqueta centrada en la dimensión total del bbox de cada vista (ancho horizontal + alto vertical). (3) Cuadro de rotulación tipo NX `_title_block` con 6 filas: Proyecto/Empresa, Título del plano, Fecha/Escala/Autor/Revisión, Material, Peso/Piezas/Hoja/Formato, firma. Escala calculada del transform (1 mm SVG / scale_mm_per_m × 1000). (4) Tabla BOM integrada `_bom_table` con cabecera + fila por categoría (Categoría, Cant., Tubo m, Peso) + fila TOTAL en negrita. (5) Layout: alzado frontal arriba-izquierda (58 % ancho × 55 % alto), planta abajo-izquierda, alzado lateral arriba-derecha, BOM medio-derecha, rotulación abajo-derecha. Marco doble de hoja. (6) `wrap_in_html(svg)` envuelve el SVG en HTML con `@page size: A3 landscape; margin: 0` para impresión PDF a tamaño real (Chrome/Firefox respetan el tamaño físico). Toolbar superior con instrucciones (Ctrl+P, márgenes ninguno, escala 100 %) que se oculta con `@media print`. (7) `extract_scaffold_lines_3d(scene)` recorre la colección Scaffold y produce list de dicts con `p1, p2, category, name`, filtrando los no-tubo. (8) `andamios.calc_cad_export` operador con FileSelect; botón en panel "Exportar plano CAD (HTML)" con icon OUTLINER_OB_LATTICE. (9) **Rosetas añadidas al BOM**: la roseta es pieza de catálogo independiente (Layher Allround Ø120 mm, ~0,6 kg) que se pide al fabricante. Antes se filtraba como decorativa; ahora `category_for_name("Rose_*") == "rosette"` y `ESTIMATED_WEIGHT_KG["rosette"] = 0.6`. CATEGORY_LABELS["rosette"] añade la descripción. Tests actualizados: rosetas pasan a `test_rosettes_included_in_bom`, fuera de las decorativas. **Smoke test U-shape**: BOM ahora 297 piezas / 1311 kg (antes 165/1232) con +132 rosetas a 0,6 kg = +79,2 kg. Plano CAD se genera en 86 KB de HTML/SVG autocontenido — 33× más ligero que el render raster (2,85 MB) y vectorial (imprimible nítido a cualquier resolución). **253/253 PASSED**. |
| 0.6.7 | **Vistas globales + plano CAD en el informe**: el informe HTML de cálculo ahora incluye una sección "Vistas del andamio" con 5 imágenes capturadas automáticamente del modelo: isometría 3/4 perspectiva, alzado frontal ortográfico, alzado lateral ortográfico, planta ortográfica (con relación de aspecto adaptable al bbox), y plano técnico CAD-style desde isometría con shading `light='FLAT'` + `color_type='SINGLE'`. (1) `calc/screenshots.py:capture_overview_view(scene, view, size, ortho, cad_style)` posiciona cámara temporal según el bbox global de la colección Scaffold (`_scaffold_world_bbox`), orientada según `_OVERVIEW_VIEW_DIRECTIONS` (iso=(1,-1,0.7), front=(0,-1,0), side=(1,0,0), top=(0,0,1)). Para vistas planas usa cámara ortográfica con `ortho_scale = diagonal × 1.15`; iso queda en perspectiva. Fondo blanco automático para informes. CAD-style modifica `display.shading` temporalmente y restaura al terminar. (2) `capture_overview_set(scene, size=800, include_cad=True)` produce dict `{iso, front, side, top, cad}`. (3) `calc/report.py:_overview_views_html(overview_screenshots)` renderiza un grid `auto-fit minmax(380px,1fr)` con figuras tipo `<figure><img/><figcaption/></figure>`. CSS añade `.overview-figure` con sombra suave + caption en barra azul. (4) `generate_html_report` recibe nuevo param `overview_screenshots`. La sección "Vistas del andamio" aparece justo tras el resumen ejecutivo, ANTES de "Cómo leer este informe", para dar contexto visual del modelo analizado. (5) `calc_report` operator captura las overviews via `capture_overview_set(scene, size=800)` y las pasa al report. **Smoke test**: informe del U-shape andamio crece a 2,85 MB con 5 imágenes globales + 0 tarjetas de fallo (el cálculo cumple). Las 4 vistas planas son ortográficas tipo plano técnico, la iso es perspectiva 3D, el CAD-style usa shading plano para look de plano de ingeniería. **253/253 PASSED**. |
| 0.6.6 | **BOM — Lista de materiales exportable a HTML**: nuevo módulo `calc/bom.py` (puro, sin bpy) y `calc/bom_report.py` (HTML autocontenido) que generan documentación de suministros para subcontratistas. (1) `category_for_name(name)` clasifica objetos del Scaffold por prefijo: pole, ledger_floor (Ledger_F/B/T/TC), ledger_rail (Rail_*), toe, brace, tie, plank (Deck_/Plank_/Corner_Plank_), trapdoor (Lid_/Trapdoor_), ladder, husillo. **Excluye decorativos** Rose_/Hinge_/LidHandle_ y sub-piezas duplicantes (Ladder_*_rail_b, Ladder_*_step_*) — solo `_rail_a` cuenta como una escalera ensamblada. (2) `tube_weight_kg(L)` con ρ=7850 + A=4,534·10⁻⁴ (≈3,56 kg/m). (3) `enumerate_scaffold_objects(scene)` recorre la colección Scaffold, lee deck_id de los planks (consulta el catálogo Ringlock EU del addon principal vía `andamios_addon._RINGLOCK_DECK_CATALOG`). (4) `aggregate_bom(items, length_round_m=0.05)` agrupa tubos por (categoría, longitud redondeada) y plataformas por deck_id; `summarize_bom(groups)` calcula peso total, piezas totales, metros lineales de tubo y breakdown por categoría. (5) `representative_member_per_category(items)` elige el objeto más pesado de cada categoría como representante para la "foto promocional". (6) `bom_report.generate_bom_html(groups, summary, screenshots)` produce HTML con CSS embebido: resumen en grid (peso total / piezas / m de tubo / categorías), tabla breakdown por categoría con %, sección detallada por categoría con foto + descripción + tabla de tipos agrupados, glosario al final. (7) `andamios.calc_bom_export` operador con FileSelect y panel button "Exportar BOM HTML" en la sección de acciones (icon LINENUMBERS_ON). Captura una foto representativa por categoría con `screenshots.capture_failures_batch` (mismo flujo de highlight). (8) `tests/test_bom.py` — 18 tests pytest: categorización parametrizada con 21 nombres reales del addon, exclusión de decorativos (rosetas, bisagras, sub-piezas de escalera no-rail_a), peso lineal coincide con catálogo Layher (3,56 kg/m), agrupación por longitud redondeada, distinción de longitudes alejadas, agrupación de plataformas por deck_id, summary con peso/piezas/longitud totales, orden por categoría. **Smoke test U-shape**: 165 piezas / 1232 kg, breakdown realista (12 postes 214 kg, 32 travesaños 201 kg, 64 barandillas 361 kg, 28 rodapiés 15 kg, 3 cruces 33 kg, 18 plataformas 271 kg, 4 trampillas 74 kg, 4 escaleras 64 kg). Informe generado en ~2,3 MB con foto por categoría. **253/253 PASSED**. |
| 0.6.5 | **UX — Auto-corrección iterativa estilo ANSYS**: nuevo módulo `calc/autofix.py` (puro, sin bpy) y dos operadores que prueban sucesivamente cambios de diseño hasta lograr cumplimiento. (1) `BAY_STEPS = (3.07, 2.57, 2.07, 1.57, 1.40, 1.09, 0.73)` y `POLE_SEG_STEPS = (4.0, 3.0, 2.0, 1.5, 1.0, 0.5)` — pasos descendentes inspirados en catálogo Layher. (2) `next_lower_step(value, steps)` devuelve el step inmediatamente menor o None si ya está al mínimo. (3) `decide_next_fix(props_state, failures)` función pura con estrategia priorizada: (a) activar `add_braces` si está off, (b) activar `add_horizontal_braces` idem, (c) si pandeo domina o postes son mayoría → reducir `pole_segment_length`, (d) forzar `bay_length_catalog="UNIFORM"` si está en LAYHER y luego reducir `bay_length`, (e) si todo al mínimo → None. Devuelve dict `{prop, before, after, action}`. (4) `snapshot_props(props)` y `restore_props(props, snap)` capturan/restauran las 6 props relevantes. (5) `calc/ui.py:ANDAMIOS_OT_calc_autofix` operador que itera hasta 8 veces: ejecuta calc_run, lee status, si `util_max < 0.95` y `n_failed == 0` declara éxito; si no, llama a `decide_next_fix`, aplica el cambio sobre `props` y llama a `bpy.ops.andamios.generate()` para regenerar. Persiste snapshot inicial en `scene["calc_autofix_snapshot"]` y log de iteraciones en `scene["calc_autofix_history"]`. (6) `ANDAMIOS_OT_calc_autofix_revert` deshace todos los cambios desde el snapshot inicial y regenera. (7) Panel: nueva caja "Auto-corrección iterativa" con botón Auto-corregir + botón Revertir (sólo cuando hay snapshot) + listado del historial ("#1: util_max=1.42, fallos=3", "  → Activar cruces de arriostramiento", "✓ Convergió en 2 iteraciones"). (8) `tests/test_autofix.py` — 16 tests pytest: `next_lower_step` con valores en y entre steps, prioridades a/b cruces, pandeo+pole reduce pole_seg, flexión+ledger reduce bay_length, UNIFORM forzado antes de bajar bay, combinada+pole con pandeo prefiere pole_seg, mayoría ledgers reduce bay; sin más opciones devuelve None; sin fallos devuelve None; **simulación iterativa convergente** que aplica los fixes hasta None; snapshot y restore con dummy props. **Smoke test Blender**: andamio U-shape con Q6+viento C inicialmente al 99% util converge en 1 iter activando cruces (util→0.83); revert restaura el estado inicial. **213/213 PASSED**. |
| 0.6.4 | **UX — resalto visual en screenshots del informe**: cada foto del informe muestra ahora el elemento protagonista en rojo brillante con el resto del Scaffold en gris claro neutro, para identificar al instante la barra de la que habla cada tarjeta. (1) `calc/screenshots.py:_ensure_highlight_materials()` crea/reutiliza `Calc_Highlight_Gray` (0,78×3) y `Calc_Highlight_Hot` (1,0/0,2/0,1). (2) `capture_failures_batch` reescrito con sesión de highlight: snapshot del material slot 0 de cada objeto del Scaffold, aplica gris a todos, luego para cada miembro target aplica hot y captura, vuelve a gris para no afectar a la siguiente captura, y al final restaura todos los materiales originales. (3) `_set_scaffold_visible_temporarily` + `_restore_scaffold_visibility` aseguran que la captura funcione aunque la deformada esté activa (Scaffold oculto → visibilidad restaurada al estado previo). (4) Si no hay colección Scaffold, fallback al modo sin highlight. **Smoke test verificado**: 8 imágenes capturadas con resalto, materiales originales restaurados (Andamio_Postes intacto), sin leak de `Calc_Highlight_*`. |
| 0.6.3 | **FIX CRÍTICO — Conectividad FEM (uniones a media barra)**: Bug detectado al observar la deformada — muchas vinculaciones del andamio no estaban siendo capturadas por el solver. Específicamente, los **mid-rails y top-rails de barandilla** atan al poste a alturas intermedias entre segmentos pero el `extract_model` original sólo fusionaba nodos en los EXTREMOS de los tubos, dejando las uniones a media barra como elementos independientes y haciendo que el FEM tratara los postes como si no recibieran rigidez de las barandillas. (1) `calc/pipeline.py:weld_close_nodes(model, *, tol=5e-3)` — fusiona pares de nodos a distancia ≤ 5 mm (margen frente al ruido floating-point en operaciones geométricas con esquinas y bisectrices); para cada cluster elige un representante y redirige todas las referencias en miembros, soportes y cargas nodales; elimina miembros degenerados (i==j) junto con sus cargas distribuidas. (2) `calc/pipeline.py:weld_mid_span_attachments(model, *, tol=5e-3, margin=0.05, max_iterations=6)` — detecta nodos del modelo que caen sobre la línea media de un miembro (entre 5 % y 95 % de la longitud, distancia ≤ tol) y parte ese miembro en dos sub-piezas conectadas a través del nodo. Itera hasta que no hay más uniones que crear (un split puede crear miembros que a su vez tengan uniones intermedias). Helper `_split_member_at_existing_node` preserva las releases sólo en los extremos exteriores; las uniones interiores son siempre continuas. (3) `build_and_solve` ejecuta `weld_close_nodes` y `weld_mid_span_attachments` ANTES de `auto_add_base_supports` y de aplicar cargas (Model.split_member rechaza barras ya cargadas). (4) `tests/test_connectivity.py` — 12 tests pytest: weld de 2 nodos a 2 mm fusiona correctamente, mantiene separados los lejanos, elimina miembros degenerados, redirige soportes/cargas nodales; mid-span split de un poste con tie a media altura, no toca extremos dentro del margen, itera correctamente con 2 ataches a 2 m y 4 m, preserva releases brace="pinned" sólo en extremos exteriores; `build_and_solve` ejecuta los welds automáticamente. **Smoke test U-shape con 4 puntos de polilínea**: ANTES 47 miembros / util 2,53 / δ 51,1 mm / 8 fallos · DESPUÉS 71 miembros (24 splits, todos en postes) / util 0,55 / δ 14,4 mm / 0 fallos. La estructura es **4,6× más rígida en utilización** y **3,5× menos deformable** porque las 24 uniones poste↔mid-rail/top-rail ya están en el modelo. **197/197 PASSED**. |
| 0.6.2 | **UX — Fase F (informe HTML rediseñado + screenshots automáticos)**: (1) Nuevo módulo `calc/screenshots.py`: `capture_member_screenshot(scene, member_id, *, size=600)` crea cámara temporal en vista 3/4 isométrica encuadrando el bbox del objeto (distance = diagonal × 4, mín 2 m, lente 35 mm), configura render a `BLENDER_WORKBENCH` (rápido, headless-compatible — `OpenGL` falla en --background), renderiza a fichero temporal y devuelve los bytes PNG. Restaura toda la configuración de render previa. Fallback al duplicado deformado `<obj>_def` si Scaffold está oculto. `capture_failures_batch` itera, `png_to_base64_data_url` produce string `data:image/png;base64,…` para embeber en HTML. (2) `calc/report.py` rediseñado completo (+520 líneas) con CSS embebido (~2 KB) y 7 secciones nuevas: **Resumen ejecutivo** con círculo de semáforo (✓/⚠/✗) en color + título grande ("ANDAMIO SEGURO" / "MARGEN AJUSTADO" / "ATENCIÓN: NO CUMPLE") + subtítulo narrativo + métricas resumen; **Cómo leer este informe** card en azul claro con párrafo introductorio para no-experto; **Configuración del cálculo** card con tabla de 4 filas que traduce las opciones a plano ("Q3 — uso general (≈4 trabajadores)", "viento moderado zona A, terreno II", "Tolerancias EN 1993-1-1 §5.3 ≈0,5%", "Resistencia con viento dominante 1,35 G + 1,05 L + 1,5 W"); **Resumen de comprobaciones** con grid de 4-5 metric-cards (analizadas / OK holgadas / cerca del límite / sobrepasadas / δ_max si hay deflections); **Elementos críticos** con tarjetas 320×auto que combinan imagen del miembro (320 px aspect-ratio 1) + cabecera con id + badge de severidad coloreado + meta (util/tipo/sección/L) + secciones "¿Qué le pasa?" + "¿Cómo corregir?" usando `diagnose_failure`; separadas en "Sobrepasados" + "Cerca del límite"; **Tabla detallada** con buckets coloreados para auditoría; **Glosario** con 11 entradas (utilización, ULS/SLS, compresión, pandeo, flexión, tracción, combinada, deformación, Q1..Q6, zonas viento) en plano. (3) Operador `andamios.calc_report` actualizado: identifica los hasta 20 miembros más utilizados (≥0,85), llama a `capture_failures_batch`, convierte los PNG a data URLs y pasa todo al `generate_html_report`. Reporta `"… (N imágenes)"` al usuario. (4) `tests/test_report.py` reescrito (16 tests): resumen ejecutivo presente, sección Cómo leer, configuración con descriptions correctas, métricas con todas las cajas, deflections agregadas, tarjetas tienen ¿Qué le pasa?/¿Cómo corregir?, imagen embebida cuando se pasa screenshots, "Imagen no disponible" cuando no, modelo seguro no muestra tarjetas, tabla detallada con buckets, glosario con términos clave (Utilización, Pandeo, Compresión, EN 12811), escapado de ids con caracteres especiales, top_n > n_total no rompe, combo desconocido aparece literal. **Smoke test Blender headless**: andamio U-shape con 8 fallos genera informe de 3 MB con 8 tarjetas + 8 imágenes embebidas en base64 (375 KB cada una a 600×600), captura completada en ~3 s. **185/185 PASSED**. **Cierre del ciclo de UX (Fases A-F).** |
| 0.6.1 | **UX — Fase E (diagnóstico heurístico) + mejora deformada (bucket 0 gris)**: (1) `calc/pipeline.py:diagnose_failure(check, member_type)` función pura que devuelve `{type, severity, severity_label, why, fix}` con explicación en plano de qué le pasa al elemento y qué cambiar para corregirlo. Tabla `_DIAGNOSTICS_BY_TYPE` con textos específicos por (tipo de fallo × tipo de miembro): pole+pandeo→"reducir altura libre / Ø60×3,2 / S355", ledger+flexión→"reducir bay_length / añadir travesaño intermedio", tie+tracción→"añadir más anclajes a fachada", brace+pandeo→"acortar diagonal / perfil reforzado", combinada+pole→"reducir axil con más postes o acortar vano por flexión". Fallback "_default" cuando member_type no está catalogado. Severidad 4 niveles: ok < 0,85 ≤ minor < 1,0 ≤ serious < 1,3 ≤ critical, con etiquetas "Holgado", "Margen ajustado", "Sobrepasado", "Muy sobrepasado". (2) `ANDAMIOS_FailureEntry` gana campos `severity`, `severity_label`, `why`, `fix`, `member_type`. `calc_run` populates con diagnose_failure pasando member_type del modelo. (3) Panel: bajo el botón "Localizar barra", nuevo box `_draw_failure_diagnosis` para la fila activa con cabecera severidad+util (alert si serious/critical), tipo de fallo, sección "¿Qué le pasa?" + texto wrap-eado de `why`, sección "¿Cómo corregir?" + texto wrap-eado de `fix`. Helper `_wrap_text(text, width=48)` parte líneas largas respetando palabras (Blender no tiene word-wrap nativo en labels). (4) **Mejora deformada**: `DEFORMED_COLORS[0]` cambia de verde brillante a gris (0,5,0,5,0,5) para que los miembros sin deformación apreciable actúen como contexto estructural sin competir visualmente con los que sí se deforman — se mantiene la silueta completa del andamio (resolviendo la pérdida de coherencia geométrica) y sólo destacan en color las zonas que se mueven. (5) `tests/test_diagnose.py` — 19 tests pytest: severidad parametrizada en 8 puntos críticos (incluyendo 0,85, 1,0, 1,3 — bordes), label traducido, pandeo+pole menciona "altura"/"Ø60", brace+pandeo menciona "diagonal", flexión+ledger menciona "travesaño"/"vano"/"luz", tracción+tie menciona "anclaje", combinada+pole menciona axil+flexión, member_type desconocido cae al _default sin mencionar tipos específicos, dict completo con todas las claves. **Smoke test Blender**: 8 entradas en calc_failures con campos why/fix/severity_label/member_type populados; los 3 peores (postes esquina) clasifican correctamente como combinada / Muy sobrepasado y reciben el texto específico para postes. **176/176 PASSED**. |
| 0.6.0 | **UX — Fase D (lista de fallos clicable) + mejora deformada (oculta Scaffold)**: (1) `calc/pipeline.py:classify_failure_basic(check)` — heurística pura que devuelve la etiqueta del componente dominante: tracción, compresión, pandeo, flexión, cortante o combinada; gana "combinada" si supera 1,0 o si está por encima del resto; empates resueltos por orden de prioridad pandeo > flexión > compresión > tracción > cortante. (2) Nuevo PropertyGroup `ANDAMIOS_FailureEntry(member_id, utilization, failure_type, coords_x/y/z)` registrado antes de `ANDAMIOS_Props`. ANDAMIOS_Props gana `calc_failures: CollectionProperty` y `calc_failures_index: IntProperty` para el UIList. (3) `calc/ui.py:ANDAMIOS_UL_failures` UIList con icono por tipo (EMPTY_SINGLE_ARROW compresión, FORWARD tracción, STICKY_UVS_LOC pandeo, MOD_CURVE flexión, MOD_BEVEL cortante, X combinada) + columna util (alert si >1) + etiqueta tipo. (4) Operador `andamios.calc_select_failure` con poll() que requiere ≥1 entrada: deselecciona todo, selecciona la barra de la fila activa (con fallback a su copia deformada `<obj>_def` si Scaffold está oculto), la pone como activa y llama `view3d.view_selected` para encuadrar la cámara. (5) `calc_run.execute` populates calc_failures con los miembros de util ≥ 0,85 (máx 20, ordenados desc), cada entrada incluye centroide del miembro para futuro framing por coords. `calc_restore` la limpia. (6) Panel: nueva sección "Elementos críticos (N)" con título alert si hay fallos, tabla con cabecera Barra/Util/Tipo, UIList template_list de 3-8 filas, botón "Localizar barra en viewport" (icono ZOOM_SELECTED). (7) **Mejora deformada**: `calc/deformed.py:_set_scaffold_visibility` activa/desactiva `coll.hide_viewport` y `layer_collection.hide_viewport` de la colección Scaffold. `build_deformed_overlay` la oculta automáticamente al construir la deformada (estilo ANSYS — sólo se ve la geometría desplazada). `clear_deformed_overlay` la restaura. (8) `tests/test_failure_classification.py` — 14 tests pytest: cada componente individual (tracción/compresión/pandeo/flexión Y/Z/cortante), combinada gana cuando ≥1 o > resto, combinada pierde si está por debajo individual, empates pandeo>compresión y flexión>compresión, casos realistas (poste con pandeo dominante, ledger con flexión dominante), dict vacío → "—". **Smoke test Blender**: andamio U-shape genera 8 entradas en calc_failures (los 8 fallos), select_failure selecciona Pole_BC_003 y lo hace activo, show_deformed oculta Scaffold y hide_deformed lo restaura. **157/157 PASSED**. |
| 0.5.9 | **UX — Fase C2 (deformada tipo ANSYS) + FIX crítico auto-soportes**: (1) Nuevo módulo `calc/deformed.py`: `store_tube_displacements(model, results)` persiste en cada objeto Blender un custom prop `_calc_disp = [dxi, dyi, dzi, dxj, dyj, dzj]` con los desplazamientos de sus dos extremos (permite reconstruir la deformada sin re-solver); `build_deformed_overlay(scene, scale)` lee la prop de cada tubo, calcula los extremos amplificados (×100 default), y crea duplicados en una colección `Scaffold_Deformed` con location/rotation/scale_z ajustados al segmento deformado; cada copia recibe material `Calc_Deformed_0..5` por bucket de magnitud δ/L (misma paleta que `viewport`); `clear_deformed_overlay(scene)` elimina la colección y libera meshes huérfanas. Los duplicados tienen `hide_select=True` para no interferir con la edición. (2) Dos operadores nuevos `andamios.calc_show_deformed` / `calc_hide_deformed` con poll que exige `_calc_disp` en al menos un objeto. (3) `ANDAMIOS_Props.calc_deformation_scale` FloatProperty (1×–1000×, default 100×) con tooltip "las deformaciones reales son de pocos milímetros — ×100 las hace visibles". (4) Panel: nueva sub-sección "Geometría deformada (vista ANSYS)" con slider + dos botones (mostrar/ocultar) + indicador "✓ Vista deformada activa" cuando la colección existe. (5) `calc_run` llama a `store_tube_displacements` siempre y reconstruye `Scaffold_Deformed` si ya existía (mantiene coherencia entre runs); `calc_restore` limpia la colección y los `_calc_disp`. (6) **FIX CRÍTICO — auto-soportes**: bug existente desde Fase 5: `extract_model.py` no añade soportes y `pipeline.build_and_solve` tampoco lo hacía → sistema FEM singular → desplazamientos NaN → reportado falsamente como "OK" porque comparaciones con NaN dan False. Solución: `pipeline.auto_add_base_supports(model)` empotra los nodos en z = z_min (caso típico: husillos sobre el suelo) si el modelo no tiene soportes ya. Añadido en `build_and_solve` antes del solve. Nuevo `_check_results_for_nan(results)` que tras solve verifica desplazamientos finitos y eleva RuntimeError con mensaje claro si encuentra NaN. (7) `tests/test_deformed.py` — 3 tests: `store_tube_displacements` con stub bpy escribe 6 floats por objeto, `_displacement_to_bucket` coincide con `pipeline.deflection_ratio_to_bucket`, longitud cero → bucket 0. `tests/test_ui_pipeline.py` ampliado: `auto_add_base_supports` empotra nodos z_min, respeta soportes ya existentes, `build_and_solve` sin soportes explícitos no produce NaN y devuelve reacciones finitas, NaN explícito en Results se detecta y se reporta. **Smoke test Blender embebido**: andamio U-shape 4 puntos genera 47 tubos, calc_run da util_max=2.53/δ_max=51 mm/8 fallos (antes: NaN silencioso), `Scaffold_Deformed` se crea con 47 tubos, `Calc_DeflMax_51.1mm` empty localiza el punto crítico. **143/143 PASSED**. |
| 0.5.8 | **UX — Fase C (visualización de deformaciones)**: (1) `calc/pipeline.py` — helpers puros para deformaciones: `_node_displacement_magnitude` (norma euclídea de DX/DY/DZ), `deflection_ratio_to_bucket` con tabla `DEFLECTION_RATIO_THRESHOLDS = (1/1000, 1/500, 1/300, 1/200, 1/100)` coherente con EN 12811-1 (postes L/200 + plataformas L/100); `compute_member_deflections(model, results)` recorre miembros y para cada uno produce `{max_disp_m, L, ratio, worst_node, bucket, label}` con etiquetas `DEFLECTION_BUCKET_LABELS` ("muy rígido" → "deformación excesiva"); `find_max_deflection_node(results)` localiza el nodo más desplazado; `deflection_summary(deflections)` agrega para el panel/informe (n_excessive, n_warning, worst_member, worst_ratio). (2) `calc/viewport.py` — refactor con `_ensure_palette_materials` genérico que se reusa para los dos modos; nuevo `apply_deflection_colors(deflections)` que crea materiales `Calc_Defl_0..5` (misma paleta verde→rojo de utilización para coherencia visual) y los asigna por bucket. (3) `andamios_addon.py:ANDAMIOS_Props.calc_color_mode` — EnumProperty {utilization | deflection} con tooltips en plano ("Rojo = deformación excesiva >L/100"). (4) `calc/ui.py` — el operador `calc_run` calcula `compute_member_deflections` siempre y `apply_deflection_colors` o `apply_check_colors` según el modo elegido; persiste resumen en custom props `calc_defl_*` (worst_member, worst_disp_m, worst_ratio, worst_label, n_excessive, n_warning, coordenadas del nodo peor); el report final incluye `δ_max NN.N mm`. (5) Nuevo operador `andamios.calc_locate_max_deflection` (icono OUTLINER_DATA_EMPTY) que crea un Empty tipo SPHERE de nombre `Calc_DeflMax_NN.Nmm` en las coordenadas del nodo peor, lo selecciona y centra la vista 3D con `view3d.view_selected`. `poll()` exige `calc_defl_worst_member` ya guardado. (6) Panel reorganizado con nueva sección "Visualización del resultado" justo antes de las acciones: dropdown `calc_color_mode` + resumen "δ máx: 12.3 mm (deformación moderada) · ≈ L/450 · 0 barra(s) > L/100" + botón "Localizar deformación máxima". `calc_restore` limpia las custom props de deformación y elimina los empties `Calc_DeflMax*` previos. (7) `tests/test_deflection_visualization.py` — 15 tests pytest: `deflection_ratio_to_bucket` parametrizado para cada bucket [0..5], umbrales 1/200 y 1/100 presentes, voladizo CHS Ø48,3×3,2 con P=1 kN da δ = P·L³/(3EI) en `compute_member_deflections` con error <0,5 %, `find_max_deflection_node` devuelve el extremo libre de un voladizo, `deflection_summary` agrega buckets correctamente (n_excessive bucket≥5, n_warning bucket≥3), maneja dict vacío y Results vacío sin reventar. **136/136 PASSED**. |
| 0.5.7 | **UX — Fase B (workflow guiado de 3 etapas)**: (1) `calc/pipeline.py:compute_workflow_state(n_structural, validation_level, …)` — función pura que devuelve estado de las 3 fases del flujo: `design ∈ {empty, ok}`, `validation ∈ {empty, ok, warning, fail}`, `report ∈ {blocked, available}`. Reglas: diseño OK con ≥1 barra estructural; informe disponible tras cualquier validación (incluso fallida — para documentar el problema); niveles desconocidos se tratan como "empty" sin error. (2) `calc/ui.py:_detect_workflow_state(scene)` cuenta tubos estructurales en la colección "Scaffold" filtrando por prefijos (Pole_F/B, Ledger_, Brace_, HBrace_, Tie_) y delega en `compute_workflow_state` la lógica de niveles. (3) `_draw_workflow_header` pinta arriba del panel un box "Pasos del cálculo" con 3 filas verticales: cada fase muestra icono según estado (CHECKMARK / ERROR / CANCEL / DOT / DOCUMENTS / LAYER_USED) + descripción en plano ("24 barras estructurales generadas", "✓ 24 barras OK · util max 0,62", "⚠ 3 cerca del límite · util max 0,93", "✗ 2 elemento(s) sobrepasados", "Listo para exportar HTML", "Esperando a que se complete la validación"). (4) **Callout iterativo**: cuando `validation.state == "fail"` aparece un box con `alert=True` titulado "Hay elementos sobrepasados" + lista de acciones concretas para volver al diseño y corregir (acortar altura libre, reducir vano, añadir cruces, perfil reforzado o S355). (5) Si `design.state == "empty"` el panel oculta cargas/combinación/acciones — sólo muestra el workflow para guiar al usuario a generar el andamio primero. (6) `tests/test_workflow.py` — 12 tests pytest: design empty/ok según n_structural, validation passes-through metrics y trata niveles desconocidos como empty, report blocked sin validación previa, report available para los 3 niveles válidos (incluido fail), escenario iterativo donde el último resultado persiste tras editar geometría. **121/121 PASSED**. |
| 0.5.6 | **UX — Fase A (estado en plano + tooltips claros)**: (1) `calc/pipeline.py:format_status_message(checks, options)` produce semáforo `level ∈ {ok, warning, fail}` + `title` (ANDAMIO SEGURO / ATENCIÓN: N sobrepasados / Margen ajustado) + `subtitle` con descripción narrativa del escenario aplicado ("uso general 200 kg/m² · viento moderado zona A · combinación ULS — viento dominante"). Umbrales: ok < 0,85 / warning 0,85-1,00 / fail > 1,00. Diccionarios `SERVICE_DESCRIPTION` y `WIND_DESCRIPTION` traducen Q1..Q6 y A/B/C a frases legibles. (2) `calc/ui.py:_draw_status` dibuja arriba del panel un box con icono CHECKMARK/ERROR/CANCEL según level + título + subtítulo (partido por '·' en líneas) + métricas (barras totales, util max, fallos/cerca-límite/holgado). El operador `andamios.calc_run` persiste el status en custom props `calc_status_*` del scene para que sobreviva entre redibujos. (3) **Tooltips reescritos** en las 8 props de cálculo con lenguaje no-experto: Q3 → "Trabajo habitual de fachada (≈4 trabajadores con herramienta)", zona A → "costa cantábrica e interior, viento moderado", imperfecciones → "considera que los postes nunca están perfectamente verticales · Aplica fuerza horizontal ≈0,5% del peso total". (4) `tests/test_status.py` — 10 tests pytest: niveles ok/warning/fail con umbrales correctos, plural correcto (1 sobrepasado vs 2 sobrepasados), modelo vacío genera level=warning sin reventar, subtítulo incluye descripción del servicio cuando activo y "sin carga de servicio" cuando off, viento dominante aparece en subtítulo de ULS_LeadW, fallback a literal cuando combo desconocido. **109/109 PASSED**. |
| 0.5.5 | **FEM — UI completa con cargas variables**: (1) `ANDAMIOS_Props` recibe 8 propiedades de cálculo: toggle + clase Q1..Q6 + ancho deck para servicio EN 12811-1; toggle + zona CTE A/B/C + categoría terreno 0-IV para viento EN 1991-1-4; toggle para imperfecciones EN 1993-1-1 §5.3; selector de combinación (ULS_LeadL / LeadW / Uplift / SLS char / freq / quasi). (2) Nuevo `calc/pipeline.py` (puro Python, sin bpy) con `is_deck_supporting_ledger` (heurística por nombre que excluye Mid/Top/Rail/_E_), `apply_imperfections_at_top(model)` que estima V_total de cargas distribuidas D+L sin pre-solve y aplica H = φ·V/n a los nodos superiores, y `build_and_solve(model, options)` que orquesta todo el flujo. (3) `calc/ui.py` queda como capa fina: `_options_from_props` y `_build_and_solve` delegan en `pipeline`. (4) Panel `ANDAMIOS_PT_calc` reorganizado con secciones "Cargas variables" / "Combinación" / "Acciones" / "Resultado" usando boxes y enabled-toggle por carga. (5) `tests/test_ui_pipeline.py` — 19 tests pytest: filtro `is_deck_supporting_ledger` con 8 nombres realistas, imperfecciones aplicadas a 2 nodos top con H = φ·V/n exacto, suma V_total incluye servicio, sin cargas verticales no genera imperfecciones, pipeline completo D+L+W+I sobre pórtico simple devuelve utilizaciones finitas, fallback a ULS_LeadL si combo desconocido, toggles desactivados omiten cargas, mid-rail filtrado correctamente del servicio, ULS_LeadW genera reacciones X+Z no nulas. **99/99 PASSED**. |
| 0.5.4 | **FEM — Fase 5 (viewport + report + UI + validación bibliografía)**: (1) `calc/viewport.py` — 6 buckets de color verde→rojo (umbrales 0,50 / 0,70 / 0,85 / 1,00 / 1,30); `apply_check_colors(checks)` crea/reutiliza materiales `Calc_Util_0..5`, reasigna el slot 0 de cada tubo y guarda el material original en custom property `_calc_orig_mat`; `restore_original_colors()` revierte. Mapeo `member_id → obj.name` por strip del prefijo `M_` que `extract_model.py` añade. (2) `calc/report.py` — generación HTML sin jinja2 (f-strings + `html.escape`): cabecera fecha → resumen modelo (stats por tipo) → combinación → resumen utilización → top N tabla coloreada por bucket → lista de fallos (>1.0). `write_html_report(path, model, results, checks)` escribe a fichero. CSS embebido coherente con los buckets del viewport. (3) `calc/ui.py` — panel "Cálculo estructural" en categoría Andamios del N-panel; tres operadores: `andamios.calc_run` (extract→releases→peso propio→solve→checks→colorear), `andamios.calc_restore` (restaura materiales), `andamios.calc_report` (FileSelect → HTML). Imports bpy diferidos para que el módulo sea importable fuera de Blender. (4) **Integración en `andamios_addon.py`**: `register()` llama opcionalmente a `calc.ui.register()` con try/except — si PyNite no está instalado el panel no aparece pero el resto del addon funciona. (5) `tests/test_validation_frame.py` — pórtico 1 vano × 2 plantas (L=3 m, h=2 m, q=0,8 kN/m sobre cada ledger), bases empotradas, ledgers articulados (releases ledger="pinned"): 6 tests verifican R_z=q·L=2,40 kN, R_FX=R_FY=0, axil pole inferior=−q·L=−2,40 kN, axil pole superior=−q·L/2=−1,20 kN, M_ledger=q·L²/8=0,90 kN·m con error 0,0000 % en todos (vector de cargas consistente Bernoulli-Euler). Pipeline integrado verifica que todas las barras pasan (worst util < 1) y que el ledger gobierna sobre los postes. (6) `tests/test_report.py` — 6 tests: estructura HTML (DOCTYPE, secciones, título), barra que falla aparece marcada con clase `fail`, sin fallos no se muestra el bloque correspondiente, escape HTML de ids con caracteres especiales, `write_html_report` crea el fichero, `top_n` mayor que el número de barras se acota correctamente. **80/80 PASSED** (4 Fase 1 + 6 Fase 2 + 27 Fase 3 + 31 Fase 4 + 12 Fase 5). **Cierre del módulo de cálculo según roadmap §16**. |

---

Documento mantenido a la par del código. Si añades una decisión o cambias una constante, actualízalo aquí.
