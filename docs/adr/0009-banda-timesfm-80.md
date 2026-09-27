# ADR-0009: Banda de TimesFM al 80%, cuantiles buscados por valor

## Contexto

TimesFM 2.5 devuelve los cuantiles como [media, p10, …, p90]. El motor
tomaba la columna 0 (la media) como límite inferior, así que la banda era
[media, p90] y a veces el punto quedaba fuera. El guard de auto-discovery,
además, comparaba la cobertura de Holt al 95% con esa banda "del 80%"
(mensaje del commit f340706).

## Decisión

- p10 y p90 se buscan **por valor** en `model.config.quantiles`
  (columna = 1 + índice). Si la salida no tiene la forma esperada, TimesFM
  cae a Holt de forma explícita (`inference_error`).
- Cada motor declara el nivel real de su intervalo en `interval_level`:
  Holt y Holt-Winters, el pedido; TimesFM, 0,80, porque su cabeza de
  cuantiles no ofrece un intervalo más ancho. No se estira.
- En el mini-backtest los dos motores se comparan al mismo nivel (80%).

## Consecuencias

- La UI, el backtest, el copiloto y los snapshots usan el nivel entregado,
  no el pedido.
- Cambió el criterio (v2, ADR-0006).

## Estado

Aceptada.

## Referencias

- PR #29, commit `f340706`.
