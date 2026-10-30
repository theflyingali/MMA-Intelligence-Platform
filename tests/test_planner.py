from collections import Counter
from dataclasses import replace
from datetime import timedelta

from ingestion.ufcalendar.manifest import Manifest
from ingestion.ufcalendar.planner import (
    event_fetch_reason,
    fight_state,
    iso,
    page_is_exhausted,
    pending_children,
    summarise_card,
)
from ingestion.ufcalendar.runner import Runner
from ingestion.ufcalendar.storage import LocalSink

from .conftest import NOW, FakeClient, fight


def ev(eid, days_ago):
    return {"id": eid, "starts_at": iso(NOW - timedelta(days=days_ago))}


def known_event(m, eid, days_ago, fetched_hours_ago, card):
    fights, fighter_ids = summarise_card(card)
    m.record("event", eid, fetched_at=iso(NOW - timedelta(hours=fetched_hours_ago)), http_status=200,
             starts_at=iso(NOW - timedelta(days=days_ago)), status="completed",
             fights=fights, fighter_ids=fighter_ids)


# ---- event_fetch_reason ----------------------------------------------------

def test_unknown_event_is_new():
    assert event_fetch_reason(ev(1, 100), Manifest(), NOW, 14, 72) == "new"


def test_old_known_event_is_not_refetched():
    m = Manifest()
    known_event(m, 1, days_ago=40, fetched_hours_ago=1000, card=[])
    assert event_fetch_reason(ev(1, 40), m, NOW, 14, 72) is None


def test_recent_event_respects_min_refetch_interval():
    m = Manifest()
    known_event(m, 1, days_ago=3, fetched_hours_ago=71, card=[])
    assert event_fetch_reason(ev(1, 3), m, NOW, 14, 72) is None
    known_event(m, 1, days_ago=3, fetched_hours_ago=73, card=[])
    assert event_fetch_reason(ev(1, 3), m, NOW, 14, 72) == "refresh"


# ---- card summary and children ---------------------------------------------

def test_summarise_card_skips_cancelled_corners_and_dedupes():
    card = [fight(1, 10, 11), fight(2, 10, 12), fight(3, 13, 14, status="cancelled")]
    fights, fighter_ids = summarise_card(card)
    assert set(fights) == {"1", "2", "3"}
    assert fighter_ids == [10, 11, 12]


def test_new_event_owes_odds_played_rounds_and_fighters():
    m = Manifest()
    known_event(m, 1, 3, 0, [fight(101, 1, 2), fight(102, 3, 4, status="cancelled")])
    tasks = pending_children(1, m)
    assert [(t.endpoint, t.key) for t in tasks] == [
        ("event_odds", 1), ("fight_rounds", 101), ("fighter", 1), ("fighter", 2)]


def test_complete_event_owes_nothing():
    m = Manifest()
    card = [fight(101, 1, 2)]
    known_event(m, 1, 3, 1, card)
    later = iso(NOW)
    m.record("event_odds", 1, fetched_at=later)
    m.record("fight_rounds", 101, fetched_at=later, fight_state=fight_state(card[0]))
    m.record("fighter", 1, fetched_at=later)
    m.record("fighter", 2, fetched_at=later)
    assert pending_children(1, m) == []


def test_changed_result_refetches_rounds_and_refresh_refetches_odds():
    m = Manifest()
    original = fight(101, 1, 2, winner=1)
    known_event(m, 1, 3, 1, [original])
    m.record("event_odds", 1, fetched_at=iso(NOW))
    m.record("fight_rounds", 101, fetched_at=iso(NOW), fight_state=fight_state(original))
    m.record("fighter", 1, fetched_at=iso(NOW))
    m.record("fighter", 2, fetched_at=iso(NOW))

    # Result overturned on review, seen when the event is refreshed later.
    known_event(m, 1, 3, -1, [fight(101, 1, 2, winner=2)])
    assert [(t.endpoint, t.key) for t in pending_children(1, m)] == [("event_odds", 1), ("fight_rounds", 101)]


def test_fighter_refetched_after_a_newer_fight():
    m = Manifest()
    m.record("fighter", 1, fetched_at=iso(NOW - timedelta(days=20)))
    known_event(m, 1, days_ago=3, fetched_hours_ago=0, card=[fight(101, 1, 2)])
    keys = [t.key for t in pending_children(1, m) if t.endpoint == "fighter"]
    assert keys == [1, 2]

    m.record("fighter", 1, fetched_at=iso(NOW))
    m.record("fighter", 2, fetched_at=iso(NOW))
    known_event(m, 2, days_ago=10, fetched_hours_ago=0, card=[fight(201, 1, 2)])
    assert [t for t in pending_children(2, m) if t.endpoint == "fighter"] == []


def test_page_is_exhausted_only_when_all_known_and_old():
    m = Manifest()
    known_event(m, 1, 40, 1000, [])
    assert page_is_exhausted([ev(1, 40)], m, NOW, 14)
    assert not page_is_exhausted([ev(1, 40), ev(2, 50)], m, NOW, 14)  # 2 unknown
    known_event(m, 3, 5, 1, [])
    assert not page_is_exhausted([ev(3, 5)], m, NOW, 14)  # inside refresh window


# ---- end to end with a fake API --------------------------------------------

def test_second_run_fetches_only_the_events_list(api, clock, settings):
    sink = LocalSink(settings.local_root)
    m = Manifest()

    first = FakeClient(api, clock)
    s1 = Runner(settings, first, sink, m, "r1", now=clock).run()
    assert s1.stop_reason == "completed"
    # 1 list + 3 events + 3 odds + 5 played bouts + 8 unique fighters
    # (cancelled bout's corners 5 and 6 skipped; fighters 1 and 3 fetched once, on their newest event)
    assert first.by_endpoint == Counter(events_list=1, event=3, event_odds=3, fight_rounds=5, fighter=8)

    clock.advance(minutes=5)
    second = FakeClient(api, clock)
    Runner(settings, second, sink, m, "r2", now=clock).run()
    assert second.calls == [("events_list", "/events")]


def test_refresh_after_interval_only_costs_event_and_odds(api, clock, settings):
    sink = LocalSink(settings.local_root)
    m = Manifest()
    Runner(settings, FakeClient(api, clock), sink, m, "r1", now=clock).run()

    clock.advance(hours=73)
    unchanged = FakeClient(api, clock)
    Runner(settings, unchanged, sink, m, "r2", now=clock).run()
    # Events 1 and 2 are inside the 14-day window; event 3 is not.
    assert unchanged.by_endpoint == Counter(events_list=1, event=2, event_odds=2)

    clock.advance(hours=73)
    api.events[1]["card"][0] = fight(101, 1, 2, winner=2)  # overturned
    changed = FakeClient(api, clock)
    Runner(settings, changed, sink, m, "r3", now=clock).run()
    assert ("fight_rounds", "/fights/101/rounds") in changed.calls
    assert changed.by_endpoint["fight_rounds"] == 1


def test_dry_run_makes_no_calls(api, clock, settings):
    s = replace(settings, dry_run=True, max_events=10)
    summary = Runner(s, None, LocalSink(settings.local_root), Manifest(), "dry", now=clock).run()
    est = summary.estimate
    assert summary.requests_used == 0
    assert est["new_events"] == 10
    assert est["requests_by_endpoint"]["events_list"] == 1
    assert est["total_requests"] == 1 + 10 + 10 + 10 * 12 + 10 * 24
    assert not (settings.local_root / "_manifest.json").exists()
