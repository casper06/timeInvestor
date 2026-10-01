# Versión web con clave del usuario (BYOK) — análisis

**Estado:** análisis, sin cambios de código. Acompaña al ADR-0035 (Propuesta).
**Fecha:** 2026-09-30. Código analizado: `main` @ `5d7e363` (tag `v1.0`).

El caso: una web liviana, pocos usuarios, todos conocidos del dueño. Cada uno
pega **sus** claves —la de Gemini (u OpenAI) y la de FRED— en la página; quedan
en su navegador y viajan en cada pedido. El servidor las usa y no las guarda ni
las registra. **Objetivo explícito: el servidor no guarda ningún secreto**; lo
único secreto que tiene es el código de acceso. Sin Claude CLI ni Gemini
CLI. Las tesis se guardan en el navegador de cada usuario, sin cuentas. El
servidor no trae TimesFM (imagen liviana; las estacionales van con
Holt-Winters). Un código de acceso compartido impide que lo use gente de
afuera.

---

## 1. Inventario: qué asume hoy "un usuario, claves al arrancar"

| # | Dónde | Qué asume | Qué hay que hacer |
|---|---|---|---|
| 1 | `backend/config.py:29-32` | `FRED_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` se leen **una vez, del `.env`, al importar el módulo**. Son atributos de clase de `Settings`, no algo por pedido | **Ninguna de las tres** puede seguir viniendo de `settings` en el camino de un pedido: ni las de LLM ni la de FRED. `FRED_API_KEY` deja de existir en el `.env` del servidor |
| 2 | `backend/api/routes.py:71` | `fred_fetcher = FREDDataFetcher()` es un **singleton de módulo**, creado al importar, que captura `settings.FRED_API_KEY` en `self.api_key` (`data_fetcher.py:322-323`) | Hay que **eliminar el singleton**: capturaría la clave del primer usuario para siempre. Se construye un fetcher por pedido con la clave de ese pedido |
| 3 | `backend/services/llm_router.py:519-522` (`GeminiLLMClient.__init__`), `:1767+` (`get_llm_client`) | El cliente se construye **desde `settings`**, sin parámetros por pedido, y `get_llm_client()` no recibe contexto de quién pregunta | Hay que pasar la clave del usuario por parámetro hasta el cliente. Es el cambio más invasivo |
| 4 | `backend/config.py:41-45` + `routes.py:118-140` | `LLM_PROVIDER` es **estado global mutable**: `POST /api/config/llm-provider` escribe `settings.LLM_PROVIDER` en memoria, para todo el proceso | Con varios usuarios, **el que cambia el proveedor se lo cambia a todos**. El selector del Header tiene que volverse per-usuario (en el navegador), no per-servidor |
| 5 | `backend/services/llm_availability.py:96` | `_cache: Dict[str, Tuple[float, Availability, bool]]` es **global por proveedor**, con TTL 60 s (`:74`) y **24 h para el rechazo de cuenta** (`:77`, `:108-110`) | La clave del usuario A no puede decidir la disponibilidad para B. El caché tiene que ir **por clave** (por su hash), o desaparecer |
| 6 | `backend/services/data_fetcher.py:73` | `cache = SimpleCache(...)` global, con claves `yf_hist_…`, `fred_…` (`:88`, `:157`, `:326`, `:411`) que **no llevan identidad de usuario** | **Se puede dejar compartido**, y conviene: son datos públicos (FRED, yfinance) y la clave no es parte del índice. Compartirlo es lo que protege del rate limit. Ver 2.5 por la salvedad de FRED |
| 7 | `backend/database/models.py:11-26` | `theses` **no tiene columna de usuario**; `GET /api/theses` devuelve todas | Si las tesis van al navegador, la tabla no se usa para eso. Si algún día se quiere servidor, hace falta esa columna |
| 8 | `backend/database/models.py:83-95` | `engine_decisions` tiene **`series_id` como única PK** | **Se comparte a propósito**: la decisión de motor es una propiedad de la serie, no del usuario. Es trabajo caro que conviene amortizar entre todos |
| 9 | `backend/main.py:35-43` | CORS con `allow_origins` fijo a `localhost:5173/8000` y **`allow_credentials=True`** | Hay que poner el dominio real. Y `allow_credentials` deja de tener sentido: no hay cookies, la clave va por header |
| 10 | Todo el backend | **No existe ninguna función de redacción de secretos.** `grep -rn "redact\|sanitiz"` sobre `backend/` no devuelve nada | Hay que escribirla antes de aceptar claves ajenas |
| 11 | `backend/services/llm_router.py:671`, `:707` | Las claves **de LLM** ya se usan bien en headers (`Authorization: Bearer`), no en URLs | Nada que corregir; conviene mantener la regla |
| 12 | `data_fetcher.py:338-342`, `:411-418`; `fred_grounding.py:116-125` | **FRED exige la clave como parámetro de la query string** (`?api_key=…`); no acepta header. Es la única clave del sistema que va en una URL | No se puede cambiar el transporte hacia FRED: hay que **evitar que esa URL llegue a un log o a un mensaje de error** (ver el detalle abajo) |
| 13 | `FREDDataFetcher()` construido en **8 lugares fuera de `routes.py`**: `backtest_engine.py:81`, `correlation_engine.py:34`, `auto_discovery.py:554`, `engine_selector.py:169`, `series_routing.py:38`, `copilot_context.py:40`, `fred_grounding.py:174`, más el singleton de `routes.py:71` (y `search_fred_concept`, que ya recibe `api_key` por parámetro) | Casi todos están **dentro de servicios**, lejos del endpoint, y todos leen `settings.FRED_API_KEY` sin que nadie se la pase | Es el cambio más ancho del plan, más que el de LLM: la clave tiene que llegar a servicios que hoy no saben quién pregunta. Se resuelve en 2.1 con un contexto por pedido |

### El detalle que más importa del inventario

**Nada en el código escribe una clave a un log hoy a propósito**, pero tampoco
hay nada que lo impida. Hay dos caminos concretos por los que se escaparía con
claves ajenas:

- **LLM:** los mensajes de error de los proveedores se propagan enteros al
  usuario (`_format_fallback_reason`, `llm_router.py:492-502`) y se registran
  con `logger.error`. Un proveedor que devuelva la clave dentro de un mensaje de
  error la deja escrita en el log del servidor.
- **FRED, el más probable:** la clave va **en la URL**. Una excepción de `httpx`
  (timeout, error de conexión) suele incluir la URL pedida, y el código hace
  `logger.error(f"Failed to query FRED API: {e}")` (`data_fetcher.py:392`) y
  `raise ValueError(... {str(e)})` (`:466`), que sube al usuario. Además
  `logger.warning(f"FRED API returned HTTP …: {resp.text}")` (`:386`) registra el
  cuerpo de la respuesta. Hoy es inofensivo (es la clave del propio dueño); con claves
  ajenas, **una caída de red de FRED escribiría la clave de un usuario en el
  log**. Es el riesgo concreto, no teórico.

---

## 2. Diseño propuesto

### 2.1 Cómo viaja la clave

Un header por clave, en los pedidos que la necesitan:

```
X-LLM-Provider: gemini | openai
X-LLM-Key:      <la clave de Gemini/OpenAI del usuario>
X-FRED-Key:     <la clave de FRED del usuario>
```

Por qué un header y no el body ni la query:

- **nunca en la URL**: las query strings quedan en logs de acceso, en el
  historial del navegador y en el `Referer`;
- **no en el body**, para que un middleware pueda redactarla sin parsear JSON;
- **no en una cookie**, para que no viaje sola en pedidos que no la necesitan
  y no haya CSRF que pensar.

**Qué endpoints necesitan cuál.** La de LLM, pocos: `POST /api/thesis`,
`POST /api/interpret`, el copiloto y el chequeo de validez. **La de FRED, muchos
más**: cualquier ruta que toque una serie macro —series, metadata, backtest,
correlación, auto-descubrimiento, selección de motor, grounding de tesis—. Los
precios de yfinance no usan ninguna clave.

**Cómo llega la de FRED a servicios que no saben quién pregunta** (inventario
#13). Pasarla por parámetro por ocho firmas es invasivo y fácil de olvidar en
una. Propuesta: un **middleware** lee `X-FRED-Key` y la deja en una
`ContextVar` del pedido; `FREDDataFetcher.__init__` toma la clave de ahí en vez
de `settings`. Verificado que el backend **no usa** `ThreadPoolExecutor`,
`run_in_executor`, `create_task` ni `BackgroundTasks`, así que el contexto no se
pierde en un hilo suelto (Starlette lo copia al threadpool de las rutas `def`).
Si algún día se agregara trabajo en segundo plano, la clave **no** debe
sobrevivir al pedido: hay que decidirlo ahí, no heredarlo por accidente.

La `ContextVar` se vacía al terminar el pedido: la clave existe en memoria solo
mientras dura.

**Sin clave de FRED.** La ruta que la necesita responde un error claro ("Falta
tu clave de FRED"), no un dato de reemplazo. Es lo que ya hace el código con
`ALLOW_SYNTHETIC_DATA=false` (`data_fetcher.py:399-401`), que en el servidor
**tiene que quedar así**.

### 2.2 Redacción en logs y errores

Tres capas, porque una sola falla:

1. **Un `logging.Filter` global** que borre de todo registro cualquier cosa con
   forma de clave (`AIza[0-9A-Za-z_-]{35}` para Gemini, `sk-[A-Za-z0-9]{20,}`
   para OpenAI) y **todo `api_key=…` de una URL** (la de FRED son 32
   caracteres hexadecimales sin prefijo, así que el patrón por forma solo no
   alcanza: se redacta por el nombre del parámetro), sin importar quién la haya
   escrito. Es la red de seguridad.
2. **Redacción explícita en el manejo de errores del proveedor**: el mensaje
   que hoy se propaga entero (`_format_fallback_reason`) pasa por un
   `redact_secrets(text, keys)` que reemplaza la clave del pedido por
   `***`. Lo mismo para las excepciones y respuestas de FRED
   (`data_fetcher.py:386`, `:392`, `:466`), que hoy interpolan `{e}`,
   `{resp.text}` y `{str(e)}` sin tocar.
3. **Nunca registrar el header.** Ya hay precedente en el proyecto: el arnés de
   evaluación de Gemini "registra estado y cuerpo, nunca los headers"
   (`scripts/thesis_prompt_eval.py`).

Y una regla operativa: **el `access log` del servidor no debe incluir headers**.
Con uvicorn por default no los incluye; si se pone un proxy adelante, hay que
verificarlo.

### 2.3 Dónde se guarda en el navegador

**Default: `sessionStorage`**, para las dos claves. Viven mientras la pestaña
esté abierta y se borran al cerrarla. Para "pocos usuarios conocidos" que entran, prueban una
tesis y se van, es la opción correcta.

**Opción explícita "recordar en este navegador" → `localStorage`**, apagada por
default, con el texto diciendo qué implica: queda en el disco de esa máquina
hasta que la borre. Es una sola casilla para ambas claves, para que el usuario
no tenga que entender dos políticas.

Sobre **XSS**: hay que decirlo sin maquillaje. *Ninguna de las dos protege de
un XSS*: un script inyectado lee `localStorage` y `sessionStorage` por igual.
`sessionStorage` reduce la **ventana** (solo mientras la pestaña vive), no el
riesgo por pedido. Lo que sí protege es no tener XSS:

- **CSP estricta** sin `unsafe-inline` ni `unsafe-eval`;
- React ya escapa por default, y **el proyecto no usa
  `dangerouslySetInnerHTML`** — verificado: `grep -rn "dangerouslySetInnerHTML"
  frontend/src` no devuelve nada. Esa propiedad hay que conservarla, sobre todo
  porque **la app muestra texto generado por un LLM**;
- dependencias del frontend al día.

La alternativa "de verdad" sería que la clave no toque el navegador: un proxy
en el servidor con la clave por usuario. Pero eso es exactamente lo que el caso
pide evitar (sin cuentas, **el servidor no guarda ningún secreto**), y traería
el problema de custodiar claves ajenas. **BYOK en el navegador es la opción correcta para este
caso**, con los límites dichos.

### 2.4 Validar la clave y reportar los fallos

Un endpoint `POST /api/keys/validate` que hace **una** llamada mínima a cada
proveedor con la clave recibida y devuelve un estado por clave, sin guardarla.
Se llama cuando el usuario la pega, no en cada pedido. Para FRED, la llamada
mínima es pedir los metadatos de una serie conocida (p. ej. `UNRATE`), que es
barata y distingue clave inválida de red caída.

El proyecto ya tiene la clasificación que hace falta
(`classify_fallback_category`, `llm_router.py`): `rate_limit`, `transient`,
`auth_or_config`, `content_filtered`, `unknown`. Se reusa, con mensajes que
distinguen lo que el usuario puede arreglar:

| Caso | Qué ve el usuario |
|---|---|
| Clave inválida (`auth_or_config`) | "Esa clave no la acepta Gemini. Revisá que sea de AI Studio y que esté activa." |
| Sin cupo (`rate_limit`, 429 `PerDay`) | "Tu clave agotó el cupo gratuito de hoy (20 pedidos por día y por modelo). Se renueva a las 04:00 de tu hora local." |
| 429 por minuto | "Demasiados pedidos seguidos. Esperá un minuto." |
| Caído (`transient`, 503) | "Gemini no está respondiendo ahora. Volvé a intentar en un rato." |
| Sin clave | La app no llama al proveedor: pide la clave primero |
| Clave de FRED inválida (HTTP 400) | "FRED no acepta esa clave. Revisá que la copiaste completa (son 32 caracteres) y que no tenga espacios." |
| FRED caído o lento | "FRED no está respondiendo ahora. Volvé a intentar en un rato." |

Esto respeta la regla 6 de `CONTEXT.md`: el mensaje dice la causa real y si
conviene esperar o intervenir.

### 2.5 Aislar los cachés por clave

| Caché | Qué hacer | Por qué |
|---|---|---|
| `data_fetcher.cache` (yfinance, FRED) | **Compartido; la clave no entra en el índice** (`fred_{serie}_{limit}`, como hoy) | Son datos públicos: lo que devuelve FRED no depende de quién pregunta. Compartirlos baja la presión sobre yfinance y sobre el límite de cada clave de FRED (cada usuario gasta cupo solo en los fallos de caché). Ver la salvedad abajo |
| `llm_availability._cache` | **Por hash de la clave**: `sha256(key)[:16]` como parte de la clave del caché | Que la clave sin cupo de A no marque a Gemini "no disponible" para B. **Nunca la clave en claro como índice**, ni siquiera en memoria |
| `engine_decisions` (SQLite) | **Compartido, sin cambios** | Es una propiedad de la serie. Ver 2.6 |
| Respuestas del LLM | **No cachear entre usuarios** | Dos usuarios con la misma tesis pagan cada uno su llamada. Cachearlas mezclaría el gasto de cuotas ajenas y filtraría la tesis de uno al otro |

**Salvedad de FRED.** Con claves por usuario, un acierto de caché le
sirve a B un dato que costó la clave de A, y **se lo sirve igual aunque B no
tenga clave o la tenga inválida**. Se acepta, porque el dato es público y no hay
nada que proteger, pero hay que decidirlo a conciencia: **la validación de la
clave no puede apoyarse en "la serie volvió bien"**, porque puede ser un acierto
de caché. Por eso existe `POST /api/keys/validate` (2.4), que no pasa por el
caché. Y lo que **no** se debe cachear nunca es un fallo o un dato de reemplazo
(`data_fetcher.py:404-405` cachea la serie de referencia cuando
`ALLOW_SYNTHETIC_DATA=true`): la clave mala de A no puede dejarle un dato falso
a B. En el servidor ese flag queda en `false`, lo que lo vuelve imposible.

El caché de disponibilidad además debe **vaciarse al cambiar de clave** en el
navegador, para que el usuario no arrastre el rechazo de una clave vieja.

### 2.6 Qué se comparte y qué no

**Se comparte** (y está bien que así sea):

- **las decisiones de motor por serie** (`engine_decisions`): evaluar una serie
  cuesta hasta 16 backtests (`docs/ARCHITECTURE.md:355`). Que el primer usuario
  que mire UNRATE le ahorre esa espera a los demás es el mayor beneficio de
  tener servidor. No hay nada del usuario en esa fila: `series_id`, motor,
  MASEs y fecha;
- **los datos de mercado y de FRED** en caché, por la misma razón y porque
  bajan el riesgo de bloqueo de yfinance y el consumo de cupo de cada clave de
  FRED;
- **la evidencia versionada** (`CATALOG_RW_EVIDENCE`, `VINTAGE_EVIDENCE`): es
  parte del código.

**No se comparte:**

- **ninguna clave** (ni la de FRED ni la de LLM), ni nada derivado salvo el
  hash de la de LLM como índice del caché de disponibilidad;
- **las tesis**: van al navegador de cada uno (`localStorage`). El texto de una
  tesis dice en qué está pensando invertir alguien;
- **la disponibilidad del proveedor**, por 2.5;
- **el proveedor elegido**: hoy es global (`settings.LLM_PROVIDER`); pasa a ser
  del navegador y viaja en `X-LLM-Provider`.

### 2.7 La pantalla donde se piden las claves

Hoy la app no pide claves: el `.env` las trae y el Header solo muestra
`has_fred_key` / `has_gemini_key` (`routes.py:99-101`, `App.tsx:509`). En la web
esa pantalla pasa a ser **la puerta de entrada**, y la usa gente que quizá nunca
sacó una clave de API. Tiene que explicar, no solo pedir.

**Qué lleva, en este orden:**

1. **Código de acceso** (el compartido). Sin él no se ve nada más.
2. **Clave de FRED**, con el texto: *"Trae los datos económicos (desempleo,
   inflación, producción). Es gratuita y se saca en un minuto."* y el link a
   donde se consigue.
3. **Clave de Gemini**, con el texto: *"Traduce tu tesis a series y escenarios.
   Tiene un plan gratuito."* y el link, **más el aviso de datos** (abajo).
4. Un botón **"Probar claves"** que llama a `POST /api/keys/validate` (2.4) y
   muestra el estado de cada una, con los mensajes accionables.
5. La casilla **"Recordar en este navegador"** (2.3), apagada, con lo que implica.

**Dónde se consigue cada una** (hay que verificar los links antes de publicar;
son los canales oficiales):

| Clave | Dónde | Costo | Cómo se ve |
|---|---|---|---|
| FRED | `fredaccount.stlouisfed.org/apikeys` (cuenta gratuita de la Reserva Federal de St. Louis → *API Keys* → *Request API Key*) | **Gratuita** | 32 caracteres, letras minúsculas y números |
| Gemini | `aistudio.google.com/apikey` (con cuenta de Google → *Create API key*) | **Gratuita** en el plan gratuito, con cupo chico (5.2) | Empieza con `AIza` |

**Las dos son gratuitas**, y la pantalla lo dice explícitamente: es lo que
evita que alguien abandone creyendo que tiene que pagar. OpenAI queda como
opción avanzada y no figura en la pantalla por default (pregunta abierta 2).

**El aviso del plan gratuito de Gemini**, visible **junto al campo donde se pega
la clave**, no en un pie ni en unos términos aparte: *"Con la clave del plan
gratuito, Google puede usar lo que escribas para mejorar sus productos. No
escribas en la tesis nada que no quieras compartir con Google."* Es información
que cambia lo que alguien decide escribir (5.2), y la tesis dice en qué está
pensando invertir.

**Cómo se comporta la UI sin claves.** Sin la de FRED, las series macro quedan
deshabilitadas con el motivo a la vista (el mismo criterio que hoy usa la app
para "no ofrecer una opción que no funciona", `README.md` y
`llm_availability.py:5`). Sin la de Gemini, la tesis no se traduce y la pantalla
lo dice, en vez de caer en silencio al motor heurístico. Las series de
yfinance andan sin ninguna clave.

**Qué cambia en el código de UI.** `health.has_fred_key` y `has_gemini_key`
(servidor) dejan de significar nada: el servidor ya no tiene esas claves. El
estado pasa a ser **del navegador**: si hay clave guardada, y el resultado de
la última validación.

---

## 3. Seguridad

**HTTPS obligatorio, sin excepción.** La clave viaja en cada pedido: sin TLS,
cualquiera en el camino la lee. HSTS, y redirección de HTTP a HTTPS. Las tres
opciones de hosting de la sección 4 dan TLS gratis; no es un costo.

**El código de acceso compartido.** Un secreto en un header
(`X-Access-Code`), comparado con `secrets.compare_digest` (tiempo constante),
verificado en un middleware antes de cualquier ruta de API. Qué es y qué no es:

- **sirve** para que no entre alguien de afuera que encuentre la URL;
- **no sirve** para distinguir usuarios, ni para revocarle el acceso a uno
  solo: es compartido, si se filtra hay que cambiarlo para todos;
- con "pocos usuarios, todos conocidos" es proporcionado. Si el grupo crece o
  deja de ser de confianza, deja de alcanzar y hace falta autenticación real.

**Rate limiting**, en dos niveles y por motivos distintos:

1. **Por IP**, para el abuso general (p. ej. 60 pedidos/minuto). Protege al
   servidor;
2. **Por endpoint caro**, sobre todo los que pegan a yfinance (p. ej. 20
   pedidos/minuto): protege **la reputación del IP del servidor**, que es el
   único recurso del dueño que queda en juego. La clave de FRED ya no lo es:
   cada uno gasta la suya.

Los endpoints de LLM casi no necesitan límite propio: los paga la cuota del
usuario. Pero conviene uno igual, por si alguien usa el servidor de proxy.

**Qué guarda el servidor.** Solo el código de acceso. Ni la clave de FRED ni
las de LLM existen en su `.env`, su imagen, su base de datos ni sus logs. Lo que
eso implica:

- **No hay clave del dueño que robar, rotar ni agotar**, ni riesgo de que un
  tercero gaste un cupo de FRED ajeno a través del servidor.
- **Un volcado del servidor (disco, imagen, backup, `.env`) no filtra
  ninguna clave.** Lo único útil que contiene es el código de acceso, que se
  cambia en un minuto.
- **El riesgo se mueve a dos lugares**: el navegador del usuario (2.3) y los
  logs y mensajes de error del servidor (2.2). Por eso la redacción es
  prerrequisito y no un detalle: es lo único entre una clave ajena y el disco.
- **El abuso por la vía del servidor pesa menos**: un extraño que consiga el
  código de acceso gasta, como mucho, **sus propias claves**.

**Clave por pedido, dos veces.** La de FRED viaja en un header **del cliente al
servidor** y luego **en la URL del servidor a FRED** (inventario #12), porque
FRED no admite otra forma. Ese segundo tramo es TLS hacia `api.stlouisfed.org`,
no preocupa el transporte; preocupa que la URL aparezca en un log o en un
mensaje de error, que es lo que cubre 2.2.

**Si alguien abusa del servidor.** El peor caso no es el costo (no hay cuota
paga) sino **que Yahoo bloquee el IP del servidor** (sección 5) y la app deje
de traer precios para todos. Por eso el rate limiting del punto 2 es el que más
importa. Segundo peor caso: consumo de CPU en los backtests, que se mitiga con
el mismo límite y con el caché compartido.

**Lo que NO hay que hacer**, y conviene dejarlo escrito:

- no loguear el header de la clave ni el cuerpo completo de un error del
  proveedor sin redactar;
- no guardar la clave en la DB "para comodidad";
- no mandar una clave a ningún tercero que no sea el proveedor dueño de esa
  clave;
- no volver a poner `FRED_API_KEY` en el `.env` del servidor "por si el usuario
  no tiene": rompe el objetivo y mezcla el cupo de todos en una sola clave;
- no poner `ALLOW_SYNTHETIC_DATA=true` en un servidor compartido: un dato
  inventado que otro lee como real es peor acá que en local.

---

## 4. Hosting

Tres opciones concretas, con datos **verificados por búsqueda el 2026-09-30**.
Los precios cambian: reverificar antes de contratar.

### Opción A — Render (plan gratuito, para probar)

- **Free:** 512 MB RAM, 0.1 CPU, **750 horas de instancia por mes** por
  workspace, y **se duerme a los 15 minutos sin tráfico**; el primer pedido
  después tarda **30–60 s** en responder.
- **Starter: USD 7/mes** (512 MB, 0.5 CPU). Además hay un *workspace fee*
  separado, así que "USD 7" rara vez es el total.
- Sin tarjeta para el plan gratuito. TLS incluido.

**Para este caso:** el dormido de 15 minutos es el problema. Con pocos usuarios
esporádicos, **casi todas las visitas van a pagar 30–60 s de arranque**, encima
de los 30–190 s que ya tarda una traducción de tesis. Sirve para una prueba,
no para que la usen conocidos.

### Opción B — Fly.io (pago por uso)

- **`shared-cpu-1x` 256 MB: USD 0,0027/hora ≈ USD 1,94/mes** si corre siempre.
- **Ya no hay plan gratuito en 2026**: los nuevos reciben una prueba de 2 horas
  de VM o 7 días, lo que termine antes. Las organizaciones viejas conservan su
  free allowance heredado.
- Puede escalar a cero y despertar con el pedido, lo que baja el costo con
  tráfico esporádico (a cambio de latencia de arranque, igual que Render).

**Para este caso:** 256 MB es **ajustado** para este backend (pandas, numpy,
scipy, statsmodels). Habría que probar con 512 MB (≈ USD 3,90/mes). Es la
opción más barata si se acepta pago por uso.

### Opción C — Hetzner Cloud CX23 (VPS, la más predecible)

- **CX23 (ex CX22, renombrado en junio de 2026): EUR 5,99/mes**, 2 vCPU, 4 GB
  RAM, 40 GB NVMe, 20 TB de tráfico.
- Es un VPS: Docker corre sin ceremonia, con `docker compose` y un proxy
  (Caddy o Traefik) que resuelve TLS solo.

**Para este caso: es la que recomiendo.** 4 GB de RAM le sobran al backend,
corre siempre (sin dormido, sin arranque en frío), el precio es fijo y
predecible, y **el IP es dedicado**, que es justo lo que importa para yfinance
(sección 5). El costo es tener que administrar el servidor: actualizaciones,
firewall, backups.

| | Render Free | Fly.io | Hetzner CX23 |
|---|---|---|---|
| Costo | USD 0 | ≈ USD 2–4/mes | EUR 5,99/mes |
| Arranque en frío | **Sí, 30–60 s** | Sí, si escala a cero | **No** |
| RAM | 512 MB | 256 MB–512 MB | **4 GB** |
| IP | Compartido | Compartido | **Dedicado** |
| Administración | Ninguna | Poca | **Toda tuya** |

---

## 5. Riesgos externos

### 5.1 yfinance desde un IP de servidor — el riesgo más serio

Verificado el 2026-09-30. **yfinance no es una API oficial**: scrapea endpoints
web de Yahoo Finance. Yahoo responde a muchos pedidos del mismo IP con
**429 "Too Many Requests"** y bloqueos temporales.

Lo específico de este caso: **hubo incidentes en 2026 con 429 sostenidos en
varios tickers, con la sospecha puesta en IPs de egreso compartidos de
proveedores cloud.** Un IP de servidor cloud carga con el tráfico de todos los
que comparten esa salida, no solo con el nuestro. Es decir: **el riesgo no es
proporcional a nuestros usuarios**.

Mitigaciones, en orden de efectividad:

1. **El caché compartido es la defensa principal**, y ya existe
   (`data_fetcher.cache`, TTL 1 hora, `CACHE_TTL_SECONDS`). Con pocos usuarios
   mirando tickers parecidos, la mayoría de los pedidos no debería salir a
   Yahoo. **Subir el TTL** (¿4 horas? ¿un día para históricos largos?) es la
   palanca más barata que hay;
2. **IP dedicado** (opción C) en vez de compartido;
3. **Rate limiting propio** sobre los endpoints que pegan a yfinance;
4. **Persistir el caché** (hoy es en memoria: un reinicio lo pierde entero y el
   primer uso después vuelve a golpear Yahoo);
5. **Backoff y un mensaje honesto** cuando Yahoo devuelve 429, en vez de
   reintentar en loop.

**Términos de uso:** yfinance opera **sin acuerdo de API con Yahoo**, en zona
gris respecto de sus términos, y el rate limiting parece ser el mecanismo de
enforcement. Para un uso privado entre conocidos el riesgo práctico es que
dejen de funcionar los precios, no una acción legal. **Pero conviene decidirlo
a conciencia**, y tener presente que una fuente oficial (paga) sería el camino
si esto creciera.

### 5.2 Términos del plan gratuito de Gemini

Verificado el 2026-09-30. Tres cosas que **cambian el diseño**:

1. **El cupo gratuito es chico y ya lo medimos:** 20 pedidos por día y por
   modelo, y cada llamada consume hasta 3 por los reintentos internos
   (medido contra la API real el 28-29/9, `docs/results/`). Alcanza para unas
   pocas tesis por usuario por día. **Con BYOK esto es un problema de cada
   usuario, no del servidor** — que es justamente la ventaja del modelo.
2. **Los datos del plan gratuito pueden usarse para mejorar los productos de
   Google**, a diferencia del plan pago. **Hay que decírselo al usuario en la
   página donde pega la clave** (texto exacto en 2.7): la tesis que escriba
   viaja a Google bajo esos términos. No es opcional decirlo: es información
   que cambia lo que alguien decide escribir. La clave de FRED no tiene este
   problema: a FRED solo viaja un ID de serie, nunca la tesis.
3. **Restricción geográfica:** según los términos de la API de Gemini, si la
   app sirve a personas en el **EEE, Suiza o el Reino Unido**, hay que usar
   servicios **pagos** — el plan gratuito no está disponible para esos
   usuarios. Con usuarios en Argentina no aplica, **pero hay que confirmarlo
   antes de compartir el link con alguien en Europa**.

Sobre compartir claves: no encontré en los términos una prohibición explícita
de que un usuario use **su propia** clave en una app de terceros, que es el
caso de BYOK. Lo que sí está señalado como violación es el *multi-key bypass*
(rotar varias claves para saltar los límites), que **no hay que implementar
nunca**, ni siquiera como "pool de claves de los usuarios".

---

## 6. Fases y preguntas abiertas

### Fase 1 — imprescindible para una primera versión

Sin esto no se puede publicar:

1. **Las claves por header.** LLM: sacar `GEMINI_API_KEY` / `OPENAI_API_KEY` de
   `settings` en el camino de `parse_thesis` e `interpret_situation`
   (inventario #3). **FRED**: eliminar el singleton de `routes.py:71`, pasar a
   una `ContextVar` por pedido y quitar `FRED_API_KEY` de `settings` en los 8
   lugares de #13. Es la parte más ancha de la fase.
2. **Redacción de secretos**: el filtro global de logging (incluido
   `api_key=` en URLs), la redacción en los mensajes de error de LLM **y de
   FRED** (#10, #12), y el test que lo prueba, **simulando una caída de red de
   FRED y verificando que la clave no aparece en el log**. **Antes de aceptar la
   primera clave ajena, no después.**
3. **Proveedor per-usuario**: sacar el estado global mutable de
   `settings.LLM_PROVIDER` del camino de pedido (#4). Hoy un usuario le cambia
   el proveedor a todos.
4. **Caché de disponibilidad por hash de clave** (#5).
5. **Código de acceso** + **HTTPS** + **CORS al dominio real** (#9).
6. **Rate limiting** por IP y en los endpoints que pegan a yfinance.
7. **Tesis en el navegador**: guardar y reabrir desde `localStorage` en vez de
   la tabla `theses` (#7).
8. **La pantalla de claves** (2.7): los dos campos con dónde se consigue cada
   una y que son gratuitas, y **el aviso sobre los datos del plan gratuito de
   Gemini** junto al campo (5.2).
9. **Sin `FRED_API_KEY` ni `ALLOW_SYNTHETIC_DATA=true` en el servidor**, con un
   chequeo al arrancar que se niegue a iniciar si alguna está presente
   (objetivo: el servidor no guarda ningún secreto).

### Fase 2 — poco después, pero no bloquea

10. Persistir el caché de datos y subirle el TTL (5.1).
11. `POST /api/keys/validate` con mensajes accionables para las dos claves (2.4).
12. Opción "recordar en este navegador" (2.3).
13. Página de estado: qué proveedor estás usando, cuánto cupo te queda si el
    proveedor lo informa.

### Fase 3 — si el uso lo pide

14. Cuentas de verdad, si el grupo deja de ser "conocidos".
15. Tesis en el servidor con columna de usuario (#7).
16. Fuente de precios oficial, si Yahoo empieza a bloquear en serio.

### Lo que tenés que decidir vos

La 6 ya está decidida; las demás siguen abiertas.

1. **¿Hosting?** Mi recomendación es **Hetzner CX23** (EUR 5,99/mes) por el IP
   dedicado y la ausencia de arranque en frío; el costo es administrarlo. Si
   preferís no administrar nada, **Fly.io con 512 MB**. Render Free solo para
   una prueba.
2. **¿OpenAI además de Gemini?** Soportar dos proveedores duplica la
   validación, los mensajes de error y las pruebas. ¿Vale, o arrancamos solo
   con Gemini?
3. **¿yfinance es aceptable como fuente?** Con la zona gris de los términos y
   el riesgo real de bloqueo del IP. Si la respuesta es "no", eso cambia el
   proyecto, no solo el despliegue.
4. **¿Qué pasa cuando un usuario se queda sin cupo a mitad de una tesis?**
   ¿Error claro y listo, o la app cae al motor heurístico local avisando? (Hoy
   cae al mock y lo declara.)
5. **¿Usuarios en Europa?** Si sí, el plan gratuito de Gemini no les sirve
   (5.2) y hay que decírselo de entrada.
6. ~~¿Pedirle a cada usuario dos claves es aceptable?~~ **Decidido
   (2026-09-30): sí.** Cada usuario pone su clave de Gemini y la de FRED, y el
   servidor no guarda ningún secreto. La pantalla de 2.7 explica cada paso.
   La alternativa descartada era una clave de FRED del dueño.
7. **¿El código de acceso alcanza?** Es compartido y no revocable por persona.
   Con pocos conocidos sí; conviene saber de antemano en qué punto deja de
   alcanzar.

---

## Lo que este análisis NO cubre

- **No medí** el consumo real de RAM del backend bajo carga: la recomendación
  de 512 MB contra 256 MB es una inferencia de las dependencias (pandas, numpy,
  scipy, statsmodels), no una medición. **Hay que medirlo antes de elegir el
  tamaño de la instancia.**
- **No verifiqué** los términos de Gemini leyendo el documento legal completo,
  sino a través de búsqueda. Los tres puntos de 5.2 —sobre todo el geográfico—
  hay que confirmarlos en la fuente antes de publicar.
- **No hay estimación en horas.** Las fases dicen el orden y qué bloquea a qué,
  que es lo que se puede afirmar sin inventar.
