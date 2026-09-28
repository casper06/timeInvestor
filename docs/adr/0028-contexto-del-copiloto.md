# ADR-0028: Contexto del copiloto: fechas, evidencia de FRED y empresas elegidas por el LLM

## Contexto

El copiloto (`/interpret`) recibía:
- el último precio, el objetivo, la banda y el CAGR, **sin fechas**;
- los IDs de las series FRED de la tesis, **sin sus valores**;
- un `capex_summary` de las empresas.

Cada cliente armaba ese texto por su cuenta: Gemini, Gemini CLI y Claude CLI
con una lista; OpenAI y Ollama, con el JSON crudo. El resultado real, con
Gemini y la tesis de demanda eléctrica, fue "Tesis Confirmada" porque "la
aceleración del Capex en todo el ecosistema valida…". Ese ecosistema son las
empresas que eligió el propio LLM. También apareció "incertidumbre
regulatoria en contratos de energía nuclear", que no estaba en los datos
(`docs/results/copilot_context_2026-09-27.md`).

El mock hacía lo mismo con frases fijas: "confirman la fase de
aceleración…", "el crecimiento sostenido de Capex reportado por los
hiperescaladores…".

## Decisión

- **Un solo contexto para todos los clientes**
  (`backend/services/copilot_context.py`, `interpretation_context_text`):
  - la fecha de hoy;
  - la fecha del último dato de la serie activa y la del objetivo;
  - "precio" solo si la serie es una acción;
  - cada fundamental con su período ("capex: último ejercicio cerrado 2025
    (2024: …)");
  - "Sin fundamentales: …" para las empresas sin datos.
- **Evidencia de indicadores del mundo.** El servidor (`/interpret`) baja
  cada serie FRED de la tesis y agrega su último valor, su fecha y el cambio
  a 12 meses.
  - En series en porcentaje, el cambio va en puntos porcentuales.
  - Título y unidad salen de FRED (`/fred/series`). Si no se pueden obtener,
    se dice "no informado"; nunca se usa el "Index" que el fetcher completa
    por defecto.
- **Empresas.** Se presentan como "seleccionadas por el LLM al traducir la
  tesis (no una muestra representativa; sus números no confirman la tesis)".
- **Reglas en los dos system prompts** (el del ejemplo JSON y el de Claude
  CLI con `--json-schema`):
  1. afirmar solo lo recibido;
  2. decir qué falta;
  3. la evidencia sale de FRED y similares; las empresas no confirman;
  4. todo dato con su fecha; la proyección es un modelo, no un dato.
- **El mock** dice solo lo que dicen los datos: los movimientos de FRED y
  qué falta. No dice si eso confirma la tesis.
- **Informe:** los fundamentales muestran una fila por empresa, para todas.
  Antes, un corte fijo de 15 filas dejaba solo CEG y ETN de cinco.

## Consecuencias

- Verificado con Gemini, la misma tesis y los mismos números, antes y
  después, sobre copias de la DB:
  - el "después" cita los indicadores de FRED con sus fechas y dice que las
    empresas no confirman la tesis;
  - todo lo que afirma coincide con los datos.
  - Queda una imprecisión: "seleccionada manualmente".
- `/interpret` hace un pedido a FRED por serie de la tesis (en caché).
- **Pendiente:** el fetcher sigue poniendo "Index" y "FRED Series X" a las
  series fuera del catálogo, y eso se ve en la UI.

## Estado

Aceptada.

## Referencias

- Rama `fix/copilot-context`.
- Tests: `tests/test_copilot_context.py`, `ThesisCopilot.test.tsx` y
  `exportReport.test.ts`.
