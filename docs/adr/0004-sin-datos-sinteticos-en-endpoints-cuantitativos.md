# ADR-0004: Prohibición de datos sintéticos en los endpoints cuantitativos

## Contexto

Cuando falla una fuente de datos, el sistema puede generar una serie de
referencia sintética. El motivo de no usarla en ningún cálculo cuantitativo
está en `CONTEXT.md`:
- **Sección 4, regla 2:** "Nunca fabricar datos, resultados de benchmark, o
  metadata. Si una fuente de datos falla, error explícito — nunca una
  aproximación silenciosa."
- **Sección 3, el bug de caché:** al servir desde la caché, `source` se
  sobreescribía con `"cached"` y se perdía si el dato original era real o
  sintético, "lo que permitía que datos inventados pasaran los guards de
  'solo datos reales' después del primer hit de caché". Es decir, la
  prohibición sola no alcanzaba si la procedencia no sobrevivía a la caché
  (ADR-0005).

El commit que introdujo la prohibición (7038ec8) no tiene cuerpo. El texto
del guard da la razón puntual: "no se puede validar una tesis sobre datos
generados" (`backend/services/backtest_engine.py`). Cronología: el guard es
de 7038ec8 (PR #1, 2026-09-20), la corrección del bug de caché es de #3
(2026-09-21) y `CONTEXT.md` se versionó en #18.

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

- Commit `7038ec8`, en la rama de PR #1 (merge `afaa0f7`).
- Motivo: `CONTEXT.md`, sección 3 (bug de caché, corregido en PR #3, commit
  `4c318b0`) y sección 4, regla 2. Los guards de
  portfolio, riesgo y rebalanceo están en sus servicios
  (`portfolio_engine.py`, `risk_engine.py`, `rebalance_engine.py`).
