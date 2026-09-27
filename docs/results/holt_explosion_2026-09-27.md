# Explosión de Holt tras un salto de nivel (2.6): diagnóstico y opciones

Fecha: 2026-09-27.
- Snapshot: sha256 `c37cf58e…`.
- Script: `scripts/holt_explosion.py`. El diagnóstico sale de la corrida por defecto; las opciones, de `--options`, con TimesFM real.
- Datos: `holt_explosion_2026-09-27.json` y `holt_explosion_options_2026-09-27.json`.
- Las definiciones y los umbrales de las opciones quedaron escritos en la bitácora **antes** de medirlas.

## 1. Mecanismo (UNRATE, `DampedHoltForecastEngine`)

| Cutoff | Último | α | β | φ | Residuo final (log) | Tendencia (log/mes) | Suma amortiguada a 12 | Pronóstico a 12 | Factor de sesgo a 12 | Real a 12 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2020-03-01 | 4,4 | 0,658 | 0,244 | 0,927 | +0,224 | +0,032 | 7,56 | 5,22 | 1,01 | 6,1 |
| **2020-04-01** | **14,8** | **0,990** | **0,886** | 0,895 | **+1,039** | **+1,088** | 6,27 | **20.860** | 1,56 | 6,1 |
| 2020-05-01 | 13,2 | 0,959 | 0,100 | 0,920 | −0,187 | +0,104 | 7,26 | 29,7 | 1,05 | 5,8 |

1. **El ajuste se secuestra.** Holt ajusta α, β y φ minimizando la SSE de los errores a un paso sobre toda la historia (en log). El residuo de abril 2020 (+1,04) domina esa suma, y el mínimo pasa a ser α = 0,99 y β = 0,89: parámetros que hacen que el modelo "persiga" la suba de marzo, porque eso achica el error de abril. Con datos hasta marzo el ajuste era normal (α 0,66, β 0,24).
2. **El salto se vuelve tendencia.** La actualización `tendencia = φ·tendencia + α·β·e` convierte el 88% del residuo en tendencia: +1,09 en log por mes, es decir ×3 por mes.
3. **El horizonte la multiplica.** Con φ = 0,895 la tendencia se acumula a 6,27 veces a 12 meses y a 8,21 a 30. La mediana llega a exp(log 14,8 + 6,27·1,09 + …) ≈ 13.370.
4. **La corrección lognormal casi no aporta.** exp(var/2) suma ×1,56 a 12 meses y ×11 a 30, pero la explosión ya está en la mediana. El pronóstico queda en 20.860 a 12 meses y 1,22 M a 30.
5. **Es un problema del cutoff, no del régimen.** Un mes después, β se vuelve a ajustar a 0,10 y el pronóstico queda en 29,7: alto, pero no absurdo. La explosión aparece cuando **el último dato es el salto**.

**Otras series**, en ventanas cerca de 2008-09 y 2020 y en sus 5 mayores saltos: 380 corridas, con horizonte canónico y 30. Explosiones (índice X > 2):
- UNRATE 2020-04: 20.860 a 12 y 1,22 M a 30.
- INDPRO 2020-04: 50,3 a 12 meses. Es −40%, por debajo de su mínimo desde 1985; el valor real fue 98,6.
- HOUSTNSA 1988-04: ×2,8 a 12 y ×11 a 30.

Las diarias del snapshot empiezan en 2021-09 y no tienen 2008 ni 2020. En sus mayores saltos, X ≤ 0,7: sin explosiones.

## 2. Alcance en producción (copia de la DB)

Lo que devuelve `/api/forecast` si el último dato es el salto, como pasó en vivo en mayo de 2020:

| Caso | Motor que responde | A 12 meses | Aviso antes | Aviso ahora |
|---|---|---|---|---|
| UNRATE ≤ 2020-04, con TimesFM | TimesFM (auto-discovery) | 6,37 (real 6,1) | — | — (X bajo) |
| **UNRATE ≤ 2020-04, sin TimesFM** | Holt (plan B) | **20.855**; a 24 meses, 426.075 | **ninguno** | **"no confiable"** |
| **INDPRO ≤ 2020-04, con o sin TimesFM** | Holt (auto-discovery lo elige) | **50,3** | **ninguno** | **"no confiable"** |
| HOUSTNSA ≤ 1988-04 | TimesFM, o Holt-Winters sin TimesFM | 147,9 / 136,6 | — | — |
| NVDA, INDPRO actuales | Holt | normales | — | — |

**Sí, hoy puede llegarle al usuario un pronóstico absurdo sin aviso.** Por eso se implementó la marca (opción B).

Aparte: el Reality Check (`/api/backtest`) de UNRATE devuelve 400. La ruta no pasa `is_macro` y busca UNRATE en yfinance. Queda como ítem nuevo en PLAN.

## 3. Opciones

| | Qué hace | A favor | En contra |
|---|---|---|---|
| **A. Holt robusto** | Recorta el error (Huber, k = 2·σ robusto) en las actualizaciones de nivel y tendencia, y en el ajuste | Muy resistente a saltos aislados | Ignora los cambios de nivel reales (UNRATE ≤ 2020-04 da 4,5, como si abril no hubiera pasado) y puede explotar por otro lado |
| **C. Salto al nivel, no a la tendencia** | Recorta el error solo en la actualización de la tendencia | El nivel sigue al dato (UNRATE da 12,4) sin extrapolar el salto como pendiente | Cambia los pronósticos en todos los cutoffs, no solo en los saltos |
| **B. Marca "no confiable"** (implementada) | X = \|log(F_H / y_T)\| / máximo movimiento en H pasos de la historia. Si X > 2, se marca; no toca números | Honesta (regla 6), sirve para cualquier motor, no cambia nada cuando no se dispara | No arregla el pronóstico: solo lo dice |
| D. Plan B al marcar (propuesta, no medida) | Si se marca, además servir el naive o TimesFM, con aviso | Da un número sensato | Cambia de motor por una regla nueva; hay que medirlo |

## 4. Medición sobre el snapshot (grilla de 24 cutoffs, horizonte canónico y 30)

**"No empeora las series sin saltos"** (pre-registrado: en los cutoffs normales, MASE ≤ 1,02 × el actual y cobertura al 80% dentro de ±2 pp):

| Categoría, horizonte | Holt actual: MASE / cobertura | A | C |
|---|---|---|---|
| Acciones, 30 | 5,707 / 85,7 | 5,710 / 90,3 ✘ (+4,6 pp) | 5,694 / 86,8 ✔ |
| Acciones, 60 | 7,942 / 82,5 | 7,934 / 88,9 ✘ | 7,952 / 84,1 ✔ |
| ETFs, 30 | 4,628 / 87,3 | 4,656 / 91,2 ✘ | 4,645 / 87,9 ✔ |
| ETFs, 60 | 6,200 / 88,8 | 6,065 / 93,3 ✘ | 6,163 / 90,3 ✔ |
| FRED SA, 12 | 4,419 / 86,1 | 5,174 ✘ (+17%) / 91,3 ✘ | 4,359 ✔ / 89,6 ✘ (+3,5 pp) |
| FRED SA, 30 | 8,830 / 80,1 | 10,728 ✘ (+21%) / 88,1 ✘ | 8,353 ✔ / 85,6 ✘ (+5,5 pp) |

En las estacionales el motor base es Holt-Winters: las variantes no las tocan.

**En los cutoffs de salto** (FRED SA), MASE:
- a 12 meses: actual 41,9; A 12,2; C 22,6; TimesFM 4,0;
- a 30 meses: actual 857.998; A 28,2; C 42,8; TimesFM 9,9.

**Arrepentimiento** (pp, media acotada a 100 / p90). Cada variante reemplaza a Holt como motor base:

| Categoría, horizonte | Holt actual | A | C |
|---|---|---|---|
| Acciones, 30 | 2,26 / 9,68 | 2,69 / 12,15 | 2,18 / 9,15 |
| Acciones, 60 | 3,43 / 13,25 | 3,47 / 17,22 | 3,22 / 9,15 |
| ETFs, 30 | 3,15 / 9,44 | 3,70 / 10,30 | 3,39 / 9,32 |
| ETFs, 60 | 1,42 / 5,56 | 0,54 / 0,00 | 1,13 / 4,68 |
| FRED SA, 12 | 32,43 / 137,41 | 12,70 / 42,27 | 25,55 / 59,11 |
| FRED SA, 30 | 33,82 / 99,25 | 7,71 / 31,02 | 27,36 / 69,43 |

**Marca B:**
- en los cutoffs normales (2.358 corridas, todos los motores) marcó **0**: falsos positivos 0%, contra el objetivo de < 1%;
- en el scan de eventos (380 corridas de Holt) marcó exactamente las 6 explosiones conocidas (UNRATE, INDPRO y HOUSTNSA, a 12 y 30) y nada más.

## Veredicto

- **B cumple** y está implementada:
  - `backend/services/reliability.py`;
  - `ForecastResponse` y `BacktestResponse` con `reliable` y `reliability_warning`;
  - aviso en las tarjetas, el gráfico, el informe exportado y el copiloto (que lo dice en vez de narrarlo);
  - el backtest suma el aviso a `warnings`.
- **A no cumple.** Empeora el MASE en SA, corre la cobertura en todas las categorías e ignora los cambios de nivel reales.
- **C no cumple por una sola cláusula.** La cobertura de FRED SA sube 3,5 pp a 12 meses y 5,5 a 30, sobre un nominal de 80% que ya estaba cubierto de más. El MASE es igual o mejor en todo, y el arrepentimiento en FRED SA baja de 32,4 a 25,6 (a 12). Son solo 2 series SA. **No se implementa**; queda para decidir, idealmente midiéndola con las series de 3.5.
