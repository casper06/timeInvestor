# Benchmark estacional (3.0c + 3.0d): veredicto por serie

Fecha: 2026-09-26. Script: `scripts/seasonal_benchmark.py`. Datos:
`data/snapshots/seasonal_benchmark_2026-09-26.json` (sha256 `e0c71331…`,
git-ignorado). Resultado completo, por cutoff: `seasonal_benchmark_2026-09-26.json`.
Dos corridas sobre el mismo snapshot dan JSON idénticos.

- **Rivales:**
  - naive estacional;
  - Holt amortiguado;
  - Holt-Winters ETS(A,Ad,A);
  - TimesFM 2.5 con pesos reales (sin ningún fallback);
  - Prophet 1.4.0.
- **Cutoffs:** los mismos 24 por serie para todos los motores, horizonte 12
  meses. Las ventanas de 12 meses no se solapan (hay 12–16 meses entre
  cutoffs).
- **Criterio de veredicto:** el menor MASE estacional medio. Reemplaza a
  Holt-Winters solo si le gana en los cutoffs pareados con un test de signo
  significativo (p < 0,05).

## Veredicto

| Serie | Veredicto | Sin 2020 | Evidencia (MASE estacional; pares vs HW) |
|---|---|---|---|
| IPG2211A2N | **TimesFM** | TimesFM | 0,956 vs HW 1,167; 20-4 (p=0,002). Sin 2020: 19-4 (p=0,003) |
| RSAFSNA | **TimesFM** (frágil) | Holt-Winters | 0,749 vs 1,039; 18-6 (p=0,023). Sin 2020: 16-6 (p=0,052) |
| HOUSTNSA | **TimesFM** | TimesFM | 0,693 vs 0,859; 18-6 (p=0,023). Sin 2020: 17-6 (p=0,035) |
| MRTSSM4451USN | **Holt-Winters** | Holt-Winters | TimesFM 0,790 vs HW 1,034 en media, pero 16-8 (p=0,152): no significativo |

## Métricas (todos los cutoffs, las 4 series juntas, 96 cutoffs)

| Motor | MASE est. | MAPE | Cob. 95% | Cob. 80% | Ancho 95% | Ancho 80% | vs HW |
|---|---|---|---|---|---|---|---|
| Naive estacional | 1,305 | 6,12% | 93,3 | 79,7 | 30,0% | 19,5% | 29-67 |
| Holt (motor actual) | 1,924 | 9,02% | 97,0 | 85,6 | 60,1% | 38,0% | 9-87 |
| Holt-Winters | 1,025 | 5,02% | 90,5 | 75,9 | 21,1% | 13,8% | — |
| **TimesFM 2.5** | **0,797** | **4,13%** | n/d | **87,7** | n/d | 15,6% | **72-24** |
| Prophet | 1,223 | 7,67% | 68,7 | 47,6 | 15,3% | 9,9% | 40-56 |

Sin las ventanas que tocan 2020 (90 cutoffs):

| Motor | MASE est. | MAPE | Cob. 95% | Cob. 80% | vs HW |
|---|---|---|---|---|---|
| Naive estacional | 1,236 | 6,05% | 94,2 | 80,8 | 26-64 |
| Holt | 1,868 | 9,05% | 97,8 | 86,4 | 6-84 |
| Holt-Winters | 0,893 | 4,57% | 92,7 | 78,0 | — |
| TimesFM 2.5 | 0,734 | 3,97% | n/d | 88,8 | 66-24 |
| Prophet | 1,199 | 7,75% | 68,5 | 47,6 | 35-55 |

TimesFM solo tiene cuantiles nativos p10–p90, así que su 95% es "n/d": no se
aproxima.

### Pares contra el naive estacional

| Serie | TimesFM vs naive | HW vs naive | Prophet vs naive | Prophet vs HW | Prophet vs TimesFM |
|---|---|---|---|---|---|
| IPG2211A2N | 18-6 (p=0,023) | 14-10 (p=0,541) | 18-6 (p=0,023) | 17-7 (p=0,064) | 8-16 (p=0,152) |
| RSAFSNA | 22-2 (p<0,001) | 20-4 (p=0,002) | 17-7 (p=0,064) | 6-18 (p=0,023) | 2-22 (p<0,001) |
| HOUSTNSA | 17-7 (p=0,064) | 13-11 (p=0,839) | 6-18 (p=0,023) | 7-17 (p=0,064) | 5-19 (p=0,007) |
| MRTSSM4451USN | 23-1 (p<0,001) | 20-4 (p=0,002) | 19-5 (p=0,007) | 10-14 (p=0,541) | 8-16 (p=0,152) |

Sin 2020, lo que cambia:
- TimesFM vs naive en HOUSTNSA pasa a 17-6 (p=0,035);
- Prophet vs naive y vs HW en IPG2211A2N pasan a 17-6 (p=0,035 cada uno).

## Lectura

1. **TimesFM tiene el menor error en las 4 series** y le gana a HW en 72 de
   96 cutoffs. Es significativo en 3 de 4 series (IPG2211A2N, RSAFSNA,
   HOUSTNSA). En MRTSSM4451USN tiene menor media pero no le gana a HW de forma
   significativa. El hallazgo original ("TimesFM gana en FRED estacionales")
   se sostiene contra un rival estacional justo en 3 de las 4 series, no en
   las 4. RSAFSNA queda frágil: sin 2020, p=0,052.
2. **Holt, el motor actual para cuando TimesFM no está, es el peor de los
   cinco:** pierde 87-9 contra HW y también contra el naive estacional en las
   4 series. Hoy, sin TimesFM, estas series usan un modelo peor que "el mismo
   mes del año pasado".
3. **Holt-Winters no le gana significativamente al naive estacional en
   IPG2211A2N (14-10) ni en HOUSTNSA (13-11).** Como plan B es claramente mejor
   que Holt, pero en esas dos series equivale en la práctica al naive
   estacional.
4. **Prophet no entra al selector.** Solo cumple su criterio de entrada (ganarle
   al naive estacional y a HW) en IPG2211A2N sin 2020, y ahí pierde con TimesFM
   (8-15). En conjunto pierde con HW (40-56), y sus intervalos sub-cubren mucho
   (68,7% al 95%, 47,6% al 80%).
5. **Calibración de TimesFM:** su banda nativa p10–p90 cubre 87,7% (nominal
   80%), es decir, algo conservadora. HW sub-cubre (75,9% al 80%, 90,5% al 95%).

## Bug encontrado: la banda de TimesFM en la app es [media, p90], no p10–p90

TimesFM 2.5 devuelve 10 columnas de cuantiles: `[media, p10, …, p90]`. Lo
confirman la config de `timesfm_2p5` (cuantiles 0,1…0,9, `decode_index=5` =
p50, punto = columna 5) y una inferencia real.
`TimesFMForecastEngine.forecast` toma `[..., 0]` (la media) como límite
inferior, así que el "80%" que muestra la app es en realidad [media, p90]:
- en IPG2211A2N h=1 muestra 121,73 como límite inferior, cuando p10 = 118,00;
- en h=2 el "límite inferior" (120,56) queda por encima del punto (120,15).

| Serie | Cobertura de la banda de la app | Cobertura p10–p90 real |
|---|---|---|
| IPG2211A2N | 51,4% | 84,0% |
| RSAFSNA | 62,5% | 85,8% |
| HOUSTNSA | 36,1% | 88,9% |
| MRTSSM4451USN | 57,6% | 92,0% |

El punto (p50) está bien, así que los MASE y MAPE de este benchmark no se ven
afectados; las coberturas de TimesFM de arriba usan la p10–p90 real.

En este benchmark no se toca: se reporta. Consecuencias en producción:
- todas las proyecciones TimesFM muestran un intervalo colapsado hacia el
  punto;
- el guard de calibración de auto-discovery compara la cobertura de TimesFM
  con esa banda. En la DB local, CEG (MASE TimesFM 4,08 vs Holt 5,42) y NVDA
  (4,42 vs 4,77) quedaron en Holt "por calibración", justo el patrón que
  produciría este bug. No verificado que esa sea la causa.

## Propuesta para `SEASONAL_FRED_CATALOG` (no implementada)

Hoy el catálogo manda las 4 series a TimesFM y cae a Holt si no está.

1. **Primero, arreglar la banda de TimesFM** (columna 1 = p10, no la
   columna 0). Sin eso, cualquier cambio al selector sigue mostrando
   intervalos de TimesFM mal armados.
2. IPG2211A2N y HOUSTNSA: **TimesFM** (robusto sin 2020).
3. RSAFSNA: **TimesFM**, marcado como frágil (sin 2020 no es significativo
   contra HW). Alternativa conservadora: HW.
4. MRTSSM4451USN: **Holt-Winters** (TimesFM no le gana de forma significativa;
   HW es más simple y no depende de pesos con licencia no comercial).
   Alternativa: dejar TimesFM, que tiene menor error medio.
5. **Plan B cuando TimesFM no está: Holt-Winters**, no Holt. Con salvedad
   para IPG2211A2N y HOUSTNSA, donde HW ≈ naive estacional.
6. Después del arreglo del punto 1, re-evaluar las decisiones de
   auto-discovery donde TimesFM tenía mejor MASE y perdió "por calibración"
   (CEG y NVDA en la DB local).

## Limitaciones

- 24 cutoffs por serie y 4 series: los p-valores del test de signo son
  modestos, y con 4 series hay comparaciones múltiples (sin corrección).
- **Posible solapamiento con el pre-entrenamiento de TimesFM:** las series
  FRED son públicas y las ventanas de evaluación (1995–2025) podrían estar en
  su corpus de entrenamiento. No verificado; si fuera así, favorecería a
  TimesFM.
- Solo series mensuales NSA de EE.UU. Nada de esto se extiende a acciones
  ni ETFs.
- Cada motor usa su punto nativo: Holt y HW la media log-normal, TimesFM el
  p50, Prophet exp(yhat) (la mediana en log).
