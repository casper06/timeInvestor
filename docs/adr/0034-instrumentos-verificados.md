# ADR-0034: Instrumentos verificados contra yfinance, y corregidos por el LLM (4.21)

## Contexto

La evaluación 4.10 encontró a Haiku describiendo **"PSQ: ETF inverso 3x del
Nasdaq-100, de Direxion"**. PSQ existe, pero es de **ProShares** y es **−1x**.
En la misma corrida usó el ETF **"IPO"** (Renaissance IPO ETF, un fondo
Mid-Cap Growth) como **exposición a semiconductores**.

Las dos frases se leen como hechos y nada aguas abajo podía distinguirlas de
una verdadera: el texto llegaba a la UI con el rótulo genérico "Afirmación del
LLM, no verificada", que es honesto pero no dice *qué* está mal.

Es el mismo problema que ADR-0033 resolvió para los IDs de FRED, y se resuelve
con el mismo patrón: **el LLM se corrige solo, dentro del mismo análisis, sin
preguntarle nada al usuario**.

## Decisión

`backend/services/instrument_grounding.py`, llamado desde `analyze_thesis`
junto al grounding de FRED.

### 1. Verificación

Por cada ticker, yfinance dice qué es realmente: nombre oficial, `quoteType`
(EQUITY/ETF), y para los fondos el emisor (`fundFamily`) y la categoría.

**Qué informa yfinance sobre apalancamiento e inverso** (verificado contra la
API real el 2026-09-30): **no hay campo de apalancamiento**. PSQ devuelve
`category: "Trading--Inverse Equity"`, `fundFamily: "ProShares"`,
`legalType: "Exchange Traded Fund"` — y nada numérico. Entonces:

- **inverso** se lee de la categoría y del nombre de yfinance ("Inverse",
  "Short"), nunca se infiere;
- **apalancamiento** se lee del multiplicador que el propio nombre trae
  ("3X", "Ultra" = 2x, "UltraPro" = 3x), y un fondo inverso sin multiplicador
  en su nombre es −1x (PSQ "Short QQQ" frente a SQQQ "UltraPro Short QQQ").

### 2. Comparación: reglas explícitas, no a ojo

| Regla | Contradicción cuando |
|---|---|
| R1 | `instrument_type` dice "etf" y yfinance dice EQUITY (o al revés) |
| R2 | el texto lo llama ETF y es una acción; o habla de "la empresa" y es un ETF |
| R3 | el texto nombra un **emisor conocido** distinto del `fundFamily` real |
| R4 | el texto afirma un multiplicador y los datos indican **otro** |
| R5 | es inverso y el texto no lo dice; o el texto lo dice y la categoría lo desmiente |
| R6 | el texto afirma una exposición temática (semis, energía, vivienda, oro) ausente de la categoría y del nombre del fondo |

Lo que **no** es contradicción, deliberadamente:

- una afirmación que yfinance no puede juzgar ("líder del mercado de GPUs");
- un multiplicador declarado cuando yfinance **no dice nada** de
  apalancamiento: ausencia de evidencia no es evidencia de ausencia, así que se
  deja pasar y sigue rotulado como afirmación del LLM;
- un emisor que el texto no menciona.

### 3. Reparación

Los tickers inexistentes y los contradictorios van en **UNA** llamada al mismo
proveedor (`complete_json`, el de ADR-0033) con los datos reales y la lista de
contradicciones. El modelo elige por cada uno:

- **`corregir_descripcion`**: el instrumento sirve, el texto mentía;
- **`reemplazar_ticker`**: por uno real, que **se re-verifica** contra yfinance
  (si tampoco existe, se descarta);
- **`descartar`**, con el motivo.

**La corrección también se verifica.** Si el texto nuevo sigue contradiciendo
los datos, queda registrado en `contradictions` y el aviso lo dice: la
respuesta del modelo no se acepta por venir del modelo. Una segunda vuelta
sería un bucle, así que se marca y se muestra.

Como en ADR-0033, las reglas van en las **descripciones del schema** y el
system prompt es de una línea: con un system prompt largo, Claude CLI ignora
`--json-schema` y responde Markdown libre.

### 4. Estados

Los mismos que en FRED: `verificado`, `reparado` (con la justificación
visible), `descartado` (aviso informativo) y `null` (yfinance no respondió — el
instrumento se conserva sin verificar, no se tira por un problema de red).
`enters_analysis()` deja pasar `verificado` y `reparado`.

**La descripción que se muestra es la corregida**, con el original guardado en
`original_thesis_role`. El rótulo "Afirmación del LLM, no verificada"
**se mantiene** incluso en un instrumento reparado: yfinance puede confirmar un
emisor, no si una empresa lidera un mercado.

### 5. Sin LLM disponible

Con el mock, o si la corrección falla, **se descarta**. Una descripción falsa no
se conserva en silencio.

## Consecuencias

- El caso PSQ queda marcado con el emisor y el apalancamiento reales, que es la
  condición de "hecho" de 4.21 en `docs/PLAN.md`.
- **Costo:** un `.info` de yfinance por ticker (ya cacheado por
  `MarketDataFetcher`), más **una** llamada extra al LLM solo si hubo
  problemas. Medido: **20,1 s** con Claude CLI Sonnet para tres instrumentos.
- La UI muestra, junto al texto: qué dice yfinance, qué se corrigió y por qué,
  y el aviso de lo descartado.

## Verificación

- **Tests sin red** (`tests/test_instrument_grounding.py`, 24): yfinance
  reemplazado por `fake_fetch` con los campos **reales** capturados el
  2026-09-30, y `StubRepairLLM` declarado en el propio archivo. Cubren los tres
  casos pedidos, las reglas una por una, lo que no debe marcarse, sin LLM, la
  corrección que falla y la corrección que sigue mintiendo.
- **Pasada real con Claude CLI Sonnet** (instrumentos forzados con el stub;
  yfinance y la corrección, reales), sobre una COPIA de la DB — **20,1 s**:

| Propuesto | Contradicción detectada | Resultado |
|---|---|---|
| `PSQ` "inverso **3x** de **Direxion**" | emisor Direxion vs ProShares; 3x vs 1x | **reparado**: "ETF inverso 1x sobre el Nasdaq-100, de ProShares…" — *"El emisor real es ProShares (no Direxion) y el apalancamiento es 1x, no 3x."* |
| `IPO` como semiconductores | categoría real "Mid-Cap Growth" | **reparado**: reemplazado por **SOXS** (Direxion Daily Semiconductor Bear 3X) — *"Renaissance IPO ETF es un fondo Mid-Cap Growth diversificado, no da exposición específica a semiconductores."* |
| `NVDIA` (no existe) | 404 de yfinance | **reparado**: reemplazado por **NVDA**, re-verificado — *"El ticker 'NVDIA' no existe; el correcto es NVDA."* |
| `NVDA` "líder del mercado de GPUs" | ninguna (no es verificable) | **verificado**, el texto queda intacto con su rótulo de afirmación |

  El reemplazo `IPO → SOXS` muestra por qué la corrección se vuelve a verificar:
  el modelo cambió de un fondo largo a uno **inverso apalancado**, coherente con
  la tesis bajista pero un instrumento muy distinto del propuesto. Su
  descripción sí coincide con los datos (Direxion, Bear 3X, inverso), así que
  pasa limpio; si no hubiera coincidido, el aviso lo diría.

## Estado

Aceptada.

## Referencias

- Rama `feat/instrument-grounding`.
- 4.21 en `docs/PLAN.md`; ADR-0033 (mismo patrón, para FRED), ADR-0030 (prompt
  v2, `source` y el modo de falla del `--json-schema`).
