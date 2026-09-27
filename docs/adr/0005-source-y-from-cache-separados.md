# ADR-0005: `source` y `from_cache` como campos separados

## Contexto

Al servir desde la caché, `source` se sobreescribía con `"cached"` y se
perdía si el dato original era real o sintético. Eso dejaba pasar datos
inventados por los guards de "solo datos reales" después del primer hit de
caché (`CONTEXT.md`, sección 3). El commit (4c318b0) no tiene cuerpo; el
motivo está en `CONTEXT.md`.

## Decisión

`source` (`live` | `synthetic`) dice de dónde vino el dato y **nunca**
cambia. `from_cache` y `cached_at` dicen si se sirvió desde la caché. Los
fetchers clonan el objeto cacheado preservando `source`
(`backend/services/data_fetcher.py`).

## Consecuencias

Los guards de la ADR-0004 son confiables con la caché. Un test cubre que
una serie en vivo cacheada conserve `source="live"`
(`tests/test_cache_provenance.py`).

## Estado

Aceptada.

## Referencias

- PR #3, commit `4c318b0`.
