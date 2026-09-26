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

- [x] **0.1 Test de Claude CLI independiente del binario.** (PR #14, sin mergear)
  `test_claude_cli_no_tool_use_attempted` hoy llama a `shutil.which` real a
  través de `ClaudeCliLLMClient.__init__`.
  Hecho cuando: el test pasa con `shutil.which` devolviendo `None` para
  `claude`, y el arreglo está en el test (no en el código de producción).
- [x] **0.2 Fijar la versión de `timesfm`.** (PR #14, sin mergear; fijado en `==3.0.2`) Hoy
  `requirements-timesfm.txt` acepta `>=2.0.0,<4.0.0`.
  Hecho cuando: la versión instalada y la última de PyPI están verificadas
  (ambas exportan `TimesFM_2p5_200M_torch`), el pin elegido está justificado
  con fecha y método en un comentario, y los tests reales de TimesFM pasan con
  los pesos en caché.
- [ ] **0.3 `CONTEXT.md` actualizado** (cuota de Claude CLI verificada el
  2026-09-25; TimesFM-3 existe y no fue evaluado).
  Hecho cuando: el archivo existe, tiene esas dos notas y quedó decidido si se
  versiona.
  Estado: bloqueado. Se decidió crearlo en la raíz y versionarlo (rama
  `docs/context-md`), pero falta el documento base: no está en el repo y no se
  reconstruye de memoria.

- [x] **0.4 Test de fechas independiente del día de la semana.** (PR #17, sin
  mergear)
  `test_cached_live_series_keeps_live_source` fallaba sábados y domingos: con
  pandas 3, `date_range(end=<fin de semana>, periods=100, freq="B")` devuelve
  99 fechas.
  Hecho cuando: los valores salen de `len(dates)` y el test cubre un sábado y
  un domingo fijos, además de "now".
- [ ] **0.5 Decidir el rango de pandas.** `requirements.txt` declara
  `pandas>=2.2.0,<3.0.0`, pero el entorno local tiene 3.0.1 (entró el
  2026-03-29 como dependencia de un `pip install yfinance` sin restricciones).
  Opciones: volver el entorno a <3, o subir el techo a <4. La suite da 114
  passed con las dos (venv limpio, 2026-09-26). La decide el dueño del repo.
  Hecho cuando: `requirements.txt` y el entorno local coinciden.

## Fase 1 — Auto-discovery: "no evaluado" ≠ "Holt ganó"

Rama: `fix/autodiscovery-not-evaluated`

- [x] **1.1 Distinguir la decisión tomada sin TimesFM.** (PR #15, sin mergear) Hoy una serie evaluada
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

- [ ] **2.1 Detectar el fallback interno de TimesFM→Holt dentro de
  `BacktestEngine.run_backtest`.** Hoy `BacktestResponse` no lo expone, así que
  `mase_timesfm` podría ser en realidad de Holt, y eso es una métrica fabricada.
  Va primero: medir oscilaciones o fijar un margen sobre un `mase_timesfm` que
  puede no ser de TimesFM no tiene sentido.
  Hecho cuando: el mini-backtest descarta o marca los cutoffs donde TimesFM no
  corrió de verdad, con un test que lo demuestre.
- [ ] **2.2 Medir cuánto oscilan hoy las decisiones** (3 cutoffs, gana TimesFM
  con MASE estrictamente menor, sin margen).
  Hecho cuando: hay una medición reproducible (script + resultado) de cuántas
  decisiones cambian entre corridas o ventanas cercanas.
- [ ] **2.3 Decisión más robusta:** 5–8 cutoffs, un margen (por ejemplo
  `MASE_tfm ≤ 0.95·MASE_holt` o Diebold-Mariano) y que un empate lo gane Holt.
  Hecho cuando: el umbral está elegido a partir de la medición de 2.2, no antes,
  y hay tests del margen y del empate.

## Fase 3 — Experimento TimesFM-3

Rama: a definir.

Contexto: salió el 31/08/2026 (330M parámetros, checkpoint
`google/timesfm-3.0-pytorch`, covariables de pasado y pasado-futuro). Los pesos
tienen licencia **no comercial**.

- [ ] **3.1 Univariado** contra TimesFM 2.5 y contra Holt, en el mismo arnés
  walk-forward.
- [ ] **3.2 Con covariables:** las series FRED de la tesis como covariables de
  pasado.
- [ ] **3.3 Latencia en CPU.**

Hecho cuando: los tres resultados están documentados tal como salieron,
incluso si la hipótesis no se sostiene.

## Fase 4 — Pendientes

Rama: una por ítem, a definir.

- [ ] **4.1 Validar los FRED IDs en `CorrelationEngine`** antes de enrutar a
  yfinance.
- [ ] **4.2 Invalidar el caché de rechazo de Gemini CLI cuando cambia la
  cuenta.** Hoy dura 24 h o hasta reiniciar el server.
