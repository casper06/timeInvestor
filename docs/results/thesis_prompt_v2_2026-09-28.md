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

## Latencia por modelo (segundos por traducción de tesis)

Es el tiempo de pared de `parse_thesis`, reintentos internos incluidos.

| Modelo | Prompt | n | Mediana | Máxima |
|---|---|---|---|---|
| Gemini | viejo | 5 (principal T1–T2 + complementaria T1–T3) | 29,3 | 31,0 |
| Gemini | nuevo | 0 | sin dato | sin dato |
| Haiku | viejo | 4 | 31,8 | 169,8 (T2; timeout de 45 s y reintentos) |
| Haiku | nuevo | 4 | 89,4 | 191,0 |
| Sonnet | viejo | 4 | 35,3 | 48,1 |
| Sonnet | nuevo | 4 | 48,9 | 72,1 |

La mediana supera los 30 s en todos los casos con datos salvo Gemini con el
prompt viejo (29,3). Por eso la UI muestra un indicador de progreso mientras
traduce ("Traduciendo la tesis con <proveedor>…" y el tiempo transcurrido).

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
   - El 29/9, con presupuesto cerrado (un intento por celda), se cubrió **1 de
     las 4 tesis** del prompt nuevo: las otras tres cayeron por `503` de alta
     demanda, no por cupo. Ver "Corrida complementaria de Gemini (29/9/2026)".
   - **Gemini con el prompt nuevo queda con 1 de 4 tesis**, sin tabla por
     criterio.

## Corrida complementaria de Gemini (29/9/2026, 18:42–18:43 hora local)

Presupuesto cerrado, arnés de `a8fd978`: tope de 6 pedidos HTTP, **un intento
por celda, sin reintentos automáticos**. Solo el prompt nuevo, las 4 tesis en
el orden pre-registrado.

**Pedidos usados: 4 de 6** (0 rechazados por el tope).

| # | Tesis | Pedido | Hora | Estado |
|---|-------|--------|------|--------|
| T1 | Demanda eléctrica por centros de datos de IA | 1 | 18:42:26 | sin dato (503) |
| T2 | La IA es una burbuja | 2 | 18:42:41 | sin dato (503) |
| T3 | Impacto de tasas de interés en múltiplos tecnológicos | 3 | 18:42:56 | sin dato (503) |
| T4 | Las tasas hipotecarias altas frenan la construcción de viviendas en EE.UU. | 4 | 18:43:11 | **ok**, formato válido |

**Tesis cubiertas: 1 de 4.** Crudo en
`thesis_prompt_v2_gemini_complementaria_2026-09-29.json`.

- **El corte no fue por cupo.** Las tres fallas son `503 UNAVAILABLE`, *"This
  model is currently experiencing high demand"*: indisponibilidad del lado de
  Google. El cupo diario se había renovado (04:00 hora local) y quedó en 4 de
  20 pedidos usados. Un agotamiento de cupo se habría visto como el `429` con
  `quotaId ...PerDay...` que cortó la corrida del 28/9, y no aparece.
- **Formato:** la única celda con respuesta (T4) es válida y muestra el prompt
  nuevo funcionando — 4 instrumentos ETF primero (ITB, XHB, WOOD, TLT),
  `instrument_type` poblado y `MORTGAGE30US` como driver de FRED. **Ninguna
  celda rompió el formato**; T1–T3 no tienen formato que validar porque no
  hubo respuesta.
- **Sin tabla por criterio para Gemini.** Con 1 de 4 tesis, ponerla al lado de
  Haiku y Sonnet (4 de 4 cada uno) invita a leer una diferencia de prompt
  donde solo hay ruido de disponibilidad del proveedor.

### Desvío respecto del protocolo original

El pre-registro reintentaba cada falla hasta 3 veces con 60 s de espera. El
presupuesto cerrado lo reemplaza por **un solo intento por celda**, para que
el gasto sea acotado y conocido de antemano.

Ese desvío es exactamente lo que convirtió estos 503 en "sin dato". El 28/9,
con reintentos, los mismos 503 se absorbían: T1 falló dos veces con 503 y aun
así terminó `ok` al tercer intento. Hoy, el primer 503 mata la celda. El arnés
hizo lo que dice hacer; lo que faltó fue margen para un proveedor inestable.

### Condiciones de la corrida

- Clave de Gemini **exclusiva de TimeInvestor** (termina en `omgw`). Se
  verificó que el otro proyecto local ("Asistente de inversiones") no usa
  Gemini, comparando solo los últimos 4 caracteres.
- **Sin consumo concurrente**: no había otro proceso con acceso a la clave.
- **DB real intacta**: la corrida usó una COPIA en el scratchpad
  (`DATABASE_URL` con "eval" en el nombre, como exige el arnés).

### Conclusión

**Evaluación de Gemini incompleta, y no bloqueante para 4.10.** Tres razones:

1. el cliente de Gemini **fuerza la salida JSON** con
   `response_mime_type="application/json"` (`llm_router.py:527`), así que el
   modo de falla de formato que sí tuvo Haiku con el CLI no aplica acá;
2. la única respuesta obtenida es **válida y bien formada** con el prompt
   nuevo;
3. en producción los 503 **se reintentan** (`_call_with_retry`, con backoff);
   el intento único existe solo dentro del arnés de evaluación.

Queda pendiente, si se quiere la tabla completa de Gemini, correr T1–T3 un día
con el proveedor estable.

## Propuesta (la decisión es del usuario)

- **4.10, qué prompt queda:** el nuevo.
  - Mejora C2 y C3 en los dos modelos con datos, sin empeorar C1.
  - Con Gemini queda evaluado en 1 de 4 tesis (29/9): esa celda salió con
    formato válido. Es incompleto, pero **no bloqueante**: el cliente de
    Gemini fuerza el JSON con `response_mime_type` y en producción los 503 se
    reintentan.
  - Si se quiere la tabla completa de Gemini, correr T1–T3 un día con el
    proveedor estable.
- **4.6, qué modelo de Claude CLI por defecto:** Sonnet, si el costo de
  tiempo y uso es aceptable.
  - Con el prompt nuevo, Haiku propuso series irrelevantes e inexistentes
    en T1, usó `source` para afirmaciones y cometió errores de hecho.
    Sonnet no.
  - Haiku no es más rápido con el prompt nuevo en estas corridas.
