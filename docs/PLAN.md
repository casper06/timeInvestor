# Plan de trabajo

Fases de trabajo pendientes sobre `main`. Cada ítem tiene su rama y su criterio
de "hecho". Un ítem se marca `[x]` cuando su criterio se cumple y el PR está
abierto; el número de PR se anota al lado. El merge a `main` lo hace quien
revisa.

Reglas (vienen del pedido que abrió este plan):
- No fabricar datos, versiones ni resultados. Lo que no se pudo verificar se
  escribe "no verificado", nunca un valor plausible.
- Una rama por feature y un PR antes de mergear a `main`.
- Correr la suite completa después de cualquier rebase.

El registro detallado de cada ronda (salida real de pytest, decisiones, qué quedó
sin verificar) va en `.bitacora/RONDAS.md`, que es local y no se versiona.

## Fase 0 — Higiene

Rama: `chore/fase-0-higiene`

- [x] **0.1 Test de Claude CLI independiente del binario.** (PR #14, mergeado)
  `test_claude_cli_no_tool_use_attempted` hoy llama a `shutil.which` real a
  través de `ClaudeCliLLMClient.__init__`.
  Hecho cuando: el test pasa con `shutil.which` devolviendo `None` para
  `claude`, y el arreglo está en el test (no en el código de producción).
- [x] **0.2 Fijar la versión de `timesfm`.** (PR #14, mergeado; fijado en `==3.0.2`) Antes
  `requirements-timesfm.txt` aceptaba `>=2.0.0,<4.0.0`.
  Hecho cuando: la versión instalada y la última de PyPI están verificadas
  (ambas exportan `TimesFM_2p5_200M_torch`), el pin elegido está justificado
  con fecha y método en un comentario, y los tests reales de TimesFM pasan con
  los pesos en caché.
- [x] **0.3 `CONTEXT.md` actualizado** (PR #18, mergeado)
  Notas: cuota de Claude CLI verificada el 2026-09-25 (re-leída el
  2026-09-26), TimesFM-3 existe y no fue evaluado, `timesfm` fijado en
  3.0.2, auto-discovery "no evaluado" y estado del repo.
  Hecho cuando: el archivo existe en la raíz, versionado, con esas notas.
- [x] **0.4 Test de fechas independiente del día de la semana.** (PR #17,
  mergeado)
  `test_cached_live_series_keeps_live_source` fallaba sábados y domingos: con
  pandas 3, `date_range(end=<fin de semana>, periods=100, freq="B")` devuelve
  99 fechas.
  Hecho cuando: los valores salen de `len(dates)` y el test cubre un sábado y
  un domingo fijos, además de "now".
- [x] **0.5 Alinear dependencias con lo que realmente corre.** (PR #19,
  mergeado)
  Decisión del dueño del repo: no volver atrás el entorno; se actualizan los
  rangos. `requirements.txt` sube fastapi (`>=0.136,<1`), uvicorn
  (`>=0.49,<1`), yfinance (`>=1.2,<2`) y pandas (`>=3.0,<4`), y el proyecto
  pasa a instalarse en `.venv/`.
  Resultado (2026-09-26):
  - suite en un `.venv` limpio: 120 passed;
  - smoke test con datos reales (`scripts/smoke_real_data.py`), rangos viejos
    vs. nuevos: mismas fechas, forecast y backtest (MASE y cobertura
    idénticos). Solo 4 cierres de SPY difieren en 1 centavo, y es ruido de
    Yahoo entre requests, no de las versiones;
  - `docker compose build` OK; en la imagen, `/api/health` responde.
  Hecho cuando: `requirements.txt` incluye lo que corre localmente y Docker
  instala las mismas versiones.

- [x] **0.6 Suite aislada de la DB real.** (PR #21, mergeado)
  `tests/test_database.py` corría `init_db()` y un CRUD contra
  `backend/database/time_investor.db`.
  Hecho cuando: la suite usa un SQLite temporal y el hash de la DB real no
  cambia tras correrla.

## Fase 1 — Auto-discovery: "no evaluado" ≠ "Holt ganó"

Rama: `fix/autodiscovery-not-evaluated`

- [x] **1.1 Distinguir la decisión tomada sin TimesFM.** (PR #15, mergeado) Hoy una serie evaluada
  con TimesFM no disponible queda como `engine_choice="holt"` por 30 días.
  Hecho cuando:
  - una decisión no evaluada se re-evalúa en cuanto TimesFM está disponible,
    sin esperar el TTL;
  - mientras no está disponible, no se re-corre el mini-backtest en cada
    request;
  - chequear la disponibilidad no carga los pesos en cada request;
  - una DB existente sigue funcionando sin migración (o la migración está
    testeada);
  - `engine_selection_reason` es coherente con este comportamiento;
  - hay tests para los tres casos (re-evaluación, sin re-corrida, TTL normal
    cuando Holt ganó de verdad).

## Fase 2 — Robustez de la decisión del selector

Rama: a definir.

- [x] **2.1 Detectar el fallback interno de TimesFM→Holt dentro de
  `BacktestEngine.run_backtest`.** (PR #20, mergeado; aviso en la UI en #22) Hoy `BacktestResponse` no lo expone, así que
  `mase_timesfm` podría ser en realidad de Holt, y eso es una métrica fabricada.
  Va primero: medir oscilaciones o fijar un margen sobre un `mase_timesfm` que
  puede no ser de TimesFM no tiene sentido.
  Hecho cuando: el mini-backtest descarta o marca los cutoffs donde TimesFM no
  corrió de verdad, con un test que lo demuestre.
- [x] **2.2 Medir cuánto oscilan hoy las decisiones** (PR #32, mergeado; resultado en `docs/results/decision_stability_2026-09-26.md`: en acciones y ETFs, una decisión de 3 cutoffs contradice a la de 24 en 34–41% de los casos y cambia 3–4 veces en 12 semanas) (3 cutoffs, gana TimesFM
  con MASE estrictamente menor, sin margen).
  Hecho cuando: hay una medición reproducible (script + resultado) de cuántas
  decisiones cambian entre corridas o ventanas cercanas.
  Requisito agregado: un mínimo de cutoffs en par (donde TimesFM realmente
  corrió, ver 2.1) para poder elegir TimesFM. Hoy, si TimesFM falla en 2 de 3
  cutoffs, la decisión sale de un solo cutoff.
- [x] **2.3 Decisión más robusta:** (PR #33, mergeado; criterio v4 en `docs/results/decision_variants_2026-09-26.md`: 8 cutoffs en ventana reciente, mayoría + margen 10%, ≥ 7 pares, empate → base, histéresis ×2, sin guard. Acciones/ETFs: 88% al motor base y 0 cambios; FRED estacional baja el desacuerdo, FRED SA no) 5–8 cutoffs, un margen (por ejemplo
  `MASE_tfm ≤ 0.95·MASE_holt` o Diebold-Mariano) y que un empate lo gane Holt.
  Hecho cuando: el umbral está elegido a partir de la medición de 2.2, no antes,
  y hay tests del margen y del empate.
  Además: el guard de calibración por cobertura (`MAX_ACCEPTABLE_COVERAGE_GAP_PP`)
  sobre 3 cutoffs no es confiable. 2.5 mostró que la cobertura por ventana va
  de 0% a 100%, con mediana 100%, así que 3 ventanas pueden dar cualquier
  cosa. La decisión tiene que usar muchos cutoffs o sacar la cobertura del
  criterio.

- [ ] **2.3b Horizonte del mini-backtest por frecuencia.** Medido
  (`docs/results/horizon_variants_2026-09-27.md`): **no se implementó**. Con
  12 meses desaparece la superposición (8 de 8 ventanas independientes, contra
  3 de 8 con 30), pero el desacuerdo en FRED SA sube de 18,5% a 34,2%; en
  diarias, 60 mejora ETFs (13,3% → 5,6%) y deja igual acciones. Bloqueado por
  4.14: sin horizonte en las unidades de la serie en la UI, no se puede
  evaluar "en el horizonte que se muestra". Re-medir después de 4.14 con
  `scripts/horizon_variants.py`.
  Re-medido en el horizonte canónico (4.14,
  `docs/results/horizon_units_2026-09-27.md`):
  - 12 meses reproduce #34 y empeora FRED SA (18,5% → 34,2%);
  - 6 meses mejora las dos categorías FRED en la muestra (estacional 19,0%, SA 8,9%);
  - 3 meses oscila en SA.
  **Decisión del usuario (2026-09-27): el canónico mensual es 12 meses.** Es el
  horizonte de uso (ciclo estacional completo, comparación interanual); no
  se elige por cuál da menos desacuerdo. Si v5 decide en él se resuelve con
  2.3c.
- [ ] **2.3c Arrepentimiento como métrica.** Medido
  (`docs/results/decision_regret_2026-09-27.md`, PR #36, mergeado): **v5 no se implementó**.
  - Métrica: error relativo extra del motor elegido frente al mejor, en los
    cutoffs de la grilla que no se usaron para decidir.
  - Criterio pre-registrado (media ≤ v4 + 2 pp y p90 ≤ v4 + 5 pp): lo
    cumplen FRED estacional, Acciones y ETFs; **falla FRED SA**, con p90 de
    137,4 contra el límite de 104,3.
  - La media de SA a 30 está dominada por una explosión de Holt en UNRATE
    (2020-04, ver 2.6), y serie por serie las dos SA mejoran a 12. Un
    criterio nuevo tendría que fijarse ahora y validarse con otro snapshot.
  - UNRATE a 12 no es un empate: depende del régimen (Holt 10 / TimesFM 14
    cutoffs; medianas 1,43 y 1,51; solo 4 de 24 cutoffs dentro de ±10%).

  **v5 queda en v4 por ahora.** Criterio para re-evaluarla, PRE-REGISTRADO el
  2026-09-27 11:41, antes de que exista el snapshot de 3.5. Se evalúa SOLO con las
  series nuevas de 3.5, nunca con `holt_coverage_2026-09-26.json`.
  - **Qué se compara.** v4 (30 pasos en todas las frecuencias) contra v5
    (canónico de cada frecuencia: diaria 60, semanal 13, mensual 12,
    trimestral 4). La regla es la misma (`decide_robust`).
  - **Protocolo.** El de `scripts/horizon_variants.py`: grilla de 24
    cutoffs, 400 subconjuntos de 8 con la semilla `"{sid}-2.3b-{h}"`, y el
    arrepentimiento en los cutoffs no usados para decidir.
  - **Por serie, no agregado.** Para cada serie s y cada versión, A_s es la
    media de sus 400 arrepentimientos acotados.
  - **Cota del arrepentimiento: 100 pp por decisión**, es decir min(r, 1,0).
    100 pp significa que el motor elegido tuvo el doble de error que el
    mejor. Para decidir, eso ya es un fracaso total: pasado ese punto no hay
    diferencia que importe, y una sola corrida que explota (UNRATE 2020-04,
    2.6) no puede dominar la media. Se prefiere a winsorizar al p99 porque
    esa cota dependería de los mismos datos que se miden y de cuántas
    decisiones tenga cada serie. Se prefiere a limitar el MASE porque su
    escala cambia con el horizonte (lo normal a 30 meses es 10-25), así que
    una cota fija recortaría valores normales en un horizonte y no en otro.
  - **Mejora o empate** de una serie: A_s(v5) ≤ A_s(v4) + 2 pp. Los 2 pp son
    el orden del ruido de semilla visto en 2.3b.
  - **Empeora de forma catastrófica:** A_s(v5) − A_s(v4) > 25 pp. En
    promedio, la decisión le costaría a esa serie un cuarto de error más que
    con v4 (un cuarto de "fracaso total"). Es más que la diferencia típica
    entre TimesFM y Holt (10-30%), así que no puede ser ruido ni un empate
    mal resuelto.
  - **Regla de adopción.** v5 se adopta si, en CADA categoría con ≥ 3
    series, mejora o empata en la mayoría estricta de sus series (más de la
    mitad) y ninguna serie de ninguna categoría empeora de forma
    catastrófica. Una categoría con < 3 series se reporta pero no decide.
    Si no hay ninguna categoría con ≥ 3 series, v5 no se adopta.
  - **Qué se reporta.** Por serie: A_s(v4), A_s(v5), la diferencia y el
    veredicto. Por categoría: el conteo. Todo tal como salga.
- [x] **2.10 MASE no definido.** (rama `fix/undefined-mase-and-v5-checks`, PR
  abierto; ADR-0020)
  - MASE, MASE estacional y MAPE ya no usan `+1e-8`: con escala 0 son
    `None`, con el motivo en `BacktestMetrics.undefined`.
  - La decisión usa MAE en pares si el MASE no está definido en algún
    cutoff (criterio v6). La UI muestra "no definido".
  - DFEDTARU: MAE, Holt (igual que en #41); ya no aparece 2,5 millones.
  - También en esta rama: el motivo "Historia insuficiente para evaluar (N
    de M puntos): se usa Holt por defecto", con M =
    `min_history_for_decision` (diaria 186).
  - Latencia de v5 medida: primer pedido de 1,1 a 2,1 s, menos de 10 s.
  - **Relevamiento del `+1e-8`:**
    - backend: MASE, MASE estacional y MAPE, corregidos; sMAPE y los
      porcentajes del veredicto se dejaron, porque ahí no puede aparecer un
      0 en el denominador;
    - scripts con piso de escala 1e-8: `benchmark_real_data.py:88` y
      `download_and_benchmark_timesfm.py:234`;
    - `seasonal_benchmark.py:168` divide sin protección.
  - **Resultados versionados afectados** (no re-corridos):
    - solo 3.5, en los números de v5 y C de DFEDTARU; los veredictos no
      cambian;
    - los snapshots de 2.2–2.6 y 3.0d no tienen escalas nulas ni valores en
      0;
    - el `--replay` de 3.5 exacto requiere el commit `5ee140d`: los
      scripts de medición todavía no toleran MASE `None`.
- [x] **2.11 Los motores redondean sus pronósticos a 2 decimales.** (rama
  `fix/no-rounding-in-engines`, PR #46, mergeado; ADR-0022)
  - Motores y backtest (pronóstico, bandas y métricas) con precisión
    completa; el redondeo es solo de presentación.
  - Criterio v8: con los datos precisos, NFCI da vuelta un cutoff (6-2 →
    5-3); ninguna de las 8 series medidas cambia de motor.
  - Detalle original: `forecast_engine.py` hace `round(pred_val, 2)` en los
  valores y las bandas, y el backtest calcula las métricas sobre esos
  pronósticos redondeados. En series de magnitud chica (NFCI ≈ −0,5,
  T10Y2Y) eso es comparable al error. Visto en 2.9.
  Hecho cuando: los motores devuelven la precisión completa y la UI y los
  snapshots redondean al mostrar; se mide el efecto como en 2.9.
- [x] **2.9 Redondeo en la carga de datos.** (rama `fix/no-rounding-on-load`,
  PR #45, mergeado; ADR-0021)
  - `data_fetcher.py` ya no redondea (las 6 líneas). La UI ya formatea al
    mostrar; el prompt formatea el último precio con 4 decimales.
  - Caché de datos: solo en memoria, se vacía al reiniciar; no necesita
    invalidación.
  - Decisiones: criterio v7 para re-evaluarlas con los datos precisos.
  - Impacto, medido con gemelos precisos de los snapshots (mismas fechas):
    2.5, 3.0d y 3.5 no cambian ningún veredicto. En 3.5, NFCI pasa a
    "empeora" en v5 y la semanal sigue 4/5.
  - La afirmación de 3.5 sobre empates en NFCI y STLFSI4 era una
    inferencia: hubo 0 empates. Quedó corregida. `data_fetcher.py` redondea a 2
  decimales al cargar (líneas 91, 174, 196, 236, 342 y 456, la última en la
  serie sintética). En índices como NFCI o STLFSI4 eso descarta información
  antes de los motores y genera empates artificiales (visto en 3.5).
  - Los datos se guardan y se procesan con la precisión de la fuente; se
    redondea solo al mostrarlos.
  - Hay que evaluar el impacto en la caché existente y en los resultados
    versionados (probablemente los cambia) y documentar cuáles cambian.
  Hecho cuando: el fetcher conserva la precisión de la fuente, la UI
  redondea al mostrar, hay tests, y hay una lista de los resultados
  versionados afectados (re-corridos o marcados).
- [x] **2.4 Lockfile de dependencias.** (PR #24, mergeado: `uv pip compile --universal`; `requirements-timesfm.txt` fuera del lock, instalado con `-c requirements.lock`) Los rangos de #19 permiten versiones que
  el smoke test no probó: un venv limpio instala pandas 3.0.6, yfinance 1.7.0 y
  fastapi 0.141, contra las verificadas 3.0.1, 1.2 y 0.136. Evaluar
  `pip-compile` (o equivalente), o un `requirements.lock` con las versiones
  verificadas.
  Hecho cuando: hay un archivo de versiones exactas que Docker y `.venv` usan,
  y cada actualización del lock pasa por la suite y `scripts/smoke_real_data.py`.
- [x] **2.5 Cobertura del cono de Holt sobre datos reales.** (PR #25, mergeado; resultado en `docs/results/holt_coverage_2026-09-26.json`) El smoke test dio
  SPY 43,3% en una sola ventana, contra ~96% validado sobre datos simulados.
  Una ventana sola no prueba nada.
  Hecho cuando: hay una medición de cobertura empírica con muchos cutoffs sobre
  acciones, ETFs y series FRED, reproducible (script + resultado), antes de
  sacar conclusiones sobre la calibración.
  Resultado (2026-09-26, 24 cutoffs × 14 series, `scripts/holt_coverage_real.py`):
  - la cobertura agregada NO está por debajo de la nominal en acciones y ETFs
    (97,3% y 97,6% contra 95%): el intervalo es más ancho de lo que debería
    (std del error estandarizado 0,72–0,81);
  - la ventana mediana cubre 100%, y los fallos se concentran en pocos
    episodios (SPY/QQQ/XLK en el cutoff 2026-04-02; UNRATE e INDPRO en 2009 y
    2020, con 0%);
  - el 43,3% de SPY del smoke test fue una de esas ventanas malas;
  - pendiente la decisión del dueño del repo antes de proponer cambios al
    intervalo.
  Decisión explícita: el sesgo positivo (el precio real terminó por encima del
  centro, cada vez más con el horizonte) **NO se corrige**. Sale de una muestra
  de ~5 años mayormente alcista, y agregar drift sería ajustarse a ese régimen.
- [ ] **2.6 Holt explota tras un salto de nivel.** (PR #37, mergeado; la
  marca está hecha y la estimación robusta queda pendiente;
  `docs/results/holt_explosion_2026-09-27.md`)
  - Diagnóstico: cuando el último dato es el salto, el ajuste SSE lleva α y β
    a ~0,99 y 0,89, y el salto pasa a la tendencia. UNRATE ≤ 2020-04 da
    20.860% a 12 meses; INDPRO ≤ 2020-04, −40%; HOUSTNSA ≤ 1988-04, ×2,8.
  - En producción llegaba sin aviso: Holt por plan B sin TimesFM, o elegido
    por auto-discovery (INDPRO).
  - **Hecho:** marca "no confiable" (X > 2) para cualquier motor, sin tocar
    los números. 0 falsos positivos en 2.358 corridas normales, y marca las 6
    explosiones conocidas.
  - **Pendiente de decisión:** la estimación robusta.
    - A (recorte en nivel y tendencia): descartada.
    - C (recorte solo en la tendencia): MASE igual o mejor en todo y menor
      arrepentimiento en SA, pero falla la cláusula de cobertura en FRED SA
      (+3,5 / +5,5 pp, con 2 series). Medirla con las series de 3.5.
  **Criterio para adoptar C, PRE-REGISTRADO el 2026-09-27 12:13**, antes de que exista
  el snapshot de 3.5. Se evalúa SOLO con las series nuevas de 3.5, nunca con
  `holt_coverage_2026-09-26.json`.
  - **Qué se compara.** El Holt actual contra C (`make_robust_holt("trend")`,
    k = 2) como motor base, en las series donde el base es Holt (no
    estacionales). En las estacionales el base es Holt-Winters: C no aplica.
  - **Horizontes.** El canónico de cada frecuencia y el del criterio vigente
    del auto-discovery (30 mientras siga v4). Hay que cumplir en los dos.
  - **Protocolo.** El de 2.3c: grilla de 24, 400 subconjuntos de 8 con la
    semilla `"{sid}-2.3b-{h}"`, y el arrepentimiento acotado a 100 pp en
    los cutoffs no usados. Cortes "normales" y "de salto" como en 2.6
    (último paso > 4 σ robustos).
  - **Por serie**, en los cortes normales:
    - arrepentimiento: C empata o mejora si A_s(C) ≤ A_s(actual) + 2 pp;
    - error: MASE(C) ≤ 1,02 × MASE(actual);
    - cobertura, medida como distancia al nominal:
      |cob(C) − 80| ≤ |cob(actual) − 80| + 2 pp.
  - **Cambio respecto de 2.6, dicho explícitamente:** la cobertura pasa de
    "±2 pp respecto de la actual" a "distancia al nominal", porque acercarse
    al 80% no es empeorar. Se escribió después de ver el resultado de 2.6,
    pero sobre ese snapshot C **seguiría fallando** en FRED SA: a 12, 9,6 pp
    contra el límite de 8,1; a 30, 5,6 contra 2,1. No está hecho a la medida
    del resultado.
  - **Empeora de forma catastrófica:** A_s(C) − A_s(actual) > 25 pp, o C
    marca "no confiable" (X > 2) en algún corte normal donde el Holt actual
    no marca.
  - **Regla de adopción.** C reemplaza a Holt si, en cada categoría con ≥ 3
    series no estacionales, la mayoría estricta cumple las tres condiciones
    por serie, en los dos horizontes, y ninguna serie empeora de forma
    catastrófica. Una categoría con < 3 series se reporta pero no decide; si
    no hay ninguna con ≥ 3, C no se adopta.
- [x] **2.7 El Reality Check de series FRED fuera del catálogo devuelve 400.**
  **Primero en el orden (2026-09-27): bloquea el uso normal.**
  (rama `fix/backtest-fred-routing`, PR #39, mergeado)
  - `BacktestRequest.series_type` (`macro` | `equity`, como en `/forecast`),
    y la ruta lo pasa como `is_macro`. El panel manda `seriesData.type`.
  - Sin tipo, el comportamiento no cambia (solo el catálogo va a FRED),
    pero el 400 dice que hay que mandar `series_type='macro'`.
  - Verificado sobre una copia de la DB: UNRATE daba 400 y ahora da 200
    (mensual, 12 evaluados); INDPRO, IPG2211A2N y NVDA dan lo mismo que antes.
  - La correlación tiene el mismo ruteo por catálogo; queda en 4.11.
  `/api/backtest` no recibe `is_macro`, y `BacktestEngine` busca en yfinance
  cualquier serie que no esté en `FREDDataFetcher.SERIES_CATALOG` (UNRATE,
  verificado en 2.6).
  Hecho cuando: la ruta sabe si la serie es de FRED (tipo en el request, o
  el catálogo de la tesis) y hay un test.

## Fase 3 — Experimento TimesFM-3

Rama: a definir.

Contexto: checkpoint `google/timesfm-3.0-pytorch`, 330M parámetros, covariables
de pasado y pasado-futuro; pesos con licencia **no comercial** (verificado el
2026-09-26, ver `CONTEXT.md`). La fecha de lanzamiento del 31/08/2026 no está
verificada.

**3.0 Prerrequisito: comparación justa en series estacionales.** Hoy
  nada en el sistema es estacional: Holt no tiene componente estacional, el
  único benchmark es el random walk (`run_naive_rw_at_cutoff`), y el MASE se
  escala contra el naive de 1 paso (`mean(|diff(y_train)|)`, en
  `backtest_engine.py` y en `benchmark_real_data.py`). El hallazgo "TimesFM
  gana en FRED estacionales", que justifica `SEASONAL_FRED_CATALOG`, se midió
  solo contra rivales que ignoran la estacionalidad.
  - Naive estacional (m=12 para mensuales) como benchmark obligatorio, al lado
    del random walk.
  - MASE escalado estacionalmente (escala = MAE in-sample del naive de lag m)
    para esas series.
  - Holt-Winters (ETS con componente estacional) como rival clásico. Evaluar
    implementación propia vs. librería (por ejemplo, `statsmodels`) y justificar
    la elección: peso de la dependencia, calidad del ajuste MLE e intervalos.
  - Re-correr el benchmark de las 4 series del catálogo (IPG2211A2N, RSAFSNA,
    HOUSTNSA, MRTSSM4451USN). Si TimesFM no le gana al naive estacional o a
    Holt-Winters, se documenta tal cual y se revisa el catálogo.
  - Holt-Winters como plan B cuando TimesFM no está disponible, en vez de caer
    a un Holt que no ve la estacionalidad.
  - Prophet (Meta) como rival, solo en el benchmark de series estacionales,
    no en producción.
    - Estado verificado el 2026-09-26 en `facebook/prophet`: el README dice
      "Prophet is in maintenance mode as of v1.4.0. Only bug fixes, dependency
      bumps, and changes to the R package to meet parity with Python will be
      accepted. No new features are planned." Última release v1.4.0-patched
      (2026-08-15), repo no archivado, MIT. En PyPI la última es 1.4.0, con
      wheel `py3-none-win_amd64` (bajado sin instalar). Que funcione en
      Python 3.14: no verificado.
    - Si se usa, va en un archivo de dependencias opcional aparte (como
      `requirements-timesfm.txt`), porque depende de cmdstan y es pesado.
    - Criterio: entra al selector solo si le gana al naive estacional y a
      Holt-Winters en alguna categoría. Si no, se documenta tal cual.
    - Sus regresores externos son una opción para la Fase 3 (covariables
      FRED), comparable con TimesFM-3 (3.2).
  Hecho cuando: el benchmark reporta, por serie, MASE estacional de TimesFM,
  Holt, Holt-Winters, Prophet, naive estacional y random walk, y el catálogo
  quedó confirmado o corregido según esos números.
  Se parte en cuatro sub-ítems, un PR cada uno:
  - [x] **3.0a Naive estacional + MASE estacional** en el backtest (PR #26,
    mergeado). El MASE de 1 paso se mantiene; el estacional
    va en un campo aparte.
  - [x] **3.0b Holt-Winters** como motor (PR #27, mergeado):
    `ETSModel` de statsmodels, ETS(A,Ad,A) en log, MLE, intervalos analíticos.
    Disponible con `engine: "holt_winters"` en /forecast y /backtest; no está en
    el selector. Cobertura sobre las FRED estacionales:
    `docs/results/hw_vs_holt_coverage_2026-09-26.json`.
  - [x] **3.0c + 3.0d (una sola ronda, PR #28, mergeado):** veredicto en `docs/results/seasonal_benchmark_2026-09-26.md`.
    - TimesFM tiene el menor error en las 4 series y le gana a HW de forma
      significativa en 3 (IPG2211A2N, RSAFSNA frágil, HOUSTNSA); en
      MRTSSM4451USN, HW.
    - Holt (el plan B actual) pierde incluso contra el naive estacional.
    - Prophet no entra al selector.
  - [x] **3.0e Arreglar la banda de TimesFM (prerrequisito del selector).**
    (PR #29, mergeado)
    `TimesFMForecastEngine` usa la columna 0 de los cuantiles (la media) como
    límite inferior. La banda real es columnas 1 (p10) y 9 (p90). La app
    muestra [media, p90]: cubre 36–62%, contra 84–92% de la p10–p90 real.
    Después, re-evaluar las decisiones de auto-discovery que TimesFM perdió
    "por calibración" (CEG y NVDA en la DB local).
  - [x] **3.0f Aplicar el veredicto al selector** (`SEASONAL_FRED_CATALOG` y
    Holt-Winters como plan B) (PR #30, mergeado).
    - Catálogo con entradas por serie (motor, solidez, evidencia y
      referencia): IPG2211A2N TimesFM (firme), HOUSTNSA TimesFM (probable),
      RSAFSNA TimesFM (probable, frágil), MRTSSM4451USN Holt-Winters.
    - Plan B estacional = Holt-Winters.
    - Auto-discovery compara TimesFM contra Holt-Winters con el MASE
      estacional en series estacionales (criterio v3).
    - Con corrección de Bonferroni (4 series, α = 0,05/4 = 0,0125), la única
      victoria firme de TimesFM sobre Holt-Winters es IPG2211A2N (p=0,002).
      HOUSTNSA y RSAFSNA (p=0,023) son probables, no firmes.
    - El cambio de plan B (Holt → Holt-Winters) se justifica aparte e
      independientemente de lo anterior: Holt pierde incluso contra el naive
      estacional en las 4 series.
    - Limitación: posible contaminación por pre-entrenamiento. Las series FRED
      son públicas y sus ventanas de evaluación (1995–2025) podrían estar en
      el corpus de TimesFM, lo que lo favorecería. No verificado.

- [ ] **3.1 Univariado** contra TimesFM 2.5 y contra Holt, en el mismo arnés
  walk-forward.
- [ ] **3.2 Con covariables:** las series FRED de la tesis como covariables de
  pasado. Comparar con los regresores externos de Prophet (ver 3.0).
- [ ] **3.3 Latencia en CPU.**
- [x] **3.4 Revisiones de datos (vintages de ALFRED).** Los backtests sobre FRED
  usan la serie *revisada de hoy*: en cada cutoff el modelo ve valores que en
  esa fecha todavía no existían. Eso puede inflar la capacidad de pronóstico
  medida (auto-discovery, benchmarks de 2.5 y 3.0d). Las revisiones de las
  series del catálogo existen y no son chicas (consultado el 2026-09-26 con la
  API):
  - HOUSTNSA, enero 2019: primera publicación 82,6 → hoy 87,0 (+5,3%, 3
    versiones);
  - IPG2211A2N, enero 2019: 121,43 → 120,05 (−1,1%, 11 versiones en 6 años);
    enero 2016 tiene 15 versiones.

  Acceso verificado (documentación de `fred/series/observations` y
  `fred/series/vintagedates`, más llamadas reales):
  - `fred/series/vintagedates?series_id=…` devuelve las fechas en que la serie
    se revisó o publicó (hasta 10.000 por llamada);
  - `fred/series/observations` con `vintage_dates=AAAA-MM-DD` devuelve la serie
    tal como se veía ese día (hasta 2000 vintages por pedido en json);
  - `output_type=4` devuelve solo la primera publicación y `output_type=1`
    todas las versiones por período. **Hace falta pasar
    `realtime_start=1776-07-04&realtime_end=9999-12-31`**: con los valores
    por defecto (hoy) la API responde 400, "No vintage dates exist for the
    specified real-time period".

  Limitación: el historial de vintages empieza tarde.
  - IPG2211A2N: 2015-02; RSAFSNA: 2001-06; HOUSTNSA: 2011-03;
    MRTSSM4451USN: 2017-11.
  - Los cutoffs de 3.0d arrancan en 1995, así que un backtest
    point-in-time solo cubre los posteriores (en IPG2211A2N, ~10 años).

  Hecho cuando: el benchmark de 3.0d se re-corre con vintages en los cutoffs
  donde existen. Se reporta, por serie, cuánto cambia el MASE estacional y si
  cambia algún veredicto del catálogo.

  **Medición PRE-REGISTRADA el 2026-09-28**, en commit propio, antes de
  descargar ningún vintage (rama `feat/vintage-benchmark`). Solo mide: no
  cambia criterios ni catálogos.
  - **Series:**
    - las 4 del catálogo estacional (IPG2211A2N, HOUSTNSA, RSAFSNA,
      MRTSSM4451USN) y las 5 mensuales SA de 3.5 (HOUST, INDPRO, JTSJOL,
      PSAVERT, UNRATE);
    - entra solo la que tenga historia de vintages suficiente: primera fecha
      de `fred/series/vintagedates` ≤ 2016-12-31, para que la ventana de
      cutoffs cubra al menos 8 años. Las demás se reportan como excluidas,
      con su primera fecha.
  - **Cutoffs:** 24 fechas mensuales equiespaciadas entre el primer mes
    posterior a la primera fecha de vintage y la última observación actual
    menos 12 meses.
  - **Horizonte:** 12 meses (el canónico mensual).
  - **Dos versiones de los datos de entrenamiento en cada cutoff `c`:**
    - **de época:** la serie como se publicó el día `c`
      (`fred/series/observations?vintage_dates=c`), con su última
      observación `t`;
    - **revisada:** la serie actual cortada en esa misma `t`. Así las dos ven
      el mismo período y difieren solo en las revisiones.
  - **Dos verdades para los 12 meses siguientes a `t`:**
    - el valor de la **primera publicación** (`output_type=4`);
    - el **revisado** actual.
  - **Métrica:** la capacidad de pronóstico de 3.5 (`capability()` de
    `scripts/fred_category_benchmark.py`), en cada una de las 4
    combinaciones (datos × verdad):
    - motores Holt, Holt-Winters (si la serie es estacional según 3.0a sobre
      los datos revisados completos) y TimesFM real (si cae a Holt, se
      frena, como en 3.5);
    - naive de referencia: el más exigente de los dos (menor error total),
      calculado con los mismos datos de entrenamiento;
    - un motor "le gana" si el test de signo da p < 0,05/k (k = motores) y
      el skill (1 − ΣMAE motor / ΣMAE naive) es > 0;
    - la serie "tiene capacidad" si algún motor le gana.
  - **Qué contaría como "la conclusión no se sostiene"**, por serie:
    - la serie tiene capacidad con datos revisados y verdad revisada (lo que
      miden hoy los benchmarks) y **no** la tiene con datos de época y verdad
      de primera publicación (lo que se habría podido saber en tiempo real);
    - el caso contrario (sin capacidad → con capacidad) se reporta aparte;
    - por motor se reporta además el cambio de skill entre las dos
      condiciones;
    - las combinaciones cruzadas (datos de época con verdad revisada, y al
      revés) se reportan para separar el efecto del entrenamiento del efecto
      de la verdad.
  - **Snapshot:** todo lo bajado queda en `data/snapshots/vintages_<fecha>.json`
    con su sha256, y la medición se re-corre desde ahí.
  - **Límite de la API de FRED:** 120 pedidos por minuto. Unos 27 pedidos
    por serie, espaciados.

  **Resultado (2026-09-28)** (rama `feat/vintage-benchmark`, PR #56,
  mergeado; `docs/results/vintage_benchmark_2026-09-28.md`):
  - **Se sostienen:** HOUSTNSA, IPG2211A2N y RSAFSNA (el catálogo estacional).
  - **No se sostienen:** HOUST, INDPRO y JTSJOL. Su capacidad con datos
    revisados era de TimesFM; en INDPRO el skill cae de +0,42 a +0,08.
  - **Sin capacidad en ninguna:** PSAVERT y UNRATE.
  - **Excluida:** MRTSSM4451USN.
  - **Límites:** cambios de base y de definición (INDPRO, PSAVERT) hacen
    ininterpretables las combinaciones cruzadas; las ventanas de HOUST,
    INDPRO y UNRATE mezclan décadas.
  - No se cambió ningún criterio ni catálogo.

  **Lectura (2026-09-28):** la capacidad del catálogo estacional (NSA) se
  sostiene con datos de época. En las tres mensuales SA que tenían capacidad
  con datos revisados (HOUST, INDPRO, JTSJOL), no.

  **Propuesta, sin implementar: reflejarlo en el badge de 4.13** para series
  SA revisables:
  - Hoy el badge mide siempre con la serie revisada de hoy (la decisión de
    auto-discovery), sin decirlo.
  - Propuesta: cuando el badge dice "aporta" y la serie es SA (metadato
    `seasonal_adjustment_short` de FRED, 4.3), agregar una nota bajo el
    veredicto. Tiene dos variantes:
    - si 3.4 midió la serie y no se sostuvo: "capacidad medida con datos
      revisados; con datos de época no se sostuvo" (hoy: HOUST, INDPRO,
      JTSJOL), con enlace al resultado;
    - si 3.4 no la midió: "capacidad medida con datos revisados; no
      verificada con datos de época".
  - Las NSA del catálogo que se sostuvieron no llevan nota. "No aporta" y
    "no evaluado" tampoco, porque las revisiones no pueden empeorar un
    veredicto que ya es negativo.
  - La lista de series medidas saldría de un snapshot versionado (como
    `CATALOG_RW_EVIDENCE` en 4.17), no de una lista escrita a mano en el
    componente.
  - No cambia el criterio del badge: es una nota de procedencia. Antes de
    implementarla hay que decidir si "no verificada" se muestra en todas
    las SA o solo en las que tienen revisiones grandes.

  **Pendiente de pre-registro: re-medir desde 2000 las series cuyos cutoffs
  mezclan épocas.**
  - En HOUST, INDPRO y UNRATE los 24 cutoffs van de 1927/1960 a 2025. Mezclan
    décadas con otra metodología, y en INDPRO y PSAVERT hay cambios de base
    de 58% y 130%.
  - La re-medición usaría las mismas reglas de 3.4, con la ventana de cutoffs
    arrancando en 2000-01 para todas las series con vintages anteriores a
    esa fecha.
  - Antes de descargar nada hay que escribir en su propio commit: la regla
    de ventana, qué contaría como "cambia la lectura" y qué se hace con
    PSAVERT si el cambio de definición cae dentro de la ventana.
  - No se corre hasta que se pre-registre.

- [x] **3.5 Capacidad de pronóstico por categoría de FRED.** (rama
  `feat/fred-category-benchmark`, PR #40, mergeado;
  `docs/results/fred_category_benchmark_2026-09-27.md`)
  - Tiene capacidad solo la mensual NSA (3/5). Mensual SA 1/5, trimestral
    2/5, semanal 2/5, financiera diaria 0/5.
  - La hipótesis de las financieras diarias **se sostiene**.
  - **v5 se adopta** según su criterio: pasa las 4 categorías evaluables,
    sin casos catastróficos. La trimestral no es evaluable.
  - **C no se adopta**: falla mensual SA, 2/5. Benchmark de los
  motores contra el naive que corresponda a cada serie (random walk, o
  estacional si el detector de 3.0a la marca así), en estas categorías:
  - economía real mensual NSA;
  - economía real mensual SA;
  - trimestral;
  - semanal;
  - financiera diaria (tasas, spreads).

  Hipótesis a testear, no a asumir: las financieras diarias se comportan
  como un random walk (ningún motor le gana al naive).
  Hecho cuando: por categoría, varias series representativas, cutoffs
  pareados y test de signo contra el naive (mismo arnés que 3.0d), con el
  resultado en `docs/results/`, incluido "ningún motor le gana al naive"
  donde pase.
  Incluye re-evaluar v5 con el criterio pre-registrado en 2.3c, sobre las
  series nuevas de este ítem.

  **PRE-REGISTRO de 3.5 (2026-09-27, antes de descargar ninguna observación).**
  Todo lo que sigue queda fijo antes del snapshot. Los resultados se reportan
  contra esto tal cual.

  - **Categorías:**
    - mensual de economía real NSA;
    - mensual de economía real SA;
    - trimestral;
    - semanal;
    - financiera diaria (tasas, spreads, volatilidad).
  - **Regla de selección** (`scripts/fred_category_select.py`; usa solo
    metadatos de FRED, sin observaciones). Para cada categoría se recorre la
    lista de FRED ordenada por `popularity` descendente (al momento de la
    consulta) para las etiquetas de la categoría (frecuencia + `usa` +
    `nation`, excluyendo `discontinued`). Se toma cada serie que pasa todos
    los filtros, hasta 5:
    - **activa**: última observación desde 2026-09-01 (diarias y semanales),
      2026-06-01 (mensuales) o 2026-01-01 (trimestrales);
    - **historia**: primera observación hasta 2024-09-01 (diarias),
      2016-09-01 (semanales), 2006-09-01 (mensuales) o 1986-09-01
      (trimestrales);
    - **tema**, con el árbol de categorías de FRED:
      - mensuales de economía real: alguna categoría de la serie cuelga de
        las raíces *Production & Business Activity* (1), *Population,
        Employment, & Labor Markets* (10) o *National Accounts* (32992), y
        ninguna de *Prices* (32455) ni de *Money, Banking, & Finance*
        (32991);
      - trimestral y semanal: cualquier tema nacional (alguna categoría en
        las raíces 1, 10, 32992, 32455 o 32991);
      - financiera diaria: alguna categoría en la raíz 32991 y alguna de las
        etiquetas `interest rate`, `spread` o `volatility`;
    - **a lo sumo una serie por release de FRED** dentro de la categoría;
    - **enmienda 1** (misma fecha, al ver la lista y antes de descargar
      datos): se excluyen los indicadores binarios (unidades de FRED
      "+1 or 0"), porque MASE y skill no aplican a una variable 0/1. La
      primera corrida de la regla había elegido USREC en mensual NSA.

    Las series del snapshot de 2.5 (HOUSTNSA, INDPRO, IPG2211A2N, UNRATE,
    RSAFSNA) entran solo si la regla las elige, y se marcan "ya vistas".
  - **Datos:** `FREDDataFetcher().get_series(id)` sin cambios (las 500
    observaciones más recientes: lo mismo que ve la app). El snapshot se
    guarda en `data/snapshots/` con sha256 y se reproduce con `--replay`.
  - **Horizonte canónico** (4.14): diaria 60, semanal 13, mensual 12,
    trimestral 4. Los cutoffs son la grilla de 24 de `recent_cutoff_indices`
    dentro de la ventana de v4 (`RECENT_WINDOW`).
  - **Motores:** Holt, Holt-Winters (solo en las series que el detector de
    3.0a marca estacionales sobre la serie completa) y TimesFM con pesos
    reales, todos al 80%. **Si TimesFM no carga o cae a Holt en algún
    cutoff, la corrida se aborta y se avisa.**
  - **Naives:** random walk (último valor) para todas las series; además,
    naive estacional (m = 12 mensual, 4 trimestral) en las estacionales. El
    **naive de referencia** de una serie es el random walk o, en las
    estacionales, el que tenga menor MAE medio en la grilla (el más difícil
    de los dos).
  - **Métricas por serie y motor m**, en los 24 cutoffs:
    - MAE de m y del naive de referencia en los H puntos de cada cutoff;
    - MASE contra el naive = Σ MAE_m / Σ MAE_naive;
    - skill = 1 − MASE contra el naive (se reporta también contra el random
      walk y, en estacionales, contra el naive estacional);
    - cobertura del intervalo contra el nivel nominal que declara cada
      motor (80%).
  - **Test y criterio de "hay capacidad de pronóstico":**
    - por serie y motor: test de signo en pares, unilateral (binomial
      exacto; los empates no cuentan), sobre los 24 cutoffs: el motor tiene
      menor MAE que el naive de referencia;
    - m **le gana al naive** en la serie si p < 0,05 / k y skill > 0, con k
      el número de motores evaluados en esa serie (2, o 3 si es
      estacional): corrección de Bonferroni por serie;
    - una **serie tiene capacidad** si algún motor le gana al naive;
    - una **categoría tiene capacidad** si la tienen al menos 3 de sus 5
      series;
    - como sensibilidad, no decisiva, se reporta Holm sobre todos los pares
      (serie, motor) de cada categoría.
  - **Hipótesis "las financieras diarias no le ganan al random walk":**
    - se sostiene si 0 o 1 de las 5 series tiene capacidad;
    - se refuta si la tienen 3 o más;
    - es no concluyente con 2.
  - **v5 y variante C:** se evalúan con los criterios ya commiteados
    (`db4fcdb` y `0ba851a`), que no se tocan. Aplicación operativa, fijada
    ahora:
    - "categoría" = las 5 de arriba;
    - una serie donde la grilla de algún horizonte del criterio (30 o el
      canónico) no llega a 24 cutoffs distintos queda **no evaluable** para
      ese criterio y no cuenta (por ejemplo, las trimestrales a 30: la
      ventana de 40 trimestres solo deja 10 cutoffs);
    - en C, "en los cortes normales" se aplica al arrepentimiento
      restringiendo los cutoffs no usados a los normales, y al MASE y la
      cobertura promediando solo los cortes normales.

  **Series elegidas por la regla** (consulta del 2026-09-27 15:28; detalle y
  rechazos en `docs/results/fred_category_selection_2026-09-27.json`):

  | Categoría | Series (★ = ya vista en 2.5) |
  |---|---|
  | Mensual NSA (economía real) | `MTSDS133FMS`, `POPTHM`, `MSPNHSUS`, `UNRATENSA`, `IMPCH` |
  | Mensual SA (economía real) | ★ `UNRATE`, `PSAVERT`, ★ `INDPRO`, `HOUST`, `JTSJOL` |
  | Trimestral | `GDP`, `GFDEBTN`, `MSPUS`, `GFDEGDQ188S`, `M2V` |
  | Semanal | `MORTGAGE30US`, `WALCL`, `NFCI`, `STLFSI4`, `ICSA` |
  | Financiera diaria | `BAMLH0A0HYM2`, `DGS10`, `T10Y2Y`, `VIXCLS`, `DFEDTARU` |

  UNRATENSA es la versión NSA de UNRATE (ya vista): otro ID, la misma variable.

Hecho cuando: los tres resultados están documentados tal como salieron,
incluso si la hipótesis no se sostiene.

## Fase 4 — Pendientes

Rama: una por ítem, a definir.

- [ ] **4.1 Validar los FRED IDs en `CorrelationEngine`** antes de enrutar a
  yfinance. **Absorbido por 4.11.** Diagnóstico corregido (2026-09-26):
  `CorrelationEngine` manda a FRED solo los IDs de un `SERIES_CATALOG` fijo de
  5 series (`correlation_engine.py:35`); cualquier otro ID de FRED, **válido o
  no**, va a yfinance y falla. El ejemplo de antes (`IPG2211N` como "ID mal
  escrito") era incorrecto: `IPG2211N` existe en FRED (mensual NSA,
  1972–2026). El problema es el ruteo por catálogo, no la ortografía.
- [ ] **4.2 Invalidar el caché de rechazo de Gemini CLI cuando cambia la
  cuenta.** Hoy dura 24 h o hasta reiniciar el server.
- [ ] **4.3 SA vs NSA en series FRED.** Leer `seasonal_adjustment` de la
  metadata de FRED, mostrarlo en la UI y tenerlo en cuenta al elegir el motor.
  **Leerlo y mostrarlo: hecho** (rama `fix/fred-metadata`, PR abierto;
  ADR-0029). Falta usarlo al elegir el motor, lo que implica un cambio de
  criterio.
  Una serie SA ya no tiene el ciclo anual, así que "motor estacional" no aplica.
  Hoy la app no lo lee: solo un comentario de `scripts/benchmark_real_data.py`
  lo menciona.
- [ ] **4.4 Warnings no mostrados en otros paneles.** Llegan desde la API pero
  la UI no los muestra:
  - Fundamentales: `fetchFundamentals` (`api.ts`) devuelve solo
    `data.metrics` y descarta `warnings`.
  - Optimización de cartera: `PortfolioOptimizeResponse.warnings` está tipado,
    `portfolio_engine.py` los genera, y `PortfolioRiskView` no los renderiza.
  - Riesgo / Monte Carlo: `PortfolioRiskResponse.warnings` está tipado y no se
    renderiza.
  Hecho cuando: los tres paneles los muestran (con tests de componente), como
  ya hacen Backtest (#22) y Rebalanceo.
- [ ] **4.5 Torch en la imagen CUDA.** `Dockerfile.timesfm` termina con torch
  2.5.1+cu121, porque el índice `whl/cu121` llega solo hasta ahí; en local es
  2.14.0+cpu. Decidir entre un índice CUDA más nuevo o fijar torch. Hoy la
  inferencia en esa imagen no está verificada (sin pesos ni GPU en la
  verificación de #24).
  Hecho cuando: la versión de torch de la imagen es una decisión explícita y
  hay al menos una inferencia real de TimesFM verificada en esa imagen.
- [ ] **4.6 Calidad del LLM al traducir la tesis.** **Medido junto con 4.10
  (2026-09-28):** con el prompt nuevo, Sonnet sin errores de hecho y con series
  relevantes (15/16); Haiku con series irrelevantes e inexistentes en T1, mal
  uso de `source` y errores de hecho, y no más rápido. Propuesta: Sonnet por
  defecto en Claude CLI. Gemini no se pudo evaluar (cupo). Decide el usuario.
  **Decidido (2026-09-28): `CLAUDE_CLI_MODEL=sonnet` por defecto** (rama
  `feat/thesis-prompt-v2`; ADR-0031, reemplaza a ADR-0016). Falta Gemini con
  el prompt nuevo. Con
  `CLAUDE_CLI_MODEL=haiku`, la tesis "Demanda eléctrica por centros de datos
  de IA" dio como series FRED TOTALSA, GPDI, INDPRO y DFEDTARU, ninguna
  eléctrica. Comparar Haiku contra Sonnet con las mismas 3–4 tesis y
  registrar qué tickers y series elige cada uno. Evaluación manual, no un
  benchmark automático.
  Hecho cuando: hay una tabla tesis × modelo con tickers y series elegidos, y
  una conclusión sobre qué modelo usar por defecto.
- [x] **4.20 Contexto del copiloto.** (rama `fix/copilot-context`, PR abierto;
  ADR-0028; `docs/results/copilot_context_2026-09-27.md`)
  - Un solo contexto para todos los clientes: fecha de hoy y período de cada
    dato.
  - Evidencia de FRED (último valor y cambio a 12 meses), que agrega el
    servidor.
  - Las empresas se presentan como elegidas por el LLM, no representativas.
  - Se dice qué datos faltan.
  - Las reglas "afirmar solo lo recibido" van en todos los prompts.
  - El mock ya no confirma la tesis.
  - El informe trae fundamentales de todas las empresas: el corte de 15
    filas dejaba solo CEG y ETN.
  - Pendiente: el fetcher completa "Index" y "FRED Series X" por defecto en
    las series fuera del catálogo, y eso se ve en la UI. Tendría que usar la
    unidad y el título de `/fred/series`. **Resuelto en `fix/fred-metadata`
    (ADR-0029).**
- [x] **4.21 Validación de instrumentos.** (ADR-0034, rama
  `feat/instrument-grounding`, PR abierto.) `instrument_grounding` corre en
  `analyze_thesis`: yfinance da nombre oficial, tipo, emisor y categoría; seis
  reglas explícitas (tipo, ETF/empresa, emisor, apalancamiento, inverso,
  exposición temática) deciden qué es contradicción; y **el propio LLM corrige
  en UNA llamada extra** — reescribe la descripción, reemplaza el ticker (que
  se re-verifica) o lo descarta. Mismo patrón que ADR-0033, sin preguntarle
  nada al usuario.
  - **yfinance no tiene campo de apalancamiento** (verificado el 2026-09-30):
    lo inverso sale de su `category` y el multiplicador, del nombre del fondo
    ("3X", "Ultra"=2x, "UltraPro"=3x); un inverso sin multiplicador es −1x.
    Si yfinance no dice nada, no se contradice al LLM: se deja rotulado.
  - **La corrección también se verifica**: si el texto nuevo sigue
    contradiciendo los datos, queda marcado (una segunda vuelta sería un bucle).
  - Estados `verificado` / `reparado` / `descartado` / `null`; el rótulo
    "afirmación del LLM" se mantiene para lo no verificable ("líder del
    mercado").
  - **Una corrección no puede cambiar la apuesta:** el reemplazo mantiene la
    dirección (largo → largo, inverso → inverso) y no agrega apalancamiento
    (bajarlo sí se permite). Si el instrumento correcto exigiría cambiarla, se
    descarta con ese motivo. En el schema **y** validado en el backend.
  - Verificado con Claude CLI Sonnet real: **PSQ** corregido a "inverso 1x de
    ProShares"; **NVDIA** (inexistente) reemplazado por **NVDA**; **NVDA**
    verificado sin tocar (20,1 s). **IPO** → **SOXX** (ETF largo de semis,
    9,6 s): antes de la regla había elegido SOXS, un inverso 3x.
- [x] **4.7 Comunicación del cono.** (Rama `fix/closing-ux`, PR abierto.)
  - La tarjeta "Cono de Confianza" dice qué significa el nivel: un promedio
    sobre muchas ventanas, no una promesa sobre esta; más ancho de lo
    necesario en calma y corto en shocks; y manda el riesgo de cola a la
    pestaña de Riesgo.
  - El panel de backtest muestra ahora la tabla "contra qué se comparó" (modelo,
    random walk y naive estacional cuando aplica), la cobertura real del
    intervalo contra su nivel nominal, y el veredicto de estacionalidad con su
    ACF y su umbral.
  - Lo de la tarjeta "Objetivo" ya estaba resuelto en 4.13/4.18 (rango primero
    cuando "no aporta").
  Texto original del pendiente: En "¿Qué estoy viendo?", aclarar que el
  95% es un promedio sobre muchas ventanas: el cono es más ancho de lo
  necesario en períodos tranquilos y falla en shocks (2.5). Para riesgo de
  cola, remitir a la pestaña de Riesgo.
  (La tarjeta y el Reality Check se resolvieron en 4.13 y 4.18: rango
  primero cuando "no aporta", y nivel real de la banda. Queda el texto de
  "¿Qué estoy viendo?".)
  Además, la tarjeta "Objetivo +{horizon}d" (`MetricCards.tsx`) muestra un
  precio puntual con más precisión de la que respaldan los backtests en
  acciones individuales. Evaluar mostrar el rango como dato principal y el
  punto central como secundario, o agregar una advertencia.
  Además, el panel de backtest tiene que mostrar `mase_seasonal`,
  `seasonal_naive_metrics` y el veredicto de estacionalidad con su ACF y su
  umbral (`seasonality`). Hoy solo los menciona el texto del veredicto.
- [ ] **4.8 (baja prioridad, solo investigar)** Intervalo con volatilidad
  adaptativa (EWMA/GARCH) para mejorar la cobertura condicional. Investigar,
  no implementar.
- [ ] **4.9 (baja prioridad, después de 3.0d)** Los intervalos analíticos de
  `ETSModel` no incluyen la incertidumbre de los parámetros (Holt-Winters
  sub-cubre: 91,3% al 95% en 3.0b). Evaluar intervalos por simulación o
  bootstrap.
- [x] **4.19 Simulación de riesgo: semilla y tendencia.** (rama
  `fix/risk-simulation`, PR abierto; ADR-0027;
  `docs/results/risk_drift_2026-09-27.md`)
  - Cada clic simula con una semilla nueva, y la usada se muestra y se puede
    reproducir. Antes era siempre 42.
  - Por defecto, retornos centrados (sin la tendencia del período), con la
    opción histórica y una etiqueta visible.
  - Medido con CEG, ETN, GEV, PWR y VST a pesos iguales: tendencia +26,9%
    anual (t = 0,9). Con ella, el VaR95 del bootstrap a 30 días baja de 18,8%
    a 16,2% (8 veces el ruido de semilla), y a un año de 44,4% a 27,3%.
- [ ] **4.10 Sesgos del prompt que traduce la tesis** (`SYSTEM_PROMPT` en
  `backend/services/llm_router.py`, ~línea 283, y su variante
  `CLAUDE_CLI_SYSTEM_PROMPT` + `--json-schema` de `ClaudeCliLLMClient`, que
  tienen que cambiar juntas).
  - Hoy exige 3–6 tickers con pesos que suman 1,0 y un racional de "por qué
    este activo se beneficia de la tesis", y deja FRED en segundo plano (1–4
    series). No pide mecanismo ni qué la falsaría, así que empuja a
    confirmarla con acciones individuales.
  - Orden propuesto:
    1. mecanismo causal;
    2. drivers medibles (series FRED);
    3. qué dato falsaría la tesis;
    4. recién ahí, instrumentos, prefiriendo ETFs sectoriales, commodities y
       tasas antes que acciones individuales.
  - Agregar un benchmark amplio obligatorio (SPY) contra el que comparar.
  - Los 4 ejemplos de la UI (`PRESET_THESES` en `ThesisBar.tsx`) giran todos
    alrededor de tecnología, IA y electricidad: centros de datos de IA,
    semiconductores, red eléctrica con baterías, y tasas sobre múltiplos
    **tecnológicos**. Diversificar sectores (consumo, financieras, agro,
    vivienda, commodities).
  - Evaluar prompt viejo contra nuevo con las mismas tesis, en conjunto con
    4.6 (Haiku vs Sonnet): tabla tesis × prompt × modelo con instrumentos,
    series, mecanismo y falsador. Evaluación manual.
  Hecho cuando: esa tabla existe y se decidió qué prompt queda.

  **Evaluación PRE-REGISTRADA el 2026-09-27**, en commit propio, antes de
  escribir el prompt nuevo (rama `feat/thesis-prompt-v2`). Se reporta tal como
  salga; no se cambian los criterios después de ver resultados, y no se elige
  ganador antes de tener la tabla completa.
  - **Tesis:**
    - T1 "Demanda eléctrica por centros de datos de IA";
    - T2 "La IA es una burbuja";
    - T3 "Impacto de tasas de interés en múltiplos tecnológicos";
    - T4 (no tecnológica, elegida acá) "Las tasas hipotecarias altas frenan la
      construcción de viviendas en EE.UU.".
  - **Matriz:** prompt {viejo = código de `main`, nuevo = esta rama} × modelo
    {Gemini API `gemini-3.6-flash`, Claude CLI `haiku`, Claude CLI `sonnet` si
    responde} × 4 tesis. Una corrida por celda, sin re-sortear.
    - Si una llamada falla (429, 503, CLI), se reintenta hasta 3 veces con al
      menos 60 s entre intentos. Si sigue fallando, la celda queda "sin
      dato", con el motivo.
    - Una respuesta del mock (fallback) nunca cuenta como del modelo: la celda
      es "sin dato".
    - La DB es una copia (Claude CLI registra su uso).
  - **Criterios por corrida:**
    - **C1 Series FRED relevantes al mecanismo.**
      - C1a: cuántas de las propuestas existen en FRED (`/fred/series`;
        mecánico).
      - C1b: de las que existen, cuántas miden una variable de la cadena
        causal (causa, canal o efecto), con una línea de justificación cada
        una (juicio manual). Mecanismo de referencia, escrito antes de correr:
        - T1: demanda o consumo eléctrico; generación o capacidad; precios o
          tarifas de electricidad; construcción o inversión en centros de
          datos; equipos eléctricos.
        - T2: valuaciones o precios de activos tecnológicos; inversión o capex
          tecnológico; crédito y condiciones financieras; productividad o
          adopción; ganancias corporativas.
        - T3: tasas (nominales, reales, curva); valuaciones o precios de
          acciones tecnológicas o índices; prima de riesgo o condiciones
          financieras.
        - T4: tasas hipotecarias; inicios y permisos de construcción; ventas
          y precios de viviendas; empleo en construcción; costo de
          materiales.
    - **C2 Criterios de refutación:**
      - 0 = no hay;
      - 1 = hay, pero no medibles (no nombran una variable);
      - 2 = al menos uno medible: una variable o serie y una dirección o
        umbral.
      - El prompt viejo no los pide: un 0 ahí es por construcción, y se
        reporta igual.
    - **C3 Instrumentos:**
      - C3a: SPY aparece como benchmark (en el viejo cuenta si aparece en
        cualquier parte de la salida);
      - C3b: peso en acciones sueltas. Suma de pesos de los instrumentos cuyo
        `quoteType` de yfinance es `EQUITY`. ETF, índice, futuro o
        commodity no suman.
      - C3c: el primer instrumento listado no es una acción suelta.
    - **C4 Textos de cada empresa** (solo acciones sueltas): cuántos textos
      afirman hechos concretos (cifras, contratos, cuotas, eventos) sin fuente
      ni marca de "afirmación del LLM". Se reporta n de m. Juicio manual, con
      la frase afectada citada.
  - **Sesgo conocido:** quien juzga (Claude) escribió el prompt nuevo.
    Mitigación:
    - C1a, C3a, C3b y C3c son mecánicos;
    - C1b, C2 y C4 llevan su justificación escrita;
    - las salidas crudas quedan versionadas en `docs/results/` para
      re-juzgarlas.
  - **Salida:** una tabla tesis × prompt × modelo con C1a, C1b, C2, C3a, C3b,
    C3c y C4. Con la tabla completa se propone qué prompt queda (4.10) y qué
    modelo por defecto (4.6), y lo decide el usuario.

  **Resultado (2026-09-28)** (rama `feat/thesis-prompt-v2`, PR abierto;
  ADR-0030; `docs/results/thesis_prompt_v2_2026-09-28.md`):
  - Con Claude CLI (Haiku y Sonnet, las 4 tesis), el prompt nuevo trae
    refutación medible en 8 de 8 corridas (el viejo en 0).
  - Peso en acciones sueltas: de 94% a 5% (Haiku) y de 51% a 18% (Sonnet).
  - Primer instrumento que no es una acción: 8 de 8 (el viejo, 2 de 8).
  - Series relevantes: Sonnet 15/16 con los dos prompts; Haiku, de 8/13 a
    10/13.
  - Haiku con el prompt nuevo usó `source` para afirmaciones y cometió
    errores de hecho.
  - **Gemini sin datos con el prompt nuevo:** se agotó el cupo gratuito
    diario.
  - Desviaciones dichas en el documento: variante de Claude CLI corregida y
    celdas nuevas corridas de cero; mismo timeout para los dos prompts.
  - Propuesta: queda el prompt nuevo; con Gemini, correr antes sus 4 celdas.
    La decisión es del usuario.
- [x] **4.11 IDs de FRED anclados en datos reales.** (ADR-0033, rama
  `feat/fred-id-grounding`, PR abierto.) `fred_grounding.ground_macro_series`
  corre en `analyze_thesis`: cada ID se verifica contra `/fred/series`. Los
  inexistentes van a `fred/series/search` (hasta 5 candidatos reales con
  metadata) y **el propio LLM los repara en UNA llamada extra**: elige uno de
  esa lista con su justificación, o descarta. Puede pedir **una** reformulación
  por serie, nunca más. **El usuario no elige nada**: el análisis sigue siendo
  de un solo paso y no hay selector en la UI.
  - Estados: `verificado`, `reparado` (con justificación visible), `descartado`
    (aviso informativo) y `null` (FRED caído o sin clave). **Entran al análisis
    `verificado` y `reparado`**; `enters_analysis` y el "Sin medir" del
    copiloto quedan como chequeo defensivo.
  - **Sin LLM (mock o reparación fallida): se descarta.** Nunca se adopta el
    primer resultado de la búsqueda — para TOTALSI ese primero es MSPUS, un
    *precio*, en una tesis sobre *cantidades*.
  - Las reglas de la reparación van en las descripciones del schema, no en el
    system prompt: con un system prompt largo, Claude CLI ignoró
    `--json-schema` y respondió Markdown libre (3/3), como en ADR-0030.
  - Verificado con Claude CLI Sonnet real (24,5 s): TOTALSI → **HSN1F**
    (reparado, tras una reformulación), IPGD → **descartado** ("todos los
    candidatos son subsectores específicos"), UMCSENT → verificado.
  - **El índice de búsqueda de FRED es solo en inglés** (verificado el
    2026-09-29: "new home sales" → 2986, el mismo concepto en español → 0). El
    prompt ahora pide `search_concept_en`; con el `name` en español la búsqueda
    habría descartado todo en vez de repararlo.
  - Verificado con TOTALSI e IPGD (no existen → MSPUS e IPG3344S) y UMCSENT
    (existe), y con una traducción real de Claude CLI Sonnet sobre una copia de
    la DB.
  Detalle original del pedido, que queda como registro: El LLM propone
  *conceptos*; `fred/series/search` devuelve candidatas reales con metadata, y
  se elige entre esas. Nunca un ID generado por el LLM sin verificar contra
  FRED.
  - Verificado el 2026-09-26: `fred/series/search?search_text=…` responde con
    `id`, `frequency_short`, `seasonal_adjustment_short`, `observation_start`,
    `observation_end` y `title` (ejemplo: "electric power generation
    industrial production" → 84 resultados, entre ellos IPG2211S, IPG2211N y
    CAPUTLG2211S).
  - El ruteo FRED/yfinance pasa a depender de que el ID exista en FRED
    (`fred/series`), no de un catálogo fijo. Absorbe 4.1.
    **Hecho en parte (rama `fix/correlation-fred-routing`, PR abierto;
    ADR-0026):**
    - `series_routing.is_fred_series` decide en correlación, backtest y
      auto-discovery. Manda el tipo del pedido; si no hay tipo, el catálogo
      y después FRED mismo.
    - El heatmap manda el tipo de cada serie.
    - Se arregló el mensaje duplicado "ALLOW_SYNTHETIC_DATA=false y
      ALLOW_SYNTHETIC_DATA=false".
    - Verificado con PCU221110221110 y DGS10.
    - Falta la búsqueda de conceptos → candidatas reales.
  Hecho cuando: ninguna serie macro llega a la app sin haber sido validada
  contra FRED, y `CorrelationEngine` acepta cualquier ID válido de FRED.
- [ ] **4.12 Fuentes fuera de FRED (solo investigación).** SEC EDGAR (datos
  contables de empresas, por ejemplo capex) y la API de la EIA (consumo
  eléctrico por sector).
  Verificado el 2026-09-26 leyendo las páginas oficiales (sin llamadas reales):
  - **SEC EDGAR** (`data.sec.gov`):
    - sin API key ("These APIs do not require any authentication or API
      keys to access");
    - APIs JSON: `submissions`, `companyconcept`
      (`/api/xbrl/companyconcept/CIK##########/us-gaap/<tag>.json`),
      `companyfacts` y `frames`. Solo taxonomías estándar (us-gaap,
      ifrs-full, dei, srt), no los tags propios de cada empresa;
    - límite: **10 pedidos por segundo** en total (si se supera, bloqueo
      temporal de la IP);
    - hay que **declarar un User-Agent con nombre y email de contacto**;
    - sin CORS (solo desde el backend), y bulk ZIP nocturno;
    - uso: "public information and may be copied or further distributed",
      con cita a la SEC. No usar el sello ni los logos.
    - **No verificado:** que el tag de capex
      (`PaymentsToAcquirePropertyPlantAndEquipment`) esté disponible para las
      empresas que importan. La SEC no lo documenta por tag.
    - **Sin llamada real:** la política exige un email de contacto real en el
      User-Agent, y eso es decisión del dueño del repo.
  - **EIA API v2** (`https://api.eia.gov/v2/`):
    - **API key gratuita**, registrada por email, siempre en la URL
      (`api_key=`, no en headers);
    - máximo 5.000 filas por respuesta en JSON (300 en XML); se pagina con
      `offset`/`length`;
    - throttling no publicado: la FAQ sugiere menos de ~9.000 pedidos por
      hora y menos de 5 por segundo;
    - ruta `electricity/retail-sales` ("Electricity Sales to Ultimate
      Customers"): facetas `stateid` y `sectorid` (RES, COM, IND, TRA, OTH,
      ALL), datos `sales` (millones de kWh), `price`, `revenue` y
      `customers`; frecuencia mensual, trimestral y anual; desde 2001;
    - uso: dominio público ("You may use and/or distribute any of our
      data…"), con atribución pedida ("Source: U.S. Energy Information
      Administration (fecha)"); no usar el logo;
    - **No verificado:** los términos de servicio de la API
      (`/opendata/terms-of-service.php`, no leídos), y ninguna llamada real
      (no hay key).
  Hecho cuando: hay una recomendación de cuál integrar primero para el caso
  "consumo eléctrico por IA" de la Fase 5, con una llamada real a cada una.
- [x] **4.14 Horizonte en las unidades de la serie (UI/API), alta prioridad.**
  (PR #35, mergeado; `docs/results/horizon_units_2026-09-27.md`)
  - La frecuencia sale de las fechas (`backend/services/horizons.py`).
  - Horizontes por frecuencia: diaria 30/60/90/180, semanal 4/13/26,
    mensual 3/6/12/24, trimestral 2/4/8. Canónicos: 60, 13, 12 y 4.
  - Etiquetas, fechas y CAGR en la unidad real.
  - `decision_horizon` y la nota "motor elegido evaluando a N".
  - Snapshots con su frecuencia.
  - El gráfico dual respeta la frecuencia de cada serie.
  - El backtest toma la frecuencia de las fechas (DGS10 es diaria).
  - El criterio de auto-discovery **no** cambió de versión (ver 2.3b).
  La UI pide siempre 30/60/90/180 pasos con `freq='D'` (`App.tsx`), también
  para series mensuales. Verificado con INDPRO: el pedido por defecto
  devuelve 60 pasos **mensuales** (una banda de 5 años, [84; 127]),
  etiquetados con fechas diarias (2026-06-02 → 2026-08-24) y "Objetivo +60d";
  con 180 serían 15 años mostrados como ~8 meses (por cálculo, no
  verificado). Además, 180 pasos supera `MAX_HORIZON` = 128 de TimesFM y cae
  a Holt.
  Hecho cuando: la UI elige horizonte y `freq` según la frecuencia detectada
  de la serie (por ejemplo, 3/6/12/24 meses para mensuales), las tarjetas y
  el gráfico muestran la unidad correcta, y hay tests.
- [ ] **4.15 Calibración empírica de los intervalos por categoría (conformal),
  baja prioridad.** En 3.5, Holt cubre de más en diarias y semanales (94-98%
  contra 80%) y TimesFM cubre de menos en mensuales (70-79% contra 80%).
  Hecho cuando: hay una propuesta de calibración conformal por categoría,
  medida en cutoffs que no se usaron para calibrar, que no empeora el
  arrepentimiento.
- [x] **4.13 Capacidad de pronóstico visible en la UI.** (rama
  `feat/forecast-skill-badge`, PR #47, mergeado; ADR-0023; criterio v9)
  Para cada serie, mostrar si el motor le gana al naive en su backtest
  (random walk o estacional, según corresponda) y, cuando no le gana, decirlo
  explícitamente ("para esta serie, el pronóstico no supera a repetir el
  último valor").
  Hecho cuando: la proyección de cada serie muestra ese veredicto, con el
  número y su fuente.
  - Resultado sobre una copia de la DB: NVDA no aporta (6 de 8, 7%), IPG2211A2N
    aporta (18 de 24, 17%, 3.0d), DGS10 no aporta (5 de 8, 0,6%), POPTHM
    aporta (8 de 8, 91%).
  - Verificado en el navegador en los dos estados.
  - Chequeo posterior (2026-09-27): en las series estacionales, 4.13 compara
    solo contra el naive estacional, y en 5 de 6 series de 3.5 el random walk
    es más exigente. GFDEGDQ188S "aporta" solo por eso. Ver 4.17.

  **Criterio PRE-REGISTRADO el 2026-09-27 17:28**, antes de implementar (rama
  `feat/forecast-skill-badge`, sobre la de 2.11). Se reporta tal como salga;
  no se ajusta después de ver los estados.
  - **Qué se evalúa:** el motor que eligió la decisión para esa serie.
  - **Contra qué naive:**
    - el naive estacional (mismo período del ciclo anterior) si el detector
      de 3.0a marca la serie completa como estacional;
    - si no, el random walk ("igual que el último dato").
  - **Con qué evidencia:**
    - serie con decisión del auto-discovery: los cutoffs de su mini-backtest
      (criterio vigente, horizonte canónico). En cada cutoff, el MAE del
      motor elegido contra el MAE del naive, en los mismos puntos;
    - serie del catálogo estacional: los 24 cutoffs de 3.0d
      (`docs/results/seasonal_benchmark_2026-09-26.json`), MASE estacional
      del motor del catálogo contra el del naive estacional. Dentro de un
      cutoff la escala es común, así que el orden es el mismo que con MAE.
      Esos cutoffs cubren toda la historia, no la ventana reciente;
    - serie del catálogo de ETFs y camino por defecto: no hay evidencia
      contra el naive → "no evaluado".
  - **Regla** (en la línea de v8):
    - con **al menos 7 cutoffs en par** (los dos errores definidos);
    - **"aporta sobre el naive"** si el motor tiene menor error que el
      naive en la mayoría de los pares (ganados > perdidos) **y** su error
      medio es al menos un 10% menor (media motor ≤ 0,9 × media naive);
    - si no, **"no aporta más que el naive"**.
  - **"No evaluado", siempre con el motivo:**
    - menos de 7 pares;
    - historia insuficiente para decidir;
    - serie sin decisión (catálogo de ETFs o camino por defecto);
    - decisión de una versión anterior sin esta evidencia;
    - la respuesta no la dio el motor evaluado (plan B o fallback).
  - **Almacenamiento:** los errores por cutoff (motor base, TimesFM y naive)
    se guardan en la decisión (`engine_decisions`), con migración como en
    #20, y se sube el criterio a v9 para que las decisiones se re-evalúen y
    los completen.

- [x] **4.16 Agregar una serie de FRED a mano la carga como acción
  (bug).** (rama `fix/manual-fred-and-race`, PR abierto; ADR-0024)
  - "+ FRED ID" valida el ID contra `/fred/series` y lo carga siempre como
    macro. Si FRED dice que no existe, lo dice así y no lo agrega.
  - Las cargas llevan un número de pedido y las respuestas viejas se
    descartan.
  - Verificado en el navegador sobre una copia de la DB, incluida una
    carrera forzada (respuesta de IPG2211A2N demorada 2,5 s).
  Descripción original: `handleAddMacro` (`App.tsx`) llama a `handleSelectSeries` justo
  después de `setActiveMacro`, con el estado viejo. Entonces la serie se pide
  a yfinance y falla con "No se pudo cargar la serie". Además,
  `loadSeriesAndForecast` no descarta respuestas viejas: dos cargas que se
  pisan mezclan serie, error y pronóstico. Visto al verificar 4.13
  (IPG2211A2N).
  Hecho cuando: agregar una serie de FRED a mano la carga como macro al
  primer intento, las respuestas viejas se descartan, y hay un test.

- [x] **4.17 Capacidad contra el más exigente de los dos naives.** (rama
  `feat/skill-strictest-naive`, PR abierto; ADR-0032; criterio v10;
  `docs/results/skill_strictest_naive_2026-09-28.md`)
  - Validación con 6 series elegidas por la regla: se adopta, porque ningún
    "aporta" pierde la mayoría contra el otro naive.
  - CSUSHPINSA y APU0000708111 pasan a "no aporta"; GFDEGDQ188S también,
    como se había medido.
  - Desviación corregida: en una primera corrida, una descarga fallida dejó
    afuera FEDFUNDS y CSUSHPINSA.
  Propuesta original (2026-09-27):
  - **Problema (medido, criterio v9, copia de la DB):** en las series
    estacionales, el indicador de 4.13 compara solo contra el naive
    estacional.
    - 3.5 no hacía eso: `capability()` en
      `scripts/fred_category_benchmark.py` toma como referencia el naive de
      menor error total (`if seasonal and sum(snaive) < sum(rw): ref =
      snaive`).
    - En 5 de las 6 series estacionales de 3.5 (POPTHM, GFDEBTN,
      GFDEGDQ188S, IMPCH, UNRATENSA) el random walk es el más exigente; en
      MTSDS133FMS, y en las 4 del catálogo (3.0d), lo es el estacional.
    - **GFDEGDQ188S "aporta" solo porque el rival es el naive estacional:**
      TimesFM le gana 7-1 (−28%), pero contra el random walk queda 5-3 y
      −5,6%, que no llega al 10%.
    - Las otras 9 aportan contra los dos.
  - **Propuesta:** en las series estacionales, comparar contra el naive más
    exigente, es decir, el de menor error medio en los mismos cutoffs (como
    3.5).
    - Alternativa a decidir en el pre-registro: exigir ganarle a los dos. En
      las 10 series medidas, las dos opciones dan lo mismo.
  - **Qué hace falta:**
    - guardar en la decisión el MAE de los dos naives por cutoff, lo que
      requiere un criterio v10 para que las decisiones se re-evalúen;
    - para el catálogo, recalcular la evidencia de 3.0d contra el random
      walk. Medido: las 4 series aportan contra los dos.
  - **Pre-registro a futuro:**
    - la regla exacta se escribe con fecha y en su propio commit antes de
      implementarla;
    - honestidad: el efecto sobre estas 10 series ya se midió al escribir
      esta propuesta (bitácora 2026-09-27), así que la verificación del
      pre-registro tiene que incluir series que no se usaron acá.
  Hecho cuando: el indicador de las series estacionales compara contra el
  naive pre-registrado, la evidencia de los dos naives está guardada, y hay
  tests y verificación sobre una copia de la DB.

  **Criterio PRE-REGISTRADO el 2026-09-28**, en commit propio, antes de
  implementar y antes de mirar datos de las series de validación (rama
  `feat/skill-strictest-naive`).
  - **Regla (criterio v10 del badge):**
    - en series estacionales, la referencia es el naive de **menor error
      total** en los cutoffs de la decisión, sumando el MAE de los cutoffs
      donde el motor, el random walk y el naive estacional están definidos.
      Es el mismo criterio de 3.5 (`capability()`: `if sum(snaive) <
      sum(rw)`). Con empate, el random walk;
    - contra esa referencia, la misma regla de 4.13: al menos 7 pares,
      mayoría de cutoffs ganados y error medio al menos 10% menor;
    - en series no estacionales no cambia nada: random walk.
  - **Evidencia:**
    - la decisión guarda por cutoff el MAE del random walk y del naive
      estacional (antes, solo el del naive elegido). Se sube el criterio a
      v10 para que las decisiones se re-evalúen;
    - para el catálogo estacional, la evidencia de 3.0d contra el random walk
      se recalcula del snapshot y se versiona.
  - **Esperado por lo medido (no es validación, ya se vio):** GFDEGDQ188S
    pasa de "aporta" a "no aporta"; las otras 9 del chequeo no cambian.
  - **Series de validación (regla mecánica sobre metadatos, sin mirar
    errores):**
    - el endpoint `fred/tags/series` con `tag_names=nsa;monthly;usa`,
      `order_by=popularity`, `sort_order=desc`, primera página (`limit=1000`);
    - se recorre en orden y se toman las **primeras 6** que cumplan:
      - (a) no están en el set del chequeo de POPTHM (POPTHM, GFDEBTN,
        GFDEGDQ188S, IMPCH, MTSDS133FMS, UNRATENSA, IPG2211A2N, HOUSTNSA,
        RSAFSNA, MRTSSM4451USN);
      - (b) `observation_start` ≤ 2000-01-01 y `observation_end` ≥ 2026-01-01;
      - (c) el detector 3.0a las marca estacionales sobre las 500
        observaciones que baja la app (la regla nueva solo cambia algo en
        series estacionales);
    - si no alcanzan 6, se reporta con las que haya.
  - **Criterio de adopción (escrito antes de medir):**
    - la v10 **se adopta** salvo que, en las series de validación, aparezca
      al menos un caso donde la regla nueva diga "aporta" y el motor pierda
      la mayoría de los cutoffs (ganados ≤ perdidos) contra el **otro**
      naive, el de mayor error total;
    - ese caso mostraría que "el más exigente por error total" no alcanza
      como resumen y que habría que pasar a "contra los dos";
    - se reporta además cuántas series cambian de estado entre v9 y v10.
  - **Verificación:** sobre una copia de la DB, con TimesFM real. Se reporta
    tal como salga.

- [x] **4.18 Lote de honestidad de la UI.** (rama `fix/ui-honesty-batch`, PR
  abierto; ADR-0025)
  - El indicador de capacidad pasa al panel del gráfico, junto a "Serie
    activa", y cambia con la serie.
  - El Reality Check usa el nivel real de la banda (80% con TimesFM), y el
    veredicto nombra primero el naive más exigente (criterio de 3.5).
  - Sin "$", "Precio" ni "cierre" en series macro: "Último valor" y la unidad.
  - Con "no aporta", el CAGR también pasa a segundo plano.
  - "Estado de la inercia" se oculta en series estacionales, con el motivo.
  - Verificado en el navegador sobre una copia de la DB (NVDA e IPG2211A2N).
  - Hallazgo: en el corte por defecto de IPG2211A2N, TimesFM no supera al
    naive estacional (MAE 3,00 contra 2,67; un solo corte).

- [x] **4.22 Una serie inexistente no rompe la pantalla.** (rama
  `fix/missing-series-resilience`, PR abierto)
  - Caso: la tesis de las capturas, con TOTALSI e IPGD propuestas por el LLM.
    Ninguna de las dos existe en FRED (consultado el 2026-09-28: "The series
    does not exist"); UMCSENT sí existe.
  - **Correlación:** una serie que no existe o no carga queda afuera, con el
    motivo (`excluded` en la respuesta). La matriz se calcula con las demás.
    Si quedan menos de 2, el error nombra las excluidas. Los datos
    sintéticos siguen rompiendo la matriz, porque mezclarlos daría un
    resultado falso.
  - **Dual-axis:**
    - el selector y el gráfico muestran siempre la misma serie: se descartan
      las respuestas viejas, y el hijo ya no pisa la elección del usuario en
      cada render;
    - si la serie elegida falla, se muestra su error, no el gráfico de otra;
    - el nombre que escribió el LLM se marca "nombre según el LLM" en el
      selector; una vez cargada, se muestra el título de FRED.
  - **Reality Check:**
    - la casilla Holt-Winters se deshabilita cuando el detector de 3.0a ya
      sabe que la serie no es estacional, con el ACF y el umbral a la vista;
    - si la serie no cargó, dice por qué no se puede correr.
  - **Sin `alert()` ni `confirm()` del navegador:** se reemplazaron los de
    análisis de tesis, Reality Check, copiloto, guardar tesis y borrar tesis
    (este último con confirmación en la misma fila).
  - **Riesgo** usa solo los tickers, así que una serie macro inexistente no
    lo toca. Un ticker inexistente sigue rompiendo la optimización con un
    error visible (no verificado en esta rama: queda para 4.11).
  - Pendiente en 4.11: validar los IDs antes de que lleguen a la UI.

## Fase 5 — Examinar tesis, centrado en drivers (para discutir, no ejecutar)

**Reencuadre (2026-09-26):** el objetivo principal pasa de "construir
carteras" a **examinar tesis**. Dada una afirmación, el sistema:
- reúne la evidencia a favor y en contra;
- muestra el estado actual y el pronóstico de esos indicadores;
- dice qué dato cambiaría la conclusión.

**Los criterios de confirmación y de refutación se definen ANTES de mirar los
datos** (si se definen después, se ajustan a lo que salió). La construcción
de cartera queda como opcional, al final.

Casos de prueba de diseño:
- "el consumo eléctrico va a aumentar debido a la IA" (un driver medible,
  con series FRED y EIA);
- "la IA es una burbuja" (una afirmación sobre valuaciones y expectativas,
  más difícil de operacionalizar: qué indicador y qué umbral la confirmarían o
  la refutarían).

Hoy el sistema pronostica precios directamente, serie por serie. La propuesta
invierte el orden:
1. **Pronosticar las variables macro de la tesis** (los drivers: las series
   FRED), que es donde los modelos de series de tiempo mostraron ventaja
   (estacionalidad, 3.0d).
2. **Medir la sensibilidad histórica de cada instrumento a esos drivers**
   (betas o elasticidades) y su **estabilidad en el tiempo** (ventanas
   móviles, quiebres).
3. **Generar escenarios condicionados a la trayectoria del driver** ("si el
   driver sigue su pronóstico / su p10 / su p90, el instrumento se mueve…"),
   en vez de pronosticar el precio del instrumento directamente.

Preguntas abiertas antes de planificar ítems:
- **Estabilidad de las sensibilidades.** ¿Cuánto varían las betas entre
  ventanas? Si cambian de signo o de magnitud seguido, los escenarios
  condicionados heredan esa inestabilidad y dan una falsa precisión.
- **Causalidad vs. correlación.** Una sensibilidad histórica no prueba que el
  driver mueva al instrumento (confusores, causalidad inversa, factores
  comunes como el mercado o las tasas). ¿Alcanza con controlar por un
  benchmark amplio (SPY, 4.10) o hace falta algo más estricto?
- **Integración con los paneles existentes.** Proyección, Backtest,
  Correlaciones, Asignación y Riesgo hoy trabajan sobre precios. ¿Los
  escenarios reemplazan la proyección de precio, la complementan, o alimentan
  a Riesgo (Monte Carlo condicionado)? ¿Cómo se backtestea un escenario
  condicionado?
- **Dependencias con otros ítems:** 3.4 (los drivers pronosticados con datos
  revisados sobrestiman la precisión) y 4.10 (el prompt tendría que devolver
  drivers y mecanismo, no solo tickers).

### 5.1 Modo escenario de crash (solo diseño; no implementar sin discutir)

**Principio: la app NUNCA muestra una "probabilidad de crash" con fecha.**
Muestra "qué pasa si" y termómetros.

1. **Switch "condicionar a un crash"** en el análisis de una tesis:
   - **Repetición histórica** (2008, 2020, 2022) sobre los activos y los
     drivers de la tesis: retorno acumulado, caída máxima y tiempo de
     recuperación en cada episodio.
   - **Monte Carlo del `risk_engine`** (`backend/services/risk_engine.py`,
     `simulate_bootstrap`, bootstrap por bloques) sorteando **solo** bloques
     de períodos de crisis, en vez de toda la historia.
2. **Panel aparte de "condiciones actuales"**: indicadores de fragilidad, cada
   uno con su valor, su historia y en qué percentil de su propia historia
   está hoy, sin combinarlos en un número único. IDs verificados con la
   búsqueda de FRED (`fred/series/search`) el 2026-09-27:

   | Indicador | ID en FRED | Frecuencia | Datos en FRED |
   |---|---|---|---|
   | Curva: 10 años menos 2 años | `T10Y2Y` | diaria | 1976-06-01 → 2026-09-25 |
   | Curva: 10 años menos 3 meses | `T10Y3M` | diaria | 1982-01-04 → 2026-09-25 |
   | Spread high yield (ICE BofA US HY OAS) | `BAMLH0A0HYM2` | diaria | **solo 2023-09-26 → 2026-09-24** |
   | VIX | `VIXCLS` | diaria | 1990-01-02 → 2026-09-22 |
   | Probabilidad de recesión publicada ("Smoothed U.S. Recession Probabilities") | `RECPROUSM156N` | mensual | 1967-06 → 2026-07 |
   | Regla de Sahm en tiempo real | `SAHMREALTIME` | mensual | 1959-12 → 2026-08 |
   | Índice de estrés financiero de la Fed de St. Louis | `STLFSI4` | semanal | 1993-12-31 → 2026-09-18 |
   | Condiciones financieras de la Fed de Chicago | `NFCI` | semanal | 1971-01-08 → 2026-09-18 |

   - La probabilidad de recesión que publica su fuente se muestra como tal
     (fuente y fecha del dato). No se transforma en una fecha de crash
     propia.
   - En FRED, `BAMLH0A0HYM2` empieza en 2023-09-26: no sirve para repetir
     2008 ni 2020. El motivo del recorte no está verificado. Buscar otra
     fuente o decirlo en el panel.

**Preguntas abiertas:**
- **Cómo definir los períodos de crisis sin elegirlos a dedo.** Candidatos
  con regla objetiva: las recesiones NBER (`USREC`, mensual, desde
  1854-12-01; verificado en FRED el 2026-09-27), una caída del mercado de
  más de X% desde el máximo, o un umbral de `STLFSI4`. Cada regla tiene un
  parámetro elegible: ¿se pre-registra, como los criterios de decisión?
  2022 no es recesión NBER; ¿cuenta como crisis?
- **Cómo trasladar un crash a activos que no existían entonces** (por
  ejemplo, un ETF lanzado en 2015). Opciones: un proxy (índice sectorial) o
  la beta contra el mercado en la ventana disponible. Riesgo: una beta
  estimada en calma no representa la de un crash. La UI tiene que decir qué
  proxy se usó.
- **Series sin historia suficiente**, como el spread HY en FRED: ¿se omiten,
  se reemplazan o se aclara en el panel?
- **Relación con la Fase 5**: ¿el escenario de crash es un caso particular
  de los "escenarios condicionados a la trayectoria del driver"?

Hecho cuando (del diseño): hay un documento que responde las preguntas
abiertas, con la lista de indicadores (fuente, frecuencia, historia
disponible y licencia), discutido con el usuario antes de planificar la
implementación.

- [x] **2.3d Implementar v5 (adoptada en 3.5).** (rama `feat/decision-v5`,
  sobre `fix/decide-robust-zero-error`; PR #42, mergeado; ADR-0019)
  - **Trimestral: decide en 4 trimestres.** Sin evidencia en 3.5, decidido
    por uso (30 pasos trimestrales son 7,5 años). Revisar cuando haya más
    series trimestrales.
  - Consecuencia: una diaria necesita 180 puntos para tener cutoffs (antes,
    90).
  - Detalle original: El auto-discovery decide
  en el horizonte canónico de cada frecuencia: diaria 60, semanal 13,
  mensual 12. Criterio v5, con `engine_decisions.horizon`. PR aparte.
  - **Pregunta abierta:** la trimestral (canónico 4) no tuvo evidencia en
    3.5. ¿Decide también en 4 o se queda en 30?
  - Hecho cuando: `AUTO_DISCOVERY_CRITERIA_VERSION = 5`, la decisión y el
    `decision_horizon` salen en el canónico, hay tests y una verificación
    sobre una copia de la DB.
- [x] **2.8 `decide_robust` lanza `ZeroDivisionError` si el error medio del
  base es exactamente 0.** (rama `fix/decide-robust-zero-error`, PR #41, mergeado)
  - Ahora: si el error del base es 0, gana el base; si los dos son 0, es
    empate → base, también contra un incumbente TimesFM.
  - Da lo mismo que producción hacía por accidente (el motor base), pero sin
    excepción y con la decisión cacheada. En el benchmark de 3.5, DFEDTARU
    da un resultado idéntico con 0 fallas (antes, 30).
  - El texto del motivo dice "empataron" cuando los errores medios son
    iguales.
  - Hallazgo aparte, sin tocar: en DFEDTARU el MASE vale ~2,5 millones. El
    MAE naive dentro de la muestra es 0 en los tramos planos y el backtest
    divide por él + 1e-8.
  - Detalle original: Divide por él para `rel_gap`, que es solo un
  dato informativo. Se vio en DFEDTARU (3.5): Holt acierta exacto los
  tramos planos de una tasa en escalones. En producción `decide()` atrapa
  la excepción y la serie cae al default sin decisión.
  Hecho cuando: `rel_gap` tolera el 0, la decisión no cambia, y hay un test
  con errores 0. De paso, `holdout_regret` (scripts) devuelve 0 cuando el
  mejor error es 0 y el elegido no; `fred_category_benchmark.capped_regret`
  lo corrige.

## Orden de trabajo acordado (2026-09-26, actualizado el 2026-09-27)

**2.8 → 2.3d (v5) → 2.9 → 4.13 → 4.11 → 3.4** (actualizado el 2026-09-27). 2.7 y 3.5 están hechos.

Historia del orden: 2.2 → 2.3 → 4.14 → 2.3b → 2.3c → 2.6 (hechos o medidos
el 2026-09-26/27). 2.7 se agregó el 2026-09-27 y va primero porque bloquea
el uso normal. Primero la confiabilidad del
pronóstico de FRED (cuánto oscilan y qué tan robustas son las decisiones, en
qué categorías se le gana al naive, y mostrarlo); después, anclar los IDs y
los vintages. El prompt (4.10) y la Fase 5 van después.

