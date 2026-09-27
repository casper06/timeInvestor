# ADR-0003: "No evaluado" no es "Holt ganó"

## Contexto

Con TimesFM no disponible (imagen liviana, pesos sin bajar), el mini-backtest
guardaba `engine_choice="holt"` con `mase_timesfm=None`, y eso quedaba
cacheado 30 días como si Holt le hubiera ganado a TimesFM (mensaje del
commit 9bdb2b2; `CONTEXT.md`, sección 3).

## Decisión

`mase_timesfm` NULL significa exactamente "no evaluado":
- esa decisión se re-evalúa apenas TimesFM está disponible, sin esperar el
  TTL;
- mientras no lo esté, se sirve la cacheada sin re-correr;
- el motivo que ve el usuario dice "TimesFM no evaluado", nunca "Holt ganó".

No hubo cambio de esquema: NULL ya tenía ese significado. Después (#20), un
TimesFM cargado que cae a Holt en todos los cutoffs se distingue con
`timesfm_failed_cutoffs > 0` y espera el TTL.

## Consecuencias

`_is_stale` puede cargar el modelo, así que esa condición se chequea al
final.

## Estado

Aceptada.

## Referencias

- PR #15, commit `9bdb2b2`.
- Relacionado: PR #20 (commit en la rama `fix/backtest-timesfm-fallback`,
  merge `96446e7`).
