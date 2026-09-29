# ADR-0033: IDs de FRED validados contra FRED antes de la UI (4.11)

## Contexto

El LLM propone IDs de FRED que *parecen* reales y no existen: `TOTALSI`,
`IPGD`. Nada aguas abajo podía distinguirlos de uno real — el ID viajaba hasta
la UI y el usuario se enteraba cuando el gráfico volvía vacío, o con el 404
humanizado de `/data/macro`, ya dentro de la vista.

El prompt v2 (ADR-0030) pide "no inventes IDs de FRED". Es una instrucción, no
una garantía: sigue siendo el LLM el que decide.

## Decisión

Todo ID de FRED que proponga el LLM se verifica **antes de llegar a la UI**, en
`backend/services/fred_grounding.py`, llamado desde `analyze_thesis` — el único
punto por donde una traducción entra a la app.

Tres resultados posibles, en el campo `grounding` de cada serie:

- **`verificado`**: el ID existe en FRED (`/fred/series`). Se conserva, y se
  guarda el **título oficial de FRED** (`fred_title`), nunca uno escrito a mano.
- **`sugerido_por_busqueda`**: el ID no existe. Se busca el *concepto* que
  describió el LLM con `fred/series/search` y se **ofrecen hasta 3 candidatos
  reales**, cada uno con su título de FRED, frecuencia, SA/NSA y rango de
  fechas. **La app no sustituye el ID: elige el usuario.** Hasta que elija, la
  serie **no entra al análisis** (`MacroSuggestion.enters_analysis()`), y la UI
  muestra el aviso "'X' no existe en FRED; elegí un reemplazo o seguí sin esta
  serie".
- **`descartado`**: el ID no existe y la búsqueda no encontró nada. Se marca
  con un aviso visible; nunca se descarta en silencio.

`grounding = null` es un cuarto estado, distinto de los tres: **no se pudo
verificar** (sin `FRED_API_KEY`, o FRED no respondió). La serie se conserva tal
como la propuso el LLM, marcada "sin verificar". Tirar series reales porque
falta la clave sería peor que mostrarlas sin sello.

### `search_concept_en`: el índice de búsqueda de FRED es solo en inglés

Verificado contra la API real el 2026-09-29:

| `search_text` | resultados |
|---|---|
| `new home sales` | 2986 |
| `Ventas totales de viviendas nuevas` | **0** |
| `industrial production durable goods` | 8153 |
| `Produccion industrial de bienes duraderos` | **0** |

El prompt devuelve `name` en español (ADR-0030). Buscar con él habría
**descartado todos los IDs inventados en vez de repararlos**: la función de
búsqueda habría nacido muerta. Por eso el prompt ahora pide además
`search_concept_en`, el concepto en inglés. `name` y `category` quedan como
respaldo para un proveedor que no lo complete (el mock, una tesis vieja en
caché).

Se toma el primer resultado del ranking de FRED (`order_by=search_rank`, su
default): elegir entre los candidatos con una heurística propia sería otra
adivinanza, y 4.11 existe para dejar de adivinar.

### Por qué lo sugerido no entra solo

El primer resultado de FRED es una conjetura sobre el *concepto*, no la serie
que el usuario pidió. El caso real lo muestra: buscar "new home sales" para
`TOTALSI` (una tesis sobre **cuántas** viviendas se construyen) devuelve
primero **MSPUS**, el **precio mediano** de las casas vendidas. Es una serie
real y del tema, pero mide otra cosa: sustituirla en silencio habría metido un
precio donde la tesis hablaba de cantidades, y todo lo que sigue —pronóstico,
correlación, copiloto— habría trabajado sobre esa confusión sin avisar.

Qué entra al análisis, entonces:

| Estado | ¿Entra a pronósticos, correlaciones y copiloto? |
|---|---|
| `verificado` | Sí |
| `sugerido_por_busqueda` sin elegir | **No** |
| `sugerido_por_busqueda` elegido por el usuario | Sí |
| `descartado` | No |
| `null` (no se pudo verificar) | No |

El copiloto además **recibe los IDs que quedaron sin resolver**
(`unresolved_macro_series`) como "Sin medir", con la instrucción de decir que
ese eslabón del mecanismo no tiene datos, en vez de callarlo.

## Consecuencias

- Ninguna serie macro llega a la app sin haber sido contrastada con FRED.
- La UI distingue los cuatro estados en el chip de cada serie: verificado
  (como siempre), sugerido (ámbar), descartado (rojo, tachado) y sin verificar
  (gris), con la nota en el `title`.
- Un ID inventado ya no puede pasar por uno confirmado por FRED.
- **Costo:** una llamada a `/fred/series` por serie en cada traducción (más una
  de búsqueda por ID que no exista). Van con la caché que ya tenía
  `get_series_metadata`.
- Se ve además que el `name` del LLM y el título real de FRED **no coinciden**
  aunque el ID exista: en la verificación real, `PERMIT` y `HOUST` salieron
  `verificado` con títulos de FRED distintos del nombre que había puesto el
  LLM. `fred_title` deja eso a la vista.

## Verificación

- **Tests sin red ni claves** (`tests/test_fred_id_grounding.py`, 11):
  `httpx.MockTransport` con los cuerpos reales de FRED, incluido su 400
  "The series does not exist".
- **Contra la API real** (2026-09-29), sobre una COPIA de la DB:
  - `TOTALSI` → 400 "does not exist" → sugiere `MSPUS` ("Median Sales Price of
    New Houses Sold for the United States");
  - `IPGD` → 400 "does not exist" → sugiere `IPG3344S`;
  - `UMCSENT` → existe → `verificado`, "University of Michigan: Consumer
    Sentiment".
- **Traducción real con Claude CLI Sonnet** (no Gemini), sobre la copia: las 4
  series de la tesis de vivienda salieron `verificado`
  (`MORTGAGE30US`, `HSN1F`, `PERMIT`, `HOUST`), con `search_concept_en` en
  inglés.

### Verificación en el navegador (2026-09-29)

Sobre una COPIA de la DB, con el frontend construido y **solo el LLM stubbeado**
(la validación, FRED y la UI son reales; una traducción real de Sonnet devuelve
IDs válidos y nunca mostraría el selector):

- `TOTALSI` e `IPGD` aparecen como chips **"sin reemplazo elegido"**, cada uno
  con su aviso y sus 3 candidatos con metadata (MSPUS/ASPUS/EXHOSLUSM495S y
  IPG3344S/IPG3344A/IPG3344N).
- **"SERIE ACTIVA" muestra solo ITB, XHB y UMCSENT**: los dos IDs inventados no
  entran al análisis.
- Al tocar "Agregar" en MSPUS, el chip pasa a **"MSPUS elegida por vos"**, su
  selector desaparece y **MSPUS se suma a "SERIE ACTIVA"**. `IPGD` sigue
  pendiente y fuera.

## Estado

Aceptada.

## Referencias

- Rama `feat/fred-id-grounding`.
- 4.11 en `docs/PLAN.md`; ADR-0026 (ruteo FRED/yfinance), ADR-0029
  (metadatos reales), ADR-0030 (prompt v2).
