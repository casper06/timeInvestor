# Horizonte en la unidad de la serie (4.14)

Fecha: 2026-09-27. Rama `fix/horizon-units`.

## Verificación real sobre una copia de la DB: INDPRO y NVDA, antes y después

Condiciones:
- Datos reales descargados una sola vez y usados en las dos corridas: INDPRO de FRED, 500 puntos (1985-01 → 2026-08-01); NVDA de yfinance, período 1y (el default de la UI), 251 puntos.
- Pedido tal como lo hace cada UI:
  - **antes** (código de `main`, c793415): 60 pasos, `freq='D'`;
  - **después** (esta rama): el horizonte canónico de la frecuencia, sin `freq`.
- Cada corrida usó su propia copia de `time_investor.db` en el scratchpad, con `DATABASE_URL` explícito; el script aborta si no apunta a la copia. La DB real no cambió: sha256 `41980b49c0f7a805…` antes y después.

| | INDPRO antes | INDPRO después | NVDA antes | NVDA después |
|---|---|---|---|---|
| Pedido | 60 pasos, `freq='D'` | 12 (canónico mensual) | 60 pasos, `freq='D'` | 60 (canónico diario) |
| Pasos devueltos | 60 (meses) | 12 | 60 | 60 |
| Fechas | 2026-08-03 → 2026-10-23 (días hábiles) | 2026-09-01 → 2027-08-01 (mensuales) | 2026-09-28 → 2026-12-18 | idénticas |
| Etiqueta de la UI | "Objetivo +60d", "60 días" | "Objetivo +12 meses", "12 meses" | "Objetivo +60d", "60 días" | "Objetivo +60d", "60 días hábiles" |
| Valor al final | 103,88 (5 años adelante) | 103,39 | 228,68 | idéntico |
| Banda al final (95%) | [84,21; 126,76], ancho 42,55 | [95,06; 112,25], ancho 17,19 | [159,09; 318,55], ancho 159,46 | idéntica |
| CAGR mostrado | 4,9% (60 días de 365,25) | 0,3% (365 días reales) | 10,2% (60/365,25) | 7,2% (84 días reales) |
| Motor | Holt (auto-discovery v4) | Holt | Holt (auto-discovery v4) | Holt |
| `decision_horizon` | — | 30 → nota "Motor elegido evaluando a 30 meses" | — | 30 → nota "Motor elegido evaluando a 30 días hábiles" |

Lectura:
- **INDPRO, antes:** mostraba 60 meses (una banda de 5 años) como si fueran 60 días hábiles, con fechas diarias y un CAGR calculado como si 5 años fueran 60 días.
- **INDPRO, después:** el paso 12 es el mismo número de siempre (103,39; [95,06; 112,25]), que antes caía en la fecha 2026-08-18 y ahora cae en 2027-08-01.
- **NVDA:** fechas, valores y banda idénticos punto por punto.
  - Lo único que cambia en diarias es el CAGR. Antes anualizaba 60 días hábiles como 60 días corridos; ahora usa las fechas reales (84 días). Es la corrección de un error que ya existía.
  - La etiqueta larga pasa a decir "días hábiles".
- **La razón del motor de NVDA** dice Holt con MASE 6,748 antes y 6,749 después. La decisión de NVDA en la copia era del criterio v2, así que cada corrida la re-evaluó descargando la historia de 5 años en vivo. Repetido sobre **la misma** serie guardada, `main` y la rama dan el mismo MASE bit a bit (6.748749999999999). La diferencia viene de las dos descargas, no del código.
- **Las etiquetas** salen de las funciones testeadas (`utils/horizon.ts`) aplicadas a estas respuestas. La UI no se abrió en un navegador: **no verificado visualmente**.

## Medición en el horizonte canónico (punto 3): el criterio NO se sube de versión

Script `scripts/horizon_variants.py` con la regla v4 fija, variando solo el horizonte:
- mismo snapshot (sha256 `c37cf58e…`), TimesFM real, 0 fallbacks;
- resultado: `horizon_canonical_monthly_2026-09-27.json`;
- h=12 reproduce exactamente el resultado de #34 (0 diferencias); h=30 y h=60 vienen de `horizon_variants_2026-09-27.json`.

| Categoría | Horizonte | Desacuerdo | Al motor base | Cambios (con histéresis) | Independientes de 8 |
|---|---|---|---|---|---|
| Acciones | **30 (v4)** | 11,4% | 88,0% | 5/30 (0/30) | 8 |
| Acciones | 60 (canónico) | 11,9% | 87,4% | 2/30 (1/30) | 8 |
| ETFs | **30 (v4)** | 13,3% | 86,7% | 0/24 (0/24) | 8 |
| ETFs | 60 (canónico) | 5,6% | 94,4% | 2/24 (0/24) | 8 |
| FRED estacional | **30 (v4)** | 23,3% | 51,5% | 10/18 (0/18) | 3 |
| FRED estacional | 12 (canónico) | 21,8% | 45,0% | 4/18 (0/18) | 8 |
| FRED estacional | 6 | 19,0% | 51,3% | 4/18 (1/18) | 8 |
| FRED estacional | 3 | 13,6% | 86,4% | 4/18 (0/18) | 8 |
| FRED SA | **30 (v4)** | 18,5% | 50,8% | 2/12 (0/12) | 3 |
| FRED SA | 12 (canónico) | **34,2%** | 74,8% | 3/12 (0/12) | 8 |
| FRED SA | 6 | 8,9% | 91,1% | 2/12 (1/12) | 8 |
| FRED SA | 3 | 19,1% | 80,9% | 7/12 (4/12) | 8 |

**Con el canónico mensual de 12, FRED SA empeora contra v4** (18,5% → 34,2%). La mayor parte viene de UNRATE, que tiene 59% de desacuerdo a 12 meses.

**6 meses mejora las dos categorías FRED** en esta muestra. Pero son solo 5 series (3 estacionales y 2 SA) y el ruido de la métrica es de ~2 pp. Tampoco es el horizonte que la UI propone por defecto.

**3 meses** baja el desacuerdo estacional porque casi todo va al motor base (86%), pero en FRED SA tiene 4 cambios de 12 incluso con histéresis.

**Por eso el criterio no se subió de versión.** Se registra el horizonte de la decisión (30) y la UI lo avisa, pero el motor se sigue eligiendo como en v4. Semanal (13) y trimestral (4) quedan **no verificados**: no hay series de esas frecuencias en el snapshot.
