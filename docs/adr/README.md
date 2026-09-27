# Decisiones de arquitectura (ADR)

Formato Nygard: contexto, decisión, consecuencias y estado. Son
**retroactivas**: cada una cita su PR, su commit y sus resultados en
`docs/results/`. Si el motivo de una decisión no está escrito en el repo
(commit, PR, `CONTEXT.md`, `PLAN.md` o resultados), dice "motivo no
documentado" en vez de reconstruirlo.

Una ADR no se edita para cambiar la decisión: se escribe una nueva que la
reemplace y se actualiza el estado de la anterior.

| # | Decisión | Estado | PR |
|---|---|---|---|
| [0001](0001-motor-por-serie.md) | Elección de motor por serie, no global | Aceptada; ampliada por 0002 y 0008 | #7 |
| [0002](0002-auto-discovery-cacheado.md) | Auto-discovery: mini-backtest por serie, cacheado en SQLite | Aceptada | #8 |
| [0003](0003-no-evaluado-no-es-holt-gano.md) | "No evaluado" no es "Holt ganó" | Aceptada | #15 |
| [0004](0004-sin-datos-sinteticos-en-endpoints-cuantitativos.md) | Prohibición de datos sintéticos en los endpoints cuantitativos | Aceptada | #1 |
| [0005](0005-source-y-from-cache-separados.md) | `source` y `from_cache` como campos separados | Aceptada | #3 |
| [0006](0006-criterio-de-decision-versionado.md) | Versionado del criterio de decisión | Aceptada | #29 |
| [0007](0007-regla-v4.md) | Regla v4: ventana reciente, mayoría + margen, empate → base, histéresis, sin guard | Aceptada | #33 |
| [0008](0008-holt-winters-plan-b-estacional.md) | Holt-Winters (statsmodels `ETSModel`) como base y plan B estacional | Aceptada | #27, #30 |
| [0009](0009-banda-timesfm-80.md) | Banda de TimesFM al 80%, cuantiles buscados por valor | Aceptada | #29 |
| [0010](0010-horizonte-canonico-por-frecuencia.md) | Horizonte en la unidad de la serie; canónico por frecuencia (mensual = 12 por uso) | Aceptada | #35, #36 |
| [0011](0011-timesfm-fijado.md) | `timesfm` fijado en 3.0.2 | Aceptada | #14 |
| [0012](0012-lockfile-con-uv.md) | Lockfile con uv | Aceptada | #24 |
| [0013](0013-marca-no-confiable.md) | Marca "no confiable" sin recortar los números | Aceptada | #37 |
| [0014](0014-db-aislada-y-verificacion-sobre-copia.md) | DB aislada en los tests y verificación sobre una copia | Aceptada | #21, #30 |
| [0015](0015-pre-registro-de-criterios.md) | Pre-registro de criterios antes de medir | Aceptada | #36, #37 |
| [0016](0016-claude-cli-haiku-por-defecto.md) | `CLAUDE_CLI_MODEL=haiku` por defecto | Aceptada | #10 |
| [0017](0017-sin-correccion-de-sesgo-de-holt.md) | No corregir el sesgo positivo de Holt | Aceptada | #26 |
| [0018](0018-v4-se-mantiene-v5-y-c-con-3-5.md) | v4 se mantiene; v5 y la variante C se evalúan solo con las series de 3.5 | Re-evaluada en 3.5: v5 adoptada (implementación pendiente, 2.3d); C no | #36, #37 |
