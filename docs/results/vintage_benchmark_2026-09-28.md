# Capacidad de pronóstico con datos de época contra datos revisados (3.4, vintages de ALFRED)

- **Pre-registro:** `docs/PLAN.md` 3.4, commit `477b979` (2026-09-28 10:04),
  antes de descargar ningún vintage.
- **Script:** `scripts/vintage_benchmark.py`.
- **Snapshot:** `data/snapshots/vintages_2026-09-28.json` (ignorado por git),
  sha256 `650ba98b8dfb2ab71e14e4f71311bef51a0f99168b6c419b54bdf6b1780fa462`.
- **Resultado completo:** `vintage_benchmark_2026-09-28.json`.
- **Solo medición:** no se cambió ningún criterio ni catálogo.

## Qué se midió

- **Cutoffs:** 24 por serie, dentro del período con vintages. Horizonte: 12
  meses.
- **Entrenamiento:**
  - "de época": la serie como se publicó el día del cutoff;
  - "revisada": la serie de hoy cortada en la misma última observación.
- **Verdad:** la primera publicación de cada mes, o el valor revisado de hoy.
- **Capacidad:** la de 3.5 (test de signo p < 0,05/k y skill > 0 contra el
  naive más exigente); la serie tiene capacidad si algún motor le gana.
- **Condiciones clave:**
  - **revisada / revisada:** lo que miden hoy nuestros benchmarks;
  - **de época / primera:** lo que se habría podido saber en tiempo real.
- **Veredicto "no se sostiene":** tiene capacidad en la primera condición y no
  en la segunda.

## Resultado por serie

| Serie | Estacional | Vintages desde | revisada / revisada | de época / primera | Veredicto |
|---|---|---|---|---|---|
| HOUSTNSA | sí | 2011-03 | sí (TimesFM 19-5, skill +0,21) | sí (TimesFM 19-5, +0,19) | **se sostiene** |
| IPG2211A2N | sí | 2015-02 | sí (HW 18-6, +0,16; TimesFM 20-4, +0,20) | sí (TimesFM 22-2, +0,18; HW 16-8, +0,05, no significativo) | **se sostiene** |
| RSAFSNA | sí | 2001-06 | sí (HW 23-1, +0,41; TimesFM 23-1, +0,42) | sí (HW 22-2, +0,40; TimesFM 21-3, +0,40) | **se sostiene** |
| HOUST | no | 1960-07 | sí (TimesFM 19-5, p=0,003, +0,22) | no (TimesFM 17-7, p=0,032, +0,23) | **no se sostiene** |
| INDPRO | no | 1927-01 | sí (TimesFM 18-6, p=0,011, +0,42) | no (TimesFM 16-8, p=0,076, +0,08) | **no se sostiene** |
| JTSJOL | no | 2010-08 | sí (TimesFM 18-6, p=0,011, +0,14) | no (TimesFM 15-9, p=0,15, +0,13) | **no se sostiene** |
| PSAVERT | no | 1997-02 | no | no | sin capacidad en ninguna |
| UNRATE | no | 1960-03 | no | no | sin capacidad en ninguna |
| MRTSSM4451USN | sí | 2017-11 | — | — | excluida (vintages desde después de 2016) |

k = 2 motores en las no estacionales (umbral p < 0,025) y 3 en las
estacionales (p < 0,0167).

## Lectura

- **Las 3 series del catálogo estacional sobreviven.** Su capacidad (TimesFM
  o Holt-Winters contra el naive estacional) casi no cambia con datos de
  época: las revisiones del último tramo son chicas (0,06–2,7% en promedio)
  y el patrón estacional domina.
- **En las 3 mensuales SA que no se sostienen, la capacidad era de TimesFM:**
  - **INDPRO:** el skill cae de forma real, de +0,42 a +0,08;
  - **HOUST y JTSJOL:** el skill en tiempo real sigue positivo (+0,23 y
    +0,13), pero deja de ser significativo con la corrección por k.
  - En esas series, lo que miden hoy los benchmarks con datos revisados
    sobrestima lo que se habría sabido en tiempo real.
- **UNRATE y PSAVERT** no tenían capacidad en ninguna condición.

## Límites, dichos tal cual

- **Cambios de base y de definición:**
  - la "revisión media" de las últimas 60 observaciones es 58% en INDPRO y
    130% en PSAVERT. Eso no es revisión fina: son cambios de año base del
    índice y de definición;
  - dentro de cada condición la escala es coherente (entrenamiento y verdad
    de la misma época). Pero **las combinaciones cruzadas** (datos de época
    con verdad revisada, y al revés) mezclan escalas en esas series y **no se
    interpretan**. RSAFSNA también muestra ese efecto en la cruzada.
  - En INDPRO, un cambio de base entre el cutoff y la primera publicación de
    los meses siguientes también puede afectar algún cutoff de la condición
    "de época / primera". No se midió cuántos.
- **Ventanas largas:** en HOUST, INDPRO y UNRATE los vintages arrancan en
  1960 o 1927. La regla pre-registrada reparte los 24 cutoffs en todo ese
  período, así que mezclan décadas muy distintas. Mirar solo desde el 2000
  sería una medición nueva, con su propio pre-registro; no se hizo.
- **Serie excluida:** MRTSSM4451USN, por la regla (vintages desde 2017-11).
- **Cutoffs de UNRATE:** 23 de 24 utilizables (en uno faltaba la primera
  publicación de algún mes).

## Qué no cambia

Esta ronda no toca criterios ni catálogos: el catálogo estacional sigue igual
(sus 3 series medibles sobreviven), y las decisiones de auto-discovery siguen
usando datos revisados. Qué hacer con INDPRO, HOUST y JTSJOL (por ejemplo,
marcar que la capacidad medida es con datos revisados) queda para decidir.
