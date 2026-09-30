# ADR-0033: IDs de FRED validados, y reparados por el propio LLM (4.11)

## Contexto

El LLM propone IDs de FRED que *parecen* reales y no existen: `TOTALSI`,
`IPGD`. Nada aguas abajo podía distinguirlos de uno real — el ID viajaba hasta
la UI y el usuario se enteraba cuando el gráfico volvía vacío, o con el 404
humanizado de `/data/macro`, ya dentro de la vista.

El prompt v2 (ADR-0030) pide "no inventes IDs de FRED". Es una instrucción, no
una garantía: sigue siendo el LLM el que decide.

## Decisión

Todo ID de FRED se verifica **antes de llegar a la UI**, en
`backend/services/fred_grounding.py`, llamado desde `analyze_thesis` — el único
punto por donde entra una traducción. **El usuario no elige nada: el análisis
sigue siendo de un solo paso**, y es el propio LLM el que corrige sus IDs.

### La pasada de reparación

1. Cada ID se verifica contra FRED (`/fred/series`).
2. Los inexistentes van a `fred/series/search` con el concepto **en inglés**
   (`search_concept_en`), que devuelve hasta **5 candidatos reales con
   metadata**: título de FRED, frecuencia, SA/NSA, rango de fechas y unidad.
3. **UNA llamada extra al mismo proveedor** (`BaseLLMClient.complete_json`) con
   el mecanismo de la tesis, los IDs inválidos y sus candidatos. Para cada uno
   el modelo responde:
   - `elegir` un `series_id` **de esa lista**, con una línea de justificación;
   - `descartar`, con el motivo;
   - `reformular` la búsqueda, **una sola vez por serie**; después elige o
     descarta. No hay bucles abiertos.
4. Lo elegido **se vuelve a verificar contra FRED**, y **un ID que no esté en
   la lista de candidatos se rechaza** y la serie se descarta.

### Estados

| `grounding` | Qué significa | ¿Entra al análisis? |
|---|---|---|
| `verificado` | el LLM propuso un ID que existe | **Sí** |
| `reparado` | no existía y el LLM eligió un reemplazo real, re-verificado, con su justificación visible | **Sí** |
| `descartado` | no existe y no hubo reemplazo válido; el aviso es informativo, no una pregunta | No |
| `null` | no se pudo verificar (FRED caído o sin clave) | No |

`MacroSuggestion.enters_analysis()` (y su gemelo `entersAnalysis` en el
frontend) queda como **chequeo defensivo**: después de la reparación no debería
quedar nada en un estado intermedio, pero la compuerta es la que decide qué ve
el pronóstico, la correlación y el copiloto. El copiloto además recibe los
descartados como **"Sin medir"**, con la instrucción de declarar que ese
eslabón no tiene datos.

### Sin LLM disponible

Con el mock, con un proveedor que no implementa `complete_json`, o si la
reparación falla, **los inválidos se descartan**. **Nunca se adopta el primer
resultado de la búsqueda.** El caso real muestra por qué: buscar
`"new home sales"` para `TOTALSI` (una tesis sobre **cuántas** viviendas se
construyen) devuelve, en orden, MSPUS y ASPUS (**precios**), dos series de
**existing** home sales y un ratio de meses de oferta. Ninguna mide viviendas
nuevas construidas. Tomar la primera habría metido un precio donde la tesis
hablaba de cantidades, y todo lo que sigue habría trabajado sobre esa confusión
sin avisar.

### `search_concept_en`: el índice de búsqueda de FRED es solo en inglés

Verificado contra la API real el 2026-09-29:

| `search_text` | resultados |
|---|---|
| `new home sales` | 2986 |
| `Ventas totales de viviendas nuevas` | **0** |
| `industrial production durable goods` | 8153 |
| `Produccion industrial de bienes duraderos` | **0** |

El prompt devuelve `name` en español (ADR-0030), así que buscar con él no daría
ningún candidato del que reparar. Por eso el prompt pide además
`search_concept_en`; `name` y `category` quedan como respaldo.

### Las reglas van en el schema, no en el system prompt

Es la lección de ADR-0030, que volvió a aparecer acá. Con un system prompt
largo y numerado, **Claude CLI ignoró `--json-schema` y respondió en Markdown
libre, 3 de 3 intentos** (2026-09-29). El razonamiento era correcto —rechazaba
MSPUS y ASPUS por ser precios— pero ningún parser podía leerlo, así que las dos
series terminaron descartadas por error de formato.

Con las reglas movidas a las descripciones de los campos del schema y un system
prompt de una línea, la misma pasada funcionó a la primera.

## Consecuencias

- Ninguna serie macro llega a la app sin haber sido contrastada con FRED.
- **Un ID inventado ya no puede pasar por uno confirmado**, y la corrección es
  visible: el chip dice "corregida: reemplaza a TOTALSI" y la justificación
  está en el tooltip.
- **Costo:** una llamada a `/fred/series` por serie, más una búsqueda por ID
  inválido, más **una llamada extra al LLM** solo si hubo IDs inválidos (dos
  como mucho, si alguna serie pide reformular). Medido: **24,5 s** con Claude
  CLI Sonnet para dos IDs inválidos.
- La UI **no tiene selector de candidatos**: no hay flujo que espere una acción
  del usuario para completar la traducción.
- Se ve además que el `name` del LLM y el título real de FRED **no coinciden**
  aunque el ID exista (`PERMIT`, `HOUST`). `fred_title` deja eso a la vista.

## Verificación

- **Tests sin red ni claves:** `tests/test_fred_id_grounding.py` (validación) y
  `tests/test_fred_repair_pass.py` (reparación), con `httpx.MockTransport` y un
  `StubRepairLLM` **declarado en el archivo de test**, nunca un cliente real.
  Cubren: elegir de la lista, rechazar un ID fuera de la lista, `descartar`, el
  tope de una reformulación, una segunda reformulación negada, sin LLM, y la
  reparación que falla.
- **Contra la API real de FRED** (2026-09-29): `TOTALSI` e `IPGD` devuelven el
  400 "The series does not exist"; `UMCSENT` existe.
- **Pasada de reparación real con Claude CLI Sonnet** (traducción stubbeada
  solo para forzar los IDs inválidos; FRED y la reparación, reales), sobre una
  COPIA de la DB — **24,5 s**:

| ID inválido | Resultado | Serie | Justificación del modelo |
|---|---|---|---|
| `TOTALSI` | **reparado** (1 reformulación) | `HSN1F` — "New One Family Houses Sold: United States" | "es la serie oficial de ventas totales de casas nuevas unifamiliares en EE.UU., mensual y SAAR, coherente con el mecanismo de asequibilidad hipotecaria" |
| `IPGD` | **descartado** (1 reformulación) | — | "todos los candidatos son subsectores específicos (semiconductores, autos), ninguno es el índice agregado de producción industrial de bienes duraderos que se necesita" |
| `UMCSENT` | verificado | `UMCSENT` | (no pasó por reparación) |

  Las dos series usaron su reformulación, y con razón: `HSN1F` **no estaba**
  entre los 5 candidatos de `"new home sales"` (que eran 2 precios, 2 series de
  *existing* home sales y un ratio de oferta). El modelo reformuló, lo encontró
  y lo justificó. En `IPGD` prefirió descartar antes que aceptar un subsector
  por el agregado — el comportamiento que el schema pide.

## Estado

Aceptada.

## Referencias

- Rama `feat/fred-id-grounding`.
- 4.11 en `docs/PLAN.md`; ADR-0026 (ruteo FRED/yfinance), ADR-0029
  (metadatos reales), ADR-0030 (prompt v2 y el modo de falla del `--json-schema`).
