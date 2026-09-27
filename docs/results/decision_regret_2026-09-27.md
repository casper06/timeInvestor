# Arrepentimiento de las decisiones de auto-discovery (2.3c): v5 no se implementa

Fecha: 2026-09-27.

- Script: `scripts/horizon_variants.py`, con la regla v4 fija (`decide_robust`) y variando solo el horizonte.
- Datos: snapshot sha256 `c37cf58e…`, 14 series, TimesFM real, 0 fallbacks.
- Resultados: `decision_regret_2026-09-27.json` y `unrate_detail_2026-09-27.json`.
- Tabla por categoría: `python scripts/horizon_variants.py --summary docs/results/decision_regret_2026-09-27.json`.
- Reproducibilidad: los 266 campos que esta corrida comparte con #34 y #35 (referencia, desacuerdo, cambios, etc.) coinciden sin diferencias.

## Métrica (definida antes de correr)

Para cada decisión de 8 cutoffs (400 subconjuntos aleatorios de la grilla de 24, por serie y horizonte):
- se toma H, los 16 cutoffs de la grilla que **no** se usaron para decidir;
- se calcula E_m(H), el error medio de cada motor m en los cutoffs de H donde corrieron los dos, con la métrica de la regla (MASE, o MASE estacional en series estacionales);
- el arrepentimiento es E_elegido(H) / min(E_base(H), E_TimesFM(H)) − 1, en puntos porcentuales de error relativo extra.

Por categoría se juntan todas las decisiones de todas sus series.

## Arrepentimiento por categoría (pp)

| Categoría | Horizonte | Media | Mediana | p90 |
|---|---|---|---|---|
| Acciones | **30 (v4)** | 2,26 | 0,00 | 9,68 |
| Acciones | 60 (canónico) | 3,43 | 0,00 | 13,25 |
| ETFs | **30 (v4)** | 3,15 | 0,65 | 9,44 |
| ETFs | 60 (canónico) | 1,42 | 0,00 | 5,56 |
| FRED estacional | **30 (v4)** | 6,56 | 5,28 | 13,28 |
| FRED estacional | 12 (canónico) | 3,87 | 0,00 | 12,13 |
| FRED estacional | 6 (solo referencia) | 4,03 | 0,00 | 11,69 |
| FRED SA | **30 (v4)** | 105.723,68 | 4,18 | 99,25 |
| FRED SA | 12 (canónico) | 40,29 | 15,53 | **137,41** |
| FRED SA | 6 (solo referencia) | 10,05 | 0,00 | 30,82 |

## Criterio pre-registrado y resultado

El criterio quedó escrito en la bitácora antes de calcular ningún número. En cada categoría, pasar al canónico exige:
- media(canónico) ≤ media(v4 a 30) + 2 pp, y
- p90(canónico) ≤ p90(v4 a 30) + 5 pp.

| Categoría | Media: canónico ≤ v4 + 2 | p90: canónico ≤ v4 + 5 | Cumple |
|---|---|---|---|
| FRED estacional (12) | 3,87 ≤ 8,56 ✔ | 12,13 ≤ 18,28 ✔ | sí |
| FRED SA (12) | 40,29 ≤ 105.725,68 ✔ | **137,41 > 104,25 ✘** | **no** |
| Acciones (60) | 3,43 ≤ 4,26 ✔ | 13,25 ≤ 14,68 ✔ | sí |
| ETFs (60) | 1,42 ≤ 5,15 ✔ | 5,56 ≤ 14,44 ✔ | sí |

**No se cumple en FRED SA, así que no se sube a v5.** El criterio de auto-discovery sigue en v4.

## Lo que el resultado no dice: dos advertencias

1. **La media de FRED SA a 30 no significa nada.** Holt explota en UNRATE con el cutoff 2020-04-01: MASE 1.715.969 a 30 meses. Es el salto de desempleo del COVID extrapolado en escala logarítmica. De las 400 decisiones de UNRATE a 30, 77 eligen Holt. En 64 de ellas el cutoff 2020-04-01 quedó entre los evaluados (fuera de los 8), y el arrepentimiento es de millones de pp. Por eso la condición de la media se cumple de forma trivial.
2. **El p90 de FRED SA a 30 está cerca de un salto.**
   - Esas 64 decisiones enormes son el 8% de las 800 del grupo, menos del 10%. Por eso el p90 cae en la cola de INDPRO (99 pp).
   - Con 16 más (2 puntos del grupo), el p90 de v4 sería de ~100.000 pp y el criterio se cumpliría.
   - Mirado serie por serie, **las dos series SA tienen media y p90 menores a 12 que a 30**:
     - INDPRO: 16,0 / 33,4 a 12, contra 50,6 / 90,5 a 30;
     - UNRATE: 64,6 / 152,6 a 12, contra 211.397 / 1.276.575 a 30.

   La falla sale de juntar series en el percentil y de una sola corrida catastrófica de Holt. No aparece en cada serie por separado. Aun así, el criterio pre-registrado es el que vale. Cambiarlo después de ver los números es justamente lo que el pre-registro busca evitar. Si se quiere otro criterio (por serie, o con el arrepentimiento acotado), habría que fijarlo ahora y validarlo con datos nuevos: otro snapshot.

## UNRATE a 12 meses: ¿empate real?

Grilla de 24 cutoffs (2016-06 → 2025-05), MASE:

| | Holt | TimesFM |
|---|---|---|
| Error medio | 9,50 | 5,01 |
| Error mediano | 1,43 | 1,51 |
| Cutoffs ganados | 10 | 14 |
| Media sin el cutoff 2020-05-01 | 5,32 | 4,90 |

**No es un empate casi perfecto. Es una dependencia del régimen:**
- **Los errores por cutoff difieren mucho.** Solo 4 de los 24 cutoffs tienen a los dos motores dentro de ±10%.
- **Cada motor gana en otro período:**
  - TimesFM gana en 2016-2017 y en todo el tramo del COVID (2019-07 → 2021-06); en el cutoff 2020-05-01, Holt tiene 105,7 contra 7,6.
  - Holt gana en la calma previa (2018-01 → 2019-03) y en la salida del COVID (2021-11 → 2023-01).
- **Por eso el desacuerdo es alto (59%) y el costo también.** Qué motor gana depende de qué cutoffs caen en los 8, y equivocarse cuesta mucho, sobre todo cuando la ventana incluye el COVID (arrepentimiento: mediana 20 pp, p90 153 pp).

A 30 meses, TimesFM gana 17 de 24 y la mediana es 8,26 contra 8,75.

## Hallazgo aparte: Holt explota tras un shock de nivel

- **Qué pasó:** con el cutoff 2020-04-01 (el pico del desempleo) y 30 meses, el MASE de Holt es 1.715.969. La tendencia amortiguada en escala logarítmica, estimada justo sobre el salto, extrapola una exponencial.
- **A 12 meses** el mismo tramo da 105,7: malo, pero sin explotar.
- **En producción** eso pasaría si alguien proyecta a horizontes largos una serie que acaba de dar un salto. Se propone como ítem aparte en PLAN (2.6); no se toca en esta ronda.

## Qué quedó en el código

- En `scripts/horizon_variants.py`:
  - `holdout_regret`: el arrepentimiento, evaluado en los cutoffs que no se usaron para decidir;
  - `_grid_summary`: el mano a mano en la grilla (errores medios y cutoffs ganados);
  - `--summary`: la tabla por categoría;
  - `--detail SERIE`: los errores por cutoff.
- `tests/test_regret.py`: 7 tests con tablas armadas a mano.
- Producción no cambia: el criterio sigue en v4.
