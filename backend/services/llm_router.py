import abc
import asyncio
import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Literal, Optional, TypeVar
import httpx

from backend.config import settings
from backend.services.llm_availability import mark_account_rejected
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

FallbackCategory = Literal["rate_limit", "transient", "auth_or_config", "content_filtered", "unknown"]

# Gemini's finish_reason values that mean "the model refused to generate, or
# generated something that got blocked" — distinct from a genuine failure
# (network, auth, quota): the request succeeded at the API level, but the
# response itself was withheld by Gemini's own content filter. Retrying with
# the SAME prompt will fail identically every time, exactly like an
# auth_or_config error — but the fix is "reword the thesis", not "check your
# .env" or "wait", so it gets its own category rather than being folded into
# either of those two.
GEMINI_SAFETY_FINISH_REASONS = frozenset({"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"})

GEMINI_SAFETY_BLOCK_MESSAGE = (
    "Gemini bloqueó esta respuesta por su filtro de contenido. Probá reformular "
    "la tesis; esto no es un problema de cuota ni de configuración."
)


class GeminiSafetyBlockError(Exception):
    """Raised when Gemini's own content filter withheld a response (finish_reason
    in GEMINI_SAFETY_FINISH_REASONS) — never retried (see _call_with_retry: this
    type is deliberately NOT added to _is_retryable, since retrying with the
    identical prompt fails identically every time)."""
    def __init__(self, finish_reason: str):
        self.finish_reason = finish_reason
        super().__init__(f"{GEMINI_SAFETY_BLOCK_MESSAGE} (finish_reason={finish_reason})")


def _check_gemini_safety_block(response) -> None:
    """Raises GeminiSafetyBlockError if the google-genai SDK response's first
    candidate was withheld by Gemini's content filter. Call this on every
    successful (non-exception) Gemini API response before trusting response.text —
    a safety-blocked response has no usable text, and previously this project
    had no handling for it at all (any candidate list access would raise its
    own confusing IndexError/AttributeError instead of a clear message)."""
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return
    finish_reason = getattr(candidates[0], "finish_reason", None)
    if finish_reason is None:
        return
    finish_reason_name = getattr(finish_reason, "name", str(finish_reason))
    if finish_reason_name in GEMINI_SAFETY_FINISH_REASONS:
        raise GeminiSafetyBlockError(finish_reason_name)

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


class CliNotInstalledError(Exception):
    """Raised when a subscription CLI binary (gemini/claude) isn't found on
    PATH at all — distinct from an authentication failure (binary present, but
    not logged in), since the fallback message the user sees must tell them to
    INSTALL something, not to re-run a login command that would just fail with
    'command not found'."""
    pass


class CliProcessError(Exception):
    """Wraps a subscription CLI subprocess failure (non-zero returncode or a
    timeout), with enough of stdout/stderr/returncode preserved for
    _classify_gemini_cli_error/_classify_claude_cli_error to look at. Not an
    HTTPStatusError-alike on purpose — the point is exactly that these two
    failure shapes (HTTP exception vs. subprocess result) are different, and
    this class marks that at the type level so a future reader doesn't need to
    intuit it from context. Defined here (not next to the CLI clients further
    down) so _is_retryable/classify_fallback_category, which need to recognize
    it, don't have to forward-reference a class defined later in the module."""
    def __init__(self, message: str, returncode: Optional[int], stderr: str = "", timed_out: bool = False):
        self.returncode = returncode
        self.stderr = stderr
        self.timed_out = timed_out
        super().__init__(message)


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


# Subset of the CLI-specific stderr patterns (see _classify_gemini_cli_error /
# _classify_claude_cli_error further down, which the CLI clients' own error
# paths use for the FINAL category) that both subscription CLIs' rate-limit
# and transient-overload failures share — enough for the generic pre-classification
# _is_retryable() needs, without this function having to know which CLI
# produced the error. GeminiSafetyBlockError is deliberately absent from every
# check in this function: a safety-filtered response is never retryable.
_CLI_RETRYABLE_STDERR_PATTERNS = (
    "quota", "resource_exhausted", "rate limit", "rate_limit", "usage limit",
    "5-hour limit", "weekly limit", "503", "unavailable", "high demand",
    "econnreset", "etimedout",
)


def _is_retryable(exc: Exception) -> bool:
    """True for transient failures (rate limit, overload, timeout, connection
    errors) worth a second attempt; False for permanent ones (bad auth, malformed
    request, model not found) that will fail identically on retry."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    if isinstance(exc, CliProcessError):
        if exc.timed_out:
            return True
        if exc.returncode == 429 or exc.returncode in RETRYABLE_STATUS_CODES:
            return True
        haystack = (exc.stderr or "").lower()
        return any(p in haystack for p in _CLI_RETRYABLE_STDERR_PATTERNS)
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

    if isinstance(exc, GeminiSafetyBlockError):
        return "content_filtered"

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

# Domain-only variants for ClaudeCliLLMClient's --json-schema path, WITHOUT the
# embedded example-JSON block the two prompts above carry. Verified
# empirically during development: passing the FULL SYSTEM_PROMPT/
# INTERPRETATION_SYSTEM_PROMPT (with their own textual JSON example) via
# --system-prompt ALONGSIDE --json-schema made Claude CLI (haiku)
# inconsistently ignore the schema and answer in free-form Markdown prose
# instead — 3/3 real attempts failed this way in one test run. A short prompt
# with the domain framing only (no competing JSON example) reliably produced
# the schema-conformant structured_output every time this was tried. The
# --json-schema flag itself is what enforces the actual field names/types now,
# so the example block in the original prompts is redundant for this client
# specifically (the other clients still need it, since they parse free JSON
# text with no schema enforcement of their own).
CLAUDE_CLI_SYSTEM_PROMPT = (
    "Eres un analista cuantitativo senior y portfolio manager. Tu tarea es "
    "traducir una hipótesis de inversión en lenguaje natural a una estructura "
    "cuantitativa ejecutable: un resumen, entre 3 y 6 tickers relevantes con "
    "sus ponderaciones (que deben sumar 1.0) y roles en la tesis, entre 1 y 4 "
    "series macroeconómicas de FRED relacionadas, y un racional por ticker."
)

CLAUDE_CLI_INTERPRETATION_SYSTEM_PROMPT = (
    "Eres un Copiloto Cuantitativo Senior y Director de Análisis Estratégico. "
    "Tu tarea es interpretar en lenguaje llano, estructurado y directo el "
    "estado de una tesis de inversión cuantitativa a partir de la telemetría "
    "proyectiva y fundamental actual: qué dicen los datos, si confirman o "
    "contradicen la hipótesis, y qué serie o indicador conviene mirar a "
    "continuación."
)

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
            _check_gemini_safety_block(response)

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
            _check_gemini_safety_block(response)

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


# ---------------------------------------------------------------------------
# Subscription CLI providers (Gemini CLI, Claude Code CLI)
# ---------------------------------------------------------------------------
# Both let this project use the user's PAID SUBSCRIPTION quota (Google AI Pro,
# Claude Pro/Max) instead of a separately-billed API key — the free Gemini API
# key tier (250 req/day, 10 RPM) is too small for real use, and the user
# doesn't want to enable API billing for either provider. Neither CLI exposes
# an HTTP status code on failure the way the SDK/REST clients above do: they
# fail via subprocess returncode + stderr text, so a SEPARATE classification
# path is needed (see _classify_cli_error below) rather than reusing
# _extract_status_code, which has nothing to extract from a subprocess result.


# CLI subprocess timeout: long enough for a real Gemini/Claude turn (including
# the CLI's own internal retries on transient errors — observed taking 60-90s
# during testing when the underlying model was overloaded), short enough that
# a genuinely hung process can't block a /thesis request forever.
CLI_SUBPROCESS_TIMEOUT_SECONDS = 45


def _run_cli_subprocess(
    binary_name: str,
    args: List[str],
    stdin_text: Optional[str] = None,
    timeout: int = CLI_SUBPROCESS_TIMEOUT_SECONDS,
    env_overrides: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """
    Runs a CLI binary (gemini or claude) as a subprocess, resolving its path
    via shutil.which() first so a missing binary raises a clear
    CliNotInstalledError instead of a raw FileNotFoundError from subprocess
    itself, or (on Windows, where `gemini`/`claude` are .CMD/.exe shims)
    subtly failing to find the right executable when passed as a bare string
    to subprocess with shell=False.

    stdout and stderr are captured SEPARATELY (never merged) — the CLIs mix
    startup warnings, internal-retry logs, and stack traces into stderr while
    the actual JSON result goes to stdout; merging them (e.g. via
    `2>&1`-equivalent) breaks JSON parsing on the very first warning line.

    env_overrides: merged onto a copy of the current process environment
    (never replacing it wholesale) — e.g. Gemini CLI's
    GEMINI_CLI_TRUST_WORKSPACE=true, which must still see PATH, HOME, etc.
    """
    binary_path = shutil.which(binary_name)
    if binary_path is None:
        raise CliNotInstalledError(
            f"El binario '{binary_name}' no está instalado o no está en el PATH."
        )

    env = None
    if env_overrides:
        import os
        env = os.environ.copy()
        env.update(env_overrides)

    try:
        result = subprocess.run(
            [binary_path, *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise CliProcessError(
            f"'{binary_name}' no respondió en {timeout}s (proceso colgado o el servicio está muy lento).",
            returncode=None,
            stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
            timed_out=True,
        ) from e

    return result


# Patterns observed in Gemini CLI's real stderr output (verified by running
# the installed CLI directly, not guessed): a genuine 503/UNAVAILABLE
# ("experiencing high demand") surfaces as an uncaught _ApiError with
# `status: 503` in its stack trace; a genuine daily-quota exhaustion surfaces
# as `TerminalQuotaError: You have exhausted your daily quota on this model.`
# with returncode 429 and a final structured
# `{"error": {"message": "...", "code": 429}}` object; OAuth refresh-token
# expiry/revocation in the underlying google-auth-library surfaces as the
# OAuth2 standard `invalid_grant` (optionally paired with "ReAuth" in the
# description) — this is a google-auth-library-wide error code, not
# Gemini-CLI-specific text, found by reading the installed package's own
# bundled source rather than assumed.
_GEMINI_CLI_QUOTA_PATTERNS = (
    "terminalquotaerror",
    "exhausted your daily quota",
    "resource_exhausted",
)
_GEMINI_CLI_TRANSIENT_PATTERNS = (
    "status: 503",
    "unavailable",
    "experiencing high demand",
    "econnreset",
    "etimedout",
)
_GEMINI_CLI_AUTH_PATTERNS = (
    "invalid_grant",
    "reauth",
    "not running in a trusted directory",
    "please sign in",
    "not authenticated",
    # Account-level rejection by Google, not a session problem — see
    # _GEMINI_CLI_INELIGIBLE_RE below.
    "ineligibletiererror",
)

# Real stderr observed on 2026-09-24 with Gemini CLI 0.61.0 and a freshly
# logged-in personal Google account (exit code 1):
#   An unexpected critical error occurred:IneligibleTierError: This client is
#   no longer supported for Gemini Code Assist for individuals. To continue
#   using Gemini, please migrate to the Antigravity suite of products: ...
# (with `reasonCode: 'UNSUPPORTED_CLIENT'`, `tierId: 'free-tier'`). Google
# refuses the account itself: re-logging in does not help, so it gets its own
# message instead of the generic "your session expired" one.
_GEMINI_CLI_INELIGIBLE_RE = re.compile(r"IneligibleTierError:\s*([^\n]+)")
_GEMINI_CLI_CRITICAL_RE = re.compile(r"An unexpected critical error occurred:\s*([^\n]+)")


def _gemini_cli_stderr_summary(stderr: str) -> Optional[str]:
    """The one stderr line that says why the CLI died. Its stderr is mostly
    startup/debug noise, so without this a failure surfaces only as "salió
    con código 1", hiding the actual cause."""
    match = _GEMINI_CLI_CRITICAL_RE.search(stderr or "")
    if match:
        return match.group(1).strip()
    error_lines = [line.strip() for line in (stderr or "").splitlines() if "error" in line.lower()]
    return error_lines[-1][:300] if error_lines else None


def _unwrap_retries_exhausted(exc: Exception) -> Exception:
    """RetriesExhaustedError wraps the ORIGINAL exception in __cause__ (see
    _call_with_retry) — its own message is a formatted sentence, not the raw
    CliProcessError, so callers that need to inspect .stderr/.returncode/
    .timed_out must unwrap it first. Same unwrapping classify_fallback_category
    already does for HTTP-based clients; the CLI classifiers need their own
    copy since they inspect CliProcessError-specific attributes instead of a
    status code."""
    if isinstance(exc, RetriesExhaustedError) and exc.__cause__ is not None:
        return exc.__cause__
    return exc


def _classify_gemini_cli_error(exc: Exception) -> FallbackCategory:
    """Maps a Gemini CLI subprocess failure to a FallbackCategory using the
    real stderr text patterns documented above — no HTTP status code exists
    here, so this does NOT reuse classify_fallback_category()."""
    exc = _unwrap_retries_exhausted(exc)
    if not isinstance(exc, CliProcessError):
        return "unknown"
    if exc.timed_out:
        return "transient"

    haystack = (exc.stderr or "").lower()

    if exc.returncode == 429 or any(p in haystack for p in _GEMINI_CLI_QUOTA_PATTERNS):
        return "rate_limit"
    if any(p in haystack for p in _GEMINI_CLI_AUTH_PATTERNS):
        return "auth_or_config"
    if any(p in haystack for p in _GEMINI_CLI_TRANSIENT_PATTERNS):
        return "transient"
    return "unknown"


def _gemini_cli_account_rejection(exc: CliProcessError) -> Optional[str]:
    """Google's own message when it refused the ACCOUNT (IneligibleTierError),
    None for any other failure. Permanent, unlike every other Gemini CLI error:
    neither retrying nor logging in again changes it."""
    ineligible = _GEMINI_CLI_INELIGIBLE_RE.search(exc.stderr or "")
    return ineligible.group(1).strip() if ineligible else None


def _gemini_cli_error_message(exc: CliProcessError, category: FallbackCategory) -> str:
    """User-facing message for a Gemini CLI failure — the auth_or_config case
    gets a message specific to the CLI's OWN login flow (`gemini` command),
    deliberately different from GeminiLLMClient's .env-focused message, since
    telling a CLI-session user to "check your .env" would send them looking
    in the wrong place entirely."""
    rejection = _gemini_cli_account_rejection(exc)
    if rejection:
        return (
            "Google rechazó tu cuenta para Gemini CLI (no es un problema de sesión: "
            f"volver a loguearte no lo arregla). Mensaje de Google: {rejection}"
        )
    if category == "auth_or_config":
        return (
            "Tu sesión de Gemini CLI expiró o no iniciaste sesión. Corré `gemini` "
            "en una terminal y volvé a loguearte."
        )
    summary = _gemini_cli_stderr_summary(exc.stderr)
    return f"Gemini CLI falló: {exc} — {summary}" if summary else f"Gemini CLI falló: {exc}"


# Patterns for Claude CLI's usage-limit error. Anthropic's own product surfaces
# (claude.ai, Claude Code's interactive mode) describe this condition as
# reaching your "usage limit" for the current 5-hour session window or the
# weekly cap — these substrings are that public terminology, checked broadly
# rather than pinned to one exact sentence, specifically because reproducing
# the precise CLI stderr text would have required deliberately exhausting the
# user's real shared 5-hour/weekly Claude quota during development, which this
# implementation does not do. If the exact wording differs once this is used
# for real, only this tuple needs updating.
_CLAUDE_CLI_RATE_LIMIT_PATTERNS = (
    "usage limit",
    "5-hour limit",
    "weekly limit",
    "rate_limit",
    "rate limit",
)
_CLAUDE_CLI_AUTH_PATTERNS = (
    "not authenticated",
    "please run \"claude login\"",
    "please run 'claude login'",
    "invalid api key",
    "authentication_error",
)


def _classify_claude_cli_error(exc: Exception) -> FallbackCategory:
    """Maps a Claude CLI subprocess failure to a FallbackCategory. See the
    module-level note on _CLAUDE_CLI_RATE_LIMIT_PATTERNS: the exact stderr
    wording for hitting the shared 5-hour/weekly usage window was not
    reproduced (doing so would burn the user's real shared quota), so this
    matches on Anthropic's known public terminology for that condition."""
    exc = _unwrap_retries_exhausted(exc)
    if not isinstance(exc, CliProcessError):
        return "unknown"
    if exc.timed_out:
        return "transient"

    haystack = (exc.stderr or "").lower()

    if any(p in haystack for p in _CLAUDE_CLI_RATE_LIMIT_PATTERNS):
        return "rate_limit"
    if any(p in haystack for p in _CLAUDE_CLI_AUTH_PATTERNS):
        return "auth_or_config"
    if exc.returncode in (500, 502, 503, 504):
        return "transient"
    return "unknown"


def _claude_cli_error_message(exc: CliProcessError, category: FallbackCategory) -> str:
    """User-facing message for a Claude CLI failure — the rate_limit case names
    the SHARED nature of this quota explicitly (5h window + weekly cap shared
    with interactive Claude Code and claude.ai usage), which is the one thing
    that makes this provider meaningfully different from Gemini CLI's
    independent quota and worth calling out every time it's hit."""
    if category == "rate_limit":
        return (
            "Se alcanzó el límite de uso de tu cuenta de Claude (compartido con "
            "Claude Code). Esperá al reset de la ventana o cambiá a otro proveedor "
            "mientras tanto."
        )
    if category == "auth_or_config":
        return (
            "Claude Code CLI no está autenticado. Corré `claude` en una terminal "
            "para iniciar sesión."
        )
    return f"Claude CLI falló: {exc}"


def _extract_json_from_cli_text(text: str) -> dict:
    """Extracts a JSON object from CLI output that may wrap it in explanation
    text and/or markdown code fences — the exact shape observed from both
    CLIs when NOT using structured-output flags (--json-schema for Claude;
    Gemini CLI has no schema flag at all). Tries, in order: the whole string
    as JSON, a ```json fenced block, then the first {...} balanced-looking
    span. Raises json.JSONDecodeError (letting existing error handling treat
    it the same as any other malformed-JSON case) if none parse."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise json.JSONDecodeError("No JSON object found in CLI output", text, 0)


def _gemini_cli_fallback(e: Exception) -> tuple:
    """(fallback_category, fallback_reason) for a failed Gemini CLI call. An
    account rejection is also reported to the provider selector, so the
    dropdown stops offering gemini_cli instead of letting it fail every time."""
    unwrapped = _unwrap_retries_exhausted(e)
    if isinstance(unwrapped, CliProcessError):
        category = _classify_gemini_cli_error(unwrapped)
        rejection = _gemini_cli_account_rejection(unwrapped)
        if rejection:
            mark_account_rejected(
                "gemini_cli",
                "Google rechazó esta cuenta para Gemini CLI (no es un problema de sesión: "
                f"volver a loguearte no lo arregla). Mensaje de Google: {rejection}",
            )
        return category, _gemini_cli_error_message(unwrapped, category)
    if isinstance(unwrapped, CliNotInstalledError):
        return "auth_or_config", str(unwrapped)
    return classify_fallback_category(e), _format_fallback_reason("Gemini CLI", e)


class GeminiCliLLMClient(BaseLLMClient):
    """
    LLM client using the Gemini CLI (`gemini -p ... -o json`), authenticated
    via the user's Google account subscription session (OAuth login done once
    interactively — see README) instead of a billed API key.

    Quota: independent of any other Gemini usage (API key, AI Studio, etc.) —
    up to 1000 req/day and 60 RPM on Google AI Pro at the time this was
    written, vastly more than the free API key tier (250 req/day, 10 RPM) this
    project otherwise defaults to.
    """

    BINARY_NAME = "gemini"

    def __init__(self):
        if shutil.which(self.BINARY_NAME) is None:
            raise CliNotInstalledError(
                "Gemini CLI no está instalado. Instalalo con: npm install -g @google/gemini-cli"
            )

    def _build_args(self) -> List[str]:
        # NO -p/--prompt flag at all — the prompt is sent via stdin only (see
        # _run). Two things were verified experimentally here:
        # 1. A multi-line -p VALUE gets TRUNCATED at its first newline when
        #    this subprocess is a Windows .CMD shim (npm's gemini.CMD), which
        #    this project's prompts (SYSTEM_PROMPT + the thesis, always
        #    multi-line) would hit every time.
        # 2. Unlike Claude CLI (where a bare `-p` with no value means "read
        #    from stdin"), Gemini CLI's yargs-based parser REJECTS a bare
        #    `-p` with no following value ("Not enough arguments following: p").
        #    Omitting -p entirely and piping the prompt via stdin works
        #    instead: with stdin not a TTY, the CLI runs non-interactively on
        #    that input on its own, matching --help's own "[Appended to input
        #    on stdin (if any)]" note for the (now-omitted) prompt argument.
        return ["-o", "json"]

    def _run(self, prompt: str) -> dict:
        # GEMINI_CLI_TRUST_WORKSPACE=true is the headless-environment escape
        # hatch for the CLI's interactive "trust this folder?" prompt (see
        # https://geminicli.com/docs/cli/trusted-folders/#headless-and-automated-environments) —
        # passing --skip-trust as a positional CLI arg was observed (during
        # this feature's own development) to NOT reliably take effect when
        # invoked via subprocess on Windows; the env var worked every time in
        # the same conditions, so it's used instead of the flag.
        result = _run_cli_subprocess(
            self.BINARY_NAME,
            self._build_args(),
            stdin_text=prompt,
            env_overrides={"GEMINI_CLI_TRUST_WORKSPACE": "true"},
        )

        if result.returncode != 0:
            raise CliProcessError(
                f"Gemini CLI salió con código {result.returncode}",
                returncode=result.returncode,
                stderr=result.stderr,
            )

        try:
            outer = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise CliProcessError(
                f"Gemini CLI devolvió una salida no-JSON en stdout pese a -o json: {result.stdout[:300]!r}",
                returncode=result.returncode,
                stderr=result.stderr,
            ) from e

        # A "successful" (returncode 0) process can still carry a structured
        # error object in its JSON stdout — observed when the CLI's own
        # internal retries exhaust (e.g. persistent 429) but it still exits 0
        # after printing the final error as its result.
        if "error" in outer:
            err = outer["error"]
            raise CliProcessError(
                f"Gemini CLI reportó un error: {err.get('message', err)}",
                returncode=outer.get("error", {}).get("code") if isinstance(err, dict) else None,
                stderr=result.stderr or json.dumps(err),
            )

        response_text = outer.get("response", "")
        try:
            data = _extract_json_from_cli_text(response_text)
        except json.JSONDecodeError as e:
            raise CliProcessError(
                f"Gemini CLI no devolvió JSON parseable en su campo 'response': {response_text[:300]!r}",
                returncode=result.returncode,
                stderr=result.stderr,
            ) from e

        # stats.models keys report which model(s) actually answered — the CLI
        # can route between Gemini family models internally (observed:
        # gemini-3.8-flash as the main model, gemini-3.5-flash-lite as an
        # internal utility router), so provider_used reflects that instead of
        # a name this code assumed.
        models_used = list(outer.get("stats", {}).get("models", {}).keys())
        data["_provider_used"] = f"gemini-cli ({'/'.join(models_used)})" if models_used else "gemini-cli"
        return data

    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        prompt = f"{SYSTEM_PROMPT}\n\nHipótesis de inversión: \"{thesis}\"\n\nResponde ÚNICAMENTE con el JSON pedido, sin texto adicional ni explicaciones."
        try:
            async def _attempt():
                return await asyncio.to_thread(self._run, prompt)

            data = await _call_with_retry("Gemini CLI", _attempt)

            provider_used = data.pop("_provider_used", "gemini-cli")
            tickers = [TickerSuggestion(**t) for t in data.get("tickers", [])]
            macro_series = [MacroSuggestion(**m) for m in data.get("macro_series", [])]

            return ThesisResponse(
                thesis=thesis,
                summary=data.get("summary", "Análisis de tesis cuantitativa"),
                tickers=tickers,
                macro_series=macro_series,
                rationales=data.get("rationales", {}),
                provider_used=provider_used,
            )
        except Exception as e:
            category, reason = _gemini_cli_fallback(e)
            logger.error(f"Gemini CLI error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.parse_thesis(thesis)
            result.fallback_reason = reason
            result.fallback_category = category
            return result

    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
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
            f"- Capex resumido: {json.dumps(ctx.capex_summary or {})}\n\n"
            f"Responde ÚNICAMENTE con el JSON pedido, sin texto adicional ni explicaciones."
        )
        try:
            async def _attempt():
                return await asyncio.to_thread(self._run, prompt)

            data = await _call_with_retry("Gemini CLI", _attempt)

            return InterpretationResponse(
                what_data_says=data.get("what_data_says", ""),
                thesis_alignment=data.get("thesis_alignment", ""),
                next_series_suggestion=data.get("next_series_suggestion", ""),
                suggested_series_id=data.get("suggested_series_id"),
                provider_used=data.get("_provider_used", "gemini-cli"),
            )
        except Exception as e:
            category, reason = _gemini_cli_fallback(e)
            logger.error(f"Gemini CLI interpretation error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.interpret_situation(ctx)
            result.fallback_reason = reason
            result.fallback_category = category
            return result


class ClaudeCliLLMClient(BaseLLMClient):
    """
    LLM client using the Claude Code CLI (`claude -p ... --output-format json`),
    authenticated via the same Claude Pro/Max subscription session Claude Code
    itself uses interactively — no separately-billed API key.

    IMPORTANT — shared quota: unlike GeminiCliLLMClient's independent daily
    quota, this shares the SAME rolling 5-hour window and weekly cap as ALL
    other Claude usage on this account (claude.ai chat, Claude Code's own
    interactive sessions). Every call this client makes measurably eats into
    that shared budget — see README for when to prefer this vs. gemini_cli.

    Tools are fully disabled (--tools "") since this is pure text/JSON
    generation, never a coding task — verified experimentally (see this
    class's own module docstring notes / README) that this does not hang
    waiting for a permission prompt that can never be answered in this
    non-interactive context.
    """

    BINARY_NAME = "claude"

    def __init__(self, model: Optional[str] = None):
        if shutil.which(self.BINARY_NAME) is None:
            raise CliNotInstalledError(
                "Claude Code CLI no está instalado. Instalalo con: npm install -g @anthropic-ai/claude-code"
            )
        # Haiku by default: this project's own EngineSelector/AutoDiscoveryEngine
        # precedent (backend/services/auto_discovery.py) already established the
        # pattern of defaulting to the cheapest option that gets the job done
        # when a shared/limited budget is at stake — here that budget is the
        # user's shared 5h/weekly Claude usage window, not a benchmark's compute
        # time, but the reasoning is the same: minimize consumption by default,
        # let the user opt into a heavier option (sonnet) via config.
        self.model = model or settings.CLAUDE_CLI_MODEL

    def _build_args(self, system_prompt: Optional[str] = None, json_schema: Optional[dict] = None) -> List[str]:
        # -p with NO positional argument here — the user prompt is sent via
        # stdin instead (see _run). Verified experimentally: a multi-line
        # positional -p argument gets TRUNCATED at its first newline when
        # this subprocess is a Windows .CMD shim (npm's claude.CMD) — a 4-line
        # test prompt arrived at the model as just its first line ("Linea 1"),
        # with the rest silently lost before the process ever started. Since
        # interpret_situation's context block is inherently multi-line, this
        # isn't an edge case to special-case around — stdin is used
        # unconditionally for reliability, matching the CLI's own documented
        # support for it ("Appended to input on stdin (if any)").
        #
        # --system-prompt is REQUIRED (not optional) whenever a system prompt
        # is available: this project's SYSTEM_PROMPT opens with "Eres un
        # analista cuantitativo senior..." (a role-assumption sentence).
        # Verified experimentally that concatenating it into the user message
        # (the pattern every OTHER client in this file uses) makes Claude CLI
        # treat it as "adopt this persona for the session" and respond
        # conversationally ("Entendido, voy a trabajar como...") instead of
        # executing the task and emitting JSON — even with --output-format
        # json set. Passing it via --system-prompt instead makes the CLI
        # treat the stdin content as the actual one-shot task.
        args = [
            "-p",
            "--output-format", "json",
            "--model", self.model,
            "--tools", "",  # Empty string disables ALL tools (verified: see README)
            "--safe-mode",  # Skips CLAUDE.md/skills/plugins/hooks — pure prompt-in, JSON-out
        ]
        if system_prompt is not None:
            args += ["--system-prompt", system_prompt]
        if json_schema is not None:
            args += ["--json-schema", json.dumps(json_schema)]
        return args

    def _run(self, user_prompt: str, system_prompt: Optional[str] = None, json_schema: Optional[dict] = None) -> dict:
        result = _run_cli_subprocess(
            self.BINARY_NAME,
            self._build_args(system_prompt, json_schema),
            stdin_text=user_prompt,
        )

        if result.returncode != 0:
            raise CliProcessError(
                f"Claude CLI salió con código {result.returncode}",
                returncode=result.returncode,
                stderr=result.stderr,
            )

        # Observed during development: with --system-prompt set, the CLI
        # occasionally (not consistently reproducible — no stderr, no
        # non-zero exit) returns an empty stdout on an otherwise-successful
        # process. Treated as transient/retryable (the SAME prompt on a
        # retry has succeeded every time this was observed) rather than a
        # permanent parse failure.
        if not result.stdout.strip():
            raise CliProcessError(
                "Claude CLI devolvió stdout vacío (returncode 0, sin stderr) — falla transitoria observada durante el desarrollo.",
                returncode=result.returncode,
                stderr="503",  # matches _CLI_RETRYABLE_STDERR_PATTERNS' "503"-style transient bucket
            )

        try:
            outer = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise CliProcessError(
                f"Claude CLI devolvió una salida no-JSON en stdout: {result.stdout[:300]!r}",
                returncode=result.returncode,
                stderr=result.stderr,
            ) from e

        if isinstance(outer, dict) and outer.get("is_error"):
            raise CliProcessError(
                f"Claude CLI reportó un error: {outer.get('result', outer)}",
                returncode=result.returncode,
                stderr=result.stderr or str(outer.get("result", "")),
            )

        _log_claude_cli_cost(outer.get("total_cost_usd") if isinstance(outer, dict) else None, self.model)

        # Observed THREE distinct real shapes for stdout depending on flag
        # combination (verified by running the installed CLI directly, not
        # assumed from docs):
        #   1. --json-schema alone: {"result": "...", "structured_output": {...}, ...}
        #      -> prefer structured_output (already schema-validated by the CLI).
        #   2. --json-schema + --system-prompt: sometimes the outer object IS
        #      the data itself (no "result"/"structured_output" wrapper at all) —
        #      i.e. outer already has the schema's own top-level keys.
        #   3. No --json-schema: {"result": "...free text, maybe fenced JSON..."}
        #      -> parse 'result' with the same fence/brace extraction used
        #      elsewhere in this module.
        if isinstance(outer, dict) and "structured_output" in outer and outer["structured_output"] is not None:
            data = outer["structured_output"]
        elif isinstance(outer, dict) and "result" not in outer:
            # Shape 2: no wrapper: the schema's own keys are already top-level.
            data = outer
        else:
            result_text = outer.get("result", "") if isinstance(outer, dict) else ""
            try:
                data = _extract_json_from_cli_text(result_text)
            except json.JSONDecodeError as e:
                # Observed for real during development: the CLI occasionally
                # ignores --json-schema entirely and answers in free-form
                # prose/Markdown instead (this project's own SYSTEM_PROMPT
                # embeds an example JSON schema as illustrative TEXT inside
                # the prompt itself, which seems to sometimes compete with the
                # --json-schema flag for the model's attention). A retry of
                # the SAME prompt succeeded every time this was observed
                # during development, so it's marked retryable ("quota" is one
                # of _CLI_RETRYABLE_STDERR_PATTERNS, reused here as a marker)
                # rather than a permanent failure.
                raise CliProcessError(
                    f"Claude CLI no respetó --json-schema y devolvió texto libre en 'result': {result_text[:300]!r}",
                    returncode=result.returncode,
                    stderr=(result.stderr or "") + " [retryable: schema-not-honored, quota-bucket]",
                ) from e

        data["_provider_used"] = f"claude-cli-{self.model}"
        return data

    async def parse_thesis(self, thesis: str) -> ThesisResponse:
        # SYSTEM_PROMPT passed via --system-prompt, NOT concatenated into the
        # user message — see _build_args' comment for why the concatenated
        # form (used by every other client here) breaks with this CLI.
        user_prompt = f'Hipótesis de inversión: "{thesis}"'
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "tickers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "name": {"type": "string"},
                            "sector": {"type": "string"},
                            "weight": {"type": "number"},
                            "thesis_role": {"type": "string"},
                        },
                        "required": ["symbol", "name", "sector", "weight", "thesis_role"],
                    },
                },
                "macro_series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "series_id": {"type": "string"},
                            "name": {"type": "string"},
                            "category": {"type": "string"},
                            "expected_correlation": {"type": "string"},
                        },
                        "required": ["series_id", "name", "category"],
                    },
                },
                "rationales": {"type": "object"},
            },
            "required": ["summary", "tickers", "macro_series", "rationales"],
        }
        try:
            async def _attempt():
                return await asyncio.to_thread(self._run, user_prompt, CLAUDE_CLI_SYSTEM_PROMPT, schema)

            data = await _call_with_retry("Claude CLI", _attempt)

            provider_used = data.pop("_provider_used", f"claude-cli-{self.model}")
            tickers = [TickerSuggestion(**t) for t in data.get("tickers", [])]
            macro_series = [MacroSuggestion(**m) for m in data.get("macro_series", [])]

            return ThesisResponse(
                thesis=thesis,
                summary=data.get("summary", "Análisis de tesis cuantitativa"),
                tickers=tickers,
                macro_series=macro_series,
                rationales=data.get("rationales", {}),
                provider_used=provider_used,
            )
        except Exception as e:
            unwrapped = _unwrap_retries_exhausted(e)
            if isinstance(unwrapped, CliProcessError):
                category = _classify_claude_cli_error(unwrapped)
                reason = _claude_cli_error_message(unwrapped, category)
            elif isinstance(unwrapped, CliNotInstalledError):
                category = "auth_or_config"
                reason = str(unwrapped)
            else:
                category = classify_fallback_category(e)
                reason = _format_fallback_reason("Claude CLI", e)
            logger.error(f"Claude CLI error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.parse_thesis(thesis)
            result.fallback_reason = reason
            result.fallback_category = category
            return result

    async def interpret_situation(self, ctx: InterpretationContext) -> InterpretationResponse:
        user_prompt = (
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
        schema = {
            "type": "object",
            "properties": {
                "what_data_says": {"type": "string"},
                "thesis_alignment": {"type": "string"},
                "next_series_suggestion": {"type": "string"},
                "suggested_series_id": {"type": "string"},
            },
            "required": ["what_data_says", "thesis_alignment", "next_series_suggestion"],
        }
        try:
            async def _attempt():
                return await asyncio.to_thread(self._run, user_prompt, CLAUDE_CLI_INTERPRETATION_SYSTEM_PROMPT, schema)

            data = await _call_with_retry("Claude CLI", _attempt)

            return InterpretationResponse(
                what_data_says=data.get("what_data_says", ""),
                thesis_alignment=data.get("thesis_alignment", ""),
                next_series_suggestion=data.get("next_series_suggestion", ""),
                suggested_series_id=data.get("suggested_series_id"),
                provider_used=data.get("_provider_used", f"claude-cli-{self.model}"),
            )
        except Exception as e:
            unwrapped = _unwrap_retries_exhausted(e)
            if isinstance(unwrapped, CliProcessError):
                category = _classify_claude_cli_error(unwrapped)
                reason = _claude_cli_error_message(unwrapped, category)
            elif isinstance(unwrapped, CliNotInstalledError):
                category = "auth_or_config"
                reason = str(unwrapped)
            else:
                category = classify_fallback_category(e)
                reason = _format_fallback_reason("Claude CLI", e)
            logger.error(f"Claude CLI interpretation error: {e}. Falling back to MockLLMClient.")
            mock_client = MockLLMClient()
            result = await mock_client.interpret_situation(ctx)
            result.fallback_reason = reason
            result.fallback_category = category
            return result


def _log_claude_cli_cost(cost_usd: Optional[float], model: str) -> None:
    """Logs (and persists to SQLite) the accumulated daily cost of Claude CLI
    calls. Not for billing — it's a subscription, not pay-per-use — but the
    user has NO OTHER WAY to see how much of their shared 5h/weekly Claude
    quota this feature alone is consuming, since that's not exposed anywhere
    else in this project. See backend/database/models.py's ClaudeCliUsageModel."""
    if cost_usd is None:
        return
    try:
        from backend.database.connection import SessionLocal
        from backend.database.models import ClaudeCliUsageModel

        today = datetime.now(timezone.utc).date().isoformat()
        db = SessionLocal()
        try:
            row = db.query(ClaudeCliUsageModel).filter(
                ClaudeCliUsageModel.usage_date == today,
                ClaudeCliUsageModel.model == model,
            ).first()
            if row is None:
                row = ClaudeCliUsageModel(usage_date=today, model=model, call_count=0, total_cost_usd=0.0)
                db.add(row)
            row.call_count += 1
            row.total_cost_usd += cost_usd
            db.commit()
            logger.info(
                f"Claude CLI usage today ({model}): {row.call_count} calls, "
                f"${row.total_cost_usd:.4f} equivalent cost (subscription, not billed)."
            )
        finally:
            db.close()
    except Exception as e:
        # Usage tracking must never break the actual LLM call it's piggybacking on.
        logger.warning(f"Could not persist Claude CLI usage tracking: {e}")


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

    elif prov == "gemini_cli":
        try:
            return GeminiCliLLMClient()
        except CliNotInstalledError as e:
            logger.warning(f"Gemini CLI not available ({e}), falling back to MockLLMClient")
            return _PreFailedMockLLMClient(str(e))

    elif prov == "claude_cli":
        try:
            return ClaudeCliLLMClient()
        except CliNotInstalledError as e:
            logger.warning(f"Claude Code CLI not available ({e}), falling back to MockLLMClient")
            return _PreFailedMockLLMClient(str(e))

    else:
        return MockLLMClient()
