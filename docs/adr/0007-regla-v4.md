# ADR-0007: Regla v4: ventana reciente, mayoría + margen, empate → base, histéresis, sin guard

## Contexto

La medición de 2.2 mostró que las decisiones con 3 cutoffs oscilaban. Los
3 cutoffs se repartían sobre toda la historia (en FRED: 1989, 2006 y 2023);
en IPG2211A2N, TimesFM ganaba 2 de 3 pero perdía fuerte en 1989, y la media
se inclinaba a Holt-Winters (mensaje del commit f56c936).

## Decisión

`decide_robust` y `recent_cutoff_indices`, criterio v4:
- **Cutoffs:** 8 en una ventana reciente según la frecuencia: 504 puntos en
  diarias, 104 en semanales, 120 en mensuales y 40 en trimestrales.
- **Cuándo gana TimesFM:** si le gana al motor base en la mayoría de los
  cutoffs en par Y con un margen del 10% en el error medio, con al menos 7
  pares; empate → motor base.
- **Histéresis:** al re-evaluar una decisión de la misma versión, dejar el
  motor vigente exige el doble de margen (20%).
- **Sin guard de cobertura:** medido en ≤ 0,5 pp de efecto.
- **Sin test de signo:** quedó implementado (`alpha`) pero no se usa. Con 8
  cutoffs exige 7 de 8 y descartaba victorias claras.

## Consecuencias

- En acciones y ETFs, 88% al motor base y 0 cambios entre ventanas
  cercanas; en FRED estacional baja el desacuerdo, en FRED SA no
  (`docs/PLAN.md`, 2.3).
- Cuesta 2,2 a 3,0 s por serie nueva.
- El horizonte del mini-backtest sigue en 30 pasos para todas las
  frecuencias (ADR-0018).

## Estado

Aceptada. Vigente como `AUTO_DISCOVERY_CRITERIA_VERSION = 4`.

## Referencias

- PR #33, commit `f56c936`.
- Resultados: `docs/results/decision_stability_2026-09-26.md` (2.2, PR #32)
  y `docs/results/decision_variants_2026-09-26.md`.
