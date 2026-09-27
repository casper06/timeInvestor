# ADR-0014: DB aislada en los tests y verificación sobre una copia

## Contexto

`tests/test_database.py` corría `init_db()` y un CRUD contra
`backend/database/time_investor.db`, porque nada apuntaba la suite a otra
DB. Así se aplicó la migración de #20 a la DB local (mensaje del commit
5e132c6).

## Decisión

- **Tests (#21):** `tests/conftest.py` fija `DATABASE_URL` a un SQLite
  temporal antes de importar `backend`. Un fixture de sesión verifica que el
  engine sea esa DB y, si no lo es, aborta la suite (exit 3).
- **Verificaciones con datos reales (#30):** van sobre una **copia** de la
  DB, apuntada con `DATABASE_URL`; la DB real solo cambia por el uso normal
  de la app con el código de `main` (`CONTEXT.md`, sección 4, punto 7). El
  motivo de esta segunda regla es **motivo no documentado** en el repo: el
  commit cf9fd27 agrega la regla pero no dice por qué.

## Consecuencias

- Cada ronda que verifica con datos reales copia la DB y lo dice en el PR.
- Los scripts de verificación comprueban que `DATABASE_URL` apunte a la
  copia antes de tocar nada.

## Estado

Aceptada.

## Referencias

- PR #21 (commit `5e132c6`) y PR #30 (commit `cf9fd27`).
