import pytest

import backend.services.llm_availability as availability


@pytest.fixture(autouse=True)
def _clear_llm_availability_cache():
    """A Gemini CLI account rejection in one test pins gemini_cli as unavailable
    in the process-wide availability cache; never let that leak across tests."""
    availability.clear_availability_cache()
    yield
    availability.clear_availability_cache()
