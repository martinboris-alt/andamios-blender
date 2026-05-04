"""Diccionario de traducciones del addon Andamios.

Estructura aceptada por ``bpy.app.translations.register``:

    TRANSLATIONS[locale_code] = {
        (msgctxt, msgid): msgstr,
        ...
    }

donde ``locale_code`` sigue la convención Blender (``en_US``, ``de_DE``,
``fr_FR``, ``it_IT``, ``pt_BR``, ``pl_PL``) y ``msgctxt`` es ``None``
salvo que el mismo msgid tenga dos significados distintos según
contexto (Iface vs Tip vs Data).

Los msgid son los strings españoles que aparecen en el código del
addon (``andamios_addon.py``, ``calc/ui.py``, ``tutorial_guide.py``).
Para usuarios con Blender en español el lookup falla y se muestra el
msgid original — ése es el comportamiento deseado.

Para añadir una traducción nueva basta con añadir entradas
``(None, "<msgid en español>"): "<traducción>"`` al dict del idioma.
No hay paso de compilación: Blender recarga el dict en cada
``register()``.
"""

# ----------------------------------------------------------------------
# Inglés (en_US) — primera entrega completa
# ----------------------------------------------------------------------
EN: dict = {
    # ── Categoría / Panel principal ────────────────────────────────────
    (None, "Andamios"): "Scaffolding",
    (None, "Andamios trayectoria"): "Scaffolding (path)",
    (None, "Cálculo estructural"): "Structural analysis",

    # ── Operadores: bl_label ───────────────────────────────────────────
    (None, "Añadir punto a la trayectoria"): "Add point to path",
    (None, "Eliminar punto"): "Remove point",
    (None, "Mover punto"): "Move point",
    (None, "Añadir escalera"): "Add ladder",
    (None, "Eliminar escalera"): "Remove ladder",
    (None, "Generar / Actualizar andamios"): "Generate / Update scaffold",
    (None, "Generar / Actualizar"): "Generate / Update",
    (None, "Exportar diagnóstico (.txt)"): "Export diagnostics (.txt)",
    (None, "Restablecer colores por defecto"): "Reset colors to defaults",
    (None, "Limpiar log de diagnóstico"): "Clear diagnostics log",
    (None, "Borrar andamios"): "Clear scaffold",
    (None, "Auditoría bandejas"): "Audit decks",
    (None, "Auto-cubrir bandejas"): "Auto-cover decks",
    (None, "Exportar lista de materiales (CSV)"): "Export bill of materials (CSV)",
    (None, "Comprobar modelo"): "Check model",
    (None, "Ejecutar cálculo"): "Run analysis",
    (None, "Ejecutar"): "Run",
    (None, "Restaurar colores"): "Restore colors",
    (None, "Auto-corregir fallos"): "Auto-fix failures",
    (None, "Revertir auto-corrección"): "Revert auto-fix",
    (None, "Mostrar deformada (ANSYS)"): "Show deformed shape (ANSYS)",
    (None, "Ocultar deformada"): "Hide deformed",
    (None, "Ocultar"): "Hide",
    (None, "Localizar deformación máxima"): "Locate max deflection",
    (None, "Localizar barra en viewport"): "Locate member in viewport",
    (None, "Exportar plano CAD (HTML)"): "Export CAD drawing (HTML)",
    (None, "Exportar BOM HTML"): "Export BOM HTML",
    (None, "Exportar informe HTML"): "Export HTML report",
    (None, "Volver a comprobar"): "Re-check",
    (None, "Deshacer cambios"): "Undo changes",
    (None, "Exportar log"): "Export log",

    # ── Operadores: bl_description ─────────────────────────────────────
    (None, "Vuelve a los colores originales del addon para todas las categorías"):
        "Restore the addon's default colors for every category",
    (None, "Borra el historial de operaciones registradas por el addon"):
        "Clear the addon's recorded operations history",
    (None, "Recorre todas las bandejas, verifica EN 12811-1 y reporta utilizaciones"):
        "Walk through every deck, check EN 12811-1 and report utilisations",
    (None, "Devuelve cada barra a su material original"):
        "Restore every member to its original material",
    (None, "Elimina la colección Scaffold_Deformed con la geometría deformada"):
        "Delete the Scaffold_Deformed collection holding the deformed geometry",
    (None, "Selecciona la barra correspondiente a la fila activa y centra la vista 3D sobre ella"):
        "Select the member matching the active row and frame the 3D view on it",
    (None,
     "Pasa una serie de chequeos rápidos sobre la geometría del andamio "
     "y la configuración del cálculo. Avisa de errores que harían "
     "fallar el solver y de warnings que pueden indicar incumplimiento "
     "normativo. No ejecuta el cálculo FEM"):
        "Run a battery of quick checks on the scaffold geometry and analysis "
        "settings. Reports errors that would crash the solver and warnings "
        "that may indicate non-compliance. Does not run the FEM analysis",
    (None,
     "Aplica las cargas configuradas, resuelve y colorea el viewport por "
     "utilización"):
        "Apply the configured loads, solve and colour the viewport by "
        "utilisation",

    # ── Sub-paneles del cálculo ────────────────────────────────────────
    (None, "Cargas y combinación"): "Loads and combination",
    (None, "Resultados"): "Results",
    (None, "Auto-corrección"): "Auto-correction",
    (None, "Exportar documentos"): "Export documents",

    # ── Properties: name ───────────────────────────────────────────────
    (None, "Punto"): "Point",
    (None, "Pos"): "Pos",
    (None, "Indicador"): "Indicator",
    (None, "Preset"): "Preset",
    (None, "Nº de plantas"): "Storey count",
    (None, "Altura por planta (m)"): "Storey height (m)",
    (None, "Profundidad (m)"): "Depth (m)",
    (None, "Longitud de tramo (m)"): "Bay length (m)",
    (None, "Catálogo vanos (horizontal)"): "Bay catalogue (horizontal)",
    (None, "Z base (m)"): "Base Z (m)",
    (None, "Trayectoria cerrada"): "Closed loop",
    (None, "Terreno irregular"): "Uneven terrain",
    (None, "Husillo de base (m)"): "Base jack (m)",
    (None, "Rosetas (acoples)"): "Rosettes (couplers)",
    (None, "Cada (m)"): "Every (m)",
    (None, "Longitud poste (m)"): "Standard length (m)",
    (None, "Catálogo postes (vertical)"): "Standard catalogue (vertical)",
    (None, "Anclajes a fachada"): "Façade ties",
    (None, "Anclaje cada N vanos"): "Tie every N bays",
    (None, "Anclaje cada M plantas"): "Tie every M storeys",
    (None, "Longitud anclaje (m)"): "Tie length (m)",
    (None, "Plataformas"): "Decks",
    (None, "Plataforma de esquina"): "Corner deck",
    (None, "Bandejas por vano"): "Decks per bay",
    (None, "Ancho bandeja (m)"): "Deck width (m)",
    (None, "Material bandeja"): "Deck material",
    (None, "Barandillas + rodapié"): "Guardrails + toeboard",
    (None, "Cruces (diagonales)"): "Bracing (diagonals)",
    (None, "Patrón cruces"): "Brace pattern",
    (None, "Subdivisión cruces"): "Brace subdivision",
    (None, "Cruces en planta (rigidizan torsión)"): "Plan bracing (torsion stiffening)",
    (None, "Diag. horiz. cada N plantas"): "Plan diag. every N storeys",
    (None, "Diag. horiz. cada M vanos"): "Plan diag. every M bays",
    (None, "Escaleras"): "Ladders",
    (None, "Escalera cada N vanos"): "Ladder every N bays",
    (None, "Posición manual de escaleras"): "Manual ladder positions",
    (None, "Longitud de escalera (m)"): "Ladder length (m)",
    (None, "Anchura escalera (m)"): "Ladder width (m)",
    (None, "Pasamanos lateral (escalera)"): "Side handrail (ladder)",
    (None, "Altura pasamanos (m)"): "Handrail height (m)",
    (None, "Apertura tapa (°)"): "Trapdoor opening (°)",
    (None, "Auto-actualizar al mover la trayectoria"): "Auto-update when path moves",
    (None, "Postes"): "Standards",
    (None, "Travesaños"): "Ledgers",
    (None, "Cruces"): "Braces",
    (None, "Trampillas"): "Trapdoors",
    (None, "Anclajes"): "Ties",
    (None, "Husillos"): "Jacks",
    (None, "Acoples"): "Couplers",
    (None, "Barandillas"): "Guardrails",
    (None, "Filtro ancho"): "Width filter",
    (None, "Filtro clase"): "Class filter",
    (None, "Filtro material"): "Material filter",
    (None, "Bandeja seleccionada"): "Selected deck",
    (None, "Carga de uso"): "Service load",
    (None, "Tipo de uso"): "Use type",
    (None, "Ancho de tablón (m)"): "Plank width (m)",
    (None, "Viento"): "Wind",
    (None, "Zona del viento"): "Wind zone",
    (None, "Tipo de entorno"): "Terrain type",
    (None, "Tolerancias de montaje"): "Erection tolerances",
    (None, "Carga en barandilla (EN 12811 §7.2)"): "Guardrail load (EN 12811 §7.2)",
    (None, "Análisis P-Δ (2º orden geométrico)"): "P-Δ analysis (2nd-order geometric)",
    (None, "Visualización"): "Display",
    (None, "Amplificación deformada (×)"): "Deformation magnification (×)",
    (None, "Caso a comprobar"): "Combination to check",

    # ── Properties: descriptions ───────────────────────────────────────
    (None, "Empty u objeto cuya posición define un vértice de la trayectoria"):
        "Empty or object whose position defines a path vertex",
    (None, "Posición a lo largo de la trayectoria (0=inicio, 1=fin). Hace snap al vano más cercano"):
        "Position along the path (0=start, 1=end). Snaps to the nearest bay",
    (None, "Empty visible en el viewport que se mueve con el slider"):
        "Empty visible in the viewport that moves with the slider",
    (None, "Preset que ajusta profundidad, número/ancho de bandejas y catálogo de longitudes"):
        "Preset that adjusts depth, deck count/width and length catalogue",
    (None, "Longitud objetivo de cada vano. Sólo se usa con catálogo Uniforme."):
        "Target length per bay. Only used with the Uniform catalogue.",
    (None,
     "Cómo subdividir cada tramo HORIZONTAL de la polilínea en vanos "
     "(longitud entre postes). Las dos primeras opciones usan piezas estándar "
     "+ pieza de compensación al final del tramo si no encaja exacto"):
        "How to subdivide each HORIZONTAL polyline segment into bays "
        "(length between standards). The first two options use standard "
        "pieces + a closing fill piece at the end of the run if it does "
        "not fit exactly",
    (None, "Altura del pie del andamio. Anula la Z de los puntos de la trayectoria."):
        "Scaffold base height. Overrides the Z of the path points.",
    (None, "Conecta el último punto con el primero formando un loop alrededor de un edificio"):
        "Connect the last point with the first to form a loop around a building",
    (None,
     "Cada empty mantiene su Z propia (= cota del terreno). Los husillos se "
     "ajustan automáticamente para nivelar el andamio: ref_z = max(P.z) + jack_height"):
        "Every empty keeps its own Z (= terrain elevation). The base jacks "
        "auto-adjust to level the scaffold: ref_z = max(P.z) + jack_height",
    (None, "Altura del husillo de base bajo cada poste (0 = sin husillo)"):
        "Base jack height beneath each standard (0 = no jack)",
    (None, "Genera rosetas a lo largo de los postes cada `rosette_pitch` metros"):
        "Generate rosettes along the standards every `rosette_pitch` metres",
    (None, "Distancia vertical entre rosetas soldadas al poste (Layher Allround = 0.5 m)"):
        "Vertical pitch between rosettes welded to the standard (Layher Allround = 0.5 m)",
    (None,
     "Longitud estandarizada (modo Uniforme) de cada segmento de poste. "
     "0 = poste continuo. Ignorado si el catálogo no es Uniforme"):
        "Standard length (Uniform mode) of each standard segment. "
        "0 = single-piece standard. Ignored unless the catalogue is Uniform",
    (None,
     "Cómo segmentar cada poste VERTICAL en piezas. Los modos Mixto y Layher "
     "combinan piezas estándar hasta cubrir la altura completa de cada poste"):
        "How to segment each VERTICAL standard into pieces. Mixed and Layher "
        "modes combine standard pieces until the full standard height is covered",
    (None, "Genera anclajes (ties) desde los postes delanteros hacia la fachada"):
        "Generate ties from the front standards towards the façade",
    (None,
     "Genera una pieza de esquina dedicada (trapezoide) en cada vértice "
     "interior. Equivale a la 'corner platform' del catálogo Layher"):
        "Generate a dedicated corner piece (trapezoid) at every interior "
        "vertex. Equivalent to the Layher 'corner platform'",
    (None, "Número de bandejas estandarizadas colocadas en paralelo dentro de cada vano"):
        "Number of standard decks laid in parallel within each bay",
    (None, "Ancho estandarizado de cada bandeja (e.g. 0.32 m, 0.19 m)"):
        "Standard width of each deck (e.g. 0.32 m, 0.19 m)",
    (None, "Preferencia de material al asignar bandejas del catálogo a cada vano"):
        "Preferred material when assigning catalogue decks to each bay",
    (None, "Distribución de las diagonales entre las caras frontal y posterior del andamio"):
        "Diagonal distribution between the front and back faces of the scaffold",
    (None,
     "Subdivide cada cruce diagonal en sub-tramos zigzag entre rosetas "
     "intermedias del poste. Reduce la longitud máxima de pieza a costa "
     "de más unidades. Patrón N triangulado (estructuralmente válido)."):
        "Subdivide each diagonal brace into zigzag sub-segments between "
        "intermediate rosettes on the standard. Reduces the maximum piece "
        "length at the cost of more units. Triangulated N pattern "
        "(structurally valid).",
    (None,
     "Genera diagonales en el plano horizontal del deck (vistas desde arriba "
     "forman aspas), cada N plantas y M vanos. Rigidizan el andamio frente a "
     "torsión (racking)"):
        "Generate diagonals on the deck horizontal plane (X-shaped when seen "
        "from above), every N storeys and M bays. Stiffen the scaffold "
        "against torsion (racking)",
    (None,
     "Define la posición de cada escalera con sliders (en vez de cada N "
     "vanos). Snap al centro del vano más cercano"):
        "Define each ladder position with sliders (instead of every N bays). "
        "Snaps to the centre of the nearest bay",
    (None,
     "Longitud estándar de cada tramo de escalera. La inclinación se calcula "
     "a partir de esta longitud y la altura por planta."):
        "Standard length of each ladder run. The tilt is computed from this "
        "length and the storey height.",
    (None, "Separación entre rieles (= longitud de los peldaños)"):
        "Stringer spacing (= rung length)",
    (None,
     "Añade un tubo paralelo a un lado de la escalera, elevado sobre los "
     "rieles principales, para que el trabajador se agarre durante el "
     "ascenso. Equivale a la pieza Layher Steigleiterschutzgeländer "
     "(EN 12811-1 §7.2 — protección personal en accesos verticales)"):
        "Add a tube parallel to one side of the ladder, raised above the "
        "main stringers, for the worker to grip while climbing. Equivalent "
        "to the Layher Steigleiterschutzgeländer "
        "(EN 12811-1 §7.2 — personal fall protection on vertical accesses)",
    (None,
     "Distancia vertical entre el riel de la escalera y el pasamanos elevado. "
     "0,9-1,0 m es el rango ergonómico estándar para que el trabajador llegue "
     "al agarre sin esfuerzo durante el ascenso"):
        "Vertical distance between the ladder stringer and the raised "
        "handrail. 0.9–1.0 m is the standard ergonomic range so the worker "
        "can reach the grip effortlessly while climbing",
    (None, "Ángulo de apertura visible de la tapa de la trampilla"):
        "Visible opening angle of the trapdoor lid",
    (None, "Regenera el andamio automáticamente al mover cualquier punto de la polilínea"):
        "Regenerate the scaffold automatically when any polyline point moves",
    (None, "Bandeja del catálogo Ringlock EU. Filtra arriba si quieres reducir la lista"):
        "Deck from the Ringlock EU catalogue. Use the filters above to narrow the list",
    (None,
     "Considera el peso de los trabajadores y materiales sobre las "
     "plataformas. Sin esto sólo se calcula con el peso del propio "
     "andamio (irrealmente bajo)"):
        "Account for the weight of workers and materials on the decks. "
        "Without this only the scaffold's self-weight is analysed "
        "(unrealistically low)",
    (None,
     "Clase de servicio EN 12811-1 — selecciona según el uso "
     "previsto del andamio"):
        "EN 12811-1 service class — pick based on the intended use of the scaffold",
    (None,
     "Ancho útil del paño de plataforma que cada par de travesaños "
     "soporta. 0,61 m es el estándar Layher para 2 tablones de ancho"):
        "Useful width of the deck panel that each pair of ledgers carries. "
        "0.61 m is the Layher standard for 2-plank width",
    (None,
     "Aplica la presión de viento sobre los postes según el CTE "
     "DB-SE-AE. Necesario para certificar el andamio en exterior"):
        "Apply wind pressure to the standards per CTE DB-SE-AE. "
        "Required to certify the scaffold for outdoor use",
    (None,
     "Zona de viento del CTE DB-SE-AE Anejo D según la "
     "ubicación geográfica del andamio"):
        "Wind zone from CTE DB-SE-AE Annex D based on the scaffold's "
        "geographic location",
    (None,
     "Categoría de terreno EN 1991-1-4: cuanto más expuesto "
     "al viento, más alta la velocidad efectiva"):
        "EN 1991-1-4 terrain category: the more exposed to wind, the "
        "higher the effective speed",
    (None,
     "Considera que los postes nunca están perfectamente verticales "
     "(EN 1993-1-1 §5.3). Aplica una fuerza horizontal equivalente "
     "≈0,5 % del peso total. Recomendado siempre activado"):
        "Account for the fact that standards are never perfectly vertical "
        "(EN 1993-1-1 §5.3). Applies an equivalent horizontal force "
        "≈0.5 % of total weight. Recommended always on",
    (None,
     "Aplica 0,3 kN puntuales horizontales en los postes a la altura "
     "de la barandilla, según exige EN 12811-1 §7.2.1 (carga de "
     "protección personal contra caídas). Activar para verificar "
     "que los postes resisten también este cortante adicional"):
        "Apply 0.3 kN horizontal point loads to the standards at guardrail "
        "height, as required by EN 12811-1 §7.2.1 (personal fall-protection "
        "load). Enable to verify the standards also withstand this extra "
        "shear",
    (None,
     "Activa análisis de segundo orden P-Delta: la rigidez se "
     "recalcula iterativamente teniendo en cuenta la posición "
     "deformada de los postes. Captura la amplificación de "
     "momentos cuando la cúspide del andamio se desploma bajo "
     "carga (efecto P·Δ). Más lento (~2-5×) pero requerido por "
     "EN 1993-1-1 §5.2 cuando α_cr ≤ 10. RECOMENDADO en torres "
     "esbeltas (>15 m sin anclajes) o si el cálculo lineal da "
     "utilizaciones próximas a 1,0 — el segundo orden puede "
     "subir el resultado un 10-20 %"):
        "Enable P-Delta second-order analysis: stiffness is recomputed "
        "iteratively accounting for the deformed standard position. "
        "Captures moment amplification when the scaffold top sways under "
        "load (P·Δ effect). Slower (~2–5×) but required by EN 1993-1-1 "
        "§5.2 when α_cr ≤ 10. RECOMMENDED for slender towers (>15 m "
        "untied) or when linear analysis yields utilisations near 1.0 — "
        "second-order can raise the result by 10–20 %",
    (None,
     "Qué propiedad muestran los colores en el viewport tras "
     "ejecutar el cálculo. Cambia el modo y vuelve a pulsar "
     "Ejecutar para ver la otra capa de información"):
        "Which property the colours display in the viewport after running "
        "the analysis. Switch the mode and hit Run again to see the other "
        "information layer",
    (None,
     "Factor de exageración para la geometría deformada. "
     "Las deformaciones reales son de pocos milímetros (invisibles a "
     "simple vista); ×100 las hace claramente perceptibles. Sólo "
     "afecta a la visualización: el cálculo no cambia"):
        "Exaggeration factor for the deformed geometry. Real deflections "
        "are a few millimetres (invisible to the naked eye); ×100 makes "
        "them clearly perceptible. Visualisation only — the analysis "
        "itself is unchanged",
    (None,
     "Selecciona qué tipo de comprobación quieres realizar. "
     "Para certificar un andamio normalmente se ejecutan "
     "ULS — uso dominante y ULS — viento dominante"):
        "Select which check you want to run. To certify a scaffold you "
        "typically run ULS — service-dominant and ULS — wind-dominant",
    (None,
     "Selecciona la barra correspondiente a la fila activa y centra la "
     "vista 3D sobre ella"):
        "Select the member matching the active row and frame the 3D view on it",

    # ── Items de EnumProperty ──────────────────────────────────────────
    # preset
    (None, "Personalizado"): "Custom",
    (None, "Sin preset (configura cada propiedad manualmente)"):
        "No preset (configure each property manually)",
    (None, "Profundidad 0.732 m, 2 bandejas, catálogo Layher"):
        "Depth 0.732 m, 2 decks, Layher catalogue",
    (None, "Profundidad 1.09 m, 3 bandejas, catálogo Layher"):
        "Depth 1.09 m, 3 decks, Layher catalogue",
    (None, "Genérico 1 m"): "Generic 1 m",
    (None, "Profundidad 1.0 m, 3 bandejas, catálogo Genérico"):
        "Depth 1.0 m, 3 decks, Generic catalogue",
    (None, "Estrecho"): "Narrow",
    (None, "Profundidad 0.64 m, 2 bandejas, catálogo Genérico"):
        "Depth 0.64 m, 2 decks, Generic catalogue",
    # bay_length_catalog & pole_length_catalog
    (None, "Mixto múltiplos 0,5 m"): "Mixed 0.5 m multiples",
    (None,
     "Combina piezas de 1.0/1.5/2.0/2.5/3.0 m. Encaja exacto con planificaciones "
     "en múltiplos de 0.5 m"):
        "Combine 1.0/1.5/2.0/2.5/3.0 m pieces. Exact fit for plans in "
        "0.5 m multiples",
    (None, "Layher Allround (catálogo real)"): "Layher Allround (real catalogue)",
    (None,
     "Combina piezas Layher reales: 0.73/1.09/1.40/1.57/1.73/2.07/2.57/3.07 m"):
        "Combine real Layher pieces: 0.73/1.09/1.40/1.57/1.73/2.07/2.57/3.07 m",
    (None, "Iguales (divide en N partes)"): "Equal (split in N parts)",
    (None,
     "Reparte el tramo en partes iguales del tamaño 'Longitud objetivo' "
     "(ningún vano estandarizado)"):
        "Split the run into equal pieces of 'Target length' size "
        "(no standardised bay)",
    (None, "Uniforme (longitud fija)"): "Uniform (fixed length)",
    (None,
     "Usa el valor 'Longitud poste' como tamaño único del segmento (modo legacy)"):
        "Use 'Standard length' as the single segment size (legacy mode)",
    (None, "Combina piezas de 0.5/1.0/1.5/2.0/2.5/3.0 m hasta cubrir la altura"):
        "Combine 0.5/1.0/1.5/2.0/2.5/3.0 m pieces to cover the height",
    (None, "Combina piezas Layher reales: 0.5/1.0/1.5/2.0/3.0/4.0 m"):
        "Combine real Layher pieces: 0.5/1.0/1.5/2.0/3.0/4.0 m",
    # deck_material_pref
    (None, "Cualquiera"): "Any",
    (None, "Cualquier construcción del catálogo"): "Any construction from the catalogue",
    (None, "Acero"): "Steel",
    (None, "Acero galvanizado S350GD+Z (más pesado, más MRd)"):
        "Galvanised steel S350GD+Z (heavier, higher MRd)",
    (None, "Aluminio"): "Aluminium",
    (None, "Aluminio extruido EN AW-6082 T6 (ligero)"):
        "Extruded aluminium EN AW-6082 T6 (lightweight)",
    (None, "Alu+LVL"): "Alu+LVL",
    (None, "Alu + LVL"): "Alu + LVL",
    (None, "Marco aluminio + tablero LVL fenólico"):
        "Aluminium frame + phenolic LVL board",
    # brace_pattern
    (None, "Solo frontal"): "Front only",
    (None, "Diagonales solo en la cara frontal del andamio"):
        "Diagonals only on the front face of the scaffold",
    (None, "Solo posterior"): "Back only",
    (None, "Diagonales solo en la cara posterior del andamio"):
        "Diagonals only on the back face of the scaffold",
    (None, "Ambas caras"): "Both faces",
    (None, "Diagonales en ambas caras (mismas bays)"):
        "Diagonals on both faces (same bays)",
    (None, "Alternadas"): "Alternating",
    (None, "Frontal y posterior alternando bays (cada 4)"):
        "Front and back alternating bays (every 4)",
    # brace_subdivision
    (None, "Cruz completa"): "Full diagonal",
    (None, "Una diagonal por bay×planta esquina-a-esquina (≈2,9 m en Layher 2,07×2 m)"):
        "One diagonal per bay×storey corner-to-corner (≈2.9 m in Layher 2.07×2 m)",
    (None, "Sub-cruces ½ altura (zigzag)"): "Sub-braces ½ height (zigzag)",
    (None,
     "Dos diagonales por bay×planta ancladas a roseta intermedia, formando "
     "patrón en N. Cada pieza ≈2,3 m. Usa más material pero piezas más manejables."):
        "Two diagonals per bay×storey anchored to an intermediate rosette, "
        "forming an N pattern. Each piece ≈2.3 m. Uses more material but "
        "with easier-to-handle pieces.",
    (None, "Sub-cruces ¼ altura (zigzag fino)"): "Sub-braces ¼ height (fine zigzag)",
    (None,
     "Cuatro diagonales por bay×planta ancladas a rosetas cada 0,5 m. "
     "Cada pieza ≈2,1 m. Sólo recomendado en torres de altura ≥15 m."):
        "Four diagonals per bay×storey anchored to rosettes every 0.5 m. "
        "Each piece ≈2.1 m. Only recommended for towers ≥15 m tall.",
    # deck filters
    (None, "Clase 1"): "Class 1",
    (None, "Clase 2"): "Class 2",
    (None, "Clase 3"): "Class 3",
    (None, "Clase 4"): "Class 4",
    (None, "Clase 5"): "Class 5",
    (None, "Clase 6"): "Class 6",
    # calc_service_class
    (None, "Inspección — 75 kg/m²"): "Inspection — 75 kg/m²",
    (None, "Solo se camina por encima, sin herramientas pesadas"):
        "Walk-on only, no heavy tools",
    (None, "Uso ligero — 150 kg/m²"): "Light use — 150 kg/m²",
    (None, "Pintura, limpieza, instalaciones ligeras"):
        "Painting, cleaning, light installation work",
    (None, "Uso general — 200 kg/m²"): "General use — 200 kg/m²",
    (None, "Trabajo habitual de fachada (≈4 trabajadores con herramienta)"):
        "Typical façade work (≈4 workers with tools)",
    (None, "Carga elevada — 300 kg/m²"): "Heavy load — 300 kg/m²",
    (None, "Albañilería, reparaciones con material acopiado"):
        "Masonry, repairs with stored material",
    (None, "Almacenaje pesado — 450 kg/m²"): "Heavy storage — 450 kg/m²",
    (None, "Almacenamiento de materiales pesados sobre el andamio"):
        "Storage of heavy materials on the scaffold",
    (None, "Almacenaje muy pesado — 600 kg/m²"): "Very heavy storage — 600 kg/m²",
    (None, "Almacenamiento intensivo (raro en andamio de fachada)"):
        "Intensive storage (rare on a façade scaffold)",
    # calc_wind_zone
    (None, "Zona A — costa cantábrica e interior"): "Zone A — Cantabrian coast and inland",
    (None, "26 m/s, viento moderado (la mayor parte de España)"):
        "26 m/s, moderate wind (most of Spain)",
    (None, "Zona B — costa atlántica"): "Zone B — Atlantic coast",
    (None, "27 m/s, viento medio (Galicia, Andalucía atlántica)"):
        "27 m/s, mid wind (Galicia, Atlantic Andalusia)",
    (None, "Zona C — Canarias y litoral expuesto"): "Zone C — Canaries and exposed coast",
    (None, "29 m/s, viento fuerte"): "29 m/s, strong wind",
    # calc_wind_terrain
    (None, "Mar abierto"): "Open sea",
    (None, "Sin obstáculos (frente marítimo, lago grande)"):
        "No obstacles (waterfront, large lake)",
    (None, "Campo llano"): "Flat country",
    (None, "Llanura sin árboles, terrenos costeros"):
        "Treeless plains, coastal terrain",
    (None, "Campo abierto"): "Open country",
    (None, "Lo más habitual: terreno con setos y construcciones aisladas"):
        "Most common: terrain with hedges and isolated buildings",
    (None, "Suburbano"): "Suburban",
    (None, "Zona urbana con edificaciones bajas dispersas"):
        "Urban area with scattered low buildings",
    (None, "Urbano denso"): "Dense urban",
    (None, "Centros de ciudad con edificios de 5+ plantas"):
        "City centres with 5+ storey buildings",
    # calc_color_mode
    (None, "Utilización (riesgo de fallo)"): "Utilisation (failure risk)",
    (None,
     "Colorea cada barra según su grado de aprovechamiento de la "
     "capacidad. Rojo = al límite o sobrepasada"):
        "Colour each member by capacity utilisation. Red = at the limit "
        "or exceeded",
    (None, "Deformación (cuánto se mueve)"): "Deflection (how much it moves)",
    (None,
     "Colorea cada barra según cuánto se ha desplazado al cargar. "
     "Rojo = deformación excesiva (>L/100)"):
        "Colour each member by how much it has displaced under load. "
        "Red = excessive deflection (>L/100)",
    # calc_combo
    (None, "Resistencia — uso dominante"): "Strength — service dominant",
    (None,
     "Comprueba la rotura cuando el peso de trabajo es lo crítico "
     "(útil cuando hay mucha carga sobre las plataformas)"):
        "Check failure when working weight governs "
        "(useful when decks carry heavy loads)",
    (None, "Resistencia — viento dominante"): "Strength — wind dominant",
    (None,
     "Comprueba la rotura cuando el viento es lo crítico "
     "(el caso más exigente para andamios altos / expuestos)"):
        "Check failure when wind governs "
        "(toughest case for tall / exposed scaffolds)",
    (None, "Resistencia — levantamiento por viento"): "Strength — wind uplift",
    (None,
     "Verifica que el viento no levanta la estructura "
     "(carga de uso minorada)"):
        "Verify the wind does not lift the structure "
        "(reduced service load)",
    (None, "Servicio — deformación característica"): "Service — characteristic deflection",
    (None, "Comprueba flecha y deformaciones bajo cargas habituales"):
        "Check deflection and deformations under typical loads",
    (None, "Servicio — deformación frecuente"): "Service — frequent deflection",
    (None, "Como característica pero con cargas reducidas (frecuencia diaria)"):
        "Like characteristic but with reduced loads (daily frequency)",
    (None, "Servicio — deformación casi-permanente"): "Service — quasi-permanent deflection",
    (None, "Cargas que actúan la mayor parte del tiempo"):
        "Loads acting most of the time",

    # ── Panel principal: layout.label literales ────────────────────────
    (None, "Cambia: profundidad, nº y ancho de bandejas, catálogo de vanos"):
        "Changes: depth, deck count/width, bay catalogue",
    (None, "Has cambiado algo · pon 'Personalizado' para no liarte"):
        "You changed something · switch to 'Custom' to avoid confusion",
    (None, "Trayectoria (polilínea)"): "Path (polyline)",
    (None, "Dimensiones"): "Dimensions",
    (None, "Componentes"): "Components",
    (None, "Bandejas — Catálogo Ringlock EU"): "Decks — Ringlock EU catalogue",
    (None, "Ancho"): "Width",
    (None, "Clase"): "Class",
    (None, "Material"): "Material",
    (None, "⚠ Valores estructurales conservadores estimados"):
        "⚠ Estimated conservative structural values",
    (None, "Colores"): "Colors",
    (None, "Estructura"): "Structure",
    (None, "Acceso"): "Access",
    (None, "Seguridad"): "Safety",
    (None, "Resumen:"): "Summary:",
    (None, "Reporte de errores"): "Error report",
    (None, "(Solo para depurar fallos)"): "(For crash debugging only)",

    # ── calc/ui.py: layout.label literales ─────────────────────────────
    (None, "Servicio (L)"): "Service (L)",
    (None, "Viento (W)"): "Wind (W)",
    (None, "Imperfecciones (I)"): "Imperfections (I)",
    (None, "Carga barandilla (Q, EN 12811)"): "Guardrail load (Q, EN 12811)",
    (None, "Combinación a comprobar:"): "Combination to check:",
    (None, "Avanzado"): "Advanced",
    (None, "Análisis P-Δ (2º orden)"): "P-Δ analysis (2nd order)",
    (None, "↳ Captura desplome — más lento, requerido en torres esbeltas"):
        "↳ Captures sway — slower, required for slender towers",
    (None, "✓ Limpio"): "✓ Clean",
    (None, "Coloreado:"): "Colour mode:",
    (None, "Geometría deformada"): "Deformed geometry",
    (None, "Amplificación ×"): "Magnification ×",
    (None, "✓ Vista deformada activa"): "✓ Deformed view active",
    (None, "Mejora tu andamio automáticamente:"): "Improve your scaffold automatically:",
    (None, "añade cruces, acorta vanos y ajusta"): "add braces, shorten bays and adjust",
    (None, "postes hasta que cumpla (8 intentos)."): "standards until it passes (8 attempts).",
    (None, "✓ Listo, tu andamio se ha mejorado"): "✓ Done, your scaffold has been improved",
    (None, "Geometría modificada · vuelve a comprobar"):
        "Geometry modified · re-check",
    (None, "Historial de iteraciones:"): "Iteration history:",

    # ── Strings dinámicos del cálculo (% formatting) ───────────────────
    (None, "%d aviso(s), %d info — revisa el panel"):
        "%d warning(s), %d info — check the panel",
    (None, "Modelo limpio · %d info · listo para calcular"):
        "Model is clean · %d info · ready to analyse",
    (None, "✗ %dE / %dW"): "✗ %dE / %dW",
    (None, "⚠ %dW"): "⚠ %dW",
    (None, "… y %d más"): "… and %d more",
    (None, "δ máx: %.1f mm  (%s)"): "δ max: %.1f mm  (%s)",
    (None, "   ≈ L/%.0f"): "   ≈ L/%.0f",
    (None, "   %d barra(s) > L/100"): "   %d member(s) > L/100",
    (None, "No se encuentra el objeto en la escena: %s"):
        "Object not found in the scene: %s",

    # ── Strings dinámicos del panel principal (% formatting) ──────────
    (None, "⚠ Solo entran %d bandejas en %.2f m"):
        "⚠ Only %d decks fit in %.2f m",
    (None, "⚠ tilt %.2f m > vano %.2f m: la base puede salir"):
        "⚠ tilt %.2f m > bay %.2f m: the base may stick out",
    (None, "%.2f m × %.2f m · %s"): "%.2f m × %.2f m · %s",
    (None, "Clase %s → qk = %.2f kN/m²"): "Class %s → qk = %.2f kN/m²",
    (None, "Peso: %.1f kg · MRd = %.2f kN·m · VRd = %.1f kN"):
        "Weight: %.1f kg · MRd = %.2f kN·m · VRd = %.1f kN",
    (None, "Sistema: %s · CE"): "System: %s · CE",
    (None, "⚠ Hueco perp %.0f mm > %d mm (EN 12811-1)"):
        "⚠ Perp gap %.0f mm > %d mm (EN 12811-1)",
    (None, "⚠ Bandejas exceden depth en %.0f mm"):
        "⚠ Decks exceed depth by %.0f mm",
    (None, "Hueco perp %.0f mm ≤ %d mm ✓"): "Perp gap %.0f mm ≤ %d mm ✓",
    (None, "💡 Sugerido: %s m → hueco %.0f mm"):
        "💡 Suggested: %s m → gap %.0f mm",

    # ── tutorial_guide.py ──────────────────────────────────────────────
    (None, "Tutorial guiado"): "Guided tutorial",
    (None, "Empezar tutorial guiado"): "Start guided tutorial",
    (None,
     "Asistente paso a paso para crear tu primer andamio. "
     "Te guía con instrucciones sobre el viewport y detecta "
     "automáticamente cuándo completas cada acción"):
        "Step-by-step wizard to build your first scaffold. Walks you "
        "through with viewport instructions and automatically detects "
        "when you complete each action",
    (None, "Siguiente"): "Next",
    (None,
     "Avanza al siguiente paso del tutorial sin esperar a la detección "
     "automática"):
        "Advance to the next tutorial step without waiting for automatic "
        "detection",
    (None, "Cancelar tutorial"): "Cancel tutorial",
    (None, "Termina el tutorial sin completarlo"):
        "End the tutorial without completing it",
    (None, "El tutorial ya está activo"): "The tutorial is already active",
    (None, "▶ Empezar tutorial"): "▶ Start tutorial",
    (None, "Te guía a crear tu primer andamio."):
        "Walks you through building your first scaffold.",
    (None, "5 pasos · 5 minutos."): "5 steps · 5 minutes.",
    (None, "✓ Cerrar"): "✓ Close",
    (None, "Siguiente ▶"): "Next ▶",
    (None, "Paso %d de %d"): "Step %d of %d",
    (None, "Paso %d/%d: %s"): "Step %d/%d: %s",
    (None, "ESC para salir · ▶ Siguiente en el panel lateral para avanzar"):
        "ESC to exit · ▶ Next in the side panel to advance",
    # STEP_INFO entries
    (None, "👋 ¡Bienvenido al tutorial guiado!"): "👋 Welcome to the guided tutorial!",
    (None,
     "Vas a crear tu primer andamio en 5 pasos. "
     "Sigue las instrucciones aquí abajo."):
        "You're going to build your first scaffold in 5 steps. "
        "Follow the instructions below.",
    (None, "Pulsa SIGUIENTE para empezar · ESC para cancelar."):
        "Press NEXT to start · ESC to cancel.",
    (None, "Paso 1 de 5 — Crea el primer punto"):
        "Step 1 of 5 — Create the first point",
    (None, "En el menú superior del viewport: Add → Empty → Plain Axes."):
        "From the viewport top menu: Add → Empty → Plain Axes.",
    (None,
     "Esto crea un marcador 3D que será el inicio de "
     "tu andamio. Avanza automáticamente al detectarlo."):
        "This creates a 3D marker that will be the start of your "
        "scaffold. Advances automatically once detected.",
    (None, "Paso 2 de 5 — Crea el segundo punto"):
        "Step 2 of 5 — Create the second point",
    (None, "Añade otro empty: Add → Empty → Plain Axes."):
        "Add another empty: Add → Empty → Plain Axes.",
    (None,
     "Sepáralo del primero (mueve con G y X 8 unidades). "
     "Será el otro extremo del andamio."):
        "Separate it from the first (move with G and X 8 units). "
        "It will be the other end of the scaffold.",
    (None, "Paso 3 de 5 — Añádelos a la lista"):
        "Step 3 of 5 — Add them to the list",
    (None,
     "Abre la pestaña Andamios (N) y, en Trayectoria, "
     "pulsa + dos veces y asigna los dos empties."):
        "Open the Scaffolding tab (N) and, in Path, press + twice "
        "and assign the two empties.",
    (None, "Avanza cuando los dos puntos estén en la lista."):
        "Advances once both points are in the list.",
    (None, "Paso 4 de 5 — Genera el andamio"):
        "Step 4 of 5 — Generate the scaffold",
    (None, "Pulsa el botón ⟳ Generar / Actualizar."):
        "Click the ⟳ Generate / Update button.",
    (None,
     "Por defecto crea un andamio de 2 plantas con "
     "plataformas, barandillas y escalera."):
        "By default it creates a 2-storey scaffold with decks, "
        "guardrails and a ladder.",
    (None, "🎉 ¡Listo! Has creado tu primer andamio"):
        "🎉 Done! You've built your first scaffold",
    (None, "Ahora puedes calcular su resistencia o exportar un plano CAD."):
        "Now you can analyse its strength or export a CAD drawing.",
    (None, "Pulsa CERRAR para terminar. El modo guía se desactiva."):
        "Press CLOSE to finish. The guide mode turns off.",

    # ── self.report messages ────────────────────────────────────────────
    (None, "Genera el andamio primero"): "Generate the scaffold first",
    (None, "Genera primero el andamio."): "Generate the scaffold first.",
    (None, "Colores restablecidos a los valores por defecto"):
        "Colors restored to defaults",
    (None, "Log de diagnóstico limpiado"): "Diagnostics log cleared",
    (None, "Selecciona una fila de la lista primero."):
        "Select a row from the list first.",
}


# ----------------------------------------------------------------------
# Tabla pública consumida por bpy.app.translations.register
#
# Sólo se registra inglés. Para usuarios con Blender en español el
# msgid es ya el texto fuente y no hace falta entrada — Blender muestra
# el msgid directamente.
# ----------------------------------------------------------------------
TRANSLATIONS = {
    "en_US": EN,
}
