# ADR-0026: Ruteo FRED / yfinance por tipo y por FRED, no por catálogo fijo (4.11 parcial)

## Contexto

`CorrelationEngine` decidía de dónde bajar cada serie mirando solo el
catálogo fijo `FREDDataFetcher.SERIES_CATALOG`. Todo lo que no estuviera ahí
iba a yfinance. Resultado: una correlación con `PCU221110221110`, una serie
de FRED fuera del catálogo, fallaba con:

> Fallo en la ingesta de datos para 'PCU221110221110': No se pudieron obtener
> datos de mercado para 'PCU221110221110' (yfinance devolvió dataframe vacío
> …) y ALLOW_SYNTHETIC_DATA=false y ALLOW_SYNTHETIC_DATA=false

El texto repetido tenía su propia causa: el `ValueError` de "dataframe
vacío" se lanzaba dentro del `try` de `MarketDataFetcher.get_history`, y el
`except Exception` lo volvía a envolver.

- El backtest (2.7) solo iba a FRED si el pedido decía `series_type='macro'`.
- El auto-discovery del pronóstico, igual.

## Decisión

Una sola regla, en `backend/services/series_routing.py` (`is_fred_series`):
1. **Si el pedido trae el tipo, decide el tipo.** La UI siempre lo sabe: los
   tickers son `equity` y los chips de "+ FRED ID", `macro`. Por eso
   `/correlation` acepta `series_types` y el heatmap lo manda.
2. **Si no trae tipo:** primero el catálogo, y después FRED mismo
   (`/fred/series`, la validación de #48). Un ID que FRED conoce es de FRED,
   nunca un ticker de yfinance. Las respuestas definitivas ("existe" o "no
   existe") se recuerdan en memoria del proceso.
3. **Si FRED no se puede consultar** (sin clave o sin red) y el ID no está en
   el catálogo, un ID sin tipo va a yfinance, como antes: en ese caso nada
   prueba que sea de FRED. El error del backtest lo dice.

La usan la correlación, la ruta de backtest y el auto-discovery del
pronóstico. El mensaje duplicado se arregla con `MarketDataUnavailableError`,
que se relanza sin volver a envolverlo.

La búsqueda de FRED de 4.11 (conceptos → candidatas reales) sigue pendiente.

## Consecuencias

- Verificado sobre una copia de la DB, con la API real:
  - `PCU221110221110` + `DGS10`, con y sin tipos: r = 0,051 sobre 22 meses.
    PCU se consultó a FRED y se bajó de FRED; DGS10 está en el catálogo.
  - Con NVDA: solo NVDA fue a yfinance.
  - En el navegador, el heatmap manda `series_types` y muestra la matriz sin
    errores.
- Un pedido sin tipo de un ticker que no está en el catálogo cuesta una
  consulta a FRED por proceso: la respuesta queda recordada.
- En los tests, `conftest.py` hace que FRED "no se pueda consultar" por
  defecto: la suite no sale a la red.

## Estado

Aceptada.

## Referencias

- Rama `fix/correlation-fred-routing`.
- Tests: `tests/test_series_routing.py` y `CorrelationHeatmap.test.tsx`.
