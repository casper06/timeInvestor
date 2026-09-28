# Badge de capacidad contra el naive más exigente: validación (4.17, criterio v10)

- **Pre-registro:** `docs/PLAN.md` 4.17, commit `24d90b4` (2026-09-28 09:58).
- **Script:** `scripts/skill_strictest_validation.py`. Resultado:
  `skill_strictest_naive_2026-09-28.json`.
- **Montaje:** copia de la DB, TimesFM real, decisiones v10 nuevas.

## Selección de las series de validación (regla pre-registrada)

- **Fuente:** `fred/tags/series` con `nsa;monthly;usa`, por popularidad.
- **Filtros, en orden:** fuera del chequeo de POPTHM; historia de 2000 a 2026;
  estacional según 3.0a sobre las 500 observaciones.
- **Recorrido:**
  - FEDFUNDS (no estacional);
  - **CSUSHPINSA**;
  - APU0000703112, UMCSENT (no estacionales);
  - **CPIAUCNS**;
  - REAINTRATREARAT10Y (no estacional);
  - **APU0000708111**, **TB3MS**;
  - PPIACO (no estacional);
  - **AAA**;
  - GS10 (no estacional);
  - **BOGMBASE**.

**Desviación, dicha tal cual:**
- En una primera corrida (`skill_strictest_naive_2026-09-28_corrida1.json`),
  FEDFUNDS y CSUSHPINSA quedaron afuera por una **descarga fallida**
  transitoria. Ese no es uno de los criterios de la regla: lo había agregado
  el script.
- Se agregaron reintentos a la descarga y se volvió a correr.
- Con la regla bien aplicada, CSUSHPINSA entra y APU000072610 queda afuera
  (era la 7.ª). Lo que sigue es la corrida corregida.

## Resultado

Estado v9 (contra el naive estacional) → v10 (contra el más exigente por
error total).

| Serie | Decisión | Σ error RW / Σ estacional | Referencia v10 | v9 | v10 | Contra el otro naive |
|---|---|---|---|---|---|---|
| CSUSHPINSA | HW, 12 m | 74,0 / 120,3 | random walk | aporta 6-2, −52% | **no aporta** 4-4, −23% | 6-2 |
| CPIAUCNS | HW, 12 m | 45,1 / 73,9 | random walk | aporta 8-0, −56% | aporta 8-0, −28% | 8-0 |
| APU0000708111 | HW, 12 m | 4,98 / 7,00 | random walk | aporta 6-2, −25% | **no aporta** 5-3, +6% | 6-2 |
| TB3MS | TimesFM, 12 m | 4,97 / 8,65 | random walk | aporta 8-0, −57% | aporta 6-2, −25% | 8-0 |
| AAA | HW, 12 m | 0,38 / 0,55 | random walk | no evaluado (2 pares) | no evaluado (2 pares) | — |
| BOGMBASE | HW, 12 m | 1595 / 1965 | random walk | no evaluado (6 pares) | no evaluado (6 pares) | — |

- **Criterio de adopción:** ninguna serie tiene "aporta" en v10 perdiendo la
  mayoría contra el otro naive, así que **v10 se adopta**, como estaba
  pre-registrado.
- **Cambios de estado:** de las 4 series de validación evaluables, 2 pasan de
  "aporta" a "no aporta" (CSUSHPINSA y APU0000708111).
- **Referencia:** en las 6, el naive más exigente es el random walk.
- **AAA y BOGMBASE:** siguen sin evaluar, porque Holt-Winters rechaza algunas
  ventanas de entrenamiento y quedan menos de 7 pares. No cambia con v10.

## Las 10 series del chequeo de POPTHM (no son validación; ya se habían visto)

- **GFDEGDQ188S:** pasa a "no aporta" (5-3, −5,6%, contra el random walk),
  como se había medido.
- **Las otras 9:** siguen "aporta". Para POPTHM, GFDEBTN, IMPCH y UNRATENSA
  la referencia pasa a ser el random walk; para MTSDS133FMS y las 4 del
  catálogo sigue siendo el estacional.
- **Catálogo:** el badge de producción usa la evidencia de 3.0d. Contra el
  random walk (`seasonal_benchmark_rw_2026-09-28.json`) el naive estacional
  sigue siendo el más exigente en las 4 series, así que el estado no cambia.
- **API real sobre la copia:** GFDEGDQ188S "no aporta" 5-3; CSUSHPINSA "no
  aporta" 4-4; IPG2211A2N "aporta" 18-6 contra el naive estacional.
