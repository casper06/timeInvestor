# Versión web con clave del usuario (BYOK) — análisis

**Estado:** análisis, sin cambios de código. Acompaña al ADR-0035 (Propuesta).
**Fecha:** 2026-09-30. Código analizado: `main` @ `5d7e363` (tag `v1.0`).

El caso: una web liviana, pocos usuarios, todos conocidos del dueño. Cada uno
pega **su** clave de Gemini (u OpenAI) en la página; queda en su navegador y
viaja en cada pedido. El servidor la usa y no la guarda ni la registra. La
clave de FRED es la del dueño, fija en el servidor. Sin Claude CLI ni Gemini
CLI. Las tesis se guardan en el navegador de cada usuario, sin cuentas. El
servidor no trae TimesFM (imagen liviana; las estacionales van con
Holt-Winters). Un código de acceso compartido impide que lo use gente de
afuera.

---

## 1. Inventario: qué asume hoy "un usuario, claves al arrancar"

| # | Dónde | Qué asume | Qué hay que hacer |
|---|---|---|---|
| 1 | `backend/config.py:29-32` | `FRED_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` se leen **una vez, del `.env`, al importar el módulo**. Son atributos de clase de `Settings`, no algo por pedido | La de FRED se queda como está (es la del dueño). Las de LLM dejan de venir de acá |
| 2 | `backend/api/routes.py:71` | `fred_fetcher = FREDDataFetcher()` es un **singleton de módulo**, creado al importar, que captura `settings.FRED_API_KEY` en `self.api_key` (`data_fetcher.py:322-323`) | **Se puede dejar igual**: la clave de FRED es única y del servidor. Es el único singleton de clave que sobrevive sin cambios |
| 3 | `backend/services/llm_router.py:519-522` (`GeminiLLMClient.__init__`), `:1767+` (`get_llm_client`) | El cliente se construye **desde `settings`**, sin parámetros por pedido, y `get_llm_client()` no recibe contexto de quién pregunta | Hay que pasar la clave del usuario por parámetro hasta el cliente. Es el cambio más invasivo |
| 4 | `backend/config.py:41-45` + `routes.py:118-140` | `LLM_PROVIDER` es **estado global mutable**: `POST /api/config/llm-provider` escribe `settings.LLM_PROVIDER` en memoria, para todo el proceso | Con varios usuarios, **el que cambia el proveedor se lo cambia a todos**. El selector del Header tiene que volverse per-usuario (en el navegador), no per-servidor |
| 5 | `backend/services/llm_availability.py:96` | `_cache: Dict[str, Tuple[float, Availability, bool]]` es **global por proveedor**, con TTL 60 s (`:74`) y **24 h para el rechazo de cuenta** (`:77`, `:108-110`) | La clave del usuario A no puede decidir la disponibilidad para B. El caché tiene que ir **por clave** (por su hash), o desaparecer |
| 6 | `backend/services/data_fetcher.py:73` | `cache = SimpleCache(...)` global, con claves `yf_hist_…`, `fred_…` (`:88`, `:157`, `:326`, `:411`) que **no llevan identidad de usuario** | **Se puede dejar compartido**, y conviene: son datos públicos traídos con la clave del dueño (FRED) o sin clave (yfinance). Compartirlo es lo que protege del rate limit |
| 7 | `backend/database/models.py:11-26` | `theses` **no tiene columna de usuario**; `GET /api/theses` devuelve todas | Si las tesis van al navegador, la tabla no se usa para eso. Si algún día se quiere servidor, hace falta esa columna |
| 8 | `backend/database/models.py:83-95` | `engine_decisions` tiene **`series_id` como única PK** | **Se comparte a propósito**: la decisión de motor es una propiedad de la serie, no del usuario. Es trabajo caro que conviene amortizar entre todos |
| 9 | `backend/main.py:35-43` | CORS con `allow_origins` fijo a `localhost:5173/8000` y **`allow_credentials=True`** | Hay que poner el dominio real. Y `allow_credentials` deja de tener sentido: no hay cookies, la clave va por header |
| 10 | Todo el backend | **No existe ninguna función de redacción de secretos.** `grep -rn "redact\|sanitiz"` sobre `backend/` no devuelve nada | Hay que escribirla antes de aceptar claves ajenas |
| 11 | `backend/services/llm_router.py:671`, `:707` | Las claves ya se usan bien en headers (`Authorization: Bearer`), no en URLs | Nada que corregir; conviene mantener la regla |

### El detalle que más importa del inventario

**Nada en el código escribe una clave a un log hoy**, pero tampoco hay nada que
lo impida. Los mensajes de error de los proveedores se propagan enteros al
usuario (`_format_fallback_reason`, `llm_router.py:492-502`) y se registran con
`logger.error`. Hoy eso es correcto —es la clave del propio dueño— pero con
claves ajenas, **un proveedor que devuelva la clave dentro de un mensaje de
error la deja escrita en el log del servidor**. Es el riesgo concreto, no
teórico.

---

## 2. Diseño propuesto

### 2.1 Cómo viaja la clave

Header propio en cada pedido que use un LLM:

```
X-LLM-Provider: gemini | openai
X-LLM-Key: <la clave del usuario>
```

Por qué un header y no el body ni la query:

- **nunca en la URL**: las query strings quedan en logs de acceso, en el
  historial del navegador y en el `Referer`;
- **no en el body**, para que un middleware pueda redactarla sin parsear JSON;
- **no en una cookie**, para que no viaje sola en pedidos que no la necesitan
  y no haya CSRF que pensar.

Solo tres endpoints la necesitan: `POST /api/thesis`, `POST /api/interpret` y
el chequeo de validez. **El resto del backend no la ve.** Cuanto menos
superficie la toca, menos lugares hay donde se pueda filtrar.

### 2.2 Redacción en logs y errores

Tres capas, porque una sola falla:

1. **Un `logging.Filter` global** que borre de todo registro cualquier cosa con
   forma de clave (`AIza[0-9A-Za-z_-]{35}` para Gemini, `sk-[A-Za-z0-9]{20,}`
   para OpenAI), sin importar quién la haya escrito. Es la red de seguridad.
2. **Redacción explícita en el manejo de errores del proveedor**: el mensaje
   que hoy se propaga entero (`_format_fallback_reason`) pasa por un
   `redact_secrets(text, keys)` que reemplaza la clave del pedido por
   `***`.
3. **Nunca registrar el header.** Ya hay precedente en el proyecto: el arnés de
   evaluación de Gemini "registra estado y cuerpo, nunca los headers"
   (`scripts/thesis_prompt_eval.py`).

Y una regla operativa: **el `access log` del servidor no debe incluir headers**.
Con uvicorn por default no los incluye; si se pone un proxy adelante, hay que
verificarlo.

### 2.3 Dónde se guarda en el navegador

**Default: `sessionStorage`.** La clave vive mientras la pestaña esté abierta y
se borra al cerrarla. Para "pocos usuarios conocidos" que entran, prueban una
tesis y se van, es la opción correcta.

**Opción explícita "recordar en este navegador" → `localStorage`**, apagada por
default, con el texto diciendo qué implica: queda en el disco de esa máquina
hasta que la borre.

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
pide evitar (sin cuentas, sin guardar claves), y traería el problema de
custodiar claves ajenas. **BYOK en el navegador es la opción correcta para este
caso**, con los límites dichos.

### 2.4 Validar la clave y reportar los fallos

Un endpoint `POST /api/llm/validate` que hace **una** llamada mínima al
proveedor con la clave recibida y devuelve un estado, sin guardarla. Se llama
cuando el usuario la pega, no en cada pedido.

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

Esto respeta la regla 6 de `CONTEXT.md`: el mensaje dice la causa real y si
conviene esperar o intervenir.

### 2.5 Aislar los cachés por clave

| Caché | Qué hacer | Por qué |
|---|---|---|
| `data_fetcher.cache` (yfinance, FRED) | **Compartido, sin cambios** | Son datos públicos traídos con la clave del dueño o sin clave. Compartirlos es lo que baja la presión sobre yfinance |
| `llm_availability._cache` | **Por hash de la clave**: `sha256(key)[:16]` como parte de la clave del caché | Que la clave sin cupo de A no marque a Gemini "no disponible" para B. **Nunca la clave en claro como índice**, ni siquiera en memoria |
| `engine_decisions` (SQLite) | **Compartido, sin cambios** | Es una propiedad de la serie. Ver 2.6 |
| Respuestas del LLM | **No cachear entre usuarios** | Dos usuarios con la misma tesis pagan cada uno su llamada. Cachearlas mezclaría el gasto de cuotas ajenas y filtraría la tesis de uno al otro |

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
  bajan el riesgo de bloqueo de yfinance;
- **la evidencia versionada** (`CATALOG_RW_EVIDENCE`, `VINTAGE_EVIDENCE`): es
  parte del código.

**No se comparte:**

- **la clave**, obviamente, ni nada derivado salvo su hash como índice de caché;
- **las tesis**: van al navegador de cada uno (`localStorage`). El texto de una
  tesis dice en qué está pensando invertir alguien;
- **la disponibilidad del proveedor**, por 2.5;
- **el proveedor elegido**: hoy es global (`settings.LLM_PROVIDER`); pasa a ser
  del navegador y viaja en `X-LLM-Provider`.

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
2. **Por endpoint caro**, sobre todo los que pegan a yfinance/FRED (p. ej. 20
   pedidos/minuto): protege **la clave de FRED y la reputación del IP del
   servidor**, que son recursos del dueño.

Los endpoints de LLM casi no necesitan límite propio: los paga la cuota del
usuario. Pero conviene uno igual, por si alguien usa el servidor de proxy.

**Si alguien extrae la clave de FRED.** No se puede extraer del navegador
—nunca sale del servidor— pero sí se puede **usar** a través del servidor: eso
es precisamente lo que el código de acceso y el rate limiting limitan. Si aun
así pasa: la clave de FRED es **gratuita y regenerable en minutos** desde la
cuenta de FRED, no tiene costo asociado y su límite es generoso. El daño
realista es que FRED bloquee esa clave un rato. **Plan: regenerarla y
rotarla.** Conviene que esté en una variable de entorno del hosting, no en una
imagen, justamente para poder rotarla sin rebuild.

**Si alguien abusa del servidor.** El peor caso no es el costo (no hay cuota
paga) sino **que Yahoo bloquee el IP del servidor** (sección 5) y la app deje
de traer precios para todos. Por eso el rate limiting del punto 2 es el que más
importa. Segundo peor caso: consumo de CPU en los backtests, que se mitiga con
el mismo límite y con el caché compartido.

**Lo que NO hay que hacer**, y conviene dejarlo escrito:

- no loguear el header de la clave ni el cuerpo completo de un error del
  proveedor sin redactar;
- no guardar la clave en la DB "para comodidad";
- no mandar la clave a ningún tercero que no sea el proveedor dueño de esa
  clave;
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
   página donde pega la clave**: la tesis que escriba viaja a Google bajo esos
   términos. No es opcional decirlo: es información que cambia lo que alguien
   decide escribir.
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

1. **La clave por header**, hasta el cliente del LLM: sacar `GEMINI_API_KEY` /
   `OPENAI_API_KEY` de `settings` en el camino de `parse_thesis` e
   `interpret_situation` (inventario #3).
2. **Redacción de secretos**: el filtro global de logging, la redacción en los
   mensajes de error, y el test que lo prueba (#10). **Antes de aceptar la
   primera clave ajena, no después.**
3. **Proveedor per-usuario**: sacar el estado global mutable de
   `settings.LLM_PROVIDER` del camino de pedido (#4). Hoy un usuario le cambia
   el proveedor a todos.
4. **Caché de disponibilidad por hash de clave** (#5).
5. **Código de acceso** + **HTTPS** + **CORS al dominio real** (#9).
6. **Rate limiting** por IP y en los endpoints que pegan a yfinance.
7. **Tesis en el navegador**: guardar y reabrir desde `localStorage` en vez de
   la tabla `theses` (#7).
8. **El aviso sobre los datos del plan gratuito de Gemini** en la pantalla
   donde se pega la clave (5.2).

### Fase 2 — poco después, pero no bloquea

9. Persistir el caché de datos y subirle el TTL (5.1).
10. `POST /api/llm/validate` con mensajes accionables (2.4).
11. Opción "recordar en este navegador" (2.3).
12. Página de estado: qué proveedor estás usando, cuánto cupo te queda si el
    proveedor lo informa.

### Fase 3 — si el uso lo pide

13. Cuentas de verdad, si el grupo deja de ser "conocidos".
14. Tesis en el servidor con columna de usuario (#7).
15. Fuente de precios oficial, si Yahoo empieza a bloquear en serio.

### Lo que tenés que decidir vos

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
6. **¿El código de acceso alcanza?** Es compartido y no revocable por persona.
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
