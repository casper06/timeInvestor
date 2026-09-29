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
  describió el LLM con `fred/series/search` y se propone el mejor candidato
  real, con su título de FRED. El ID original queda registrado en
  `proposed_series_id`, y la UI lo marca "sugerido por búsqueda".
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

## Estado

Aceptada.

## Referencias

- Rama `feat/fred-id-grounding`.
- 4.11 en `docs/PLAN.md`; ADR-0026 (ruteo FRED/yfinance), ADR-0029
  (metadatos reales), ADR-0030 (prompt v2).
