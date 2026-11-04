from datetime import datetime, timedelta, timezone

import pytest

from ingestion.ufcalendar.__main__ import load_api_key
from ingestion.ufcalendar.client import QuotaExhausted
from ingestion.ufcalendar.storage import LocalSink, RunLocked, acquire_lock, release_lock

from .test_client import FakeResponse, make_client

T0 = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)


def test_second_run_is_refused_while_lock_is_held(tmp_path):
    sink = LocalSink(tmp_path)
    acquire_lock(sink, "job-run", T0)
    with pytest.raises(RunLocked):
        acquire_lock(sink, "laptop-run", T0 + timedelta(minutes=5))


def test_released_or_stale_lock_can_be_taken(tmp_path):
    sink = LocalSink(tmp_path)
    acquire_lock(sink, "a", T0)
    release_lock(sink, "a", T0 + timedelta(minutes=30))
    acquire_lock(sink, "b", T0 + timedelta(minutes=31))  # released

    acquire_lock(sink, "c", T0 + timedelta(hours=13), break_lock=False)  # b went stale after 12h


def test_break_lock_and_only_owner_releases(tmp_path):
    sink = LocalSink(tmp_path)
    acquire_lock(sink, "a", T0)
    release_lock(sink, "someone-else", T0)  # not the owner: no effect
    with pytest.raises(RunLocked):
        acquire_lock(sink, "b", T0)
    acquire_lock(sink, "b", T0, break_lock=True)


def test_key_from_secret_scope_wins_over_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("UFCAL_KEY=from_env_file_123\n")
    seen = []

    def fake_secret(scope, key):
        seen.append((scope, key))
        return "from_secret_scope_456"

    assert load_api_key(env, "mma", "ufcal_key", read_secret=fake_secret) == "from_secret_scope_456"
    assert seen == [("mma", "ufcal_key")]
    assert load_api_key(env) == "from_env_file_123"


def test_missing_secret_stops_the_run(tmp_path):
    with pytest.raises(SystemExit):
        load_api_key(tmp_path / ".env", "mma", "ufcal_key", read_secret=lambda s, k: "")


def test_backfill_refuses_to_run_on_a_small_plan():
    c = make_client([FakeResponse(200, {}, {"X-RateLimit-Limit": "1000"})] * 2)
    c.min_plan_quota = 30000
    c.get("events_list", "/events")  # first response reveals the plan
    with pytest.raises(QuotaExhausted, match="plan allows 1000"):
        c.get("event", "/events/1")
    assert c.used == 1
