# ADR-0021: Precisión de la fuente: sin redondeo en la carga; se redondea al mostrar (criterio v7)

## Contexto

`data_fetcher.py` redondeaba cada valor a 2 decimales al cargarlo (yfinance,
FRED, fundamentales y series sintéticas). Eso descarta información antes de
los motores. Por ejemplo, INDPRO publica 4 decimales, STLFSI4 4 y NFCI 3.

## Decisión

- **Carga y proceso:** los valores se cargan, se cachean y se procesan con
  la precisión de la fuente. Se redondea **solo al mostrar**: la UI ya
  formatea con `toFixed`, Chart.js muestra hasta 3 decimales, y el prompt
  del copiloto formatea el último precio con 4 decimales.
- **Caché de datos:** no necesita invalidación ni versión de formato. Vive
  solo en la memoria del proceso (TTL `CACHE_TTL_SECONDS`), así que un
  reinicio la vacía y ningún valor redondeado sobrevive a un deploy.
- **Decisiones cacheadas (`engine_decisions`):** se subió el criterio a
  **v7** (mecanismo de ADR-0006). La regla no cambia, pero sus entradas sí,
  y en NFCI el cambio alcanzó para mover el arrepentimiento de v5 (ver
  abajo). Costo: un mini-backtest por serie, de 1 a 2 s.

## Impacto medido en los resultados versionados (no se re-corrieron para reemplazarlos)

Los tres snapshots guardados (2.5, 3.0d y 3.5) están redondeados a 2
decimales y **no se pueden "desredondear"**.
- **Método:** se armó un **gemelo** de cada uno, bajando las mismas series a
  la precisión de la fuente y conservando exactamente las mismas fechas. Las
  diferencias fueron de redondeo (≤ 0,005; en algunos ETF hasta 0,0051 por
  ruido de punto flotante o ajuste de yfinance).
- **Comparación:** para aislar la precisión de los cambios de código
  posteriores, se comparó el código actual sobre el snapshot redondeado
  contra el código actual sobre el gemelo.

| Resultado | ¿Se puede re-medir? | ¿Cambia el veredicto? |
|---|---|---|
| 2.5 (cobertura de Holt) | sí, con el gemelo | **no**: cobertura al 95% idéntica; la de ETFs al 80% pasa de 90,56 a 90,54 |
| 3.0d (benchmark estacional) | sí, con el gemelo | **no**: las 4 series con el mismo motor y los mismos conteos |
| 3.5 (categorías FRED) | sí, con el gemelo (24 series; DFEDTARU ya tenía 2 decimales en la fuente) | **no**: la capacidad, la hipótesis de las diarias, v5 (adoptada) y C (rechazada) quedan iguales |

- **El único cambio a nivel de serie** es NFCI en v5: pasa de "mejora o
  empata" a "empeora" (A4 3,16, A5 8,59). La semanal sigue pasando 4/5.
- **NFCI y STLFSI4** no tenían empates en la comparación de capacidad, ni
  redondeados ni precisos. La afirmación de 3.5 sobre empates era una
  inferencia; quedó corregida en ese documento.
- **3.0d, aparte:** con el código actual, 3.0d ya no reproduce el campo
  `cov80_app_band` ni siquiera sobre su snapshot redondeado, porque #29
  corrigió después la banda de TimesFM. Es independiente de 2.9; el resto
  de 3.0d se reproduce igual.
- **Reproducción:** los gemelos y sus corridas quedaron en el scratchpad de
  la sesión. No son resultados versionados, y los resultados de
  `docs/results/` no se reemplazaron.

## Consecuencias

- Los pronósticos de los **motores** todavía se redondean a 2 decimales
  (`round(pred_val, 2)` en `forecast_engine.py`), y las métricas del
  backtest se calculan sobre esos pronósticos. En series de magnitud chica
  (NFCI ≈ −0,5) eso es comparable al error. Queda propuesto como 2.11.

## Estado

Aceptada.

## Referencias

- Rama `fix/no-rounding-on-load` (2.9).
- Tests: `tests/test_source_precision.py`.
