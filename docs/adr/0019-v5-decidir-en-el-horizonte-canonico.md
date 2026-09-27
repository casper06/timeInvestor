# ADR-0019: Criterio v5: el auto-discovery decide en el horizonte canónico de cada frecuencia

## Contexto

Hasta v4, el mini-backtest del auto-discovery evaluaba a 30 pasos en todas
las frecuencias: 30 meses en una mensual, 7,5 años en una trimestral. La UI,
en cambio, pronostica en el horizonte canónico de la frecuencia (ADR-0010).

En 2.3c, con el snapshot de 2.5, v5 no cumplió el criterio agregado. En su
lugar se pre-registró un criterio por serie (`db4fcdb`), para evaluarlo solo
con series nuevas (ADR-0018).

## Decisión

**Criterio v5** (`AUTO_DISCOVERY_CRITERIA_VERSION = 5`):
- misma regla que v4 (`decide_robust`: 8 cutoffs recientes, mayoría +
  margen del 10%, empate → base, histéresis ×2, sin guard);
- pero el mini-backtest evalúa en el **horizonte canónico** de la frecuencia
  inferida de las fechas: diaria 60, semanal 13, mensual 12, trimestral 4
  (`AutoDiscoveryEngine._decision_horizon`);
- el horizonte queda guardado en `engine_decisions.horizon`, y la UI lo
  muestra como `decision_horizon`.

Evidencia:
- **Diaria, semanal y mensual:** 3.5 las evaluó con el criterio
  pre-registrado, sin reinterpretarlo. Pasan las 4 categorías evaluables:
  mensual NSA 5/5, mensual SA 4/5, semanal 5/5, financiera diaria 4/5; sin
  casos catastróficos (el peor, UNRATE, +10,3 pp).
- **Trimestral: sin evidencia en 3.5**, porque a 30 pasos la ventana de 40
  trimestres deja solo 10 cutoffs y la comparación no era evaluable.
  **Decidido por uso**, como el mensual en 12: 30 pasos trimestrales son 7,5
  años y no tienen sentido como horizonte de decisión (decisión del dueño
  del repo, 2026-09-27). **Revisar cuando haya más series trimestrales.**

**La variante C de Holt no se adopta.** No cumplió su criterio
pre-registrado (`0ba851a`) en 3.5: falla mensual SA (2/5). Holt sigue sin
cambios (ADR-0013, ADR-0018).

## Consecuencias

- **Re-evaluación:** subir la versión (mecanismo de ADR-0006) deja viejas
  todas las decisiones anteriores. Se re-evalúan solas en el próximo
  pedido de cada serie, desde cero (sin incumbente, porque son de otra
  versión).
- **Historia mínima:** para tener cutoffs, una serie diaria necesita 180
  puntos en la re-descarga del mini-backtest (antes, 90): 120 de
  entrenamiento mínimo más 60 de evaluación. Semanal, mensual y trimestral
  siguen necesitando unos 40. Una diaria con menos historia (un ticker
  recién listado) queda sin decisión y va al camino por defecto, con un
  aviso en el log.
- **Costo:** en diarias cada pronóstico del mini-backtest es el doble de
  largo (60 pasos contra 30); en mensuales, más corto. No se re-midió.
- **Scripts:** `MINI_BACKTEST_HORIZON = 30` se mantiene para los scripts
  que reproducen 2.2 y 2.3, y como significado de un `horizon` NULL en
  filas viejas.

## Estado

Aceptada. Reemplaza a ADR-0018 en lo que toca a v5.

## Referencias

- Pre-registro del criterio: commit `db4fcdb` (PR #37).
- Pre-registro de 3.5: commit `2c07372`.
- Medición: PR #40 (commits `2c07372` y `5ee140d`, merge `0cd1dd5`),
  `docs/results/fred_category_benchmark_2026-09-27.md`.
- Implementación: rama `feat/decision-v5` (2.3d), sobre la de 2.8.
