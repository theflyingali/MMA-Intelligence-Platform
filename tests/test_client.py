import logging

import pytest

from ingestion.ufcalendar.__main__ import RedactFilter
from ingestion.ufcalendar.client import ApiClient, BudgetExhausted, QuotaExhausted
from ingestion.ufcalendar.ratelimit import SlidingWindowLimiter

KEY = "ufcalendar_test_key_123456"


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.url = "https://api.test/v1/x"

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)

    def get(self, url, params=None, headers=None, timeout=None):
        return self.responses.pop(0)


def make_client(responses, budget=10, reserve=0):
    return ApiClient(KEY, "https://api.test/v1", SlidingWindowLimiter(100, sleep=lambda s: None),
                     budget=budget, quota_reserve=reserve, session=FakeSession(responses),
                     sleep=lambda s: None)


def test_retries_429_and_5xx_and_counts_every_attempt():
    c = make_client([
        FakeResponse(429, {"error": {"code": "rate_limited"}}, {"Retry-After": "2"}),
        FakeResponse(503),
        FakeResponse(200, {"data": 1}, {"X-RateLimit-Remaining": "990"}),
    ])
    r = c.get("event", "/events/1")
    assert r.status == 200 and r.body == {"data": 1}
    assert c.used == 3
    assert c.quota_remaining == 990


def test_quota_exceeded_stops_without_retry():
    c = make_client([FakeResponse(429, {"error": {"code": "quota_exceeded"}})])
    with pytest.raises(QuotaExhausted):
        c.get("event", "/events/1")
    assert c.used == 1


def test_budget_and_quota_reserve_stop_before_calling():
    c = make_client([FakeResponse(200, {}, {"X-RateLimit-Remaining": "50"})] * 2, budget=1)
    c.get("event", "/events/1")
    with pytest.raises(BudgetExhausted):
        c.get("event", "/events/2")

    c = make_client([FakeResponse(200, {}, {"X-RateLimit-Remaining": "50"})] * 2, reserve=100)
    c.get("event", "/events/1")
    with pytest.raises(QuotaExhausted):
        c.get("event", "/events/2")


def test_api_key_is_redacted_from_logs():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "header was Bearer %s", (KEY,), None)
    RedactFilter([KEY]).filter(record)
    assert KEY not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
