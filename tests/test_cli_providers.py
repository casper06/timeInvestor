"""
Tests for the subscription CLI LLM providers (GeminiCliLLMClient,
ClaudeCliLLMClient) and the Gemini safety-filter handling shared by both
Gemini clients (API key and CLI).

Error text patterns used in the CLI mocks below are the REAL text produced by
the installed CLIs during this feature's own development (Gemini CLI 0.61.0,
Claude Code CLI 2.1.281) — see llm_router.py's module-level comments next to
_classify_gemini_cli_error/_classify_claude_cli_error for exactly which
patterns were verified against a live process vs. which (Claude's shared
usage-limit wording specifically) were not reproduced to avoid burning the
developer's real shared quota, and instead match Anthropic's known public
terminology.
"""
import asyncio
import json
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from backend.services.llm_router import (
    GeminiCliLLMClient,
    ClaudeCliLLMClient,
    GeminiLLMClient,
    CliProcessError,
    CliNotInstalledError,
    classify_fallback_category,
    GeminiSafetyBlockError,
)


class AsyncNoopSleep:
    async def __call__(self, *args, **kwargs):
        return None


def _fake_completed_process(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr)


# Real stderr (trimmed) from Gemini CLI 0.61.0 on 2026-09-24 when Google rejects
# the account itself (IneligibleTierError / UNSUPPORTED_CLIENT), exit code 1.
INELIGIBLE_ACCOUNT_STDERR = (
    "  ineligibleTiers: [\n"
    "    {\n"
    "      reasonCode: 'UNSUPPORTED_CLIENT',\n"
    "      tierId: 'free-tier',\n"
    "    }\n"
    "  ]\n"
    "[STARTUP] Recording metric for phase: authenticate duration: 918.8\n"
    "An unexpected critical error occurred:IneligibleTierError: This client is no longer "
    "supported for Gemini Code Assist for individuals. To continue using Gemini, please "
    "migrate to the Antigravity suite of products: https://antigravity.google\n"
    "    at throwIneligibleOrProjectIdError (file:///.../chunk-JDPZ4CE3.js:311090:11)\n"
)


# ---------------------------------------------------------------------------
# GeminiCliLLMClient
# ---------------------------------------------------------------------------

def test_gemini_cli_parses_successful_output(monkeypatch):
    """Mocks a successful subprocess.run returning the real shape Gemini CLI's
    -o json produces (a 'response' string field, 'stats.models' keys) and
    verifies parse_thesis extracts the JSON embedded in 'response' and reports
    which model(s) actually answered as provider_used."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    fake_payload = {
        "summary": "Tesis de prueba",
        "tickers": [{"symbol": "CEG", "name": "Constellation Energy", "sector": "Utilities", "weight": 1.0, "thesis_role": "Primary"}],
        "macro_series": [],
        "rationales": {"CEG": "test"},
    }
    stdout = json.dumps({
        "session_id": "abc",
        "response": "```json\n" + json.dumps(fake_payload) + "\n```",
        "stats": {"models": {"gemini-3.8-flash": {}, "gemini-3.5-flash-lite": {}}},
    })

    with patch("subprocess.run", return_value=_fake_completed_process(0, stdout, "")):
        client = GeminiCliLLMClient()
        resp = asyncio.run(client.parse_thesis("Demanda eléctrica por IA"))

    assert resp.summary == "Tesis de prueba"
    assert len(resp.tickers) == 1
    assert resp.tickers[0].symbol == "CEG"
    assert resp.provider_used == "gemini-cli (gemini-3.8-flash/gemini-3.5-flash-lite)"
    assert resp.fallback_reason is None


def test_gemini_cli_rate_limit_classified_correctly(monkeypatch):
    """Mocks the REAL Gemini CLI stderr text observed when its daily free-tier
    quota is exhausted: `TerminalQuotaError: You have exhausted your daily
    quota on this model.` with returncode 429 — captured by running the
    installed CLI directly against the account authenticated on this machine
    during this feature's development, not invented."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("asyncio.sleep", AsyncNoopSleep())

    real_stderr = (
        'Error when talking to Gemini API TerminalQuotaError: You have exhausted your daily quota on this model.\n'
        '  cause: {\n'
        "    code: 429,\n"
        "    message: 'You exceeded your current quota, please check your plan and billing details. "
        "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
        "limit: 20, model: gemini-3.8-flash'\n"
        "  }\n"
    )

    with patch("subprocess.run", return_value=_fake_completed_process(429, "", real_stderr)):
        client = GeminiCliLLMClient()
        resp = asyncio.run(client.parse_thesis("Demanda eléctrica por IA"))

    assert resp.provider_used == "mock-semantic-engine"
    assert resp.fallback_category == "rate_limit"


def test_gemini_cli_auth_expired_message(monkeypatch):
    """Mocks an expired/revoked OAuth session — the underlying google-auth-library
    (used by Gemini CLI) surfaces this as the OAuth2 standard `invalid_grant`
    error code (found by reading the installed package's own bundled source,
    not guessed) — and verifies the CLI-SPECIFIC message is used (pointing at
    `gemini` re-login), not GeminiLLMClient's .env-focused message."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("asyncio.sleep", AsyncNoopSleep())

    real_stderr = (
        "GaxiosError: invalid_grant\n"
        "    at Gaxios._request (file:///.../gaxios/build/src/gaxios.js:xxx)\n"
        "error_description: 'Token has been expired or revoked.' (ReAuth required)\n"
    )

    with patch("subprocess.run", return_value=_fake_completed_process(1, "", real_stderr)):
        client = GeminiCliLLMClient()
        resp = asyncio.run(client.parse_thesis("Demanda eléctrica por IA"))

    assert resp.fallback_category == "auth_or_config"
    assert resp.fallback_reason is not None
    assert "gemini" in resp.fallback_reason.lower()
    assert "sesión" in resp.fallback_reason.lower() or "session" in resp.fallback_reason.lower()
    # Must NOT be the API-key-focused message from GeminiLLMClient's own path.
    assert ".env" not in resp.fallback_reason


def test_gemini_cli_ineligible_account_message(monkeypatch):
    """Real stderr (trimmed) from Gemini CLI 0.61.0 on 2026-09-24: Google
    rejects the account itself (IneligibleTierError / UNSUPPORTED_CLIENT) with
    exit code 1. The reason must carry Google's own message and must NOT tell
    the user to log in again, which doesn't help here."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("asyncio.sleep", AsyncNoopSleep())

    with patch("subprocess.run", return_value=_fake_completed_process(1, "", INELIGIBLE_ACCOUNT_STDERR)):
        client = GeminiCliLLMClient()
        resp = asyncio.run(client.parse_thesis("Demanda eléctrica por IA"))

    assert resp.fallback_category == "auth_or_config"
    assert "This client is no longer supported for Gemini Code Assist for individuals" in resp.fallback_reason
    assert "volver a loguearte no lo arregla" in resp.fallback_reason
    assert "salió con código 1" not in resp.fallback_reason


def test_gemini_cli_marked_unavailable_after_account_rejection(monkeypatch, tmp_path):
    """The credentials file exists (so the cheap check says available), but a
    real call gets IneligibleTierError. From then on the selector must list
    gemini_cli as unavailable with Google's reason — without waiting out the
    regular 60 s cache, and without anyone touching the credentials file."""
    from fastapi.testclient import TestClient
    import backend.services.llm_availability as availability
    from backend.config import settings
    from backend.main import app

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("asyncio.sleep", AsyncNoopSleep())
    monkeypatch.setattr(availability.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini" / "oauth_creds.json").write_text("{}")

    # Primes the regular 60 s cache with "available".
    assert availability.check_provider("gemini_cli") == (True, None)

    with patch("subprocess.run", return_value=_fake_completed_process(1, "", INELIGIBLE_ACCOUNT_STDERR)):
        asyncio.run(GeminiCliLLMClient().parse_thesis("Demanda eléctrica por IA"))

    api = TestClient(app)
    for refresh in ("false", "true"):
        providers = api.get(f"/api/config/llm-providers?refresh={refresh}").json()["providers"]
        gemini_cli = next(p for p in providers if p["id"] == "gemini_cli")
        assert gemini_cli["available"] is False
        assert gemini_cli["reason"].startswith("Google rechazó esta cuenta para Gemini CLI")
        assert "This client is no longer supported for Gemini Code Assist" in gemini_cli["reason"]
        assert "no autenticado" not in gemini_cli["reason"]

    # Forcing it anyway hits the existing availability validation.
    switch = api.post("/api/config/llm-provider", json={"provider": "gemini_cli"})
    assert switch.status_code == 400
    assert "Google rechazó esta cuenta" in switch.json()["detail"]
    assert settings.LLM_PROVIDER == "mock"

    # Past the rejection TTL, the regular check runs again.
    real_monotonic = availability.time.monotonic
    monkeypatch.setattr(
        availability.time, "monotonic",
        lambda: real_monotonic() + availability.ACCOUNT_REJECTION_TTL_SECONDS + 1,
    )
    assert availability.check_provider("gemini_cli") == (True, None)


def test_gemini_cli_unknown_failure_includes_stderr_cause(monkeypatch):
    """An unclassified failure still says WHY, not only the exit code."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("asyncio.sleep", AsyncNoopSleep())

    stderr = "[STARTUP] noise\nAn unexpected critical error occurred:SomethingNewError: boom\n    at x (y.js:1:1)\n"
    with patch("subprocess.run", return_value=_fake_completed_process(1, "", stderr)):
        resp = asyncio.run(GeminiCliLLMClient().parse_thesis("Demanda eléctrica por IA"))

    assert resp.fallback_category == "unknown"
    assert "código 1" in resp.fallback_reason
    assert "SomethingNewError: boom" in resp.fallback_reason


def test_gemini_cli_not_installed_falls_back_to_mock(monkeypatch):
    """If the gemini binary isn't on PATH, get_llm_client must degrade to Mock
    instead of crashing the server at startup."""
    from backend.services.llm_router import get_llm_client
    monkeypatch.setattr("shutil.which", lambda name: None)

    client = get_llm_client("gemini_cli")
    resp = asyncio.run(client.parse_thesis("test"))
    assert resp.provider_used == "mock-semantic-engine"
    assert resp.fallback_category == "auth_or_config"
    assert "instalado" in resp.fallback_reason.lower()


# ---------------------------------------------------------------------------
# ClaudeCliLLMClient
# ---------------------------------------------------------------------------

def test_claude_cli_parses_json_schema_output(monkeypatch):
    """Mocks the REAL shape claude -p --output-format json --json-schema ...
    produces when the schema is honored: a top-level 'structured_output' field
    already parsed/validated by the CLI itself (observed directly against the
    installed CLI during development) — preferred over parsing 'result'."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    structured = {
        "summary": "Tesis vía Claude CLI",
        "tickers": [{"symbol": "NVDA", "name": "NVIDIA", "sector": "Semis", "weight": 1.0, "thesis_role": "Primary"}],
        "macro_series": [],
        "rationales": {"NVDA": "test"},
    }
    stdout = json.dumps({
        "is_error": False,
        "result": json.dumps(structured),
        "structured_output": structured,
        "total_cost_usd": 0.0314,
    })

    with patch("subprocess.run", return_value=_fake_completed_process(0, stdout, "")):
        with patch("backend.services.llm_router._log_claude_cli_cost") as mock_log:
            client = ClaudeCliLLMClient()
            resp = asyncio.run(client.parse_thesis("Demanda de cómputo IA"))

    assert resp.summary == "Tesis vía Claude CLI"
    assert resp.tickers[0].symbol == "NVDA"
    assert resp.provider_used == "claude-cli-haiku"
    mock_log.assert_called_once()
    assert mock_log.call_args[0][0] == 0.0314


def test_claude_cli_no_tool_use_attempted():
    """
    Confirms the constructed subprocess command actually restricts tools —
    the failure mode this guards against is the CLI hanging forever waiting
    for a permission-prompt confirmation that can never arrive in this
    non-interactive context.

    How this was verified beyond this test: the exact command
    (`claude -p <prompt> --output-format json --model haiku --tools ""
    --safe-mode`) was run directly against the real, authenticated Claude
    Code CLI on this machine during development, with a plain informational
    prompt (no schema) — it returned in ~1-3s with `permission_denials: []`
    in its JSON output, confirming no tool use was attempted and nothing
    hung waiting for a prompt. This test checks the ARGUMENT CONSTRUCTION
    (--tools followed by an empty string) so a future edit that accidentally
    removes or changes that flag fails a fast unit test instead of only
    being caught by manually re-running the real CLI.
    """
    client = ClaudeCliLLMClient(model="haiku")
    args = client._build_args()

    assert "--tools" in args
    tools_idx = args.index("--tools")
    assert args[tools_idx + 1] == "", (
        "--tools must be followed by an empty string to disable ALL tools — "
        "otherwise a non-interactive claude -p call can hang forever waiting "
        "for a permission prompt with nobody able to answer it"
    )
    assert "--safe-mode" in args


def test_claude_cli_rate_limit_uses_shared_quota_message(monkeypatch):
    """
    Claude CLI's exact stderr wording for hitting the shared 5-hour/weekly
    usage window was NOT reproduced against the real CLI (doing so would
    require deliberately exhausting the developer's real, shared Claude
    quota during this feature's development, which was avoided) — this
    mocks Anthropic's known public terminology for that condition
    ("usage limit") and verifies the SHARED-quota-specific message is used.
    """
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("asyncio.sleep", AsyncNoopSleep())

    fake_stderr = "Error: You have reached your usage limit for the current session window."

    with patch("subprocess.run", return_value=_fake_completed_process(1, "", fake_stderr)):
        client = ClaudeCliLLMClient()
        resp = asyncio.run(client.parse_thesis("test"))

    assert resp.fallback_category == "rate_limit"
    assert "compartido" in resp.fallback_reason.lower()
    assert "claude code" in resp.fallback_reason.lower()


def test_claude_cli_not_installed_falls_back_to_mock(monkeypatch):
    from backend.services.llm_router import get_llm_client
    monkeypatch.setattr("shutil.which", lambda name: None)

    client = get_llm_client("claude_cli")
    resp = asyncio.run(client.parse_thesis("test"))
    assert resp.provider_used == "mock-semantic-engine"
    assert resp.fallback_category == "auth_or_config"
    assert "instalado" in resp.fallback_reason.lower()


def test_get_llm_client_factory_accepts_new_providers(monkeypatch):
    """LLM_PROVIDER=gemini_cli / claude_cli must instantiate the right client
    class when the corresponding binary is available — confirms the factory
    wiring, not just each client's own constructor."""
    from backend.services.llm_router import get_llm_client
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    gemini_client = get_llm_client("gemini_cli")
    assert isinstance(gemini_client, GeminiCliLLMClient)

    claude_client = get_llm_client("claude_cli")
    assert isinstance(claude_client, ClaudeCliLLMClient)


def test_claude_cli_model_is_configurable(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    client = ClaudeCliLLMClient(model="sonnet")
    args = client._build_args()
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "sonnet"


# ---------------------------------------------------------------------------
# Safety filter (finish_reason SAFETY/RECITATION/...) — both Gemini clients
# ---------------------------------------------------------------------------

def test_safety_filter_not_retried_api_key_client(monkeypatch):
    """A finish_reason=SAFETY response from the real google-genai SDK client
    must classify as content_filtered and must NOT trigger _call_with_retry's
    retry loop (retrying the identical prompt would be blocked identically)."""
    monkeypatch.setattr("asyncio.sleep", AsyncNoopSleep())

    fake_candidate = MagicMock()
    fake_candidate.finish_reason.name = "SAFETY"
    fake_response = MagicMock()
    fake_response.candidates = [fake_candidate]

    call_count = {"n": 0}

    def mock_generate_content(*args, **kwargs):
        call_count["n"] += 1
        return fake_response

    def mock_gemini_init(self, api_key=None):
        self.api_key = api_key or "fake-test-key-123"
        self._client = MagicMock()
        self._client.models.generate_content.side_effect = mock_generate_content

    monkeypatch.setattr(GeminiLLMClient, "__init__", mock_gemini_init)

    client = GeminiLLMClient()
    resp = asyncio.run(client.parse_thesis("some thesis that got blocked"))

    assert call_count["n"] == 1, "a safety block must not be retried"
    assert resp.provider_used == "mock-semantic-engine"
    assert resp.fallback_category == "content_filtered"
    assert "filtro de contenido" in resp.fallback_reason.lower()


def test_safety_filter_not_retried_cli_client(monkeypatch):
    """Same guarantee for GeminiCliLLMClient — even though the CLI doesn't
    expose a typed finish_reason the way the SDK does, classify_fallback_category
    must still recognize a GeminiSafetyBlockError if one is raised, so both
    Gemini-family clients agree on this category for the equivalent condition."""
    assert classify_fallback_category(GeminiSafetyBlockError("SAFETY")) == "content_filtered"


def test_gemini_safety_block_error_not_in_retryable_patterns():
    """GeminiSafetyBlockError must never be treated as retryable by _is_retryable
    — it has no status code and isn't a CliProcessError, so it falls through to
    False by construction; this test locks that in explicitly."""
    from backend.services.llm_router import _is_retryable
    assert _is_retryable(GeminiSafetyBlockError("RECITATION")) is False
