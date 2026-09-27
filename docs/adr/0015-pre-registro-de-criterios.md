# ADR-0015: Pre-registro de criterios antes de medir

## Contexto

En 2.3c, un criterio que se elige después de ver los números se puede
ajustar al resultado. `docs/results/decision_regret_2026-09-27.md` lo dice:
"cambiarlo después de ver los números es justamente lo que el pre-registro
busca evitar".

## Decisión

Todo criterio que decide algo a partir de una medición se escribe **con
fecha, antes de medir**: primero en la bitácora y, desde 2.6, también en
`docs/PLAN.md`, con su propio commit. El resultado se reporta contra ese
criterio tal cual, aunque después se vea que tiene un problema. Un criterio
nuevo se fija de nuevo antes de medir y se valida con datos nuevos.

## Consecuencias

- En 2.3c el criterio pre-registrado dejó v5 afuera (FRED SA, p90), aunque
  serie por serie mejoraba.
- Los criterios de v5 y de la variante C para 3.5 quedaron commiteados
  antes de que exista ese snapshot (`db4fcdb`, `0ba851a`).
- La bitácora está ignorada por git: el registro versionado es el commit en
  `PLAN.md`.

## Estado

Aceptada.

## Referencias

- PR #36 (commit `e4b7842`, resultados de 2.3c) y PR #37 (commit `db4fcdb`,
  pre-registro de v5).
- Commit `0ba851a`, en la rama `docs/architecture-adr`: pre-registro de la
  variante C.
