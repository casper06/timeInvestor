# ADR-0012: Lockfile con uv

## Contexto

Los rangos de `requirements.txt` permitían versiones que el smoke test no
había probado (`docs/PLAN.md`, 2.4). `pip-compile` solo resuelve para la
plataforma donde corre (Windows): omitía `uvloop`, que Docker instala en
Linux, y fijaba `colorama` y `tzdata` sin condición (mensaje del commit
26da52a).

## Decisión

`requirements.lock`, generado con
`uv pip compile requirements.txt --universal --python-version 3.12`: un solo
lock con marcadores, válido para Windows y Linux. Lo instalan `.venv` y
Docker. `requirements-timesfm.txt` queda fuera del lock porque el wheel de
`torch` depende del hardware; se instala con `-c requirements.lock`.

## Consecuencias

- Los rangos se editan a mano y el lock se regenera.
- Antes de commitear un lock nuevo, hay que probarlo en un venv limpio con
  la suite y `scripts/smoke_real_data.py` (README).

## Estado

Aceptada.

## Referencias

- PR #24, commit `26da52a`.
