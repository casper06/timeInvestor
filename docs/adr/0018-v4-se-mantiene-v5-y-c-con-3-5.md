# ADR-0018: v4 se mantiene; v5 y la variante C se evalúan solo con las series de 3.5

## Contexto

- **2.3b:** decidir en otro horizonte no confirmó la mejora esperada.
- **2.3c:** con el horizonte canónico mensual (12), el criterio
  pre-registrado de arrepentimiento falló en FRED SA (p90 de 137,4 contra
  un límite de 104,3), aunque serie por serie las dos SA mejoraban.
- **2.6:** la variante C de Holt (el salto va al nivel, no a la tendencia)
  mejoró el error, pero falló la cláusula de cobertura en FRED SA con 2
  series.

## Decisión

- El auto-discovery sigue en v4, a 30 pasos.
- v5 (decidir en el canónico de cada frecuencia) y la variante C se
  re-evalúan **solo con las series nuevas de 3.5**, nunca con el snapshot
  `holt_coverage_2026-09-26.json`, con criterios pre-registrados en
  `docs/PLAN.md`:
  - por serie;
  - arrepentimiento acotado a 100 pp;
  - empate de 2 pp;
  - empeoramiento catastrófico de más de 25 pp;
  - para C, además, cobertura medida como distancia al nominal.

## Consecuencias

- `MINI_BACKTEST_HORIZON = 30` se mantiene; los scripts de 2.2 y 2.3
  dependen de él y siguen siendo reproducibles.
- La UI avisa cuando el motor se eligió evaluando a otro horizonte
  (ADR-0010).

## Estado

Re-evaluada en 3.5 (`docs/results/fred_category_benchmark_2026-09-27.md`):
- **v5 cumple su criterio pre-registrado y se adopta.** En lo que toca a v5,
  la **reemplaza ADR-0019** (implementada en 2.3d).
- **La variante C no cumple su criterio** (falla mensual SA, 2/5) **y no se
  adopta.** Esta parte sigue vigente: Holt no cambia.

## Referencias

- PR #34 (merge `c793415`), PR #36 (commit `e4b7842`), PR #37 (commits
  `db4fcdb` y `452d950`) y commit `0ba851a`.
- Resultados: `docs/results/horizon_variants_2026-09-27.md`,
  `docs/results/decision_regret_2026-09-27.md` y
  `docs/results/holt_explosion_2026-09-27.md`.
