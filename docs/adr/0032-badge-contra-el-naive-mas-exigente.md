# ADR-0032: Badge de capacidad contra el naive más exigente (4.17, criterio v10)

## Contexto

El badge de 4.13 comparaba las series estacionales solo contra el naive
estacional. 3.5 medía contra el naive más exigente de los dos, el de menor
error total (`capability()`). En 5 de las 6 series estacionales de 3.5, el
random walk tenía menos error. GFDEGDQ188S decía "aporta" solo porque el
rival era el naive estacional: 7-1 contra él, pero 5-3 y −5,6% contra el
random walk.

## Decisión

- **Referencia (pre-registrado en `docs/PLAN.md` 4.17, commit `24d90b4`):**
  en series estacionales, el naive de menor error total en los cutoffs de la
  decisión; con empate, el random walk.
- **Regla:** la misma de 4.13 contra esa referencia (al menos 7 pares,
  mayoría y 10% menos de error medio).
- **Series no estacionales:** sin cambios.
- **Evidencia:** la decisión guarda por cutoff el MAE de los dos naives, y el
  criterio sube a **v10**, así que todas las decisiones se re-evalúan.
- **Catálogo:** se compara también contra el random walk en los 24 cutoffs
  de 3.0d (`docs/results/seasonal_benchmark_rw_2026-09-28.json`,
  `CATALOG_RW_EVIDENCE`). En las 4 series el naive estacional sigue siendo el
  más exigente.

## Consecuencias

- **Validación pre-registrada** (`docs/results/skill_strictest_naive_2026-09-28.md`):
  - 6 series elegidas por una regla sobre metadatos de FRED;
  - ninguna "aporta" perdiendo la mayoría contra el otro naive, así que se
    adopta;
  - 2 de 4 evaluables pasan de "aporta" a "no aporta" (CSUSHPINSA y
    APU0000708111);
  - GFDEGDQ188S pasa a "no aporta", como se había medido.
- Con v10, el badge es más exigente en las series estacionales con
  tendencia. Ahí el random walk suele ser el rival más difícil.
- **La regla es "el más exigente por error total", no "contra los dos".** El
  criterio de adopción era justamente que no apareciera un "aporta" que
  perdiera la mayoría contra el otro naive, y no apareció.

## Estado

Aceptada.

## Referencias

- Rama `feat/skill-strictest-naive`.
- Tests: `tests/test_skill_strictest_naive.py` y `tests/test_forecast_skill.py`.
