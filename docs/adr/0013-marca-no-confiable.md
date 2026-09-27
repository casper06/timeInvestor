# ADR-0013: Marca "no confiable" sin recortar los números

## Contexto

Cuando el último dato es un salto de nivel, el ajuste SSE de Holt lleva α y
β a ~0,99 y 0,89, y el salto pasa a la tendencia. UNRATE cortada en 2020-04
da 20.860% a 12 meses. En producción eso le llegaba al usuario sin aviso:
Holt como plan B sin TimesFM, o elegido por auto-discovery (INDPRO:
−40%). Ver `docs/results/holt_explosion_2026-09-27.md`.

## Decisión

`backend/services/reliability.py`: un pronóstico se marca "no confiable" si
al final del horizonte se mueve más de 2 veces (X > 2) lo máximo que la
serie se movió en ese horizonte en toda su historia.
- Aplica a cualquier motor.
- **Nunca cambia los números:** se muestran tal como salieron, con el aviso
  en tarjetas, gráfico, informe y backtest (`CONTEXT.md`, regla 6).
- El copiloto lo dice en vez de narrar la proyección.
- El umbral X > 2 quedó pre-registrado antes de medir sus falsos positivos
  (ADR-0015).

## Consecuencias

- 0 marcas en 2.358 corridas normales del snapshot, y marca las 6
  explosiones conocidas.
- No arregla el pronóstico: una estimación robusta (variante C) queda
  pendiente de evaluar con las series de 3.5 (ADR-0018).

## Estado

Aceptada.

## Referencias

- PR #37, commit `452d950`.
- Resultados: `docs/results/holt_explosion_2026-09-27.md` y
  `docs/results/holt_explosion_options_2026-09-27.json`.
