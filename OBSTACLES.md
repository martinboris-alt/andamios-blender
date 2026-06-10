# Adaptación al entorno — convenciones de obstáculos

El addon **Andamios trayectoria** adapta automáticamente el andamio a tres
tipos de obstáculos del entorno. Es opt-in por convención de nombre — si no
creas la collection, el comportamiento es el de siempre (andamio plano).

## Convención

Crea una collection llamada **`obstaculos`** en tu escena Blender. Mete
dentro meshes con uno de los siguientes prefijos:

| Prefijo | Tipo | Comportamiento del addon |
|---------|------|---------------------------|
| `Terrain_*` | Suelo (Fase A) | Raycast vertical desde cada poste para obtener Z del suelo. Cada poste obtiene su husillo individual (`ref_z - terrain_z`). |
| `Wall_*` | Pared lateral (Fase B) | Plataformas / travesaños / barandillas / rodapiés / cruces / arriostramientos / ledgers transversales se recortan o se omiten cuando cruzan la pared. Trampillas se omiten enteras si la pared cae sobre el lid. |
| `Volume_*` | Volumen sólido (Fase D) | Vanos cuyo centro cae **dentro** del volumen se skipan enteros (postes, ledgers, decks, rails, escaleras, cruces). Vanos parciales aplican el mismo clipping que paredes. |

La collection puede llamarse `obstaculos`, `obstáculos`, `Obstaculos` u
`Obstáculos` — cualquiera de las cuatro variantes funciona.

## Comportamiento detallado

### `Terrain_*` (Fase A)

- Cualquier mesh: plano inclinado, escalón, terreno ondulado, bordillo, etc.
- Para cada XY de poste, raycast desde Z=+50m hacia abajo contra todas las
  meshes Terrain_*. La primera intersección define la Z del suelo.
- Si no hay intersección bajo un poste → fallback a `props.base_z` y warning
  "N postes sin terreno bajo su XY".
- Si `jack_length > 80 cm` → warning "N husillos > 80 cm" (límite
  comercial). El usuario debe elevar `jack_height` o partir la trayectoria.

### `Wall_*` (Fase B)

- Tipo Plane (sin grosor): cada hit del raycast es un **punto de corte**, no
  entrada a un volumen. Plataformas y tubos se split en sub-piezas a ambos
  lados del plano.
- Si una pared **paralela** atraviesa lateralmente el ancho de un plank
  (`< plank_w / 2` desde el centro), el plank se omite entero.
- Si la pared cae sobre el lid de una trampilla, se omite el conjunto Lid +
  Hinge + LidHandle.
- Postes que cruzan una pared (raycast vertical) se bloquean con error fatal:
  "N postes caen DENTRO de una pared o volumen — redirige la trayectoria".

### `Volume_*` (Fase D)

- Mesh cerrada (cubo, cilindro, cono, forma orgánica). Se evalúa con
  point-in-mesh por paridad de raycast.
- Si el **centro** de un vano (XY, Z medio del andamio) está dentro del
  volumen → vano skipado entero. Postes, ledgers, decks, rails, escaleras y
  cruces de ese vano no se construyen.
- Si el vano roza pero el centro está fuera → clipping normal (igual que
  paredes).
- Postes cuyo segmento vertical entra en el volumen se bloquean.

## Multi-tramo automático

Si la trayectoria tiene un salto vertical entre dos empties consecutivos
mayor que **1 m** (constante `_TRAMO_SPLIT_DZ_M`), el addon construye dos
andamios independientes con su propio nivel de referencia. La Z relevante
es la del **terreno bajo cada empty** (raycast contra `Terrain_*`) si lo
hay; sino la del propio empty.

Resultado: andamio escalonado, cada tramo tiene prefijo `T0_`, `T1_`… en
los nombres de objetos. Los tramos no se conectan estructuralmente — el
operario monta escaleras o pasarelas aparte.

## Aviso importante: cálculo FEM

Cuando el panel detecta cualquier `Wall_*` o `Volume_*` en escena, muestra:

> ⚠ Obstáculos detectados — el cálculo FEM no está validado para piezas
> custom o vanos skipados. Úsalo solo como referencia visual.

El cálculo estructural del addon asume estructura periódica (todos los
vanos iguales, plataformas estándar). Cuando hay obstáculos:

- Plataformas recortadas a longitudes no catalogadas → carga de servicio
  mal repartida.
- Vanos skipados → modelo FEM no refleja la geometría real.
- Sub-tubos custom → topología no equivalente al modelo.

**No te fíes del veredicto del cálculo en estos casos**. Es un seguro
explícito para evitar firmar un cálculo incorrecto.

La validación FEM con piezas custom es trabajo pendiente.

## Casos de prueba documentados

Verificados en sesiones anteriores con tests automáticos (`pytest calc/`):

### Fase A — terreno
| Caso | Geometría | Resultado |
|------|-----------|-----------|
| T1 | Rampa 4% (10×3.5 m) | Jacks 0.28→0.60 m progresivos |
| T2 | Escalón 50 cm | Plates discretos a Z=0.01 / 0.51 |
| T3 | Ondulado sin/cos | 8 jacks distintos, error < 1 cm |
| T4 | Parcial | Postes fuera del terrain → fallback a `base_z` |
| T5 | Pendiente 30% | Warning de jacks > 80 cm |
| T6 | Bordillo 15 cm | Calle + acera sin colisión |

### Fase B — paredes
| Caso | Geometría | Resultado |
|------|-----------|-----------|
| W1 | Plane vertical paralelo | Planks centrales skipados |
| W2 | Plane vertical perpendicular | Planks/ledgers/rails split en ambos lados |
| W3 | Plane diagonal | Cada plank cortado en X distinta según su Y |
| W4 | Pared con ventana (NGon con hueco) | Planks dentro del hueco SÍ se construyen |
| W5 | Parapeto bajo (Z=0..1.2) | No afecta a plataformas Z=2.04+ |

### Fase D — volúmenes
| Caso | Geometría | Resultado |
|------|-----------|-----------|
| V1 | Cono grande (Volume_001) | Bays skipados + andamio rodeando |
| Combinado C1 | Terreno T1 + pared paralela | Jacks variables + planks skipados sin colisión entre lógicas |
| Combinado C2 | Escalón T2 + volume box | Jacks por escalón + bay skipado por volume |
