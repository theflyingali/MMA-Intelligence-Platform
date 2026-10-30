"""Fakes shared by the tests: a tiny in-memory UFCalendar API and a controllable clock."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from ingestion.ufcalendar.client import ApiResponse, BudgetExhausted
from ingestion.ufcalendar.config import Settings
from ingestion.ufcalendar.planner import iso

NOW = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def fight(fid: int, a: int, b: int, status: str = "completed", winner: int | None = None) -> dict[str, Any]:
    return {
        "id": fid,
        "status": status,
        "fighter_a": {"id": a, "slug": f"f{a}"},
        "fighter_b": {"id": b, "slug": f"f{b}"},
        "result": {"winner_fighter_id": winner if winner is not None else a, "method": "KO/TKO",
                   "round": 1, "time": "1:00"} if status == "completed" else None,
    }


class FakeApi:
    """Events newest first. Event 1 is 3 days old, event 2 is 10 days old, event 3 is 40 days old."""

    def __init__(self) -> None:
        self.events: dict[int, dict[str, Any]] = {
            1: {"id": 1, "slug": "e1", "starts_at": iso(NOW - timedelta(days=3)), "status": "completed",
                "card": [fight(101, 1, 2), fight(102, 3, 4), fight(103, 5, 6, status="cancelled")]},
            2: {"id": 2, "slug": "e2", "starts_at": iso(NOW - timedelta(days=10)), "status": "completed",
                "card": [fight(201, 1, 7), fight(202, 8, 9)]},
            3: {"id": 3, "slug": "e3", "starts_at": iso(NOW - timedelta(days=40)), "status": "completed",
                "card": [fight(301, 3, 10)]},
        }

    def respond(self, path: str, params: dict[str, Any] | None) -> tuple[int, Any]:
        parts = path.strip("/").split("/")
        if parts == ["events"]:
            rows = [{k: e[k] for k in ("id", "slug", "starts_at", "status")} for e in self.events.values()]
            return 200, {"data": rows, "meta": {"pagination": {"next_cursor": None, "has_more": False}}}
        if parts[0] == "events" and len(parts) == 2:
            return 200, {"data": {**self.events[int(parts[1])], "org": "ufc"}, "meta": {}}
        if parts[0] == "events" and parts[2] == "odds":
            return 200, {"data": {"fights": []}, "meta": {}}
        if parts[0] == "fights":
            return 200, {"data": [{"round": 1, "fighter_id": 1}], "meta": {}}
        if parts[0] == "fighters":
            return 200, {"data": {"id": int(parts[1])}, "meta": {}}
        return 404, {"error": {"code": "not_found"}}


class FakeClient:
    def __init__(self, api: FakeApi, clock: Clock, budget: int = 1000) -> None:
        self.api = api
        self.clock = clock
        self.budget = budget
        self.used = 0
        self.by_endpoint: Counter[str] = Counter()
        self.status_counts: Counter[str] = Counter()
        self.quota_remaining = None
        self.calls: list[tuple[str, str]] = []

    def get(self, endpoint: str, path: str, params: dict[str, Any] | None = None,
            etag: str | None = None) -> ApiResponse:
        if self.used >= self.budget:
            raise BudgetExhausted(f"request budget of {self.budget} reached")
        self.used += 1
        self.by_endpoint[endpoint] += 1
        self.calls.append((endpoint, path))
        status, body = self.api.respond(path, params)
        return ApiResponse(status=status, url=f"https://api.test/v1{path}", body=body,
                           etag=f'W/"{endpoint}-{path}"', fetched_at=iso(self.clock()))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(budget=1000, local_only=True, local_root=tmp_path / "landing", log_dir=tmp_path / "logs")
