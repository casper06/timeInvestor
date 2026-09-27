# TimeInvestor — Contexto completo del proyecto

Documento para arrancar una sesión nueva de Claude Code sin haber leído el historial de conversación previo. Pegalo entero como primer mensaje, o guardalo como `CONTEXT.md` en la raíz del repo y decile al agente que lo lea antes de tocar nada.

Repo: `github.com/casper06/timeInvestor`. Local, un solo usuario (Fer). ~15.100 líneas de Python, ~7.600 de TypeScript/TSX en `frontend/src`, 24 archivos de test de Python (`tests/test_*.py`) y 8 de frontend (`*.test.ts[x]`). Conteos medidos el 2026-09-27 sobre los archivos versionados de `main` @ `16b6782`, con `git ls-files '*.py' | xargs cat | wc -l` (y lo mismo para `frontend/src/*.ts[x]`).

Mapa de la documentación: arquitectura y diagramas en `docs/ARCHITECTURE.md`; decisiones con sus motivos en `docs/adr/`; trabajo pendiente y orden en `docs/PLAN.md`; resultados de las mediciones en `docs/results/`.

---

## 1. Qué es este proyecto

Una plataforma local de análisis cuantitativo de tesis de inversión. El usuario escribe una tesis en lenguaje natural ("boom de semiconductores por IA", "guerra en Medio Oriente y su efecto en Vaca Muerta"), un LLM la traduce a una cartera de tickers + indicadores macro de FRED, y el sistema corre proyecciones, backtests, correlaciones, optimización de portafolio y simulación de riesgo sobre esa cartera.

**El motivo de ser del proyecto es TimesFM**, el modelo fundacional de series temporales de Google — la idea original era que fuera el corazón predictivo. Ese supuesto se puso a prueba con evidencia real durante el proyecto (ver sección 3) y el resultado fue más matizado que "TimesFM es mejor": gana en algunas categorías de series, pierde en otras. El sistema hoy decide caso por caso, no por fe.

## 2. Arquitectura

**Backend** (FastAPI + SQLite, Python):
- `backend/services/forecast_engine.py` — tres motores:
  - `DampedHoltForecastEngine`: Holt amortiguado sobre el logaritmo de la serie (si es positiva), con α, β y φ ajustados minimizando la SSE de los errores a un paso; punto con corrección de sesgo lognormal e intervalo con la fórmula analítica de Hyndman & Athanasopoulos.
  - `HoltWintersForecastEngine`: ETS(A,Ad,A) con `statsmodels` `ETSModel`, por MLE e intervalos analíticos; solo para series estacionales, si no lanza `NotSeasonalError`.
  - `TimesFMForecastEngine`: modelo real `google/timesfm-2.5-200m-pytorch`, singleton; banda p10-p90 buscada por valor en `model.config.quantiles`, con `interval_level` 0,80. El paquete `timesfm` está fijado en `==3.0.2` en `requirements-timesfm.txt` (ver sección 3). `TimesFMForecastEngine.is_available()` es el chequeo barato de disponibilidad: con `USE_REAL_TIMESFM=false` no toca el modelo; si no, lo carga como mucho una vez por proceso (una carga fallida no se reintenta).
- `backend/services/engine_selector.py` — decide el motor (Holt, Holt-Winters o TimesFM) **por serie individual**, no con un switch global. Consulta primero los catálogos (series FRED estacionales, con la evidencia de cada una; ETFs/índices). Para el resto usa `AutoDiscoveryEngine` (`backend/services/auto_discovery.py`):
  - corre un mini-backtest con el criterio v4: 8 cutoffs recientes; TimesFM gana solo con mayoría de cutoffs y 10% de margen; empate → motor base; histéresis ×2;
  - cachea la decisión en SQLite (`engine_decisions`);
  - la re-evalúa si sube la versión del criterio, si pasan más de 30 días, si la serie crece un 20%, o, si se tomó sin TimesFM (`mase_timesfm` NULL = "no evaluado"), apenas TimesFM está disponible.

  Si TimesFM no corre, el plan B es Holt-Winters para las series estacionales y Holt para el resto. Ver `docs/ARCHITECTURE.md`.
- `backend/services/horizons.py` y `reliability.py` — el horizonte va en pasos de la serie, con la frecuencia inferida de las fechas (4.14). Un pronóstico que se mueve más del doble de lo máximo que la serie se movió en ese horizonte se marca "no confiable", sin tocar los números (2.6).
- `backend/services/llm_router.py` — múltiples proveedores intercambiables: `GeminiLLMClient` (API key), `GeminiCliLLMClient` (OAuth, cuota separada de la API key), `ClaudeCliLLMClient` (usa `claude -p`, **comparte cupo con el uso interactivo de Claude Code**), `OpenAILLMClient`, `OllamaLLMClient`, `MockLLMClient` (heurística local, sin red). Retry con backoff (1s/3s) para errores transitorios (429/503), clasificación de fallback (`rate_limit`/`transient`/`auth_or_config`/`content_filtered`/`unknown`) expuesta al usuario con mensajes accionables.
- `backend/services/data_fetcher.py` — `MarketDataFetcher` (yfinance) y `FREDDataFetcher` (FRED). **Todo dato tiene un campo `source: "live"|"synthetic"`**; con `ALLOW_SYNTHETIC_DATA=false` (default), una fuente caída tira error explícito en vez de inventar datos. La caché preserva `source` original y agrega `from_cache`/`cached_at` como campos separados (no los mezcles).
- `backend/services/backtest_engine.py`, `correlation_engine.py`, `portfolio_engine.py` (Markowitz + Risk Parity, shrinkage Ledoit-Wolf, μ por James-Stein/equal/forecast), `risk_engine.py` (Monte Carlo VaR/CVaR: bootstrap por bloques/Student-t/Gaussiano), `rebalance_engine.py` (backtest walk-forward de rebalanceo con costos de transacción, sin look-ahead bias).
- `backend/services/llm_availability.py` — chequea qué proveedores de LLM están realmente disponibles (keys configuradas, CLIs instalados/autenticados), con caché corto (60s) salvo casos de rechazo permanente de cuenta (24h).
- Guard universal: **ningún endpoint cuantitativo (backtest, correlación, portfolio, risk, rebalance) acepta una serie con `source="synthetic"`** — 422 explícito.

**Frontend** (React 19 + TS): dashboard con pestañas (Proyección, Reality Check/Backtest, Correlaciones, Gráfico Dual-Axis, Asignación y Riesgo), cada una con un panel colapsable "¿Qué estoy viendo?" explicando las métricas en criollo. Selector de proveedor LLM en el Header (cambio en caliente, sin reiniciar el server). Badges de transparencia: qué motor de forecast respondió, qué LLM respondió realmente (no solo el configurado — si cayó a mock, lo dice y por qué).

**Docker**: imagen liviana default (sin `torch`/`timesfm`; ~814MB medido en una ronda anterior, no re-verificado) + `Dockerfile.timesfm` opcional para GPU/inferencia real.

## 3. Hallazgos importantes de la historia del proyecto (contexto que explica por qué el código es como es)

- **El benchmark original de TimesFM estaba fabricado.** La primera versión del script de benchmark simulaba la salida de TimesFM con una fórmula (`holt_pred * 0.98 + rw_pred * 0.02`) en vez de correr el modelo real. Se corrigió para que, sin pesos reales cargados, el benchmark diga explícitamente "no evaluado" en vez de inventar un número.
- **TimesFM real, benchmarkeado en serio, pierde contra Holt en la mayoría de acciones individuales y en índices/ETFs diversificados (SPY, QQQ).** Solo gana de forma consistente en series FRED con estacionalidad estructural real (producción industrial, gas natural, etc.). Contra un rival estacional justo (Holt-Winters, 3.0c+d), la ventaja es firme solo en IPG2211A2N; en HOUSTNSA y RSAFSNA es probable, y en MRTSSM4451USN no es significativa (`docs/results/seasonal_benchmark_2026-09-26.md`). Esto es coherente con la literatura: modelos fundacionales zero-shot generalizan bien en dominios con patrones recurrentes, pero un modelo clásico ajustado a la serie específica (Holt vía MLE) le gana en series financieras idiosincráticas de alta volatilidad. Este hallazgo motivó el `EngineSelector`.
- **El cono de confianza de Holt estaba mal calibrado originalmente** (fórmula heurística inventada, cobertura empírica real de 64% contra un objetivo de 95%). Se corrigió con la fórmula analítica correcta y se validó con simulación Monte Carlo (45.000 evaluaciones, cobertura final ~96%). Sobre datos reales (2.5, 24 cutoffs × 14 series), la cobertura de acciones y ETFs quedó por encima de la nominal (97,3% y 97,6% contra 95%), con fallos concentrados en pocos episodios (`docs/results/holt_coverage_2026-09-26.json`).
- **Un bug de caché borraba la procedencia de los datos**: al servir desde caché, `source` se sobreescribía a `"cached"`, perdiendo si el dato original era real o sintético — lo que permitía que datos inventados pasaran los guards de "solo datos reales" después del primer hit de caché. Se separó en dos campos independientes (`source` + `from_cache`).
- **El catálogo fijo de series para TimesFM no escalaba.** Al principio solo 4 series de FRED, elegidas a mano en una ronda de benchmark, tenían el motor "correcto" asignado. Cualquier serie nueva que el LLM trajera caía a Holt sin haber sido evaluada nunca. Se complementó con auto-discovery: cualquier serie fuera de los catálogos se autoevalúa la primera vez y se cachea la decisión. Los catálogos siguen existiendo y se consultan primero.
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

- **El Reality Check de series FRED fuera del catálogo devuelve 400** (2.7 de `docs/PLAN.md`, primero en el orden). `/api/backtest` no recibe si la serie es de FRED, y `BacktestEngine` busca en yfinance cualquier serie que no esté en `FREDDataFetcher.SERIES_CATALOG` (verificado con UNRATE en 2.6).
- **Mini-backtest sin cutoffs no se cachea.** Si `_pick_cutoffs` devuelve `[]`, el mini-backtest falla a propósito (antes cacheaba un MASE NaN como "holt"), así que se reintenta en cada request de esa serie, con un `logger.warning` cada vez. Los datos no se re-descargan en cada request, porque el fetcher los cachea en memoria 1 hora (`CACHE_TTL_SECONDS`). Caso raro: con el criterio v4 (`recent_cutoff_indices`, 30 puntos de horizonte), requiere menos de 90 puntos en el re-fetch cuando el selector ya vio 90 o más. Si molesta, la opción es un caché negativo corto.
- **Dependencias: rangos y lock.** El drift de la máquina local (pandas, yfinance, fastapi y uvicorn fuera de rango) se resolvió subiendo los rangos (#19). Desde 2.4 hay `requirements.lock` (generado con `uv pip compile --universal`), que instalan `.venv` y Docker. `requirements-timesfm.txt` queda fuera del lock y se instala con `-c requirements.lock`. El Python global de la máquina todavía tiene las versiones viejas: usar `.venv\Scripts\python`.
- El caché de 24h de "cuenta de Gemini CLI rechazada" no se invalida si el usuario cambia de cuenta de Google (solo por tiempo o reinicio del server) — mejora menor pendiente, no crítica porque el peor caso es esperar hasta 24h para que un cambio de cuenta se refleje.
- `CorrelationEngine` tiene el mismo problema de catálogo rígido que motivó el auto-discovery de forecast: cualquier FRED ID que no esté en su `SERIES_CATALOG` fijo de 5 series (válido o no) se enruta a yfinance y falla. Ojo: el ejemplo que figuraba acá, `IPG2211N`, es un ID válido de FRED (mensual NSA). El problema es el ruteo por catálogo, no la ortografía. Lo absorbe 4.11 de `docs/PLAN.md`. Es el mismo problema que 2.7 en el backtest.
- La cuenta de Gemini CLI del usuario está permanentemente rechazada por Google (`IneligibleTierError`, ver sección 3) — el sistema ya lo detecta y lo comunica bien, no es un bug a resolver, es un hecho externo a vivir con él. Usar Claude CLI o la API key de Gemini.

## 7. Estado del repo

`main` @ `16b6782` (2026-09-27). `pytest -q` en `main`: `233 passed, 2 warnings`.

Últimos mergeados:
- #33: criterio v4 del auto-discovery (2.3).
- #34 y #36: horizonte del mini-backtest (2.3b) y arrepentimiento (2.3c), medidos. v5 no se adoptó.
- #35: horizonte en la unidad de la serie (4.14).
- #37: marca "no confiable" y diagnóstico de la explosión de Holt (2.6).

Organización del trabajo:
- `docs/PLAN.md` (versionado) tiene las fases 0 a 5 como checklist, cada ítem con su rama y su criterio de "hecho", y el orden acordado. Los criterios que deciden algo después de medir se **pre-registran con fecha** ahí antes de medir (por ejemplo, v5 y la variante C de Holt, para las series de 3.5).
- `docs/adr/` tiene las decisiones de diseño (formato Nygard), con PR, commit y resultados.
- `.bitacora/RONDAS.md` es local y está ignorado por git (`.gitignore`). Tiene una entrada por ronda: salida real de pytest, qué quedó sin verificar y decisiones.
- Los PRs se mergean solo cuando el usuario escribe "ok #N" en el chat.

`tests/conftest.py`:
- fija `DATABASE_URL` a un SQLite temporal antes de importar `backend`, y aborta la suite si el engine no es esa DB: los tests nunca tocan la DB real;
- tiene un fixture `autouse=True` que limpia el caché de disponibilidad de LLM entre tests.

## 8. Variables de entorno relevantes (`.env`)

- `GEMINI_API_KEY`, `FRED_API_KEY`, `OPENAI_API_KEY` (opcional).
- `LLM_PROVIDER`: `gemini`, `gemini_cli`, `claude_cli`, `openai`, `ollama`, `auto` o `mock`. `auto` elige `gemini` si hay key, si no `openai`, si no `mock`.
- `CLAUDE_CLI_MODEL`: default `haiku`, para gastar menos del cupo compartido.
- `OLLAMA_BASE_URL`.
- `DATABASE_URL`: la DB real por defecto. Las verificaciones apuntan a una copia; los tests, a un SQLite temporal.
- `ALLOW_SYNTHETIC_DATA`: default `false`; no tocar salvo en una demo offline consciente.
- `USE_REAL_TIMESFM`: default `true`. Controla si TimesFM está disponible como opción; qué motor corre en cada serie lo decide el `EngineSelector`. Con `true`, el backtest del panel Reality Check usa TimesFM (`get_forecast_engine`); con `false`, Holt.
- `FORECAST_ENGINE`: solo cuenta con `USE_REAL_TIMESFM=false`; `timesfm` fuerza TimesFM, y cualquier otro valor (`mock` en `.env.example`) usa Holt.
- `CACHE_TTL_SECONDS`.
