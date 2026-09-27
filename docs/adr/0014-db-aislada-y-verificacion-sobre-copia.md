# ADR-0014: DB aislada en los tests y verificación sobre una copia

## Contexto

Hubo dos incidentes con la DB real, `backend/database/time_investor.db`.

- **Tests.** `tests/test_database.py` corría `init_db()` y un CRUD contra la
  DB real, porque nada apuntaba la suite a otra DB. Así se aplicó la
  migración de #20 a la DB local (mensaje del commit 5e132c6).
- **Verificaciones.** En la ronda de #29 (3.0e), la re-evaluación de CEG y
  NVDA con el criterio nuevo se hizo sobre la DB real **antes del merge**.
  La DB quedó inconsistente con `main`: con el server corriendo desde
  `main`, CEG y NVDA mostraban TimesFM con la banda rota (la que #29
  corregía). Ningún commit registra este motivo; lo informó el dueño del
  repo el 2026-09-27, al revisar este ADR.

## Decisión

- **Tests (#21):** `tests/conftest.py` fija `DATABASE_URL` a un SQLite
  temporal antes de importar `backend`. Un fixture de sesión verifica que el
  engine sea esa DB y, si no lo es, aborta la suite (exit 3).
- **Verificaciones con datos reales (adoptada en la ronda siguiente, #30):**
  van sobre una **copia** de la DB, apuntada con `DATABASE_URL`. La DB real
  solo cambia por el uso normal de la app con el código de `main`. En esa
  misma ronda se agregó como punto 7 de la sección 4 de `CONTEXT.md`.

## Consecuencias

- Cada ronda que verifica con datos reales copia la DB y lo dice en el PR,
  con el hash de la DB real antes y después.
- Los scripts de verificación comprueban que `DATABASE_URL` apunte a la
  copia antes de tocar nada.
- Las decisiones cacheadas en `engine_decisions` de la DB real solo se
  re-evalúan con el código de `main`, así que siempre coinciden con lo que
  sirve el server.

## Estado

Aceptada.

## Referencias

- PR #21 (commit `5e132c6`): suite aislada.
- PR #29 (merge `68f856a`, commit `f340706`): la ronda del incidente.
- PR #30 (commit `cf9fd27`): adopción de la regla y punto 7 de la sección 4
  de `CONTEXT.md`.
