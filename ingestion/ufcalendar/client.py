"""HTTP client for the UFCalendar API: rate limit, retries, budget and request log.

The API key only ever lives in the session's Authorization header. Headers are never logged.
"""

from __future__ import annotations

import logging
import random
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from .planner import iso
from .ratelimit import SlidingWindowLimiter

log = logging.getLogger("ufcalendar.requests")

USER_AGENT = "mma-intelligence-ingest/0.1 (personal, non-commercial)"


class StopRun(Exception):
    """Base for conditions that end a run cleanly (manifest is still saved)."""


class BudgetExhausted(StopRun):
    pass


class QuotaExhausted(StopRun):
    pass


class ApiError(Exception):
    def __init__(self, status: int | None, code: str | None, path: str) -> None:
        super().__init__(f"{path}: HTTP {status} {code or ''}".strip())
        self.status = status
        self.code = code
        self.path = path


class FatalApiError(ApiError):
    """Auth or plan problems: retrying other requests is pointless."""


@dataclass
class ApiResponse:
    status: int
    url: str  # as sent, without credentials (auth is a header)
    body: Any
    etag: str | None
    fetched_at: str


class ApiClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        limiter: SlidingWindowLimiter,
        budget: int,
        quota_reserve: int,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 4,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.limiter = limiter
        self.budget = budget
        self.quota_reserve = quota_reserve
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        })
        self._sleep = sleep
        self.max_retries = max_retries
        self.timeout = timeout
        self.used = 0
        self.by_endpoint: Counter[str] = Counter()
        self.status_counts: Counter[str] = Counter()
        self.quota_remaining: int | None = None
        self.quota_limit: int | None = None

    def _check_budget(self) -> None:
        if self.used >= self.budget:
            raise BudgetExhausted(f"request budget of {self.budget} reached")
        if self.quota_remaining is not None and self.quota_remaining <= self.quota_reserve:
            raise QuotaExhausted(
                f"monthly quota remaining ({self.quota_remaining}) at or below reserve ({self.quota_reserve})"
            )

    def _read_quota(self, headers: Any) -> None:
        for name, attr in (("X-RateLimit-Remaining", "quota_remaining"), ("X-RateLimit-Limit", "quota_limit")):
            value = headers.get(name)
            if value is not None:
                try:
                    setattr(self, attr, int(value))
                except ValueError:
                    pass

    def _backoff(self, attempt: int) -> float:
        wait = min(60.0, 2.0 ** attempt) + random.uniform(0, 1)
        self._sleep(wait)
        return wait

    def get(
        self,
        endpoint: str,
        path: str,
        params: dict[str, Any] | None = None,
        etag: str | None = None,
    ) -> ApiResponse:
        url = self.base_url + path
        headers = {"If-None-Match": etag} if etag else {}
        attempt = 0
        while True:
            attempt += 1
            self._check_budget()
            self.limiter.acquire()
            self.used += 1
            self.by_endpoint[endpoint] += 1
            started = time.monotonic()
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                self.status_counts["connection_error"] += 1
                self._log(endpoint, path, "ERR", started, attempt, type(exc).__name__)
                if attempt > self.max_retries:
                    raise ApiError(None, "connection_error", path) from None
                self._backoff(attempt)
                continue

            self.status_counts[str(r.status_code)] += 1
            self._read_quota(r.headers)
            sent = urlsplit(r.url)
            sent_path = sent.path + (f"?{sent.query}" if sent.query else "")
            self._log(endpoint, sent_path, r.status_code, started, attempt)

            if r.status_code in (200, 304, 404):
                body = _json_or_none(r) if r.status_code != 304 else None
                return ApiResponse(
                    status=r.status_code,
                    url=r.url,
                    body=body,
                    etag=r.headers.get("ETag"),
                    fetched_at=iso(datetime.now(timezone.utc)),
                )

            code = _error_code(r)
            if r.status_code == 429:
                if code == "quota_exceeded":
                    raise QuotaExhausted("monthly quota exceeded (HTTP 429 quota_exceeded)")
                if attempt > self.max_retries:
                    raise ApiError(429, code, path)
                retry_after = _retry_after(r)
                if retry_after is not None:
                    self._sleep(retry_after)
                else:
                    self._backoff(attempt)
                continue
            if r.status_code >= 500:
                if attempt > self.max_retries:
                    raise ApiError(r.status_code, code, path)
                self._backoff(attempt)
                continue
            if r.status_code in (401, 403):
                raise FatalApiError(r.status_code, code, path)
            raise ApiError(r.status_code, code, path)

    def _log(self, endpoint: str, path: str, status: Any, started: float, attempt: int, note: str = "") -> None:
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info(
            "endpoint=%s path=%s status=%s latency_ms=%d attempt=%d used=%d/%d quota_remaining=%s%s",
            endpoint, path, status, latency_ms, attempt, self.used, self.budget,
            self.quota_remaining if self.quota_remaining is not None else "?",
            f" note={note}" if note else "",
        )


def _json_or_none(r: requests.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def _error_code(r: requests.Response) -> str | None:
    body = _json_or_none(r)
    if isinstance(body, dict):
        return (body.get("error") or {}).get("code")
    return None


def _retry_after(r: requests.Response) -> float | None:
    value = r.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(120.0, max(1.0, float(value)))
    except ValueError:
        return None
