"""
Tests for the runtime LLM provider selector (GET /api/config/llm-providers,
POST /api/config/llm-provider). The switch is in memory only: every test here
pins settings.LLM_PROVIDER through monkeypatch so the original value is
restored afterwards, exactly like a server restart would go back to .env.
"""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

import backend.api.routes as routes
import backend.services.llm_availability as availability
import backend.services.llm_router as llm_router
from backend.config import settings
from backend.main import app
from backend.schemas.models import ThesisResponse

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_provider_state(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    availability.clear_availability_cache()
    yield
    availability.clear_availability_cache()


def _no_prerequisites(monkeypatch):
    """No API keys, no CLI binaries in PATH, Ollama unreachable."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(availability.shutil, "which", lambda name: None)
    monkeypatch.setattr(llm_router.shutil, "which", lambda name: None)

    def unreachable(*args, **kwargs):
        raise availability.httpx.ConnectError("connection refused")

    monkeypatch.setattr(availability.httpx, "get", unreachable)


def test_provider_list_reflects_real_availability(monkeypatch):
    _no_prerequisites(monkeypatch)

    response = client.get("/api/config/llm-providers")
    assert response.status_code == 200
    data = response.json()
    by_id = {p["id"]: p for p in data["providers"]}

    assert set(by_id) == {"gemini", "gemini_cli", "claude_cli", "openai", "ollama", "mock"}
    assert by_id["gemini"]["available"] is False
    assert by_id["gemini"]["reason"] == "Sin GEMINI_API_KEY configurada"
    assert by_id["openai"]["available"] is False
    assert by_id["openai"]["reason"] == "Sin OPENAI_API_KEY configurada"
    assert by_id["gemini_cli"]["available"] is False
    assert by_id["gemini_cli"]["reason"].startswith("gemini CLI no instalado")
    assert by_id["claude_cli"]["available"] is False
    assert by_id["claude_cli"]["reason"].startswith("claude CLI no instalado")
    assert by_id["ollama"]["available"] is False
    assert "Ollama no responde" in by_id["ollama"]["reason"]

    # mock never depends on anything external.
    assert by_id["mock"]["available"] is True
    assert by_id["mock"]["reason"] is None

    # The quota reminder travels with the option, and the response states the
    # switch is not persisted.
    assert by_id["claude_cli"]["note"] == "Comparte cupo con tu uso de Claude Code"
    assert data["persisted"] is False
    assert ".env" in data["notice"]


def test_claude_cli_installed_but_not_logged_in(monkeypatch):
    monkeypatch.setattr(availability.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, stdout=json.dumps({"loggedIn": False}), stderr="")

    monkeypatch.setattr(availability.subprocess, "run", fake_run)

    assert availability.check_provider("claude_cli") == (
        False, "claude CLI no autenticado (corré `claude` una vez para iniciar sesión)"
    )
    assert calls == [["/usr/bin/claude", "auth", "status", "--json"]]

    # Cached: rendering the dropdown again doesn't re-spawn the CLI.
    availability.check_provider("claude_cli")
    assert len(calls) == 1


def test_gemini_cli_installed_but_not_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(availability.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(availability.Path, "home", classmethod(lambda cls: tmp_path))

    available, reason = availability.check_provider("gemini_cli")
    assert available is False
    assert reason.startswith("gemini CLI no autenticado")

    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini" / "oauth_creds.json").write_text("{}")
    assert availability.check_provider("gemini_cli", force_refresh=True) == (True, None)


def test_switch_provider_takes_effect_without_restart(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")

    async def fake_parse(self, thesis):
        return ThesisResponse(
            thesis=thesis, summary="ok", tickers=[], macro_series=[], rationales={},
            provider_used="openai-gpt-4o-mini",
        )

    monkeypatch.setattr(llm_router.OpenAILLMClient, "parse_thesis", fake_parse)

    built = []
    real_get_llm_client = routes.get_llm_client

    def spy_get_llm_client(*args, **kwargs):
        c = real_get_llm_client(*args, **kwargs)
        built.append(c)
        return c

    monkeypatch.setattr(routes, "get_llm_client", spy_get_llm_client)

    # Before the switch: the in-memory value is mock.
    r = client.post("/api/thesis", json={"thesis": "Energía nuclear para data centers de IA"})
    assert r.status_code == 200
    assert r.json()["provider_used"] == "mock-semantic-engine"

    switch = client.post("/api/config/llm-provider", json={"provider": "openai"})
    assert switch.status_code == 200
    assert switch.json()["active"] == "openai"
    assert switch.json()["previous"] == "mock"
    assert switch.json()["persisted"] is False
    assert settings.LLM_PROVIDER == "openai"

    # Same process, same app, nothing restarted: the next thesis uses openai.
    r = client.post("/api/thesis", json={"thesis": "Energía nuclear para data centers de IA"})
    assert r.status_code == 200
    assert r.json()["provider_used"] == "openai-gpt-4o-mini"
    assert type(built[-1]) is llm_router.OpenAILLMClient

    assert client.get("/api/config/llm-providers").json()["active"] == "openai"
    assert client.get("/api/health").json()["llm_provider"] == "openai"


def test_switch_to_unavailable_provider_rejected(monkeypatch):
    _no_prerequisites(monkeypatch)

    r = client.post("/api/config/llm-provider", json={"provider": "gemini"})
    assert r.status_code == 400
    assert "Sin GEMINI_API_KEY configurada" in r.json()["detail"]
    assert settings.LLM_PROVIDER == "mock"

    r = client.post("/api/config/llm-provider", json={"provider": "claude_cli"})
    assert r.status_code == 400
    assert "claude CLI no instalado" in r.json()["detail"]
    assert settings.LLM_PROVIDER == "mock"


def test_switch_to_unknown_provider_rejected():
    r = client.post("/api/config/llm-provider", json={"provider": "gpt-99"})
    assert r.status_code == 400
    assert "Proveedor desconocido" in r.json()["detail"]
    assert settings.LLM_PROVIDER == "mock"
