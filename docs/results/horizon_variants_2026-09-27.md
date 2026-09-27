# Horizonte del mini-backtest por frecuencia (2.3b): no se implementa

Fecha: 2026-09-27. Script: `scripts/horizon_variants.py`. La regla v4 queda
fija (`decide_robust`: ventana reciente, 8 cutoffs, mayoría + margen 10%,
≥ 7 pares, histéresis ×2, sin guard) y **solo varía el horizonte**. Datos:
snapshot de 2.5 (sha256 `c37cf58e…`), 14 series, TimesFM real (0 fallbacks).
Resultado completo: `horizon_variants_2026-09-27.json`.

**Chequeo cruzado:** la fila h=30 de este script coincide exactamente con la
v4 de 2.3 (referencia, cambios y cambios con histéresis): 0 diferencias en
las 14 series.

## v4 (h=30) contra los horizontes propuestos

| Categoría | Horizonte | Desacuerdo con la ref. de 24 | Al motor base | Cambios (con histéresis) | Ventanas independientes de 8 | Latencia (s) |
|---|---|---|---|---|---|---|
| Acciones | **30 (v4)** | 11,4% | 88,0% | 5/30 (0/30) | 8 | 1,24–1,50 |
| Acciones | 60 | 11,9% | 87,4% | 2/30 (1/30) | 8 | 1,23–1,46 |
| ETFs | **30 (v4)** | 13,3% | 86,7% | 0/24 (0/24) | 8 | 1,31–1,43 |
| ETFs | 60 | **5,6%** | **94,4%** | 2/24 (0/24) | 8 | 1,31–1,44 |
| FRED estacional | **30 (v4)** | 23,3% | 51,5% | 10/18 (0/18) | 3 | 1,53–1,81 |
| FRED estacional | 24 | 14,9% | 56,8% | 6/18 (1/18) | 4 | 1,64–1,82 |
| FRED estacional | 12 | 21,8% | 45,0% | 4/18 (0/18) | 8 | 1,69–1,88 |
| FRED SA | **30 (v4)** | 18,5% | 50,8% | 2/12 (0/12) | 3 | 1,26–1,40 |
| FRED SA | 24 | 40,6% | 40,6% | 4/12 (0/12) | 4 | 1,24–1,30 |
| FRED SA | 12 | **34,2%** | 74,8% | 3/12 (0/12) | 8 | 1,22–1,28 |

"Ventanas independientes": de las 8 ventanas de evaluación del último
mini-backtest, cuántas no se superponen (conteo greedy).

## Lectura

1. **La superposición existe:** con 30 meses, en mensuales solo 3 de las 8
   ventanas son independientes; con 12, las 8. En diarias las 8 ya son
   independientes con 30 y con 60.
2. **La hipótesis no se confirma.** Sacar la superposición no mejora FRED
   SA: con 12 meses el desacuerdo **sube** de 18,5% a 34,2%. En FRED
   estacional, 12 meses queda casi igual (23,3% → 21,8%, dentro del ruido).
   En conjunto FRED empeora (~21% → ~27%). La superposición no era la causa
   del empeoramiento de 2.3.
3. **En diarias, 60 mejora ETFs** (13,3% → 5,6%, 94% al motor base) y deja
   igual las acciones (11,4% → 11,9%, dentro del ruido).
4. **El ruido de la métrica es de ~2 pp:** la misma v4 dio 16,6% de
   desacuerdo en FRED SA en 2.3 y 18,5% acá. Lo único que cambió es la
   semilla de los subconjuntos aleatorios. Las diferencias menores a eso no
   significan nada; la mejora de ETFs y el empeoramiento de FRED SA sí están
   por encima.
5. **La decisión depende del horizonte.** Referencia de 24 cutoffs: INDPRO
   da Holt a 12 y a 30 meses, y TimesFM a 24. Última decisión (8 cutoffs,
   con histéresis): INDPRO da Holt a 12 y TimesFM a 30; IPG2211A2N da
   TimesFM a 12 y a 30, y Holt-Winters a 24; RSAFSNA da TimesFM a 12 y a 24,
   y Holt-Winters a 30. Es el argumento de fondo para evaluar en el
   horizonte que se muestra.

## Por qué no se implementa (v5)

- La mejora no se confirma en mensuales, y en diarias es parcial (ETFs sí,
  acciones no).
- **El principio "evaluar en el horizonte que se muestra" no se puede cumplir
  hoy:** la UI pide siempre 30/60/90/180 pasos con `freq='D'`, incluso para
  series mensuales (`App.tsx`: `fetchForecast(..., 'D', ...)`). Verificado
  con INDPRO: el pedido por defecto (60 pasos) devuelve 60 pasos mensuales
  (una banda de 5 años, [84; 127]) etiquetados con fechas diarias del
  2026-06-02 al 2026-08-24 y "Objetivo +60d". Con 180 pasos serían 15 años
  mostrados como ~8 meses de fechas (por cálculo, **no verificado** con una
  llamada), y además 180 supera `MAX_HORIZON` = 128 de TimesFM, que en ese
  caso cae a Holt (`forecast_engine.py`). Mientras la UI no pida el horizonte en las
  unidades de la serie, cualquier horizonte mensual del mini-backtest
  evaluaría algo distinto de lo que se ve. Queda como 4.14 en
  `docs/PLAN.md`; 2.3b se re-mide después.

## Qué quedó en el código

- `recent_cutoff_indices(..., horizon=None)`: parámetro opcional; el default
  sigue siendo `MINI_BACKTEST_HORIZON` (30), así que v4 no cambia.
- El evaluador de `scripts/decision_stability.py` acepta un horizonte
  opcional, también con default igual al de antes.
- `scripts/horizon_variants.py`, para re-medir después de 4.14.
- 2.2 sigue reproduciendo su resultado versionado (JSON idéntico).

## Dependencias de los resultados versionados (punto 5)

- **2.5** (`holt_coverage_real.py`) y **3.0d** (`seasonal_benchmark.py`)
  **no dependen** de `MINI_BACKTEST_HORIZON`: tienen sus propios horizontes
  (60 diarias y 12 mensuales en 2.5; `H = 12` en 3.0d).
- **2.2** (`decision_stability.py`) y **2.3** (`decision_variants.py`) **sí
  dependen**, porque miden la regla de producción. Por eso v5, si se hace, no
  tiene que cambiar esa constante sino agregar un horizonte por frecuencia
  aparte.

## Limitaciones

- Semanales y trimestrales: no hay series en el snapshot, así que 13 y 8
  quedan **no verificados**.
- Una sola ventana de datos por serie.
