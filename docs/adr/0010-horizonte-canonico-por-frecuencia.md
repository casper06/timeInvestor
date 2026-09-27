# ADR-0010: Horizonte en la unidad de la serie; canónico por frecuencia (mensual = 12 por uso)

## Contexto

La UI pedía siempre 30/60/90/180 pasos con `freq='D'`, también para series
mensuales. INDPRO mostraba 60 meses (una banda de 5 años) como "+60d", con
fechas diarias (`docs/results/horizon_units_2026-09-27.md`).

## Decisión

- **Unidad:** un horizonte es una cantidad de pasos de la serie. La
  frecuencia sale de las fechas, nunca del tipo de serie
  (`backend/services/horizons.py`, espejado en
  `frontend/src/utils/horizon.ts`).
- **Horizonte canónico** (el default de la UI): diaria 60, semanal 13,
  mensual 12, trimestral 4.
- **Por qué 12 en mensuales:** decisión del usuario del 2026-09-27,
  registrada en `docs/PLAN.md` (2.3b): "Es el horizonte de uso (ciclo
  estacional completo, comparación interanual); no se elige por cuál da menos
  desacuerdo."
- **`decision_horizon`:** dice a qué horizonte se evaluó el motor, y la UI
  lo avisa cuando difiere del pedido.
- **Etiquetas y CAGR:** en la unidad real; el CAGR, con las fechas de la
  proyección.

## Consecuencias

- Al principio el auto-discovery siguió decidiendo a 30 pasos (v4). Desde
  el criterio v5 decide en este mismo canónico (ADR-0019), con la
  trimestral en 4 decidida por uso, sin evidencia de 3.5.
- Los snapshots anteriores a 4.14 no tienen unidad registrada y se muestran
  como "N pasos".
- El CAGR diario cambió: antes anualizaba días hábiles como días corridos.

## Estado

Aceptada.

## Referencias

- PR #35 (commit `29b99c7`); la decisión sobre los 12 meses, en PR #36
  (commit `e4b7842`).
- Resultados: `docs/results/horizon_units_2026-09-27.md`,
  `docs/results/horizon_variants_2026-09-27.md` y
  `docs/results/horizon_canonical_monthly_2026-09-27.json`.
