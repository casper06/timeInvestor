# ADR-0001: Elección de motor por serie, no global

## Contexto

Hasta #7 había un solo interruptor global (`USE_REAL_TIMESFM`) que decidía
el motor para todas las series. El benchmark walk-forward con datos reales
(`scripts/benchmark_real_data.py`, 5 cutoffs por serie, FRED + yfinance)
mostró que TimesFM ganó 4 de 4 series FRED estacionales, 0 de 4 ETFs
diversificados y, en historia corta (30/60/90 días), como mucho 1 de 4
tickers en cualquier ventana (mensaje del commit 2682e87).

## Decisión

`EngineSelector` (`backend/services/engine_selector.py`) elige el motor
**por serie**, con catálogos explícitos (`SEASONAL_FRED_CATALOG`,
`DIVERSIFIED_ETF_CATALOG`) que nunca se infieren del nombre o del ticker.
Regla original: una categoría va a TimesFM solo si TimesFM ganó en al menos
el 50% de sus series representativas. La historia corta recibe un aviso de
baja confianza, no un cambio de motor. Cada respuesta explica la elección en
`engine_selection_reason`.

## Consecuencias

- El motor refleja la evidencia medida, incluidas las hipótesis que no se
  sostuvieron (ETFs, cold-start).
- Las series fuera de los catálogos caían en silencio al default (Holt).
  Lo resolvió la ADR-0002.
- La entrada estacional del catálogo se volvió a medir contra un rival
  estacional justo y pasó a tener motor y solidez de evidencia por serie
  (ADR-0008).

## Estado

Aceptada. Ampliada por ADR-0002 (auto-discovery) y ADR-0008 (catálogo
estacional con evidencia por serie).

## Referencias

- PR #7, commit `2682e87`.
- Resultados: tabla en el docstring de `backend/services/engine_selector.py`
  y en el mensaje del commit. Ese benchmark no tiene archivo en
  `docs/results/`.
