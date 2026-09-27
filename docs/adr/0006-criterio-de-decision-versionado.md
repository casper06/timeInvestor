# ADR-0006: Versionado del criterio de decisión

## Contexto

En 3.0e se corrigió la banda de TimesFM y se cambió el nivel al que se
comparan los motores en el mini-backtest. Las decisiones ya cacheadas
habían sido tomadas con el criterio anterior y tenían que re-evaluarse
(mensaje del commit f340706).

## Decisión

Columna `engine_decisions.criteria_version` (NULL = v1) y constante
`AUTO_DISCOVERY_CRITERIA_VERSION`. Una decisión de una versión anterior
queda vieja y se re-evalúa en el próximo pedido. La columna se agrega a las
bases existentes con `migrate_added_columns`.

Versiones:
- v2 (3.0e, #29): banda de TimesFM p10-p90 y los dos motores comparados al
  80%.
- v3 (3.0f, #30): Holt-Winters con MASE estacional como base de las series
  estacionales.
- v4 (2.3, #33): regla robusta (ADR-0007).
- v5 (2.3d): la misma regla, evaluada en el horizonte canónico de cada
  frecuencia (ADR-0019).
- v6 (2.10): igual que v5, pero si el MASE no está definido en algún
  cutoff, la serie se decide con MAE en pares (ADR-0020).
- v7 (2.9): la misma regla, con los datos a la precisión de la fuente
  (ADR-0021). Cambian las entradas, no la regla.
- v8 (2.11): la misma regla, con pronósticos y métricas sin redondear
  (ADR-0022).
- v9 (4.13): la misma regla; la decisión además guarda el MAE por cutoff
  del motor base, de TimesFM y del naive (ADR-0023).

## Consecuencias

- Cambiar el criterio invalida todas las decisiones de golpe: el primer
  pedido de cada serie vuelve a pagar el mini-backtest.
- La histéresis de v4 solo usa como incumbente una decisión de la versión
  vigente; una de versión anterior se decide de cero.

## Estado

Aceptada.

## Referencias

- PR #29, commit `f340706`. Versiones siguientes: PR #30 (`cf9fd27`) y
  PR #33 (`f56c936`).
