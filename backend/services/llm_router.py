import abc
import asyncio
import json
import logging
import re
from typing import Awaitable, Callable, Dict, List, Literal, Optional, TypeVar
import httpx

from backend.config import settings
from backend.schemas.models import (
    ThesisResponse,
    TickerSuggestion,
    MacroSuggestion,
    InterpretationContext,
    InterpretationResponse,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes worth a second try: rate limits and transient server-side
# overload. Everything else (bad auth, malformed request, retired/unknown model)
# will return the exact same error on retry, so retrying it only wastes time.
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

# Status codes that mean "this will never succeed until a human fixes
# something" — bad/missing API key, forbidden, or (as with the real
# gemini-2.5-flash retirement this project hit) a model ID that no longer
# exists. Distinct from RETRYABLE_STATUS_CODES: these are also non-retryable,
# but non-retryable-and-transient ("just try again later") is a different user
# message than non-retryable-and-config ("go fix your .env").
AUTH_OR_CONFIG_STATUS_CODES = frozenset({401, 403, 404})

FallbackCategory = Literal["rate_limit", "transient", "auth_or_config", "unknown"]

# Backoff schedule for the (bounded) retries: 1 retry after 1s, a 2nd after 3s.
# Total: at most 3 attempts, ~4s of extra latency in the worst case — enough to
# absorb transient noise (rate limit / overload) without making the user wait
# tens of seconds for what is, most of the time, a permanent failure anyway.
RETRY_DELAYS_SECONDS = (1.0, 3.0)


class RetriesExhaustedError(Exception):
    """Wraps the last exception after all retries were used on a retryable error.
    A dedicated class (rather than re-instantiating the original exception type)
    because some exception types (e.g. httpx.HTTPStatusError) require constructor
    args beyond a plain message and would themselves raise if reconstructed that
    way. `_format_fallback_reason` recognizes this type and uses its message
    as-is, instead of re-prefixing "{provider} falló: " on top of a message that
    already explains the retry attempts.
    """
    pass


def _extract_status_code(exc: Exception) -> Optional[int]:
    """Best-effort extraction of an HTTP-like status code from an LLM SDK exception.

    Covers:
    - google-genai's APIError (Gemini): has a `.code` int attribute directly.
    - httpx.HTTPStatusError (OpenAI/Ollama, from resp.raise_for_status()): has
      `.response.status_code`.
    - Anything else: falls back to a regex over str(exc), since some SDKs only
      expose the code inside the message (e.g. "429 RESOURCE_EXHAUSTED. {...}").
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    match = re.match(r"^\s*(\d{3})\b", str(exc))
    if match:
        return int(match.group(1))

    return None


def _is_retryable(exc: Exception) -> bool:
    """True for transient failures (rate limit, overload, timeout, connection
    errors) worth a second attempt; False for permanent ones (bad auth, malformed
    request, model not found) that will fail identically on retry."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    status_code = _extract_status_code(exc)
    return status_code is not None and status_code in RETRYABLE_STATUS_CODES


def _classify_retry_label(exc: Exception) -> str:
    """Short human label for the retryable condition, used in fallback_reason."""
    status_code = _extract_status_code(exc)
    if status_code == 429:
        return "rate limit"
    if status_code in (500, 502, 503, 504):
        return "servicio no disponible"
    if status_code == 408:
        return "timeout"
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout)):
        return "timeout de red"
    return "error transitorio"


def classify_fallback_category(exc: Exception) -> FallbackCategory:
    """
    Maps a provider failure to an ACTIONABLE category for the end user — not just
    for the internal retry decision _is_retryable() already makes, but to answer
    "is waiting going to help, or do I need to go fix something": a 429 (rate
    limit) resolves itself with time; a 401/403/404 (bad key, retired/unknown
    model — the same gemini-2.5-flash retirement this project already hit) never
    will, no matter how long the user waits.

    Reuses the same status-code extraction _is_retryable()/_classify_retry_label()
    use, so this can't disagree with the retry logic about what kind of error
    it's looking at.

    RetriesExhaustedError wraps the ORIGINAL exception in __cause__ (raised via
    `raise RetriesExhaustedError(...) from e`) and its own message is a formatted
    sentence like "Gemini falló tras 3 intentos (rate limit): 429 ...", where the
    status code is no longer at the start of the string — _extract_status_code's
    regex fallback requires that, so parsing the wrapper's own message would
    misclassify every exhausted-retry rate limit as "unknown". Unwrap to the
    original exception first, same spirit as _format_fallback_reason's special
    case for this type.
    """
    if isinstance(exc, RetriesExhaustedError) and exc.__cause__ is not None:
        exc = exc.__cause__
    status_code = _extract_status_code(exc)

    if status_code == 429:
        return "rate_limit"
    if status_code in AUTH_OR_CONFIG_STATUS_CODES:
        return "auth_or_config"
    if status_code in (500, 502, 503, 504, 408):
        return "transient"
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout)):
        return "transient"
    return "unknown"


async def _call_with_retry(
    provider_label: str,
    operation: Callable[[], Awaitable[T]],
) -> T:
    """Runs `operation` with up to 2 retries (3 attempts total) on retryable
    errors only, with a short exponential-ish backoff (1s, 3s). Re-raises the
    last exception if every attempt fails — callers still fall back to mock,
    but now know it wasn't a single unlucky call.

    On exhausting retries, re-raises a wrapped exception whose message states
    the attempt count and the retry reason, so fallback_reason downstream reads
    like "Gemini falló tras 3 intentos (rate limit): 429 ..." instead of just
    the last attempt's error with no context that retries were even tried.
    """
    attempts = len(RETRY_DELAYS_SECONDS) + 1
    last_exc: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as e:
            last_exc = e
            retryable = _is_retryable(e)
            if not retryable or attempt == attempts:
                if retryable and attempt == attempts:
                    label = _classify_retry_label(e)
                    raise RetriesExhaustedError(
                        f"{provider_label} falló tras {attempts} intentos ({label}): {e}"
                    ) from e
                raise
            delay = RETRY_DELAYS_SECONDS[attempt - 1]
            logger.warning(
                f"{provider_label} attempt {attempt}/{attempts} failed with a retryable error "
                f"({_classify_retry_label(e)}): {e}. Retrying in {delay}s."
            )
            await asyncio.sleep(delay)

    # Unreachable in practice (the loop always returns or raises), but keeps
    # type checkers happy and guards against a future refactor of the loop.
    assert last_exc is not None
    raise last_exc

SYSTEM_PROMPT = """Eres un analista cuantitativo senior y portfolio manager.
Tu tarea es traducir una hipótesis de inversión en lenguaje natural a una estructura cuantitativa ejecutable.
Debes devolver OBLIGATORIAMENTE un JSON con el siguiente esquema:
{
  "summary": "Resumen conciso y riguroso de la tesis en español",
  "tickers": [
    {
      "symbol": "TICKER",
      "name": "Nombre de la empresa",
      "sector": "Sector industrial",
      "weight": 0.25,
      "thesis_role": "Explicación del rol específico de este activo en la tesis"
    }
  ],
  "macro_series": [
    {
      "series_id": "FRED_ID (ej. IPG2211A2N, INDPRO, CPIAUCSL, DGS10, PCU33443344)",
      "name": "Nombre del indicador",
      "category": "Categoría (Energía, Macro, Tasas, Semiconductores)",
      "expected_correlation": "Positive / Negative"
    }
  ],
  "rationales": {
    "TICKER": "Racional cuantitativo y de negocio de por qué este activo se beneficia de la tesis"
  }
}
Devuelve entre 3 y 6 tickers relevantes y entre 1 y 4 series macroeconómicas de FRED. Las ponderaciones de los tickers deben sumar 1.0.
"""

INTERPRETATION_SYSTEM_PROMPT = """Eres un Copiloto Cuantitativo Senior y Director de Análisis Estratégico.
Tu tarea es interpretar en lenguaje llano, estructurado y directo el estado de una tesis de inversión cuantitativa a partir de la telemetría proyectiva y fundamental actual.
Debes devolver OBLIGATORIAMENTE un JSON con el siguiente esquema exacto:
{
  "what_data_says": "Traducción conceptual de las curvas y tendencia proyectada...",
  "thesis_alignment": "Evaluación de si los datos y proyecciones confirman o contradicen la hipótesis planteada...",
  "next_series_suggestion": "Justificación concisa de qué serie o indicador mirar a continuación para validar cuellos de botella...",
  "suggested_series_id": "TICKER_O_FRED_ID_SUGERIDO"
}
"""

class BaseLLMClient(abc.ABC):
    """Abstract interface for Semantic Router translating investment thesis to structured assets and copilot interpretation."""

    @abc.abstractmethod
    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        """Parse natural language thesis into structured tickers, macro series, and rationales."""
        pass

    @abc.abstractmethod
    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
        """Provide quantitative copilot interpretation of current series vs the thesis."""
        pass


def _format_fallback_reason(provider_label: str, exc: Exception) -> str:
    """Builds a short, user-facing explanation for why a real LLM provider fell back to mock.

    When `exc` is a RetriesExhaustedError, its message already states the provider,
    the attempt count, and the retry reason (e.g. "Gemini falló tras 3 intentos
    (rate limit): 429 ..."), so it's used as-is instead of adding another
    "{provider_label} falló: " prefix on top of it.
    """
    if isinstance(exc, RetriesExhaustedError):
        return str(exc)
    return f"{provider_label} falló: {exc}"


class GeminiLLMClient(BaseLLMClient):
    """LLM client implementation using Google Gemini via google-genai SDK."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        except Exception as e:
            logger.warning(f"Could not initialize google-genai Client: {e}")
            self._client = None

    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        try:
            if not self._client:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            from google.genai import types

            prompt = f"{SYSTEM_PROMPT}\n\nHipótesis de inversión: \"{thesis}\""

            async def _attempt():
                return self._client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

            response = await _call_with_retry("Gemini", _attempt)

            raw_json = response.text.strip()
            if raw_json.startswith("```"):
                raw_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json, flags=re.DOTALL)

            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                logger.error(f"Gemini returned non-JSON response despite response_mime_type=application/json. Raw text: {raw_json!r}")
                raise

            tickers = [TickerSuggestion(**t) for t in data.get("tickers", [])]
            macro_series = [MacroSuggestion(**m) for m in data.get("macro_series", [])]

            return ThesisResponse(
                thesis=thesis,
                summary=data.get("summary", "Análisis de tesis cuantitativa"),
                tickers=tickers,
                macro_series=macro_series,
                rationales=data.get("rationales", {}),
                provider_used="gemini-3.6-flash"
            )

        except Exception as e:
            reason = _format_fallback_reason("Gemini", e)
            category = classify_fallback_category(e)
            logger.error(f"Gemini LLM error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.parse_thesis(thesis)
            result.fallback_reason = reason
            result.fallback_category = category
            return result

    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
        try:
            if not self._client:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            from google.genai import types

            prompt = (
                f"{INTERPRETATION_SYSTEM_PROMPT}\n\n"
                f"Contexto Cuantitativo:\n"
                f"- Tesis: {ctx.thesis}\n"
                f"- Activo analizado: {ctx.active_series_id} ({ctx.active_series_name})\n"
                f"- Último precio real: {ctx.last_price}\n"
                f"- Objetivo proyectado (+{ctx.horizon}d): {ctx.projected_target} (CAGR: {ctx.cagr:.1f}%)\n"
                f"- Bandas {int(ctx.confidence * 100)}%: [{ctx.lower_bound} - {ctx.upper_bound}]\n"
                f"- Otros activos en tesis: {', '.join(ctx.other_tickers)}\n"
                f"- Series macro en tesis: {', '.join(ctx.macro_series)}\n"
                f"- Capex resumido: {json.dumps(ctx.capex_summary or {})}\n"
            )

            async def _attempt():
                return self._client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

            response = await _call_with_retry("Gemini", _attempt)

            raw_json = response.text.strip()
            if raw_json.startswith("```"):
                raw_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json, flags=re.DOTALL)

            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                logger.error(f"Gemini returned non-JSON response despite response_mime_type=application/json. Raw text: {raw_json!r}")
                raise

            return InterpretationResponse(
                what_data_says=data.get("what_data_says", ""),
                thesis_alignment=data.get("thesis_alignment", ""),
                next_series_suggestion=data.get("next_series_suggestion", ""),
                suggested_series_id=data.get("suggested_series_id"),
                provider_used="gemini-3.6-flash"
            )
        except Exception as e:
            reason = _format_fallback_reason("Gemini", e)
            category = classify_fallback_category(e)
            logger.error(f"Gemini interpretation error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.interpret_situation(ctx)
            result.fallback_reason = reason
            result.fallback_category = category
            return result


class OpenAILLMClient(BaseLLMClient):
    """LLM client implementation using OpenAI-compatible REST API."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url.rstrip("/")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured")

    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Hipótesis de inversión: \"{thesis}\""}
                ],
                "response_format": {"type": "json_object"}
            }

            async def _attempt():
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                    resp.raise_for_status()
                    return resp.json()

            result = await _call_with_retry("OpenAI", _attempt)
            content = result["choices"][0]["message"]["content"]
            data = json.loads(content)

            return ThesisResponse(
                thesis=thesis,
                summary=data.get("summary", ""),
                tickers=[TickerSuggestion(**t) for t in data.get("tickers", [])],
                macro_series=[MacroSuggestion(**m) for m in data.get("macro_series", [])],
                rationales=data.get("rationales", {}),
                provider_used="openai-gpt-4o-mini"
            )
        except Exception as e:
            reason = _format_fallback_reason("OpenAI", e)
            category = classify_fallback_category(e)
            logger.error(f"OpenAI LLM error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.parse_thesis(thesis)
            result.fallback_reason = reason
            result.fallback_category = category
            return result

    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": INTERPRETATION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Contexto: {ctx.model_dump_json()}"}
                ],
                "response_format": {"type": "json_object"}
            }

            async def _attempt():
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                    resp.raise_for_status()
                    return resp.json()

            resp_json = await _call_with_retry("OpenAI", _attempt)
            data = json.loads(resp_json["choices"][0]["message"]["content"])
            return InterpretationResponse(
                what_data_says=data.get("what_data_says", ""),
                thesis_alignment=data.get("thesis_alignment", ""),
                next_series_suggestion=data.get("next_series_suggestion", ""),
                suggested_series_id=data.get("suggested_series_id"),
                provider_used="openai-gpt-4o-mini"
            )
        except Exception as e:
            reason = _format_fallback_reason("OpenAI", e)
            category = classify_fallback_category(e)
            logger.error(f"OpenAI interpretation error: {e}. Falling back to Mock.")
            mock_client = MockLLMClient()
            result = await mock_client.interpret_situation(ctx)
            result.fallback_reason = reason
            result.fallback_category = category
            return result


class OllamaLLMClient(BaseLLMClient):
    """LLM client implementation using local Ollama instance."""

    def __init__(self, base_url: Optional[str] = None, model: str = "llama3.2"):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model

    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        try:
            payload = {
                "model": self.model,
                "prompt": f"{SYSTEM_PROMPT}\n\nHipótesis de inversión: \"{thesis}\"",
                "stream": False,
                "format": "json"
            }

            async def _attempt():
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                    resp.raise_for_status()
                    return resp.json()

            resp_json = await _call_with_retry("Ollama", _attempt)
            data = json.loads(resp_json.get("response", "{}"))

            return ThesisResponse(
                thesis=thesis,
                summary=data.get("summary", "Análisis local Ollama"),
                tickers=[TickerSuggestion(**t) for t in data.get("tickers", [])],
                macro_series=[MacroSuggestion(**m) for m in data.get("macro_series", [])],
                rationales=data.get("rationales", {}),
                provider_used=f"ollama-{self.model}"
            )
        except Exception as e:
            reason = _format_fallback_reason("Ollama", e)
            category = classify_fallback_category(e)
            logger.error(f"Ollama error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.parse_thesis(thesis)
            result.fallback_reason = reason
            result.fallback_category = category
            return result

    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
        try:
            payload = {
                "model": self.model,
                "prompt": f"{INTERPRETATION_SYSTEM_PROMPT}\n\nContexto: {ctx.model_dump_json()}",
                "stream": False,
                "format": "json"
            }

            async def _attempt():
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                    resp.raise_for_status()
                    return resp.json()

            resp_json = await _call_with_retry("Ollama", _attempt)
            data = json.loads(resp_json.get("response", "{}"))
            return InterpretationResponse(
                what_data_says=data.get("what_data_says", ""),
                thesis_alignment=data.get("thesis_alignment", ""),
                next_series_suggestion=data.get("next_series_suggestion", ""),
                suggested_series_id=data.get("suggested_series_id"),
                provider_used=f"ollama-{self.model}"
            )
        except Exception as e:
            reason = _format_fallback_reason("Ollama", e)
            category = classify_fallback_category(e)
            logger.error(f"Ollama interpretation error: {e}. Falling back to Mock.")
            mock_client = MockLLMClient()
            result = await mock_client.interpret_situation(ctx)
            result.fallback_reason = reason
            result.fallback_category = category
            return result


class MockLLMClient(BaseLLMClient):
    """Deterministic, domain-aware financial semantic parser with zero external API dependencies."""

    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        normalized = thesis.lower()

        # Topic: AI, Datacenters, Power, Electricity
        if any(w in normalized for w in ["electric", "eléctric", "datacenter", "centro de datos", "energ", "ia", "ai", "nuclear", "potencia", "power"]):
            tickers = [
                TickerSuggestion(
                    symbol="NVDA",
                    name="NVIDIA Corporation",
                    sector="Semiconductors",
                    weight=0.25,
                    thesis_role="Cálculo acelerado y plataformas de cómputo para inferencia/entrenamiento en datacenters"
                ),
                TickerSuggestion(
                    symbol="CEG",
                    name="Constellation Energy Corp",
                    sector="Utilities / Nuclear",
                    weight=0.25,
                    thesis_role="Generación nuclear limpia para suministro directo (behind-the-meter) a hiperescaladores"
                ),
                TickerSuggestion(
                    symbol="VST",
                    name="Vistra Corp",
                    sector="Independent Power Producers",
                    weight=0.20,
                    thesis_role="Generación eléctrica flexible y almacenamiento en batería para picos de demanda energética"
                ),
                TickerSuggestion(
                    symbol="MSFT",
                    name="Microsoft Corporation",
                    sector="Cloud / Software",
                    weight=0.15,
                    thesis_role="Mayor inversor de Capex en infraestructura de nube y acuerdos PPA de energía limpia"
                ),
                TickerSuggestion(
                    symbol="NEE",
                    name="NextEra Energy Inc",
                    sector="Renewable Utilities",
                    weight=0.15,
                    thesis_role="Líder en contratos renovables corporativos y expansión de líneas de transmisión"
                ),
            ]
            macro_series = [
                MacroSuggestion(
                    series_id="IPG2211A2N",
                    name="Electric Power Generation, Transmission & Distribution",
                    category="Energy Demand",
                    expected_correlation="Positive"
                ),
                MacroSuggestion(
                    series_id="INDPRO",
                    name="Industrial Production Index",
                    category="Macro Activity",
                    expected_correlation="Positive"
                ),
                MacroSuggestion(
                    series_id="PCU33443344",
                    name="PPI: Semiconductor & Electronic Component Manufacturing",
                    category="Tech Supply Chain",
                    expected_correlation="Positive"
                ),
            ]
            rationales = {
                "NVDA": "Demanda inelástica por aceleradores Blackwell y redes InfiniBand; catalizador primario de la densidad térmica y consumo de MW por rack.",
                "CEG": "Mayor operador nuclear de EE. UU.; acuerdos directos a largo plazo con primas tarifarias sustanciales para datacenters 24/7.",
                "VST": "Flotas de gas natural y activos de almacenamiento de baterías con alto apalancamiento operativo ante el encarecimiento de la energía en mercados mayoristas como PJM y ERCOT.",
                "MSFT": "Compromiso de capital multimillonario en nuevos centros de datos para Azure e integración de copilots empresariales.",
                "NEE": "Capacidad de interconexión rápida a la red y cartera diversificada de proyectos eólicos y solares con PPAs comerciales."
            }
            summary = "Tesis centrada en el cuello de botella energético de la Inteligencia Artificial: la expansión exponencial de centros de datos requiere generación de carga base (nuclear y gas) e infraestructura de red crítica."

        # Topic: Semiconductors, Hardware, Chip Capex
        elif any(w in normalized for w in ["semiconductor", "chip", "tsmc", "hardware", "asml", "litograf", "fundic"]):
            tickers = [
                TickerSuggestion(
                    symbol="NVDA",
                    name="NVIDIA Corporation",
                    sector="Semiconductors",
                    weight=0.30,
                    thesis_role="Monopolio fáctico en GPUs de cómputo avanzado para IA"
                ),
                TickerSuggestion(
                    symbol="TSM",
                    name="Taiwan Semiconductor Mfg",
                    sector="Foundry",
                    weight=0.30,
                    thesis_role="Fabricante exclusivo de nodos avanzados de 3nm y empaquetado CoWoS"
                ),
                TickerSuggestion(
                    symbol="ASML",
                    name="ASML Holding NV",
                    sector="Semiconductor Equipment",
                    weight=0.25,
                    thesis_role="Único proveedor global de máquinas de litografía ultravioleta extrema (EUV)"
                ),
                TickerSuggestion(
                    symbol="AMAT",
                    name="Applied Materials",
                    sector="Semiconductor Equipment",
                    weight=0.15,
                    thesis_role="Equipamiento indispensable para deposición y grabado en nuevos nodos"
                ),
            ]
            macro_series = [
                MacroSuggestion(
                    series_id="PCU33443344",
                    name="PPI: Semiconductor Manufacturing",
                    category="Semiconductors",
                    expected_correlation="Positive"
                ),
                MacroSuggestion(
                    series_id="INDPRO",
                    name="Industrial Production",
                    category="Macro Activity",
                    expected_correlation="Positive"
                )
            ]
            rationales = {
                "NVDA": "Poder de fijación de precios superior en chips de centros de datos y márgenes brutos por encima del 70%.",
                "TSM": "Capacidad de utilización al 100% en nodos de 3nm con demanda comprometida por los principales hiperescaladores.",
                "ASML": "Barrera de entrada insuperable en litografía avanzada High-NA para la próxima generación de chips.",
                "AMAT": "Exposición diversificada al ciclo de inversión global de fundiciones y memoria HBM."
            }
            summary = "Tesis orientada al superciclo de inversión en semiconductores avanzados, empaquetado CoWoS y memoria HBM para satisfacer la infraestructura de cómputo mundial."

        # Default / Macro / Tech thesis
        else:
            tickers = [
                TickerSuggestion(
                    symbol="NVDA",
                    name="NVIDIA Corporation",
                    sector="Information Technology",
                    weight=0.25,
                    thesis_role="Líder de infraestructura de cómputo acelerado"
                ),
                TickerSuggestion(
                    symbol="MSFT",
                    name="Microsoft Corporation",
                    sector="Cloud / Software",
                    weight=0.25,
                    thesis_role="Hiperescalador con despliegue enterprise a gran escala"
                ),
                TickerSuggestion(
                    symbol="GOOG",
                    name="Alphabet Inc",
                    sector="Technology / Search",
                    weight=0.25,
                    thesis_role="Integración vertical completa: modelos, silicio TPU y nube"
                ),
                TickerSuggestion(
                    symbol="CEG",
                    name="Constellation Energy Corp",
                    sector="Energy / Utilities",
                    weight=0.25,
                    thesis_role="Proveedor de energía firme y descarbonizada para datacenters"
                ),
            ]
            macro_series = [
                MacroSuggestion(
                    series_id="INDPRO",
                    name="Industrial Production Index",
                    category="Macro Growth",
                    expected_correlation="Positive"
                ),
                MacroSuggestion(
                    series_id="DGS10",
                    name="10-Year Treasury Constant Maturity",
                    category="Interest Rates",
                    expected_correlation="Negative"
                ),
                MacroSuggestion(
                    series_id="IPG2211A2N",
                    name="Electric Power Generation Index",
                    category="Power Demand",
                    expected_correlation="Positive"
                ),
            ]
            rationales = {
                "NVDA": "Crecimiento estructural de ingresos y expansión sostenida del flujo de caja libre.",
                "MSFT": "Alta recurrencia de ingresos por suscripción en Azure y Office 365 con márgenes operativos sólidos.",
                "GOOG": "Innovación acelerada en modelos de lenguaje y ventaja de costes con chips TPU propios.",
                "CEG": "Generación de energía limpia y acuerdos estratégicos de largo plazo para suministro a grandes tecnológicos."
            }
            summary = f"Tesis analizada para: '{thesis}'. Selección cuantitativa optimizada de activos de alta convicción y métricas macroeconómicas de referencia."

        return ThesisResponse(
            thesis=thesis,
            summary=summary,
            tickers=tickers,
            macro_series=macro_series,
            rationales=rationales,
            provider_used="mock-semantic-engine"
        )

    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
        """Rule-based quantitative copilot producing clean, structured, domain-accurate text."""
        pct_delta = ((ctx.projected_target - ctx.last_price) / ctx.last_price) * 100 if ctx.last_price > 0 else 0
        cone_width = ctx.upper_bound - ctx.lower_bound
        cone_pct = (cone_width / ctx.projected_target) * 100 if ctx.projected_target > 0 else 0

        # a) Qué dicen los datos
        direction = "expansión alcista" if pct_delta >= 0 else "contracción correctiva"
        what_data_says = (
            f"La curva proyectiva para **{ctx.active_series_id}** ({ctx.active_series_name or 'Activo analizado'}) "
            f"señala una {direction} del {pct_delta:+.1f}% hacia un precio objetivo de ${ctx.projected_target:.2f} "
            f"en un horizonte de {ctx.horizon} días (CAGR anualizado implícito del {ctx.cagr:+.1f}%). "
            f"El cono de incertidumbre al {int(ctx.confidence * 100)}% abarca el intervalo [{ctx.lower_bound:.2f}, {ctx.upper_bound:.2f}], "
            f"lo que representa una dispersión del {cone_pct:.1f}% respecto al objetivo central, "
            f"denotando una volatilidad {'moderada' if cone_pct < 25 else 'elevada y sensible a anuncios de Capex'}."
        )

        # b) Alineación con tu tesis
        is_power_related = any(w in ctx.thesis.lower() for w in ["electric", "eléctric", "datacenter", "ia", "potencia", "energia", "energía"])
        active_sym = ctx.active_series_id.upper()

        if active_sym in ("NVDA", "TSM", "ASML"):
            thesis_alignment = (
                f"Las series proyectadas para {active_sym} confirman la fase de aceleración de infraestructura. "
                f"Sin embargo, el crecimiento sostenido de Capex reportado por los hiperescaladores "
                f"requiere que la demanda de capacidad de cómputo no se frene por restricciones de potencia eléctrica en sitio."
            )
            suggested_id = "CEG" if "CEG" in ctx.other_tickers else ("IPG2211A2N" if "IPG2211A2N" in ctx.macro_series else "VST")
            next_series_suggestion = (
                f"Conviene conmutar a **{suggested_id}** (productor de energía firme/nuclear o índice de generación eléctrica) "
                f"para verificar si la oferta energética y tarifas mayoristas están acompañando la absorción proyectada."
            )
        elif active_sym in ("CEG", "VST", "NEE", "IPG2211A2N"):
            thesis_alignment = (
                f"La serie {active_sym} refleja el traspaso del cuello de botella hacia la generación eléctrica de carga base. "
                f"Las proyecciones respaldan directamente la hipótesis de escasez de megavatios y primas contractuales favorables para los proveedores de energía."
            )
            suggested_id = "NVDA" if "NVDA" in ctx.other_tickers else "MSFT"
            next_series_suggestion = (
                f"Examina ahora **{suggested_id}** para contrastar cómo el crecimiento en el gasto de capital (Capex) "
                f"de los proveedores de cómputo valida el flujo de ingresos esperado hacia el sector energético."
            )
        else:
            thesis_alignment = (
                f"Los datos muestran coherencia direccional con la hipótesis planteada ('{ctx.thesis}'). "
                f"La persistencia de la tendencia proyectada dependerá de que las tasas de reinversión en Capex se mantengan en los niveles históricos observados."
            )
            candidates = [t for t in ctx.other_tickers if t != active_sym] + ctx.macro_series
            suggested_id = candidates[0] if candidates else "IPG2211A2N"
            next_series_suggestion = (
                f"Se recomienda alternar a **{suggested_id}** para cruzar la proyección del activo con indicadores macroeconómicos clave."
            )

        return InterpretationResponse(
            what_data_says=what_data_says,
            thesis_alignment=thesis_alignment,
            next_series_suggestion=next_series_suggestion,
            suggested_series_id=suggested_id,
            provider_used="mock-semantic-engine"
        )


class _PreFailedMockLLMClient(MockLLMClient):
    """MockLLMClient variant that stamps a fixed fallback_reason, used when a real
    provider's client failed to even construct (e.g. missing/invalid API key)."""

    def __init__(self, reason: str, category: FallbackCategory = "auth_or_config"):
        self._reason = reason
        # Always "auth_or_config" by construction: the only way a client fails to
        # even construct in this codebase is a missing/invalid API key (see
        # GeminiLLMClient.__init__/OpenAILLMClient.__init__ raising ValueError),
        # which is a config problem no amount of waiting fixes — never run the
        # generic status-code classifier here, since a ValueError has no status
        # code to extract and would misclassify as "unknown".
        self._category = category

    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        result = await super().parse_thesis(thesis)
        result.fallback_reason = self._reason
        result.fallback_category = self._category
        return result

    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
        result = await super().interpret_situation(ctx)
        result.fallback_reason = self._reason
        result.fallback_category = self._category
        return result


def get_llm_client(provider: Optional[str] = None) -> BaseLLMClient:
    """Factory creating the appropriate LLM client based on configuration or explicit provider."""
    prov = (provider or settings.effective_llm_provider).lower()

    if prov == "gemini":
        try:
            return GeminiLLMClient()
        except Exception as e:
            reason = _format_fallback_reason("Gemini (inicialización)", e)
            logger.warning(f"Failed to initialize GeminiLLMClient ({e}), falling back to MockLLMClient")
            return _PreFailedMockLLMClient(reason)

    elif prov == "openai":
        try:
            return OpenAILLMClient()
        except Exception as e:
            reason = _format_fallback_reason("OpenAI (inicialización)", e)
            logger.warning(f"Failed to initialize OpenAILLMClient ({e}), falling back to MockLLMClient")
            return _PreFailedMockLLMClient(reason)

    elif prov == "ollama":
        return OllamaLLMClient()

    else:
        return MockLLMClient()
