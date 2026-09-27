# Capacidad de pronóstico por categoría de FRED (3.5) y re-evaluación de v5 y C

Fecha: 2026-09-27. Todo sigue el pre-registro de `docs/PLAN.md`, 3.5:
- commit `2c07372`, anterior a la descarga;
- criterios de v5 (`db4fcdb`) y de C (`0ba851a`) sin cambios.

**Datos:**
- Selección: `fred_category_selection_2026-09-27.json` (sha256 `9572b4eb…`),
  hecha solo con metadatos.
- Snapshot: `data/snapshots/fred_categories_2026-09-27.json` (sha256
  `41714f29…`, ignorado por git), descargado con
  `FREDDataFetcher().get_series`.
- Resultado: `fred_category_benchmark_2026-09-27.json`.
- `--replay` reproduce el JSON byte a byte.
- TimesFM real: 0 fallbacks (la corrida se abortaba si había uno).

## Capacidad de pronóstico por categoría

Horizonte canónico (diaria 60, semanal 13, mensual 12, trimestral 4) y 24
cutoffs en la ventana de v4. Un motor **le gana al naive** si el test de
signo en pares da p < 0,05/k (Bonferroni por serie) y la skill es > 0. Una
categoría **tiene capacidad** si la tienen 3 de sus 5 series.

| Categoría | Series con capacidad | ¿Capacidad? | Quién gana |
|---|---|---|---|
| Mensual NSA (economía real) | **3/5** | **sí** | POPTHM (Holt, Holt-Winters, TimesFM), UNRATENSA (Holt-Winters, TimesFM), IMPCH (TimesFM) |
| Mensual SA (economía real) | 1/5 | no | JTSJOL (TimesFM) |
| Trimestral | 2/5 | no | GDP (Holt, TimesFM), GFDEBTN (Holt, Holt-Winters, TimesFM) |
| Semanal | 2/5 | no | STLFSI4 (TimesFM), WALCL (TimesFM) |
| Financiera diaria | **0/5** | no | ninguna |

Holm por categoría (sensibilidad, no decisiva) da exactamente los mismos
ganadores.

**Hipótesis "las financieras diarias no le ganan al random walk": se
sostiene** (0 de 5).
- VIXCLS con TimesFM es la más cercana: skill +0,369, 16 de 24 cutoffs,
  p = 0,076. No alcanza el umbral.
- Holt pierde contra el random walk en 4 de 5, con skill de −2,87 en T10Y2Y.

**Skill por serie** (skill contra el naive de referencia; "cutoffs" =
ganados sobre los no empatados; ★ = ya vista en 2.5):

| Serie | Cat. | Est. | Naive de ref. | Holt | Holt-Winters | TimesFM |
|---|---|---|---|---|---|---|
| POPTHM | NSA | sí | RW | **+0,788** (24/24) | **+0,830** (24/24) | **+0,643** (20/24) |
| UNRATENSA | NSA | sí | RW | −0,036 | **+0,087** (19/24) | **+0,242** (23/24) |
| IMPCH | NSA | sí | estacional | −0,090 | +0,210 (15/24) | **+0,214** (19/24) |
| MTSDS133FMS | NSA | sí | estacional | −0,186 | +0,077 | +0,161 (14/24) |
| MSPNHSUS | NSA | no | RW | +0,082 (16/24) | — | +0,033 |
| JTSJOL | SA | no | RW | +0,142 (16/24) | — | **+0,179** (20/24) |
| HOUST | SA | no | RW | +0,025 | — | −0,149 |
| ★ INDPRO | SA | no | RW | −0,005 | — | −0,021 |
| ★ UNRATE | SA | no | RW | −0,014 | — | +0,221 (14/24) |
| PSAVERT | SA | no | RW | −0,113 | — | +0,073 |
| GDP | T | no | RW | **+0,445** (20/24) | — | **+0,409** (21/24) |
| GFDEBTN | T | sí | RW | **+0,404** (20/24) | **+0,370** (20/24) | **+0,395** (23/24) |
| M2V | T | no | RW | −0,171 | — | +0,048 |
| MSPUS | T | no | RW | −0,115 | — | −0,047 |
| GFDEGDQ188S | T | sí | RW | −0,237 | −0,312 | −0,031 |
| WALCL | S | no | RW | +0,164 (11/24) | — | **+0,406** (19/24) |
| STLFSI4 | S | no | RW | −0,005 | — | **+0,259** (19/24) |
| NFCI | S | no | RW | −0,133 | — | +0,189 (16/24) |
| ICSA | S | no | RW | −2,631 (0/24) | — | +0,147 (15/24) |
| MORTGAGE30US | S | no | RW | −0,035 | — | −0,163 |
| VIXCLS | D | no | RW | −0,475 | — | +0,369 (16/24) |
| BAMLH0A0HYM2 | D | no | RW | −0,076 | — | +0,148 (11/24) |
| DGS10 | D | no | RW | +0,001 | — | −0,120 |
| DFEDTARU | D | no | RW | −0,004 (5/8, 16 empates) | — | −0,538 |
| T10Y2Y | D | no | RW | −2,870 | — | −0,681 |

En negrita: le gana al naive según el criterio. "Est." es si la serie es
estacional según el detector de 3.0a sobre la serie completa.

**Cobertura media del intervalo del 80%**, por categoría:

| Categoría | Holt | Holt-Winters | TimesFM |
|---|---|---|---|
| Financiera diaria | 94,3 | — | 81,2 |
| Semanal | 98,1 | — | 88,9 |
| Mensual SA | 83,4 | — | 69,7 |
| Mensual NSA | 71,2 | 64,9 | 78,7 |
| Trimestral | 77,1 | 75,0 | 83,5 |

En diarias y semanales Holt cubre de más; en mensuales, TimesFM cubre de
menos.

## v5: se adopta

Criterio pre-registrado en `db4fcdb`:
- por serie, arrepentimiento acotado a 100 pp;
- mejora o empata si A(v5) ≤ A(v4) + 2 pp;
- catastrófico si empeora más de 25 pp;
- mayoría estricta en cada categoría con ≥ 3 series evaluables.

| Categoría | Evaluables | Mejora o empata | ¿Pasa? | Series que empeoran |
|---|---|---|---|---|
| Mensual NSA | 5 | 5 | sí | — |
| Mensual SA | 5 | 4 | sí | UNRATE (9,6 → 19,9) |
| Semanal | 5 | 5 | sí | — (WALCL empata por 0,01 pp: 19,11 → 21,10) |
| Financiera diaria | 5 | 4 | sí | BAMLH0A0HYM2 (10,8 → 16,2) |
| Trimestral | 0 | — | no decide | a 30 pasos la ventana de 40 trimestres deja solo 10 cutoffs |

- Ninguna serie empeora de forma catastrófica: el máximo es UNRATE, +10,3 pp.
- Mejoras grandes: INDPRO (55,9 → 3,9), HOUST (8,2 → 0,3), VIXCLS (13,6 →
  4,2), STLFSI4 (12,5 → 2,8).
- **Veredicto: v5 se adopta.**
- El veredicto no depende de los casos límite. Con WALCL como empeora, la
  semanal pasa 4/5. Con DFEDTARU como empeora, la diaria pasa 3/5.
- **Trimestral: no evaluada.** El canónico 4 de v5 no tiene evidencia en
  esta medición.
- La implementación va en un PR aparte, como pide el paso 3.

## Variante C de Holt: no se adopta

Criterio pre-registrado en `0ba851a`. Por serie no estacional y en los dos
horizontes, en los cortes normales:
- arrepentimiento ≤ el de Holt + 2 pp;
- MASE ≤ 1,02 × el de Holt;
- distancia de la cobertura al 80% ≤ la de Holt + 2 pp;
- ninguna serie catastrófica.

| Categoría | No estacionales evaluables | Pasan | ¿Pasa? |
|---|---|---|---|
| Financiera diaria | 5 | 3 | sí |
| Semanal | 5 | 4 | sí |
| Mensual SA | 5 | **2** | **no** |
| Mensual NSA | 1 | 1 | no decide (< 3) |
| Trimestral | 0 | — | no decide |

Fallan:
- en mensual SA: HOUST (arrepentimiento y MASE a 30), INDPRO (arrepentimiento
  y MASE a 12; MASE a 30) y UNRATE (arrepentimiento y cobertura a 12;
  cobertura a 30);
- en la diaria: BAMLH0A0HYM2 y T10Y2Y;
- en la semanal: NFCI.

No hubo casos catastróficos. **Veredicto: C no se adopta**, porque falla en
mensual SA.

## Desvíos y decisiones que no estaban en el pre-registro (dichos explícitamente)

1. **Enmienda 1**, antes de los datos: se excluyen los indicadores binarios
   (USREC). Está en el pre-registro.
2. **`decide_robust` lanza `ZeroDivisionError`** cuando el error medio del
   motor base es exactamente 0: divide por él para un dato informativo
   (`rel_gap`).
   - Pasó en DFEDTARU a 30 pasos, en 30 de 400 decisiones. Es una tasa en
     escalones, y el pronóstico de Holt redondeado a 2 decimales es exacto
     en los tramos planos.
   - En producción `decide()` atrapa la excepción y la serie cae al camino
     por defecto (Holt). Acá se tomó igual: la decisión es el motor base.
   - **Es un bug de producción**; queda para un PR aparte.
3. **Arrepentimiento con error 0:** si el mejor motor tiene error 0 en los
   cutoffs evaluados y el elegido no, el error relativo es ilimitado.
   - Se toma la cota (100 pp), no 0 como hacía `holdout_regret` de 2.3c.
   - Es idéntico cuando el mejor error es mayor que 0 (test).
   - `holdout_regret` no se tocó, para que 2.3c siga siendo reproducible.
4. **Redondeo:** `FREDDataFetcher` redondea cada valor a 2 decimales, y así
   se usó (es lo que ve la app). En NFCI y STLFSI4, índices con movimientos
   de centésimas, eso limita la resolución y produce empates.

## Limitaciones

- 5 series por categoría y un solo snapshot. Las series se eligieron por
  popularidad en FRED, así que representan lo más usado, no toda la
  categoría.
- Las diarias tienen unos 2 años de datos (las 500 observaciones que baja
  la app). BAMLH0A0HYM2 en FRED empieza en 2023.
