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
- [ ] **2.2 Medir cuánto oscilan hoy las decisiones** (3 cutoffs, gana TimesFM
  con MASE estrictamente menor, sin margen).
  Hecho cuando: hay una medición reproducible (script + resultado) de cuántas
  decisiones cambian entre corridas o ventanas cercanas.
  Requisito agregado: un mínimo de cutoffs en par (donde TimesFM realmente
  corrió, ver 2.1) para poder elegir TimesFM. Hoy, si TimesFM falla en 2 de 3
  cutoffs, la decisión sale de un solo cutoff.
- [ ] **2.3 Decisión más robusta:** 5–8 cutoffs, un margen (por ejemplo
  `MASE_tfm ≤ 0.95·MASE_holt` o Diebold-Mariano) y que un empate lo gane Holt.
  Hecho cuando: el umbral está elegido a partir de la medición de 2.2, no antes,
  y hay tests del margen y del empate.
  Además: el guard de calibración por cobertura (`MAX_ACCEPTABLE_COVERAGE_GAP_PP`)
  sobre 3 cutoffs no es confiable. 2.5 mostró que la cobertura por ventana va
  de 0% a 100%, con mediana 100%, así que 3 ventanas pueden dar cualquier
  cosa. La decisión tiene que usar muchos cutoffs o sacar la cobertura del
  criterio.

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
  - [x] **3.0c + 3.0d (una sola ronda, rama `feat/seasonal-benchmark`, PR
    abierto):** veredicto en `docs/results/seasonal_benchmark_2026-09-26.md`.
    - TimesFM tiene el menor error en las 4 series y le gana a HW de forma
      significativa en 3 (IPG2211A2N, RSAFSNA frágil, HOUSTNSA); en
      MRTSSM4451USN, HW.
    - Holt (el plan B actual) pierde incluso contra el naive estacional.
    - Prophet no entra al selector.
  - [ ] **3.0e Arreglar la banda de TimesFM (prerrequisito del selector).**
    `TimesFMForecastEngine` usa la columna 0 de los cuantiles (la media) como
    límite inferior. La banda real es columnas 1 (p10) y 9 (p90). La app
    muestra [media, p90]: cubre 36–62%, contra 84–92% de la p10–p90 real.
    Después, re-evaluar las decisiones de auto-discovery que TimesFM perdió
    "por calibración" (CEG y NVDA en la DB local).
  - [ ] **3.0f Aplicar el veredicto al selector** (`SEASONAL_FRED_CATALOG` y
    Holt-Winters como plan B), una vez que el dueño del repo decida sobre la
    propuesta del documento de resultados.

- [ ] **3.1 Univariado** contra TimesFM 2.5 y contra Holt, en el mismo arnés
  walk-forward.
- [ ] **3.2 Con covariables:** las series FRED de la tesis como covariables de
  pasado. Comparar con los regresores externos de Prophet (ver 3.0).
- [ ] **3.3 Latencia en CPU.**

Hecho cuando: los tres resultados están documentados tal como salieron,
incluso si la hipótesis no se sostiene.

## Fase 4 — Pendientes

Rama: una por ítem, a definir.

- [ ] **4.1 Validar los FRED IDs en `CorrelationEngine`** antes de enrutar a
  yfinance.
- [ ] **4.2 Invalidar el caché de rechazo de Gemini CLI cuando cambia la
  cuenta.** Hoy dura 24 h o hasta reiniciar el server.
- [ ] **4.3 SA vs NSA en series FRED.** Leer `seasonal_adjustment` de la
  metadata de FRED, mostrarlo en la UI y tenerlo en cuenta al elegir el motor.
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
- [ ] **4.6 Calidad del LLM al traducir la tesis.** Con
  `CLAUDE_CLI_MODEL=haiku`, la tesis "Demanda eléctrica por centros de datos
  de IA" dio como series FRED TOTALSA, GPDI, INDPRO y DFEDTARU, ninguna
  eléctrica. Comparar Haiku contra Sonnet con las mismas 3–4 tesis y
  registrar qué tickers y series elige cada uno. Evaluación manual, no un
  benchmark automático.
  Hecho cuando: hay una tabla tesis × modelo con tickers y series elegidos, y
  una conclusión sobre qué modelo usar por defecto.
- [ ] **4.7 Comunicación del cono.** En "¿Qué estoy viendo?", aclarar que el
  95% es un promedio sobre muchas ventanas: el cono es más ancho de lo
  necesario en períodos tranquilos y falla en shocks (2.5). Para riesgo de
  cola, remitir a la pestaña de Riesgo.
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
