# Estabilidad de las decisiones de auto-discovery (2.2)

Fecha: 2026-09-26. Script: `scripts/decision_stability.py`. Datos: snapshot de
2.5 (`data/snapshots/holt_coverage_2026-09-26.json`, sha256 `c37cf58e…`,
git-ignorado), 14 series reales. Resultado completo:
`decision_stability_2026-09-26.json`. Dos corridas dan JSON idénticos (124 s
cada una).

Se mide **la regla actual de producción, con su propio código** (no una copia):
- `auto_discovery.choose_engine`: TimesFM si su métrica media es
  estrictamente menor y la brecha de cobertura es ≤ 30 pp;
- `auto_discovery.pick_cutoff_indices`: 3 cutoffs equiespaciados, horizonte
  30;
- `BacktestEngine.run_backtest` al 80%;
- baseline de 3.0f: Holt-Winters con MASE estacional para series
  estacionales, Holt con MASE de 1 paso para el resto.

TimesFM corrió con pesos reales: 0 fallbacks, 3 cutoffs en par en todas las
decisiones.

Qué se mide:
- **A. Ubicación de los cutoffs:** grilla densa de 24 cutoffs evaluada una vez
  por motor. Decisión de referencia = la regla sobre los 24. Después, la regla
  sobre **cada uno** de los 2.024 subconjuntos de 3 cutoffs: qué porcentaje no
  coincide con la referencia.
- **B. Ventanas cercanas:** la decisión que tomaría producción con los datos
  terminando 0, 5, …, 60 puntos antes (diarias: pasos de ~1 semana hábil) o
  0…12 meses antes (mensuales), con sus propios 3 cutoffs. Se cuentan los
  cambios entre fechas consecutivas.

## Por categoría

| Categoría | Desacuerdo de 3 cutoffs con la referencia | Cambios entre ventanas cercanas | Decisiones de 3 cutoffs en empate ±5% / ±10% |
|---|---|---|---|
| Acciones (JNJ, JPM, KO, NVDA, XOM) | **40,5%** (21,6–55,2) | **10 de 60** | 30,0% / 54,9% |
| ETFs (SPY, QQQ, XLE, XLK) | **34,2%** (20,4–45,8) | **13 de 48** | 31,9% / 58,5% |
| FRED estacionales (HOUSTNSA, IPG2211A2N, RSAFSNA) | 26,5% (18,5–36,3) | 1 de 36 | 15,2% / 28,2% |
| FRED SA (INDPRO, UNRATE) | 7,2% (6,1–8,3) | 0 de 24 | 2,6% / 4,9% |

## Por serie

| Serie | Referencia (24c) | Brecha ref.* | Desacuerdo 3c | ±5% / ±10% (3c) | Guard cambia (3c) | Cambios B |
|---|---|---|---|---|---|---|
| JNJ | timesfm | −1,7% | 47,2% | 30,4 / 57,5 | 0,0% | 0/12 |
| JPM | timesfm | −7,0% | 32,7% | 19,0 / 38,8 | 3,3% | 3/12 |
| KO | timesfm | −0,7% | 45,9% | 39,2 / 68,8 | 0,0% | 1/12 |
| NVDA | timesfm | −10,5% | 21,6% | 26,3 / 46,8 | 0,0% | 3/12 |
| XOM | timesfm | −0,9% | **55,2%** | 34,8 / 62,6 | 0,4% | 3/12 |
| SPY | holt | +1,2% | 45,8% | 26,9 / 53,4 | 7,3% | 3/12 |
| QQQ | holt | +7,5% | 34,9% | 29,1 / 52,6 | 0,0% | **4/12** |
| XLE | timesfm | −4,0% | 35,8% | 32,0 / 62,5 | 0,0% | 3/12 |
| XLK | holt | +7,8% | 20,4% | 39,5 / 65,7 | 0,0% | 3/12 |
| HOUSTNSA | timesfm | −12,1% | 24,8% | 18,7 / 32,3 | 0,0% | 0/12 |
| IPG2211A2N | timesfm | −17,5% | 18,5% | 12,9 / 25,1 | 0,0% | 0/12 |
| RSAFSNA | timesfm | −8,7% | 36,3% | 14,0 / 27,1 | 0,0% | 1/12 |
| INDPRO | timesfm | −67,9% | 8,3% | 3,1 / 6,2 | 0,4% | 0/12 |
| UNRATE | timesfm | −62,4% | 6,1% | 2,2 / 3,6 | 2,5% | 0/12 |

\* Brecha = media(TimesFM) / media(baseline) − 1 sobre los 24 cutoffs;
negativa = TimesFM mejor.

## Lectura

1. **En acciones y ETFs, una decisión de 3 cutoffs está cerca de tirar una
   moneda.**
   - Entre un 20% y un 55% de los subconjuntos contradice a la referencia de
     24.
   - Con los datos avanzando de a una semana, la decisión cambia 3–4 veces en
     12 pasos en la mayoría de las series.
   - Es coherente con que las propias referencias sean casi empates: JNJ
     −1,7%, KO −0,7%, XOM −0,9%, SPY +1,2%. Ahí no hay un "motor correcto"
     que 3 cutoffs puedan encontrar.
2. **La mayoría de las decisiones de 3 cutoffs se toman por menos de 10% de
   diferencia** en acciones y ETFs (55–59%), y cerca de un tercio por menos
   de 5%. La regla actual (sin margen, "estrictamente menor") convierte
   diferencias de ruido en decisiones.
3. **Con la banda corregida (#29), el guard de cobertura casi no pesa:**
   cambia entre 0% y 7% de las decisiones. La inestabilidad viene de la
   métrica, no de la calibración.
4. **Donde la diferencia es grande, la decisión es estable:** FRED SA
   (INDPRO, UNRATE), con brechas de −62% a −68%, 6–8% de desacuerdo y 0
   cambios. Las estacionales quedan en el medio.
5. **3 cutoffs también pueden quedar sesgados, no solo ruidosos.** En
   IPG2211A2N la referencia de 24 elige TimesFM (−17,5%), igual que 3.0d,
   pero los 3 cutoffs de producción eligen Holt-Winters en las 13 ventanas.
   Es por un empate cercano (+0,6% en la primera ventana, cutoffs 1989, 2006
   y 2023), repetido porque la historia mensual larga casi no mueve los
   cutoffs. Hoy no tiene efecto (IPG2211A2N va por catálogo), pero muestra
   que un número chico de cutoffs puede ser sistemáticamente distinto del
   resultado con muchos.
6. **Mínimo de cutoffs en par (requisito agregado a 2.2):** en estos datos
   TimesFM no cayó nunca y siempre hubo 3 pares, así que el mínimo no se
   activó. Sigue siendo necesario para 2.3 (sin él, un solo cutoff podría
   decidir), pero esta medición no lo ejercitó.

## Insumos para 2.3 (sin elegir el umbral acá)

- Fracción de decisiones de 3 cutoffs que caerían en "empate → baseline" con
  un margen: ±5% → 15–32% según la categoría; ±10% → 28–59% (ver la tabla por
  categoría).
- El desacuerdo con la referencia baja con más cutoffs: con 24 es 0 por
  definición. Cuánto baja con 5–8 se puede medir con el mismo script,
  cambiando el tamaño del subconjunto; queda para 2.3.
- Las referencias de 24 cutoffs en acciones y ETFs son en sí casi empates,
  así que una regla robusta debería devolver el baseline en la mayoría de
  esos casos.

## Limitaciones

- Diarias: una sola ventana de ~5 años (el `period="5y"` de la app) y un
  régimen dominante. Los cutoffs de la grilla de 24 se solapan (horizonte 30,
  separación de ~39 puntos), así que el desacuerdo de subconjuntos no es de
  observaciones independientes.
- La referencia de 24 cutoffs es una media, no una prueba de significancia
  (esa comparación en pares es la que usa 3.0d).
- Horizonte 30 también en series mensuales (30 meses), como hace producción
  hoy; no se evaluó si ese horizonte es razonable para mensuales.
