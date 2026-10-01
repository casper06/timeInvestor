# ADR-0035: Versión web con la clave del usuario (BYOK)

## Contexto

La app es local y de un solo usuario: las claves se leen del `.env` al arrancar
(`backend/config.py:29-32`) y todo el proceso asume que hay **una** persona
detrás. Se evalúa publicarla como una web liviana para unos pocos conocidos.

El modelo pedido: cada usuario pega **sus** claves —Gemini (u OpenAI) y FRED,
las dos gratuitas— en la página; quedan en su navegador y viajan en cada pedido.
El servidor las usa y no las guarda ni las registra. **El servidor no guarda
ningún secreto**, salvo el código de acceso. Sin
Claude CLI ni Gemini CLI (requieren una sesión de suscripción en la máquina).
Tesis en el navegador, sin cuentas. Servidor sin TimesFM. Un código de acceso
compartido.

El análisis completo, con el inventario línea por línea, está en
`docs/analysis/web-byok.md`.

## Decisión

**Propuesta, no implementada.** Nada de esto está en el código.

- **Las claves del usuario viajan por header** (`X-LLM-Key`, `X-LLM-Provider`,
  `X-FRED-Key`), no en la URL ni en una cookie. La de LLM la tocan pocos
  endpoints; la de FRED, todos los que leen series macro, y llega a los
  servicios por una `ContextVar` del pedido porque `FREDDataFetcher()` se
  construye en 8 lugares profundos del backend. Hacia FRED la clave **sí va en
  la URL** (no admite header): por eso hay que redactar sus errores y logs.
- **Nunca se persiste ni se registra.** Tres capas de redacción: un filtro
  global de logging por patrón, redacción explícita en los mensajes de error
  del proveedor y de FRED, y la regla de no registrar headers.
- **`sessionStorage` por default** en el navegador, con `localStorage` detrás
  de un "recordar en este navegador" explícito. Ninguna de las dos protege de
  un XSS: lo que protege es una CSP estricta y no introducir
  `dangerouslySetInnerHTML`.
- **El proveedor deja de ser estado global del servidor.** Hoy
  `POST /api/config/llm-provider` escribe `settings.LLM_PROVIDER` para todo el
  proceso (`routes.py:118-140`): con varios usuarios, uno se lo cambia a todos.
- **Cachés:** el de datos (yfinance/FRED, sin la clave en el índice) y
  `engine_decisions` se **comparten** a propósito — son datos públicos y trabajo
  caro amortizable, sin nada del usuario. Un acierto de caché puede servir datos
  a quien no tiene clave de FRED válida, así que la validación de claves es un
  endpoint aparte que no pasa por el caché. El de disponibilidad de proveedor se aísla **por hash de la clave**.
  Las respuestas del LLM no se cachean entre usuarios.
- **Seguridad:** HTTPS obligatorio, código de acceso comparado con
  `compare_digest`, y rate limiting por IP y en los endpoints que pegan a
  yfinance —que protegen el IP del servidor, el único recurso del dueño en
  juego—. El servidor se niega a arrancar si encuentra `FRED_API_KEY` o claves de
  LLM en su entorno.

## Consecuencias

- **El cupo deja de ser un problema del servidor**: cada usuario paga el suyo.
  Es la razón de ser de BYOK.
- **No hay clave del dueño que robar ni rotar**: un volcado del servidor no
  filtra ninguna.
- **La superficie de riesgo se mueve al navegador y al log.** El punto más
  delicado no es el transporte sino los **mensajes de error**: los del proveedor
  de LLM (`llm_router.py:492-502`) y los de FRED, donde la clave está en la URL y
  una excepción de `httpx` la incluye (`data_fetcher.py:386,392,466`). Con
  claves ajenas hay que redactarlos antes.
- **Cada usuario hace dos trámites** (FRED y Gemini) antes de ver nada; está
  decidido que así sea. La
  pantalla de claves explica dónde se consigue cada una y que son gratuitas.
- **Hoy no existe ninguna función de redacción de secretos en el backend**
  (verificado: `grep -rn "redact\|sanitiz" backend/` no devuelve nada). Es
  trabajo nuevo, y es lo primero que hay que hacer.
- **Dependencia externa que no controlamos:** yfinance scrapea Yahoo sin
  acuerdo de API, y en 2026 hubo 429 sostenidos atribuidos a IPs de egreso
  compartidos de proveedores cloud. El caché compartido y un IP dedicado son
  las mitigaciones; el riesgo no desaparece.
- **El plan gratuito de Gemini tiene condiciones que hay que decirle al
  usuario, junto al campo donde pega la clave:** sus datos pueden usarse para mejorar los productos de Google, y en
  el EEE, Suiza y el Reino Unido el plan gratuito no está disponible.
- **El código de acceso no distingue usuarios ni se revoca por persona.** Es
  proporcionado para "pocos conocidos" y deja de serlo si el grupo crece.

## Estado

**Propuesta.** Una decisión ya está tomada (2026-09-30): **se le piden dos
claves a cada usuario, Gemini y FRED, y el servidor no guarda ningún secreto**.
Siguen abiertas, antes de implementar: hosting, si se soporta OpenAI además de
Gemini, si yfinance es aceptable como fuente, qué hacer cuando a un usuario se
le acaba el cupo, usuarios en Europa y si el código de acceso alcanza. Están
listadas al final del análisis.

## Referencias

- `docs/analysis/web-byok.md` — inventario con archivo y línea, diseño,
  seguridad, hosting con precios verificados el 2026-09-30, riesgos externos y
  fases.
- ADR-0031 (Claude CLI Sonnet como principal local, que esta versión no puede
  usar), ADR-0028 (contexto del copiloto), ADR-0024 (cargas superpuestas).
