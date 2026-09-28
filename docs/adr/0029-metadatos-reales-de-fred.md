# ADR-0029: Metadatos reales de FRED (título, unidad, frecuencia, SA/NSA)

## Contexto

`FREDDataFetcher.get_series` armaba el nombre y la unidad así:
- **Serie fuera del catálogo:** "FRED Series X" y "Index". Es una
  suposición: PCU221110221110 es "Index Dec 2003=100" y DGS10 es "Percent".
- **Serie del catálogo:** el nombre y la unidad escritos a mano.
  IPG2211A2N figuraba como "Electric Power Generation, Transmission and
  Distribution Index", pero en FRED es "Industrial Production: Utilities:
  Electric and Gas Utilities (NAICS = 2211,2)".
- **Ajuste estacional (SA/NSA):** no se leía en ningún lado (4.3).

## Decisión

- **Fuente de los metadatos:** el fetcher toma de `/fred/series` el título,
  la unidad, la frecuencia y el ajuste estacional (largo y corto). Quedan en
  `TimeSeriesData` con `metadata_source="fred"`.
- **Si FRED no responde:** `metadata_source="unavailable"`, nombre = el ID,
  `unit=None`, y el motivo en `metadata_note`. La UI muestra "metadatos no
  disponibles". No se inventa una unidad ni se usa el nombre del catálogo.
- **Serie sintética de referencia:** tampoco lleva unidad.
- **Dónde se muestra:**
  - pie del gráfico;
  - tarjeta de objetivo;
  - telemetría;
  - ejes y leyenda del gráfico dual;
  - informe (línea "Serie");
  - evidencia del copiloto, que ahora usa estos metadatos y no hace una
    consulta propia.
- **Caché:** un acierto de caché conserva los metadatos (`model_copy`).
- **4.3:** queda cubierta la parte visible. Usar SA/NSA al elegir el motor
  cambiaría el criterio, y queda pendiente.

## Consecuencias

- Cada serie FRED cuesta un pedido más a FRED (metadata), en caché.
- Verificado en el navegador sobre una copia de la DB:
  - IPG2211A2N: "Index 2017=100 · Monthly · NSA";
  - PCU221110221110: "Index Dec 2003=100 · Monthly · NSA";
  - dual-axis con las dos series;
  - informe con la línea "Serie";
  - copiloto: DGS10 "Percent (…, Daily, NSA) … +1.02 puntos porcentuales".

## Estado

Aceptada.

## Referencias

- Rama `fix/fred-metadata`.
- Tests: `tests/test_fred_metadata.py` y `SeriesMeta.test.tsx`.
