"""
The 4.10 evaluation harness never retries Gemini's DAILY-quota 429 (each retry
burns a request of the same exhausted quota); a per-minute 429 is retried.
Real error bodies seen on 2026-09-27/28.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from thesis_prompt_eval import is_daily_quota  # noqa: E402

DAILY = ("Gemini falló tras 3 intentos (rate limit): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
         "'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': "
         "'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '20'}]}]}}")
PER_MINUTE = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': [{'quotaId': "
              "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaValue': '5'}]}]}}")
UNAVAILABLE = "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}"


def test_daily_quota_is_told_apart_from_per_minute():
    assert is_daily_quota(DAILY) is True
    assert is_daily_quota(PER_MINUTE) is False
    assert is_daily_quota(UNAVAILABLE) is False
    assert is_daily_quota(None) is False
