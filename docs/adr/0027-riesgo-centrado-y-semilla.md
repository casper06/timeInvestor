# ADR-0027: Riesgo sin tendencia por defecto y semilla visible

## Contexto

Dos problemas en la simulación de riesgo de la cartera
(`backend/services/risk_engine.py`):
- **Semilla fija.** Los tres métodos (bootstrap por bloques, Student-t y
  gaussiano) usaban siempre la semilla 42. Cada clic en "Simular" daba los
  mismos números, y el usuario no podía ver cuánto se mueven entre corridas.
- **Tendencia incluida.** Los tres simulaban con la media histórica de los
  retornos del período (2 años):
  - el bootstrap, al remuestrear retornos que la incluyen;
  - Student-t y el gaussiano, al usar `mean` como centro.
  Después de un rally, eso supone que el rally se repite y achica las
  pérdidas simuladas.

## Decisión

- **Semilla:**
  - `PortfolioRiskRequest.seed` es opcional; sin ella, cada pedido usa una
    semilla nueva (`secrets.randbits(32)`);
  - la usada vuelve en `seed_used` y la UI la muestra;
  - "reproducir" la fija para la próxima corrida.
- **Tendencia:**
  - `drift` es `"centered"` por defecto: a cada activo se le resta su retorno
    medio del período antes de simular, en los tres métodos;
  - `"historical"` conserva el comportamiento anterior;
  - la respuesta dice cuál se usó (`drift_used`) y cuánta tendencia había
    (`historical_drift_annual`);
  - la UI lo muestra en una etiqueta; si es la histórica, en ámbar.
- **Por qué centrado, medido** (`docs/results/risk_drift_2026-09-27.md`):
  - cartera CEG, ETN, GEV, PWR y VST con pesos iguales;
  - la tendencia de 2 años es +26,9% anual, con un error estándar de 29,9%
    (t = 0,9): no se distingue de 0;
  - con la tendencia, el VaR95 del bootstrap a 30 días baja de 18,8% a
    16,2%, una diferencia de 8 veces el ruido de semilla;
  - a 252 días baja de 44,4% a 27,3%;
  - P(pérdida > 10%) a un año pasa de 39,5% a 14,9%.

## Consecuencias

- Con los defaults, los números de riesgo son más altos que antes, y ahora
  cambian un poco entre clics. Ese es el ruido real de Monte Carlo, que antes
  quedaba oculto por la semilla fija.
- "Retorno esperado 0" también es un supuesto, pero no depende del período
  elegido.
- **No verificado:** que la cartera medida sea la de la captura que motivó
  el cambio. No tengo la captura y la DB no tiene tesis guardadas.

## Estado

Aceptada.

## Referencias

- Rama `fix/risk-simulation`.
- `scripts/risk_drift.py`.
- Tests: `tests/test_risk_simulation.py` y `PortfolioRiskView.test.tsx`.
