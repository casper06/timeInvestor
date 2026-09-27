# ADR-0004: Prohibición de datos sintéticos en los endpoints cuantitativos

## Contexto

Cuando falla una fuente de datos, el sistema puede generar una serie de
referencia sintética. El commit que introdujo la prohibición (7038ec8,
"phase 2.5 - data provenance…") no tiene cuerpo: **motivo no documentado**
en ese commit. El texto del guard da la razón puntual: "no se puede validar
una tesis sobre datos generados" (`backend/services/backtest_engine.py`).
`CONTEXT.md` (sección 4, regla 2, escrita después en #18) la generaliza:
"Nunca fabricar datos".

## Decisión

- Con `ALLOW_SYNTHETIC_DATA=false` (el default), una fuente caída da un
  error explícito (`/data/*` responde 404 con la causa) en vez de inventar
  datos.
- Aunque se permitan los datos sintéticos, los endpoints cuantitativos los
  rechazan con 422: backtest, correlación, `portfolio/optimize`,
  `portfolio/risk` y `portfolio/rebalance-backtest`.
- La UI deshabilita esas pestañas si la serie activa es sintética.

## Consecuencias

Una métrica cuantitativa nunca se calcula sobre datos inventados. Depende de
que `source` se preserve en todo el camino (ADR-0005).

## Estado

Aceptada.

## Referencias

- Commit `7038ec8`, en la rama de PR #1 (merge `afaa0f7`). Los guards de
  portfolio, riesgo y rebalanceo están en sus servicios
  (`portfolio_engine.py`, `risk_engine.py`, `rebalance_engine.py`).
