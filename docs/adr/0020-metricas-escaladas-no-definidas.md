# ADR-0020: Métricas escaladas no definidas: sin `+ epsilon`; la decisión usa MAE en pares (criterio v6)

## Contexto

`BacktestEngine` calculaba MASE, MASE estacional y MAPE dividiendo por su
escala `+ 1e-8`:
- la escala del MASE es el error del naive en el entrenamiento;
- la del MAPE, el valor real.

Cuando la escala es 0, el resultado es un número enorme, no un error. En
DFEDTARU (tasa objetivo de la Fed, en escalones) el entrenamiento de algunos
cutoffs no se mueve y el MASE valía ~2,5 millones. El usuario lo veía en el
motivo del motor ("Holt ganó MASE 2500007.165…"), y el mini-backtest
promediaba esos valores.

## Decisión

- **Métricas:** si la escala es 0 o numéricamente despreciable
  (≤ 1e-9 × max(1, nivel medio de la serie)), la métrica **no está
  definida**. Vale `None`, con el motivo en `BacktestMetrics.undefined`:
  - MASE: "la serie no varió en el período de entrenamiento";
  - MASE estacional: "repitió exactamente el ciclo anterior";
  - MAPE: "algún valor real del período evaluado es 0".

  Aplica al modelo, al naive y al naive estacional. El sMAPE conserva su
  epsilon: solo actúa si real y pronóstico son 0, y entonces el numerador
  también es 0.
- **Decisión de motor (criterio v6):** si la métrica de la regla no está
  definida en algún cutoff, **toda la serie** se decide con el **MAE en
  pares** en todos sus cutoffs. Por qué MAE:
  - siempre está definido;
  - dentro de una misma serie está en las mismas unidades en todos los
    cutoffs;
  - en cada cutoff los dos motores comparten la escala, así que el conteo
    de cutoffs ganados es idéntico con MASE o con MAE; solo cambia el
    margen sobre la media;
  - descartar los cutoffs sin métrica perdería pares y podría dejar menos
    de 7.

  La fila guarda `metric = "mae"`, y el motivo lo explica.
- **UI:** "no definido" con el motivo, nunca un número (panel de backtest e
  informe exportado).

## Consecuencias

- Subir a v6 re-evalúa todas las decisiones una vez (mecanismo de
  ADR-0006). En las series sin escalas nulas la decisión no cambia (misma
  regla y misma métrica).
- DFEDTARU se decide con MAE: Holt, igual que en la verificación de #41.
- **Scripts de medición:** `fred_category_benchmark.py`, `horizon_variants.py`
  y `holt_explosion.py` promedian `mase` sin tolerar `None`. Con el código
  actual, el `--replay` de 3.5 ya no reproduce DFEDTARU. Para reproducir el
  JSON versionado hay que usar el commit `5ee140d`.
- **Resultados versionados afectados** (no re-corridos): solo 3.5, en los
  números de v5 y C de DFEDTARU. Los veredictos no cambian:
  - con DFEDTARU fuera o en contra, v5 igual pasa la diaria (3 de 4);
  - C ya estaba rechazada por la mensual SA.

  Los snapshots de 2.2–2.6 y 3.0d no tienen escalas nulas ni valores reales
  en 0 (verificado).

## Estado

Aceptada.

## Referencias

- Rama `fix/undefined-mase-and-v5-checks` (2.10).
- Bug visto en PR #41 (DFEDTARU).
- Criterio anterior: ADR-0019 (v5).
