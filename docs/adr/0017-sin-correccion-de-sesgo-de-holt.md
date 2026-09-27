# ADR-0017: No corregir el sesgo positivo de Holt

## Contexto

En la medición de cobertura sobre datos reales (2.5), el precio real terminó
por encima del centro del intervalo de Holt, cada vez más a medida que crece
el horizonte.

## Decisión

El sesgo positivo **no se corrige**. Motivo documentado en `docs/PLAN.md`
(2.5): "Sale de una muestra de ~5 años mayormente alcista, y agregar drift
sería ajustarse a ese régimen."

## Consecuencias

El centro de Holt sigue siendo el del modelo, sin un drift agregado a mano.
Cambiar el intervalo quedó sujeto a una decisión del dueño del repo.

## Estado

Aceptada.

## Referencias

- Escrita en `docs/PLAN.md` en el commit `816958a` (PR #26).
- Resultados: `docs/results/holt_coverage_2026-09-26.json` (PR #25).
