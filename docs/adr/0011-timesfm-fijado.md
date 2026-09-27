# ADR-0011: `timesfm` fijado en 3.0.2

## Contexto

El rango era `>=2.0.0,<4.0.0`. Desde 3.0.0 el paquete también trae
TimesFM 3, así que un `pip install -U` podía romper
`TimesFM_2p5_200M_torch`, la clase que usa el proyecto (mensaje del commit
9530777; `CONTEXT.md`, sección 3).

## Decisión

`timesfm[torch]==3.0.2` en `requirements-timesfm.txt`. Era la versión
instalada y la última de PyPI al 2026-09-25; el wheel exporta la clase y
los tests con pesos reales pasan.

## Consecuencias

Antes de subir la versión hay que repetir esos chequeos (el comentario del
archivo dice cómo). `requirements-timesfm.txt` queda fuera del lock
(ADR-0012).

## Estado

Aceptada.

## Referencias

- PR #14, commit `9530777`.
