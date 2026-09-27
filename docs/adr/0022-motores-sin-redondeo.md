# ADR-0022: Los motores y el backtest sin redondeo; el redondeo es solo de presentación (criterio v8)

## Contexto

Con 2.9 (ADR-0021) los datos dejaron de redondearse al cargarlos, pero
quedaban dos redondeos más adelante:
- los motores (Holt, Holt-Winters y TimesFM, incluida su banda de fallback)
  redondeaban pronóstico y bandas a 2 decimales;
- `BacktestEngine` redondeaba las métricas (MAE a 2, MASE a 3, cobertura y
  acierto direccional a 1) y los pronósticos que devolvía.

La regla del auto-discovery lee esas métricas. En series de magnitud chica
(NFCI ≈ −0,5) el redondeo del pronóstico es comparable al error.

## Decisión

- **Motores y backtest:** devuelven pronóstico, bandas y métricas con
  precisión completa.
- **Presentación:** se redondea solo al mostrar. La UI ya formatea con
  `toFixed`, Chart.js muestra hasta 3 decimales, el informe usa `toFixed`, y
  los prompts del copiloto formatean el objetivo y las bandas con 4
  decimales. Los snapshots de pronóstico guardados en la DB conservan lo que
  devolvió el motor y se muestran con `toFixed`.
- **Parámetros ajustados:** `fitted_params` (α, β, φ, σ) siguen con 4
  decimales. Solo se muestran; ningún cálculo los usa.
- **Criterio v8** (mecanismo de ADR-0006). Medido con los datos precisos de
  2.9, en los 8 cutoffs de la regla, comparando el pipeline anterior contra
  el actual:
  - en NFCI un cutoff se da vuelta: TimesFM pasa de ganar 6-2 a 5-3;
  - en las otras 7 series (STLFSI4, DGS10, INDPRO, IMPCH, T10Y2Y, VIXCLS,
    MORTGAGE30US) cambia solo la brecha relativa, en el 4.º decimal;
  - ninguna serie cambia de motor en esa muestra.

  Como lo que lee la regla sí cambia, las decisiones se re-evalúan una vez.

## Consecuencias

- Las respuestas JSON llevan más decimales.
- `scripts/holt_explosion.py` replica el motor, así que su variante sin
  recorte (`none`) también dejó de redondear para seguir idéntica a
  producción. El `--options` de 2.6 re-corrido hoy daría números levemente
  distintos. El resultado versionado no se re-corrió.
- Los resultados versionados anteriores se midieron con pronósticos
  redondeados a 2 decimales. No se re-corrieron.

## Estado

Aceptada.

## Referencias

- Rama `fix/no-rounding-in-engines` (2.11).
- Precisión de los datos: ADR-0021.
- Tests: `tests/test_engine_precision.py`.
