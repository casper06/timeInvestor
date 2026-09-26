# TimeInvestor — Contexto completo del proyecto

Documento para arrancar una sesión nueva de Claude Code sin haber leído el historial de conversación previo. Pegalo entero como primer mensaje, o guardalo como `CONTEXT.md` en la raíz del repo y decile al agente que lo lea antes de tocar nada.

Repo: `github.com/casper06/timeInvestor`. Local, un solo usuario (Fer). ~10.700 líneas de Python, ~6.900 de TypeScript/TSX, 16 archivos de test de Python (`tests/test_*.py`) y 5 de frontend (`*.test.ts[x]`). Conteos medidos el 2026-09-26 sobre los archivos versionados de `main` @ `c9b2125`.

---

## 1. Qué es este proyecto

Una plataforma local de análisis cuantitativo de tesis de inversión. El usuario escribe una tesis en lenguaje natural ("boom de semiconductores por IA", "guerra en Medio Oriente y su efecto en Vaca Muerta"), un LLM la traduce a una cartera de tickers + indicadores macro de FRED, y el sistema corre proyecciones, backtests, correlaciones, optimización de portafolio y simulación de riesgo sobre esa cartera.

**El motivo de ser del proyecto es TimesFM**, el modelo fundacional de series temporales de Google — la idea original era que fuera el corazón predictivo. Ese supuesto se puso a prueba con evidencia real durante el proyecto (ver sección 3) y el resultado fue más matizado que "TimesFM es mejor": gana en algunas categorías de series, pierde en otras. El sistema hoy decide caso por caso, no por fe.

## 2. Arquitectura

**Backend** (FastAPI + SQLite, Python):
- `backend/services/forecast_engine.py` — dos motores: `DampedHoltForecastEngine` (Holt amortiguado, parámetros ajustados por MLE, opera sobre log-retornos con corrección de sesgo, intervalo de confianza con la fórmula analítica de Hyndman & Athanasopoulos) y `TimesFMForecastEngine` (modelo real `google/timesfm-2.5-200m-pytorch`, singleton, cuantiles p10-p90 nativos). El paquete `timesfm` está fijado en `==3.0.2` en `requirements-timesfm.txt` (ver sección 3). `TimesFMForecastEngine.is_available()` es el chequeo barato de disponibilidad: con `USE_REAL_TIMESFM=false` no toca el modelo; si no, lo carga como mucho una vez por proceso (una carga fallida no se reintenta).
- `backend/services/engine_selector.py` — decide Holt vs TimesFM **por serie individual**, no con un switch global. Tiene un catálogo pre-benchmarkeado (series FRED estacionales, ETFs/índices) y un `AutoDiscoveryEngine` que corre un mini-backtest walk-forward la primera vez que ve una serie nueva, cachea la decisión en SQLite (`engine_decisions`), y la re-evalúa si pasan >30 días o cambia mucho la historia disponible. Además, una decisión tomada sin TimesFM (`mase_timesfm` NULL = "no evaluado") se re-evalúa apenas TimesFM está disponible, sin esperar el TTL.
- `backend/services/llm_router.py` — múltiples proveedores intercambiables: `GeminiLLMClient` (API key), `GeminiCliLLMClient` (OAuth, cuota separada de la API key), `ClaudeCliLLMClient` (usa `claude -p`, **comparte cupo con el uso interactivo de Claude Code**), `OpenAILLMClient`, `OllamaLLMClient`, `MockLLMClient` (heurística local, sin red). Retry con backoff (1s/3s) para errores transitorios (429/503), clasificación de fallback (`rate_limit`/`transient`/`auth_or_config`/`content_filtered`/`unknown`) expuesta al usuario con mensajes accionables.
- `backend/services/data_fetcher.py` — `MarketDataFetcher` (yfinance) y `FREDDataFetcher` (FRED). **Todo dato tiene un campo `source: "live"|"synthetic"`**; con `ALLOW_SYNTHETIC_DATA=false` (default), una fuente caída tira error explícito en vez de inventar datos. La caché preserva `source` original y agrega `from_cache`/`cached_at` como campos separados (no los mezcles).
- `backend/services/backtest_engine.py`, `correlation_engine.py`, `portfolio_engine.py` (Markowitz + Risk Parity, shrinkage Ledoit-Wolf, μ por James-Stein/equal/forecast), `risk_engine.py` (Monte Carlo VaR/CVaR: bootstrap por bloques/Student-t/Gaussiano), `rebalance_engine.py` (backtest walk-forward de rebalanceo con costos de transacción, sin look-ahead bias).
- `backend/services/llm_availability.py` — chequea qué proveedores de LLM están realmente disponibles (keys configuradas, CLIs instalados/autenticados), con caché corto (60s) salvo casos de rechazo permanente de cuenta (24h).
- Guard universal: **ningún endpoint cuantitativo (backtest, correlación, portfolio, risk, rebalance) acepta una serie con `source="synthetic"`** — 422 explícito.

**Frontend** (React 19 + TS): dashboard con pestañas (Proyección, Reality Check/Backtest, Correlaciones, Gráfico Dual-Axis, Asignación y Riesgo), cada una con un panel colapsable "¿Qué estoy viendo?" explicando las métricas en criollo. Selector de proveedor LLM en el Header (cambio en caliente, sin reiniciar el server). Badges de transparencia: qué motor de forecast respondió, qué LLM respondió realmente (no solo el configurado — si cayó a mock, lo dice y por qué).

**Docker**: imagen liviana default (sin `torch`/`timesfm`, ~814MB) + `Dockerfile.timesfm` opcional para GPU/inferencia real.

## 3. Hallazgos importantes de la historia del proyecto (contexto que explica por qué el código es como es)

- **El benchmark original de TimesFM estaba fabricado.** La primera versión del script de benchmark simulaba la salida de TimesFM con una fórmula (`holt_pred * 0.98 + rw_pred * 0.02`) en vez de correr el modelo real. Se corrigió para que, sin pesos reales cargados, el benchmark diga explícitamente "no evaluado" en vez de inventar un número.
- **TimesFM real, benchmarkeado en serio, pierde contra Holt en la mayoría de acciones individuales y en índices/ETFs diversificados (SPY, QQQ).** Solo gana de forma consistente en series FRED con estacionalidad estructural real (producción industrial, gas natural, etc.). Esto es coherente con la literatura: modelos fundacionales zero-shot generalizan bien en dominios con patrones recurrentes, pero un modelo clásico ajustado a la serie específica (Holt vía MLE) le gana en series financieras idiosincráticas de alta volatilidad. Este hallazgo motivó el `EngineSelector`.
- **El cono de confianza de Holt estaba mal calibrado originalmente** (fórmula heurística inventada, cobertura empírica real de 64% contra un objetivo de 95%). Se corrigió con la fórmula analítica correcta y se validó con simulación Monte Carlo (45.000 evaluaciones, cobertura final ~96%).
- **Un bug de caché borraba la procedencia de los datos**: al servir desde caché, `source` se sobreescribía a `"cached"`, perdiendo si el dato original era real o sintético — lo que permitía que datos inventados pasaran los guards de "solo datos reales" después del primer hit de caché. Se separó en dos campos independientes (`source` + `from_cache`).
- **El catálogo fijo de series para TimesFM no escalaba.** Al principio solo 4 series de FRED, elegidas a mano en una ronda de benchmark, tenían el motor "correcto" asignado. Cualquier serie nueva que el LLM trajera caía a Holt sin haber sido evaluada nunca. Se reemplazó por auto-discovery: cualquier serie nueva se autoevalúa la primera vez, se cachea la decisión.
- **Auto-discovery mezclaba "TimesFM no corrió" con "Holt ganó".** Con TimesFM no disponible (imagen liviana, pesos sin bajar), el mini-backtest guardaba `engine_choice="holt"` con `mase_timesfm` NULL, y eso quedaba cacheado 30 días como si Holt hubiera ganado. Ahora `mase_timesfm` NULL significa exactamente "no evaluado": esa decisión se re-evalúa apenas TimesFM está disponible, sin esperar el TTL, y mientras no lo está no se re-corre en cada request. El motivo que ve el usuario dice "TimesFM no evaluado", nunca "Holt ganó". Sin cambio de esquema: NULL ya tenía ese significado.
- **`timesfm` está fijado en `==3.0.2`.** Antes el rango era `>=2.0.0,<4.0.0`, y desde 3.0.0 el paquete también trae TimesFM 3, así que un `pip install -U` podía romper `TimesFM_2p5_200M_torch`, que es la clase que usa el proyecto. Verificado el 2026-09-25: 3.0.2 era la instalada y la última de PyPI, el wheel de PyPI exporta esa clase, y los tests con pesos reales pasan. Antes de subir la versión, repetir esos chequeos (el comentario en `requirements-timesfm.txt` dice cómo).
- **TimesFM-3 existe y todavía no fue evaluado en este proyecto.** Checkpoint `google/timesfm-3.0-pytorch`: 330.710.976 parámetros y licencia `timesfm-non-commercial-license-v1.0` (pesos **no comerciales**), según la API de Hugging Face, consultada el 2026-09-26. El código de `timesfm` 3.0.2 acepta covariables de pasado (`past_only_covariates`) y de pasado-futuro (`past_future_covariates`). La fecha de lanzamiento del 31/08/2026 no está verificada: el repo de Hugging Face se creó el 2026-08-24. La evaluación está planificada como Fase 3 de `docs/PLAN.md`.
- **La cuenta de Google del usuario está rechazada para Gemini CLI** (`IneligibleTierError: UNSUPPORTED_CLIENT` — Google migró ese producto a "Antigravity" para cuentas personales). No es arreglable desde el código; el sistema lo detecta y lo marca no disponible con el motivo real. El usuario usa Claude CLI (vía su suscripción de Claude Code) o la API key de Gemini mientras tanto.
- **Cuota de Claude CLI comparte pool con el uso interactivo de Claude Code** — no es una cuota separada como la de Gemini CLI. Esto es una limitación de diseño a tener en cuenta, no un bug. **Verificado 2026-09-25** (re-leído el 2026-09-26) en support.claude.com, artículo 15036540 ("Use the Claude Agent SDK with your Claude plan"). Anthropic había anunciado que desde el 15/06/2026 `claude -p` y el Agent SDK dejarían de contar contra los límites de la suscripción y usarían un crédito mensual aparte. Lo pausó ese mismo día y nunca entró en vigor. Hoy `claude -p` sigue consumiendo los límites de la suscripción. Texto de la página: "For now, nothing has changed: Claude Agent SDK, claude -p, and third-party app usage still draw from your subscription's usage limits" y "When we have an update, we'll share it before anything takes effect". Puede cambiar: volver a verificarlo antes de asumirlo.

## 4. Filosofía de trabajo establecida — lo más importante de este documento

Esto es lo que hizo que el proyecto no se llenara de deuda técnica invisible. Cualquier sesión nueva tiene que mantenerlo:

1. **Nunca aceptar un reporte del agente sin verificarlo.** Clonar/traer la rama real, correr los tests uno mismo (no confiar en "todos los tests pasan" sin ejecutarlos), leer el código de los cambios más importantes línea por línea cuando el hallazgo es central (no en cada detalle menor).
2. **Nunca fabricar datos, resultados de benchmark, o metadata.** Si una fuente de datos falla, error explícito — nunca una aproximación silenciosa. Los benchmarks comparan modelos reales sobre datos reales; si no se puede evaluar algo, se dice "no evaluado", nunca se simula un resultado plausible.
3. **Decir "esto no funciona" o "el modelo pierde acá" es preferible a forzar la narrativa hacia lo que se esperaba encontrar.** Varias rondas de este proyecto terminaron en "la hipótesis no se sostuvo" (índices/ETF con TimesFM, cold-start con TimesFM) y eso quedó documentado tal cual, no maquillado.
4. **Verificar afirmaciones sobre productos externos (límites de API, comportamiento de CLIs, políticas de Google/Anthropic) con búsqueda antes de asumir** — cambian seguido y a veces el propio agente (u otra IA externa) puede traer información desactualizada o parcialmente incorrecta.
5. **Rama por feature, PR antes de mergear a `main`, tests corridos después de cualquier rebase** (nunca asumir que lo que pasaba antes del rebase sigue pasando después).
6. **Todo mensaje de fallback/error al usuario tiene que explicar la causa real y si conviene esperar o si hace falta intervenir** — nunca un genérico "algo falló".
7. **Las verificaciones con datos reales se hacen sobre una COPIA de la DB** (en `data/` o en un directorio temporal, ignorada por git, apuntada con `DATABASE_URL`), nunca sobre `backend/database/time_investor.db` antes del merge. La DB real solo cambia por el uso normal de la app con el código de `main`.

## 5. Cómo correr el proyecto

```bash
cp .env.example .env   # completar GEMINI_API_KEY, FRED_API_KEY (gratis, fred.stlouisfed.org), etc.
python -m venv .venv   # instalar siempre en .venv, nunca en el Python global
pip install -r requirements.lock   # versiones exactas; requirements.txt tiene los rangos
python run.py          # sirve el frontend compilado + API en :8000
```

Docker: `docker compose up --build` (imagen liviana, sin TimesFM real).

TimesFM real (opcional, pesado — CPU-only anda pero es más lento y en el benchmark real no siempre gana):
```bash
pip install -r requirements-timesfm.txt -c requirements.lock   # fuera del lock: torch depende del hardware
python scripts/download_and_benchmark_timesfm.py --yes
```

Proveedores de LLM por suscripción (evitan pagar API key facturada):
```bash
npm install -g @google/gemini-cli      # gemini → "Sign in with Google"
npm install -g @anthropic-ai/claude-code  # ya autenticado si Claude Code se usa en la máquina
```
Elegir el proveedor activo desde el dropdown del Header (cambio en caliente) o fijo en `.env` con `LLM_PROVIDER`.

## 6. Pendientes conocidos, no bloqueantes

- **Fallback silencioso de TimesFM→Holt dentro del backtest** (Fase 2.1 de `docs/PLAN.md`). Si TimesFM falla en una llamada, `forecast()` cae a Holt, pero `BacktestResponse` no lo expone. En el mini-backtest de auto-discovery, `mase_timesfm` podría ser entonces un MASE de Holt: una métrica fabricada. Va antes que cualquier ajuste del margen o de los cutoffs del selector.
- **Mini-backtest sin cutoffs no se cachea.** Si `_pick_cutoffs` devuelve `[]`, el mini-backtest falla a propósito (antes cacheaba un MASE NaN como "holt"), así que se reintenta en cada request de esa serie, con un `logger.warning` cada vez. Los datos no se re-descargan en cada request, porque el fetcher los cachea en memoria 1 hora (`CACHE_TTL_SECONDS`). Caso raro: requiere < 60 puntos en el re-fetch cuando el selector ya vio >= 90. Si molesta, la opción es un caché negativo corto.
- **Dependencias: rangos y lock.** El drift de la máquina local (pandas, yfinance, fastapi y uvicorn fuera de rango) se resolvió subiendo los rangos (#19). Desde 2.4 hay `requirements.lock` (generado con `uv pip compile --universal`), que instalan `.venv` y Docker. `requirements-timesfm.txt` queda fuera del lock y se instala con `-c requirements.lock`. El Python global de la máquina todavía tiene las versiones viejas: usar `.venv\Scripts\python`.
- El caché de 24h de "cuenta de Gemini CLI rechazada" no se invalida si el usuario cambia de cuenta de Google (solo por tiempo o reinicio del server) — mejora menor pendiente, no crítica porque el peor caso es esperar hasta 24h para que un cambio de cuenta se refleje.
- `CorrelationEngine` tiene el mismo problema de catálogo rígido que motivó el auto-discovery de forecast: un FRED ID mal escrito por el LLM (ej. `IPG2211N` en vez de `IPG2211A2N`) se enruta a yfinance y falla — anotado, fuera de alcance por ahora.
- La cuenta de Gemini CLI del usuario está permanentemente rechazada por Google (`IneligibleTierError`, ver sección 3) — el sistema ya lo detecta y lo comunica bien, no es un bug a resolver, es un hecho externo a vivir con él. Usar Claude CLI o la API key de Gemini.

## 7. Estado del repo al cierre de esta ronda

`main` @ `c9b2125` (2026-09-26). `pytest -q` en `main`: `120 passed`, sin fallas, corrido un sábado.

Mergeado en esta tanda:
- #16: `docs/PLAN.md` (plan por fases) y `.bitacora/` en `.gitignore`.
- #14: Fase 0. El test de Claude CLI ya no depende de tener el binario instalado (pendiente 0.1, resuelto) y `timesfm` quedó fijado en 3.0.2.
- #15: Fase 1. Auto-discovery distingue "no evaluado" de "Holt ganó".
- #17: `test_cached_live_series_keeps_live_source` fallaba los fines de semana con pandas 3 (`date_range(end=<fin de semana>, freq="B")` devuelve una fecha menos). Ahora cubre sábado y domingo fijos.

En curso:
- #18 (`docs/context-md`): este archivo (0.3).
- #19 (`chore/deps-align`): ítem 0.5, alinear los rangos de `requirements*.txt` con lo que realmente corre.

Organización del trabajo:
- `docs/PLAN.md` (versionado) tiene las fases 0 a 4 como checklist, cada ítem con su rama y su criterio de "hecho". Fase 2 arranca por el fallback silencioso de TimesFM (sección 6).
- `.bitacora/RONDAS.md` es local y está ignorado por git (`.gitignore`). Tiene una entrada por ronda: salida real de pytest, qué quedó sin verificar y decisiones.
- Los PRs se mergean solo cuando el usuario escribe "ok #N" en el chat.

Sigue vigente: `tests/conftest.py` (fixture `autouse=True` que limpia el caché de disponibilidad de LLM entre cada test — importante si se agregan más tests de disponibilidad en el futuro, ya corre solo).

## 8. Variables de entorno relevantes (`.env`)

`GEMINI_API_KEY`, `FRED_API_KEY`, `OPENAI_API_KEY` (opcional), `LLM_PROVIDER` (`gemini`/`gemini_cli`/`claude_cli`/`openai`/`ollama`/`auto`/`mock`), `ALLOW_SYNTHETIC_DATA` (default `false`, no tocar salvo demo offline consciente), `USE_REAL_TIMESFM` (default `true` — el `EngineSelector` decide cuándo usarlo de verdad, este flag solo controla si está disponible como opción), `CACHE_TTL_SECONDS`.
