"""The Claude CLI copilot must not silently fall back to the mock (ADR-0030).

The end-to-end check of v1.0 found "Interpretar Situación" answering with the
local heuristic engine: Claude CLI had ignored --json-schema and returned free
Markdown, 3 of 3 attempts, exactly the failure ADR-0030 documented for the
thesis prompt. The fix there was a one-line system prompt with the rules in
the schema's field descriptions; this pins the same shape for the copilot.
"""
from backend.services.llm_router import (
    CLAUDE_CLI_INTERPRETATION_SHORT_SYSTEM_PROMPT,
    CLAUDE_CLI_INTERPRETATION_SYSTEM_PROMPT,
    CLAUDE_CLI_SYSTEM_PROMPT,
)


def test_el_system_prompt_del_cli_es_corto():
    """The long, numbered one is what breaks --json-schema."""
    assert len(CLAUDE_CLI_INTERPRETATION_SHORT_SYSTEM_PROMPT) < 200
    assert "\n" not in CLAUDE_CLI_INTERPRETATION_SHORT_SYSTEM_PROMPT.strip()
    # Same shape as the thesis one, which was already fixed in ADR-0030.
    assert len(CLAUDE_CLI_INTERPRETATION_SHORT_SYSTEM_PROMPT) < len(CLAUDE_CLI_SYSTEM_PROMPT)


def test_el_prompt_largo_sigue_para_los_demas_proveedores():
    """Gemini, OpenAI and Ollama do respect it: it is not deleted, just not
    used for the CLI."""
    assert "Reglas obligatorias" in CLAUDE_CLI_INTERPRETATION_SYSTEM_PROMPT
    assert len(CLAUDE_CLI_INTERPRETATION_SYSTEM_PROMPT) > 1000


def test_el_cli_usa_el_prompt_corto_y_las_reglas_van_en_el_schema():
    """The rules must survive the move: they now live in the descriptions."""
    import asyncio
    import backend.services.llm_router as lr

    captured = {}

    class FakeCli(lr.ClaudeCliLLMClient):
        def __init__(self):  # no CLI on PATH needed
            self.model = "sonnet"

        def _run(self, user_prompt, system_prompt=None, json_schema=None):
            captured["system"] = system_prompt
            captured["schema"] = json_schema
            return {"what_data_says": "a", "thesis_alignment": "b", "next_series_suggestion": "c"}

    from backend.schemas.models import InterpretationContext
    ctx = InterpretationContext(
        thesis="t", active_series_id="HOUST", last_price=1.0, projected_target=1.0,
        lower_bound=0.9, upper_bound=1.1, series_type="macro",
    )
    res = asyncio.run(FakeCli().interpret_situation(ctx))
    assert res.provider_used == "claude-cli-sonnet", "no cayó al mock"

    assert captured["system"] == CLAUDE_CLI_INTERPRETATION_SHORT_SYSTEM_PROMPT
    descriptions = " ".join(
        p.get("description", "") for p in captured["schema"]["properties"].values()
    )
    # The rules that used to live in the system prompt.
    assert "no agregues cifras" in descriptions
    assert "no son una muestra" in descriptions or "muestra representativa" in descriptions
    assert "Sin medir" in descriptions
    assert "modelo estadístico" in descriptions
