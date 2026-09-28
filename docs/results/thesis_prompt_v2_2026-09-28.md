# Prompt de traducción de tesis: viejo contra nuevo, por modelo (4.10 + 4.6)

- **Pre-registro:** `docs/PLAN.md` 4.10, commit `8b258da` (2026-09-27 22:32).
- **Implementación:** `e1877cc` (22:40), después del pre-registro.
- **Salidas crudas:** `thesis_prompt_v2_2026-09-28.json` (pasada principal)
  y `thesis_prompt_v2_gemini_complementaria_2026-09-28.json`.
- **Juicios manuales, con su justificación:** `thesis_prompt_v2_judgments_*.json`.
- **Scripts:** `scripts/thesis_prompt_eval.py` y
  `scripts/thesis_prompt_score.py`.
- **Montaje:**
  - "viejo" = código de `main` (`adc9b4c`) en un worktree; "nuevo" = rama
    `feat/thesis-prompt-v2`.
  - DB: copia (Claude CLI registra su uso).
  - Mismo timeout de Claude CLI (120 s) para las dos versiones.

## Tabla completa (pasada principal)

Criterios pre-registrados:
- **C1a:** series que existen en FRED.
- **C1b:** de las que existen, cuántas miden un eslabón del mecanismo de
  referencia.
- **C2:** refutación (0 = no hay, 1 = no medible, 2 = medible).
- **C3a:** SPY en la salida del modelo. Con el prompt nuevo, la app lo pone
  siempre como benchmark; con el viejo, nunca.
- **C3b:** peso en acciones sueltas (`quoteType` EQUITY).
- **C3c:** el primer instrumento no es una acción suelta.
- **C4:** textos de acciones sueltas con hechos concretos sin fuente.

| Tesis | Prompt | Modelo | C1a | C1b | C2 | C3a SPY (modelo) | C3b acciones | C3c | C4 sin fuente |
|---|---|---|---|---|---|---|---|---|---|
| T1 | viejo | gemini | 3/3 | 2/3 | 0 | no | 100% | no | 5/5 |
| T1 | nuevo | gemini | sin dato | | | | | | |
| T1 | viejo | haiku | 2/3 | 0/2 | 0 | no | 100% | no | 5/5 |
| T1 | nuevo | haiku | 2/3 | 0/2 | 2 | no | 20% | sí | 1/1 |
| T1 | viejo | sonnet | 4/4 | 3/4 | 0 | no | 100% | no | 6/6 |
| T1 | nuevo | sonnet | 4/4 | 3/4 | 2 | no | 40% | sí | 0/2 |
| T2 | viejo | gemini | 3/3 | 3/3 | 0 | no | 35% | sí | 2/2 |
| T2 | nuevo | gemini | sin dato | | | | | | |
| T2 | viejo | haiku | 4/4 | 2/4 | 0 | no | 75% | no | 3/3 |
| T2 | nuevo | haiku | 3/4 | 2/3 | 2 | no | 0% | sí | 0/0 |
| T2 | viejo | sonnet | 4/4 | 4/4 | 0 | no | 0% | sí | 0/0 |
| T2 | nuevo | sonnet | 4/4 | 4/4 | 2 | no | 15% | sí | 1/1 |
| T3 | viejo | gemini | sin dato | | | | | | |
| T3 | nuevo | gemini | sin dato | | | | | | |
| T3 | viejo | haiku | 4/4 | 3/4 | 0 | no | 100% | no | 5/5 |
| T3 | nuevo | haiku | 4/4 | 4/4 | 2 | sí | 0% | sí | 0/0 |
| T3 | viejo | sonnet | 4/4 | 4/4 | 0 | no | 30% | sí | 2/2 |
| T3 | nuevo | sonnet | 4/4 | 4/4 | 2 | sí | 0% | sí | 0/0 |
| T4 | viejo | gemini | sin dato | | | | | | |
| T4 | nuevo | gemini | sin dato | | | | | | |
| T4 | viejo | haiku | 3/4 | 3/3 | 0 | no | 100% | no | 5/5 |
| T4 | nuevo | haiku | 4/4 | 4/4 | 2 | no | 0% | sí | 0/0 |
| T4 | viejo | sonnet | 4/4 | 4/4 | 0 | no | 75% | no | 4/4 |
| T4 | nuevo | sonnet | 4/4 | 4/4 | 2 | no | 15% | sí | 0/1 |

**Gemini fuera del protocolo:** una pasada complementaria el 2026-09-28,
después de que se renovara el cupo diario. Solo corrió el prompt viejo: T1
2/3, 0, 100%, 5/5; T2 2/3, 0, 15%, 1/1; T3 3/3, 0, 80%, 3/3; T4 sin dato. Con
el prompt nuevo no alcanzó ninguna corrida.

## Agregados (solo Claude CLI: las 4 tesis con los dos prompts)

| Modelo | Prompt | C1a | C1b | C2 = 2 | C3b promedio | C3c | C4 sin fuente | Segundos por tesis |
|---|---|---|---|---|---|---|---|---|
| haiku | viejo | 13/15 | 8/13 | 0/4 | 94% | 0/4 | 18/18 | 34, 170, 28, 29 |
| haiku | nuevo | 13/15 | 10/13 | 4/4 | 5% | 4/4 | 1/1 | 67, 103, 76, 191 |
| sonnet | viejo | 16/16 | 15/16 | 0/4 | 51% | 2/4 | 12/12 | 36, 48, 26, 35 |
| sonnet | nuevo | 16/16 | 15/16 | 4/4 | 18% | 4/4 | 1/4 | 72, 60, 38, 31 |

## Lectura

- **C2 y C3 cambian con el prompt en los dos modelos:**
  - C2: con el prompt nuevo, todas las corridas traen refutación medible
    (el viejo no la pide).
  - C3b: el peso en acciones sueltas baja de 94% a 5% (Haiku) y de 51% a 18%
    (Sonnet).
  - C3c: el primer instrumento deja de ser una acción suelta en todas.
- **C1 (series relevantes) cambia poco.** Sonnet tiene 15/16 relevantes con
  los dos prompts; Haiku pasa de 8/13 a 10/13.
  - En T1, Haiku propone con los dos prompts series que no son del
    mecanismo (INDPRO, el IPC de alimentos) e IDs que no existen (ELECMVS,
    ELECCCMI).
- **C4:** el prompt nuevo deja menos textos de hechos sin fuente, sobre todo
  porque hay menos acciones sueltas.
  - Sonnet puso las fuentes dentro del texto (comunicado de Constellation,
    10-K de Lennar) y dejó `source` en null. La UI lo marca "afirmación del
    LLM, no verificada", que es conservador.
- **Observaciones fuera de los criterios (Haiku con el prompt nuevo):**
  - usó `source` para afirmaciones, no fuentes (en T1 los 5 instrumentos);
  - errores de hecho: "PSQ: inverso 3x Nasdaq-100 de Direxion" (PSQ es de
    ProShares, −1x) y el ETF "IPO" usado como exposición a semiconductores.
  - Sonnet no tuvo errores de ese tipo en estas corridas.
- **Latencia:** con el prompt nuevo, Claude CLI tarda más: la respuesta
  estructurada es más larga (hasta 191 s en Haiku).

## Desviaciones del protocolo (dichas tal cual)

1. **Variante Claude CLI del prompt nuevo, corregida en medio de la
   evaluación.**
   - La primera versión llevaba las instrucciones numeradas como
     `--system-prompt`. Haiku ignoró `--json-schema` y devolvió Markdown
     libre: 3 de 3 intentos en T1. Es el mismo modo de falla que ya
     documentaba el código para el prompt viejo.
   - Se reescribió con un system prompt corto y las reglas en las
     descripciones del schema (`1a7290c`), y el timeout del CLI pasó de 45 a
     120 s.
   - Se descartó esa celda y **se corrieron de cero todas las celdas del
     prompt nuevo**.
   - Ni los criterios ni las tesis cambiaron.
2. **Timeout:** para no comparar timeouts distintos, el script usa 120 s en
   las dos versiones. Las celdas viejas de Haiku ya habían corrido con 45 s y
   salieron todas bien.
3. **Gemini:**
   - El cupo gratuito es de 20 pedidos por día y por modelo
     (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`), y cada intento
     consume hasta 3 por los reintentos internos.
   - En la pasada principal se agotó en T3: las celdas viejas T3 y T4 quedan
     "sin dato". La corrida del prompt nuevo se detuvo sin gastar intentos,
     y sus 4 celdas quedan "sin dato".
   - La pasada complementaria del día siguiente volvió a agotar el cupo antes
     de llegar al prompt nuevo.
   - **No hay datos de Gemini con el prompt nuevo.**

## Propuesta (la decisión es del usuario)

- **4.10, qué prompt queda:** el nuevo.
  - Mejora C2 y C3 en los dos modelos con datos, sin empeorar C1.
  - Queda sin evaluar con Gemini, que es el proveedor configurado hoy en la
    app.
  - Antes de adoptarlo como default con Gemini, correr las 4 celdas nuevas
    de Gemini con cupo disponible (o con un plan pago).
- **4.6, qué modelo de Claude CLI por defecto:** Sonnet, si el costo de
  tiempo y uso es aceptable.
  - Con el prompt nuevo, Haiku propuso series irrelevantes e inexistentes
    en T1, usó `source` para afirmaciones y cometió errores de hecho.
    Sonnet no.
  - Haiku no es más rápido con el prompt nuevo en estas corridas.
