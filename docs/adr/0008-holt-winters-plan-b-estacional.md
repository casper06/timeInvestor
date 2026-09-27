# ADR-0008: Holt-Winters (statsmodels `ETSModel`) como base y plan B estacional

## Contexto

En series estacionales, Holt pierde incluso contra el naive estacional
(3.0d). Comparar TimesFM contra Holt en esas series era compararlo con un
rival que ni siquiera le gana al naive (comentario en
`auto_discovery._run_mini_backtest`).

## Decisión

- **Motor** (#27, 3.0b): `HoltWintersForecastEngine`, ETS(A,Ad,A) sobre el
  log de la serie si es positiva, con `statsmodels` `ETSModel`. Se eligió
  `ETSModel` porque ajusta por MLE y tiene `get_prediction` (intervalos
  analíticos exactos); `ExponentialSmoothing` minimiza SSE y no tiene
  `get_prediction` (mensaje del commit 67aa2cc). Si la serie no es
  estacional, lanza `NotSeasonalError`: nunca un Holt en silencio.
- **Selector** (#30, 3.0f):
  - si TimesFM no puede correr, el plan B es Holt-Winters para las series
    que el detector marca estacionales (Holt si Holt-Winters falla, con el
    motivo) y Holt para el resto;
  - el catálogo estacional pasa a tener motor y solidez de evidencia por
    serie, medidas contra Holt-Winters (test de signo pareado, Bonferroni);
  - el auto-discovery compara las series estacionales contra Holt-Winters
    con MASE estacional (criterio v3).

## Consecuencias

- `MRTSSM4451USN` quedó en Holt-Winters: TimesFM no le ganó de forma
  significativa.
- Suma la dependencia de `statsmodels`.

## Estado

Aceptada.

## Referencias

- PR #27 (commit `67aa2cc`) y PR #30 (commit `cf9fd27`).
- Resultados: `docs/results/seasonal_benchmark_2026-09-26.md` y
  `docs/results/hw_vs_holt_coverage_2026-09-26.json`.
