# ADR-0024: Series de FRED agregadas a mano y cargas superpuestas (4.16)

## Contexto

Dos bugs, vistos al verificar 4.13 con IPG2211A2N:
- **"+ FRED ID" cargaba la serie como acción.** `handleAddMacro`
  (`frontend/src/App.tsx`) llamaba a `handleSelectSeries` justo después de
  `setActiveMacro`. En ese closure la serie todavía no estaba en
  `activeMacro`, así que se pedía a yfinance y fallaba.
- **Un ID que no existe no se distinguía de otros fallos.** FRED responde
  HTTP 400 "The series does not exist." (verificado contra la API real el
  2026-09-27, en `/fred/series` y `/fred/series/observations`). El fetcher
  lo trataba igual que cualquier fallo de conexión. Con
  `ALLOW_SYNTHETIC_DATA=true`, incluso devolvía una serie sintética para un
  ID inexistente.
- **Cargas superpuestas.** `loadSeriesAndForecast` escribía la serie, el
  error y el pronóstico cuando llegaba cada respuesta. Si una respuesta vieja
  llegaba después de una nueva, se mezclaban datos de cargas distintas. Lo
  mismo pasaba con los re-pronósticos por cambio de horizonte o de nivel.

## Decisión

- **FRED inexistente:**
  - `FredSeriesNotFoundError` (subclase de `ValueError`) cuando FRED dice que
    la serie no existe, tanto en `get_series` como en `get_series_metadata`.
  - Nunca se reemplaza por una serie sintética.
  - `/data/macro` y `/catalog/fred-metadata` responden 404 con el mismo
    `detail` de texto y además `code: "fred_series_not_found"`.
  - Los otros 404 de FRED (sin clave, sin conexión) no llevan `code`. Así la
    UI no los confunde con "no existe", y el contrato de
    `test_fred_metadata_endpoint_404_without_key` se mantiene.
- **Agregar a mano:**
  - La búsqueda de FRED de 4.11 no está hecha. Por eso el ID se valida
    contra `/fred/series`, a través del endpoint de metadata que ya existía.
  - Si no existe, el mensaje aparece debajo de "+ FRED ID" y la serie no se
    agrega.
  - Si FRED no se pudo consultar, eso no prueba que el ID esté mal: se agrega
    igual, y la carga dice qué falló.
  - La serie se carga siempre como macro (`handleSelectSeries(id, 'macro')`).
- **Cargas superpuestas: número de pedido, no `AbortController`.**
  - Cada carga, y cada re-pronóstico, toma un número (`loadSeq`). Sus
    respuestas se aplican solo si sigue siendo el último.
  - Por qué un número:
    - el estado se escribe en pocos lugares, así que un solo chequeo ahí
      cubre todos los tipos de pedido (serie, pronóstico, re-pronóstico);
    - cancelar solo ahorraría la descarga, porque el backend sigue
      calculando: sus handlers no se enteran de que el cliente se fue;
    - cancelar obligaría a pasar una señal por cada función de
      `services/api.ts` y a distinguir `AbortError` de un error real.
  - Si se cambia el horizonte o el nivel mientras hay una carga de serie en
    curso, se relanza esa carga con el valor nuevo. Si no, se pronosticarían
    los puntos de la serie anterior bajo la solapa nueva.
  - Si mientras se valida un ID el usuario empezó otra carga, la serie se
    agrega pero no se selecciona: la última acción queda en pantalla.

## Consecuencias

- Agregar una serie de FRED a mano cuesta un pedido más a FRED (la
  validación).
- Verificado sobre una copia de la DB, con puppeteer:
  - IPG2211A2N agregada a mano cargó como macro al primer intento, sin
    ningún pedido a `/data/market`;
  - cambiando rápido entre IPG2211A2N y NVDA, la serie, la tarjeta y el
    indicador de capacidad siempre fueron de la última solapa;
  - con la respuesta de IPG2211A2N demorada a propósito 2,5 s, llegó después
    de la de NVDA y se descartó;
  - un ID inexistente mostró "La serie 'NOEXISTE416' no existe en FRED…" y
    no se agregó.
- Las otras pestañas (backtest, correlación, gráfico dual, asignación)
  tienen sus propias cargas. No se revisaron en 4.16.

## Estado

Aceptada.

## Referencias

- Rama `fix/manual-fred-and-race`.
- Tests: `tests/test_fred_not_found.py` y `frontend/src/App.test.tsx`
  (FRED a mano, ID inexistente, cargas superpuestas, horizonte durante una
  carga).
