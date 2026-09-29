# ADR-0030: Prompt de traducción de tesis v2 (4.10)

## Contexto

El prompt que traduce una tesis a una cartera pedía:
- entre 3 y 6 tickers con pesos que suman 1, más un racional de "por qué
  este activo se beneficia de la tesis";
- entre 1 y 4 series de FRED, en segundo plano.

No pedía el mecanismo ni qué dato refutaría la tesis. Empujaba a
confirmarla con acciones sueltas, sin benchmark. Los textos de empresa
mezclaban hechos (cuotas, contratos, cifras) sin fuente con opiniones del
LLM, y la UI los mostraba igual. Los 4 ejemplos de la UI eran de tecnología,
IA y electricidad.

## Decisión

- **Orden del prompt nuevo**, en todas las variantes (Gemini, Gemini CLI,
  OpenAI, Ollama, Claude CLI y el mock):
  1. mecanismo causal;
  2. drivers medibles (series de FRED, con el eslabón que miden);
  3. qué dato la refutaría (condiciones con variable y dirección o umbral);
  4. instrumentos: ETFs, commodities y tasas antes que acciones sueltas.
     SPY es el benchmark obligatorio, fuera de los pesos, y la app lo fija
     siempre.
- **Fuentes:** un hecho concreto de una empresa va con `source`, o `source`
  queda en null. La UI marca cada texto:
  - "Afirmación del LLM, no verificada";
  - "Fuente citada por el LLM: … (la app no la verificó)", si trae fuente;
  - "Texto de plantilla local (sin LLM)", si lo escribió el mock.
- **Variante de Claude CLI:** system prompt corto, con las reglas en las
  descripciones del `--json-schema`.
  - Con la lista numerada como system prompt, Haiku ignoró el schema (3 de 3
    intentos).
  - El timeout del CLI pasa de 45 a 120 s, porque la respuesta es más larga.
- **Persistencia:** `theses.analysis_json` guarda mecanismo, refutación,
  benchmark y versión, con migración.
- **UI:** muestra "Mecanismo", "Qué la refutaría" y "Benchmark". Los
  ejemplos son de sectores distintos: energía por IA, vivienda, consumo y
  agro.

## Consecuencias

- **Evaluación pre-registrada:** `docs/results/thesis_prompt_v2_2026-09-28.md`.
  - Con los dos modelos de Claude CLI, el prompt nuevo trae refutación
    medible en todas las corridas (el viejo en ninguna).
  - El peso en acciones sueltas baja de 94% a 5% (Haiku) y de 51% a 18%
    (Sonnet), y el primer instrumento deja de ser una acción.
  - La relevancia de las series cambia poco.
  - Haiku con el prompt nuevo usó `source` para afirmaciones y cometió
    errores de hecho; Sonnet no.
- **Evaluado parcialmente con Gemini**, el proveedor configurado hoy. En la
  corrida del 28/9 se agotó el cupo gratuito diario. En la complementaria del
  29/9, con presupuesto cerrado (tope de 6 pedidos, un intento por celda), se
  usaron 4 pedidos y se cubrió **1 de las 4 tesis**: T1–T3 cayeron por `503
  UNAVAILABLE` (alta demanda del lado de Google), no por cupo — quedaban 16
  pedidos de los 20 diarios.
  - El desvío del protocolo (sin reintentos, por el presupuesto cerrado) es lo
    que convirtió esos 503 en "sin dato": el 28/9, con reintentos, los mismos
    503 se absorbían.
  - La única celda con respuesta tiene **formato válido** (ETFs primero,
    `instrument_type`, driver de FRED). Ninguna celda rompió el formato.
  - Sin tabla por criterio para Gemini con 1 de 4 tesis.
  - **Incompleto pero no bloqueante:** el cliente de Gemini fuerza la salida
    JSON con `response_mime_type="application/json"`
    (`backend/services/llm_router.py:527`), la respuesta obtenida es válida, y
    en producción los 503 se reintentan (el intento único vive solo en el
    arnés de evaluación).
- La decisión de qué prompt queda y qué modelo usar por defecto (4.6) es del
  usuario, con la tabla completa.

## Estado

Propuesta: implementada en la rama, a decidir con la tabla.

## Referencias

- Pre-registro `8b258da`.
- Rama `feat/thesis-prompt-v2`.
- Tests: `tests/test_thesis_prompt_v2.py`, `MetricCards.test.tsx` y
  `App.test.tsx`.
