# Riesgo: con la tendencia histórica contra retornos centrados (2026-09-27)

Rama `fix/risk-simulation`. Script `scripts/risk_drift.py`. Resultado
completo en `risk_drift_2026-09-27.json`.

## Cartera

- CEG, ETN, GEV, PWR y VST, con pesos iguales. Son los activos de la tesis de
  demanda eléctrica que aparece en el informe revisado en esta ronda.
- **No es necesariamente "la cartera de la captura":** no tengo la captura,
  y la DB no tiene tesis guardadas. Los pesos iguales son una elección mía,
  no verificada contra la captura.
- **Datos:**
  - yfinance, 2 años (lo que usa `RiskEngine`), del 2024-09-27 al 2026-09-25;
  - 500 retornos alineados;
  - snapshot `data/snapshots/risk_drift_2026-09-27.json` (ignorado por git),
    sha256 `e2ef205e430f6c39…`, reproducible con `--replay`.
- **Tendencia histórica de la cartera:** +26,9% anual (log).
  - Por activo: GEV +67,7%, PWR +39,6%, ETN +15,2%, VST +10,3%, CEG +1,8%.
  - Error estándar de esa media: 29,9% (σ anual 42,2%, sobre 2 años).
  - Resultado: t = 0,90, IC95 [−31,7%; +85,6%]. **No se distingue de 0.**

## Protocolo

- **Cada celda:** método × horizonte × {con tendencia histórica, centrado}.
  Se corre con 20 semillas (1–20) y 10.000 caminos, y se reporta la media.
- **Ruido de semilla:** es el desvío entre semillas del VaR95, entre 0,3 y
  0,8 puntos.
- **Qué cambia al centrar:** a cada activo se le resta su retorno medio del
  período, antes de simular.

## Resultado

Todo en %; el formato es "histórico → centrado".

| Método | H (días) | VaR95 | Diferencia VaR95 | CVaR95 | VaR99 | P(pérdida >10%) | P(>20%) | P(>30%) |
|---|---|---|---|---|---|---|---|---|
| bootstrap | 30 | 16.2 → 18.8 | +2.6 (8× el ruido) | 20.8 → 23.3 | 23.7 → 26.1 | 13.3 → 19.4 | 2.3 → 4.0 | 0.2 → 0.3 |
| bootstrap | 90 | 23.1 → 30.2 | +7.0 (14× el ruido) | 30.0 → 36.4 | 34.4 → 40.4 | 17.6 → 31.2 | 7.2 → 15.2 | 2.1 → 5.1 |
| bootstrap | 252 | 27.3 → 44.4 | +17.2 (30× el ruido) | 36.8 → 51.7 | 43.0 → 56.4 | 14.9 → 39.5 | 8.5 → 27.1 | 4.0 → 16.1 |
| student_t | 30 | 18.5 → 21.1 | +2.6 (9× el ruido) | 23.7 → 26.1 | 26.9 → 29.2 | 16.7 → 22.8 | 3.9 → 6.1 | 0.5 → 0.8 |
| student_t | 90 | 27.1 → 33.8 | +6.7 (18× el ruido) | 34.4 → 40.4 | 39.1 → 44.7 | 21.0 → 33.7 | 10.1 → 18.6 | 3.6 → 7.8 |
| student_t | 252 | 34.6 → 50.0 | +15.4 (18× el ruido) | 44.5 → 57.6 | 50.9 → 62.5 | 18.5 → 40.0 | 12.1 → 29.6 | 6.9 → 19.7 |
| gaussian | 30 | 18.4 → 21.0 | +2.6 (9× el ruido) | 23.0 → 25.4 | 25.9 → 28.2 | 16.7 → 22.9 | 3.7 → 5.9 | 0.3 → 0.6 |
| gaussian | 90 | 26.7 → 33.4 | +6.7 (13× el ruido) | 33.6 → 39.7 | 38.0 → 43.7 | 20.7 → 33.5 | 9.8 → 18.3 | 3.3 → 7.4 |
| gaussian | 252 | 33.9 → 49.5 | +15.6 (21× el ruido) | 43.7 → 57.0 | 50.0 → 61.8 | 18.3 → 40.0 | 11.8 → 29.5 | 6.6 → 19.5 |

## Lectura

- **En los tres métodos, la tendencia histórica achica el riesgo.** Al
  centrar, los números suben, y la diferencia va de 8 a 30 veces el ruido de
  semilla.
- **El efecto crece con el horizonte:** +2,6 puntos de VaR95 a 30 días (el
  horizonte por defecto de la UI) y +15 a +17 a 252.
- **Con tendencia, las probabilidades de pérdida se comportan raro.** A un año
  el bootstrap dice 14,9% de perder más del 10%, menos que a 90 días
  (17,6%). Es la tendencia de +27% anual sumándose con el tiempo. Centrado da
  39,5%.

## Decisión propuesta

**Centrado por defecto para riesgo**, con la opción "Con la tendencia
histórica" disponible y una etiqueta visible de cuál se está mostrando.
- **Por qué:** la media de 2 años no es un pronóstico. Acá es +27% anual con
  un error estándar de 30%, así que no se distingue de 0. Meterla en la
  simulación supone que el rally se repite y baja las pérdidas simuladas, que
  es lo que esta pestaña tiene que medir.
- **Qué supone centrar:** retorno esperado 0. Eso también es un supuesto,
  pero no depende del período elegido. Lo que queda es volatilidad y
  co-movimiento, que se estiman mucho mejor que una media.

## Semilla

Antes todas las simulaciones usaban la semilla 42, así que cada clic daba
exactamente los mismos números. Ahora:
- cada pedido sin semilla usa una nueva;
- la semilla usada vuelve en la respuesta (`seed_used`) y se muestra;
- "reproducir" la fija para la próxima corrida.
