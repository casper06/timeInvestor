# Regla de decisión robusta (2.3): variantes medidas y la elegida

Fecha: 2026-09-26. Script: `scripts/decision_variants.py` (reusa el evaluador
de 2.2 y las funciones de producción `decide_robust`, `recent_cutoff_indices`
y `choose_engine`). Datos: snapshot de 2.5 (sha256 `c37cf58e…`), 14 series
reales, TimesFM con pesos reales (0 fallbacks). Resultado completo, con 144
variantes por serie: `decision_variants_2026-09-26.json`.

## Antes → después (regla actual v3 → regla elegida v4)

Actual: toda la historia, 3 cutoffs, media estrictamente menor, sin margen,
con guard de cobertura.
Elegida (v4): ventana reciente por frecuencia, 8 cutoffs, mayoría de cutoffs
en par + margen del 10%, ≥ 7 pares, empate → motor base, histéresis ×2, sin
guard.

| Categoría | Desacuerdo con la referencia de 24* | Decisiones que terminan en el motor base | Cambios entre ventanas cercanas |
|---|---|---|---|
| Acciones (JNJ, JPM, KO, NVDA, XOM) | 40,5% → **11,6%** | 40,5% → **87,6%** | 8/30 → 5/30 (**0/30** con histéresis) |
| ETFs (SPY, QQQ, XLE, XLK) | 34,2% → **11,9%** | 58,7% → **88,1%** | 9/24 → 0/24 (**0/24**) |
| FRED estacional (HOUSTNSA, IPG2211A2N, RSAFSNA) | 26,5% → **22,8%** | 26,5% → 52,0% | 1/18 → 10/18 (**0/18**) |
| FRED SA (INDPRO, UNRATE) | 7,2% → **16,6%** ⚠️ | 7,2% → 45,6% | 0/12 → 2/12 (**0/12**) |

\* Cada regla se compara contra **su propia** decisión con 24 cutoffs en su
propia ventana: qué tan seguido una decisión de K cutoffs coincide con lo que
la misma regla diría con mucha más evidencia.

**Latencia del primer request** (umbral aceptable, fijado antes de medir:
≤ 10 s en este CPU):
- cómputo de los pares, medido por serie: 3 cutoffs 0,42–0,78 s → 8 cutoffs
  **0,86–1,55 s**;
- de punta a punta con descarga de datos (verificación real sobre una copia
  de la DB): **2,2–3,0 s** por serie, más la carga de TimesFM (~3–4 s, una vez
  por proceso). Dentro del umbral.

## Criterios de éxito

- **Baja el desacuerdo en FRED:** se cumple en las **estacionales** (26,5% →
  22,8%). **No se cumple en las SA** (7,2% → 16,6%), y en conjunto FRED sube
  de 18,8% a 20,4%. Hay dos razones:
  1. con la ventana de 10 años cambia qué dice la referencia (en INDPRO,
     sobre toda la historia TimesFM gana por −68%, pero en los últimos 10
     años la referencia es Holt: la ventaja venía de períodos viejos);
  2. exigir mayoría + margen con 8 cutoffs tiene menos poder que la media
     sobre 24.
- **En acciones y ETFs, la mayoría termina en empate → base y deja de
  oscilar:** se cumple (87,6–88,1% al motor base, 0 cambios con histéresis).
- **La latencia no sube más de lo aceptable:** se cumple (ver arriba).

## La hipótesis de los cutoffs remotos (verificada antes de diseñar)

Con `pick_cutoff_indices` sobre toda la historia, los 3 cutoffs de producción
caen en:
- **IPG2211A2N:** 1989-12, 2006-12, 2023-12;
- **INDPRO:** las mismas fechas;
- **SPY:** 2021-12, 2024-03, 2026-05 (SPY solo tiene 5 años).

En IPG2211A2N, TimesFM gana 2 de 3 (2006: 1,040 vs 1,458; 2023: 1,330 vs
1,657), pero pierde fuerte en **1989** (2,372 vs 1,599), con solo 60 meses de
entrenamiento y un régimen remoto. Ese cutoff arrastra la media hacia
Holt-Winters. Con la ventana de 10 años y la regla de mayoría, IPG2211A2N pasa
a TimesFM, igual que 3.0d.

## Piezas elegidas y por qué

1. **Ventana reciente por frecuencia:** diarias y semanales 2 años (504 y 104
   puntos); mensuales y trimestrales 10 años (120 y 40). En diarias, un
   régimen reciente con lugar para ventanas de 30 sesiones; en mensuales, un
   ciclo económico completo, sin décadas remotas ni cutoffs con poco contexto
   de entrenamiento.
2. **Consistencia: mayoría simple de cutoffs en par + margen del 10%.**
   **Desvío deliberado del pedido** (test de signo como en 3.0d): con 8
   cutoffs, el test de signo al 5% exige 7/8, y en UNRATE y HOUSTNSA (donde la
   referencia de 24 es claramente TimesFM) mandó al baseline el 70–79% de las
   decisiones de 8 cutoffs, perdiendo victorias reales. Mayoría + margen logra
   la estabilidad en mercado sin esa pérdida. El modo test de signo quedó
   implementado (`alpha` en `decide_robust`) por si se prefiere.
3. **Mínimo de 7 cutoffs en par de 8:** tolera un fallback de TimesFM.
4. **Empate → motor base:** Holt en las no estacionales, Holt-Winters en las
   estacionales.
5. **Histéresis:** en la re-evaluación, el motor vigente (solo si su decisión
   ya es v4) se mantiene salvo que el otro le gane por mayoría y con **el
   doble del margen (20%)**. Con histéresis, los cambios entre ventanas
   cercanas bajan a 0 en todas las categorías.
6. **8 cutoffs:** con 3, el desacuerdo en mercado es 34–41%; con 8 y la regla
   elegida, ~12%. El costo extra es ~1 s por serie.
7. **Guard de cobertura: se saca.** En 2.2 cambiaba 0–7% de las decisiones, y
   acá las variantes con y sin guard difieren en ≤ 0,5 pp. Sigue disponible
   como parámetro (`guard`) y la cobertura se sigue midiendo en cada backtest.

## Verificación real (copia de la DB, datos de hoy)

| Serie | Antes | v4 | Motivo |
|---|---|---|---|
| CEG | timesfm (v2) | holt | en los últimos 2 años TimesFM es peor (+11,8%) |
| NVDA | timesfm (v2) | holt | TimesFM peor (+7,6%) |
| VIST | holt | holt | TimesFM peor (+10,7%) |
| PCU33443344 | timesfm (v1) | holt | TimesFM −1,6%: dentro del margen, empate |
| SPY | — | holt | TimesFM −24,9% en media, pero gana solo 3 de 8 cutoffs: la ventaja sale de uno solo (2025-04-08, Holt 17,07 vs 5,43) |
| JNJ | — | holt | TimesFM −5,0%: empate |

La DB real no cambió (sha256 `41980b49…` antes y después). La copia se borró.

## Limitaciones

- Una sola ventana de datos por serie (el snapshot de 2.5); diarias con ~5
  años.
- La referencia de 24 es una media, no una prueba de significancia.
- Horizonte de 30 puntos también en mensuales (30 meses), como hoy.
- Con histéresis, una decisión inicial equivocada tarda más en corregirse;
  el TTL de 30 días y el umbral de crecimiento del 20% siguen forzando la
  re-evaluación.
