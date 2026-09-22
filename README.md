# TimeInvestor

Motor cuantitativo y de proyección de tesis de inversión: ingesta datos reales
de mercado (yfinance) y macro (FRED), proyecta series temporales, hace backtest
walk-forward contra un benchmark naive, optimiza carteras (Markowitz / Risk
Parity), simula rebalanceo con costos de transacción, y usa un LLM (Gemini /
OpenAI / Ollama / motor heurístico local) para traducir una tesis en lenguaje
natural a una selección de activos.

## Quickstart

```bash
cp .env.example .env   # completar FRED_API_KEY / GEMINI_API_KEY según necesidad
pip install -r requirements.txt
python run.py           # compila el frontend si hace falta y sirve todo en :8000
```

Ver `.env.example` para el detalle de cada variable de entorno.

### Desarrollo (backend y frontend por separado)

```bash
# Backend
pip install -r requirements.txt
python run.py --no-browser

# Frontend (hot reload)
cd frontend
npm install
npm run dev
```

### Tests

```bash
python -m pytest tests/          # backend
cd frontend && npm run test      # frontend
```

### Docker

```bash
docker compose up --build
```

La imagen default (`Dockerfile`) es liviana: no instala `torch`/`transformers`.
Para el motor real de TimesFM (PyTorch + CUDA), ver `Dockerfile.timesfm` y
`requirements-timesfm.txt`.

## Selección de motor de proyección: Holt vs TimesFM por serie

TimeInvestor no usa un único motor de proyección para todo el sistema. En vez
de un interruptor global (`USE_REAL_TIMESFM=true/false` para todas las
series), `EngineSelector` (`backend/services/engine_selector.py`) elige el
motor **por serie individual**, según qué demostró funcionar mejor en un
benchmark walk-forward con datos reales (`scripts/benchmark_real_data.py`), no
según qué "debería" andar mejor.

| Categoría | Motor ganador | Evidencia |
|---|---|---|
| Series FRED estacionales (`IPG2211A2N`, `RSAFSNA`, `HOUSTNSA`, `MRTSSM4451USN`) | **TimesFM** | Ganó 4/4 series (MASE muy inferior a Holt) |
| Índices/ETF diversificados (`SPY`, `QQQ`, `XLE`, `XLK`) | **Holt** | TimesFM no ganó en ninguna (0/4) — la hipótesis inicial no se sostuvo |
| Historia corta / cold-start (contexto de 30/60/90 días) | **Holt** | TimesFM ganó en, como mucho, 1 de 4 tickers en cualquiera de las tres ventanas — nunca alcanzó el umbral en ninguna |
| Acción individual, historia completa (default) | **Holt** | Comportamiento sin cambios; no es una categoría nueva |

La regla que decide es objetiva y se aplica igual a cualquier categoría futura:
**una categoría solo enruta a TimesFM si TimesFM ganó (menor MASE promedio) en
al menos el 50% de sus series representativas** en el benchmark real. Si no
llega a ese umbral, se queda en Holt — sin excepción por intuición.

Cada respuesta de `/api/forecast` incluye `engine_selection_reason`, un texto
que explica por qué se eligió ese motor para esa serie puntual (visible en el
frontend junto al nombre del motor activo).

Ver [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) para:
- El diagrama de flujo de decisión del `EngineSelector`.
- El diagrama de arquitectura general del sistema.
- El detalle completo del benchmark y los números de MASE/cobertura por serie.
- La Variante B (selección en tiempo real vía mini-backtest por request) y por
  qué no está implementada todavía — con la estimación de latencia medida.

## Glosario de series FRED

Los IDs de FRED (`IPG2211A2N`, `PCU221110221110`, ...) no son autoexplicativos.
El endpoint `GET /api/catalog/fred-metadata?series_id=X` devuelve el `title` y
`notes` reales que FRED publica para esa serie (nunca una descripción escrita
a mano) — visible en la interfaz como un ícono (ⓘ) junto a cada tab de serie
FRED en "Serie Activa:".

## Mensajes de fallback accionables

Cuando el LLM configurado (Gemini/OpenAI/Ollama) falla y el sistema cae al
motor heurístico local, la respuesta incluye `fallback_category`
(`rate_limit` / `transient` / `auth_or_config` / `unknown`), para que el
usuario sepa si conviene esperar o si necesita revisar su configuración —
mostrado en el tooltip del badge de proveedor LLM en el frontend.
