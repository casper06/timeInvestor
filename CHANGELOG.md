# Changelog

## v1.0 — 2026-09-30

Primera versión completa de TimeInvestor.

### Qué hace

Escribís una tesis de inversión en lenguaje natural ("boom de semiconductores
por IA", "las tasas hipotecarias frenan la construcción"). Un LLM la traduce a
una cartera de instrumentos y a indicadores macro de FRED, y el sistema corre
proyecciones, backtests, correlaciones, optimización de cartera y simulación de
riesgo sobre eso. Todo local: FastAPI + SQLite + React, un solo usuario.

La traducción no se toma por buena:

- **Los IDs de FRED se verifican contra FRED** antes de llegar a la pantalla. Si
  el LLM inventó uno, se busca el concepto y el propio LLM elige un reemplazo
  real de esa lista, o lo descarta con su motivo. Nada entra sin que FRED lo
  confirme (ADR-0033).
- **Los instrumentos se verifican contra yfinance**: nombre, tipo, emisor y
  categoría reales. Si la descripción del LLM los contradice —"PSQ: inverso 3x
  de Direxion", cuando es de ProShares y −1x— el LLM la corrige con los datos
  reales. Una corrección nunca cambia la dirección de la apuesta ni agrega
  apalancamiento (ADR-0034).
- Lo que no se puede verificar ("líder del mercado") **queda rotulado como
  afirmación del LLM**, no se presenta como hecho.

### Qué se sabe que se puede pronosticar, y qué no

Esto se midió, no se supone. El motor se elige **por serie**, no por fe:

- **TimesFM gana en algunas categorías y pierde en otras.** El motivo de ser del
  proyecto era que TimesFM fuera el corazón predictivo; la evidencia dio un
  resultado más matizado, y quedó documentado tal cual.
- **En muchas series, ningún modelo le gana al naive.** Cuando el pronóstico no
  supera a "igual que el último dato", la app lo dice en la cara con un badge y
  muestra el rango antes que el punto central. Un pronóstico puntual que no
  supera al naive no merece tres decimales de confianza.
- **El 95% del cono es un promedio sobre muchas ventanas históricas**, no una
  promesa sobre esta: queda ancho en períodos tranquilos y corto en shocks. La
  cobertura real de cada serie se mide en Reality Check.
- **Con datos de época, algunas capacidades no se sostienen.** En HOUST, INDPRO
  y JTSJOL el modelo le gana al naive con la serie revisada de hoy, pero no con
  los datos como se publicaron entonces. El badge lo dice cuando corresponde.

### Limitaciones conocidas

- **Un solo usuario, local.** No hay autenticación ni multiusuario.
- **El LLM elige las empresas.** Las que aparecen en una tesis las eligió el
  modelo: no son una muestra representativa y no confirman nada. La app lo
  repite donde hace falta, incluido el copiloto.
- **Cupos de los proveedores.** El proveedor principal recomendado es **Claude
  CLI con Sonnet**, que se activa con `LLM_PROVIDER=claude_cli` en el `.env`.
  El default del código sigue siendo `gemini` porque Claude CLI **requiere
  tener Claude Code instalado** (`npm install -g @anthropic-ai/claude-code`) y
  autenticado, que no se puede asumir en una instalación nueva. Gemini queda de
  respaldo con su plan gratuito: **20 pedidos por día y por modelo**, y cada
  llamada consume hasta 3 por los reintentos. Claude CLI comparte cupo con el
  uso interactivo de Claude Code.
- **`docker compose build` no verificado en el cierre de v1.0.** Docker Desktop
  no estaba levantado (el cliente 29.8.0 está instalado; el daemon no
  respondía). El resto del chequeo de punta a punta sí se corrió: venv limpio
  desde `requirements.lock`, `pytest`, `vitest`, datos reales y la app entera
  en el navegador.
- **Sin datos sintéticos.** Con `ALLOW_SYNTHETIC_DATA=false` (el default), una
  fuente caída es un error explícito, no un número inventado. Ningún endpoint
  cuantitativo acepta una serie sintética.
- **TimesFM real es opcional.** La imagen liviana no lo trae; hay un
  `Dockerfile.timesfm` aparte. Sin los pesos, dos tests se saltean diciendo por
  qué.
- **El backtest no es asesoramiento.** Mide si un modelo le gana a un naive en
  una serie, no si conviene comprar algo.

### Lo que queda pendiente

En `docs/PLAN.md`, dividido en **Pendiente documentado** (opcional, no bloquea:
por ejemplo la estimación robusta de Holt tras un salto, o torch en la imagen
CUDA) y **Futuro** (TimesFM-3, el examinador de tesis, el modo crash y cuatro
líneas de investigación).
