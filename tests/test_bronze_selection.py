from datetime import datetime, timedelta, timezone

import pytest

from bronze.ufcal_bronze.selection import ListedFile, earliest_event_ids, eligible, file_key, plan_run

ROOT = "/Volumes/mma/raw/landing/ufcalendar"
NOW = datetime(2026, 11, 22, 14, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=2)


def lf(rel, size=100, modified=OLD):
    return ListedFile(f"{ROOT}/{rel}", size, modified)


def listing():
    """Two old events (10, 11), one new event (12), their children, and the non-data files."""
    return {
        "event": [lf("event/ingest_date=2026-10-30/10.json"), lf("event/ingest_date=2026-10-30/11.json"),
                  lf("event/ingest_date=2026-11-22/12.json")],
        "event_odds": [lf("event_odds/ingest_date=2026-10-30/10.json"),
                       lf("event_odds/ingest_date=2026-10-30/11.json"),
                       lf("event_odds/ingest_date=2026-11-22/12.json")],
        "fight_rounds": [lf(f"fight_rounds/ingest_date=2026-10-30/{i}.json") for i in (100, 101, 200, 300)],
        "fighter": [lf(f"fighter/ingest_date=2026-10-30/{i}.json") for i in (1, 2, 3, 4, 9)],
        "events_list": [lf("events_list/ingest_date=2026-10-30/ufc_completed_081048Z_p1.json")],
    }


def no_cards(files):
    raise AssertionError("not expected")


def test_eligible_drops_manifest_lock_runs_empty_and_in_flight_files():
    files = [
        lf("_manifest.json"), lf("_lock.json"), lf("_runs/20261030T081044Z.json"),
        lf("event/ingest_date=2026-10-30/10.json"),
        lf("event/ingest_date=2026-10-30/11.json", size=0),                    # empty
        lf("event/ingest_date=2026-10-30/12.json", modified=NOW - timedelta(minutes=3)),  # still being written
    ]
    got = eligible(files, ROOT, NOW, quiet_minutes=10)
    assert [f.path for f in got] == [f"{ROOT}/event/ingest_date=2026-10-30/10.json"]


def test_full_run_takes_everything_not_yet_loaded():
    plan = plan_run(listing(), {}, root=ROOT, now=NOW, card_ids_for=no_cards)
    assert {ep: len(fs) for ep, fs in plan.items()} == {
        "events_list": 1, "event": 3, "event_odds": 3, "fight_rounds": 4, "fighter": 5}


def test_loaded_files_are_skipped_and_a_changed_file_is_reloaded():
    lst = listing()
    loaded = {"event": {file_key(f) for f in lst["event"]}}
    plan = plan_run(lst, loaded, root=ROOT, now=NOW, card_ids_for=no_cards)
    assert plan["event"] == []
    changed = ListedFile(lst["event"][0].path, 100, OLD + timedelta(minutes=1))  # same path, rewritten
    lst["event"][0] = changed
    assert plan_run(lst, loaded, root=ROOT, now=NOW, card_ids_for=no_cards)["event"] == [changed]


def test_second_run_after_marking_the_plan_loaded_is_empty():
    first = plan_run(listing(), {}, root=ROOT, now=NOW)
    loaded = {ep: {file_key(f) for f in fs} for ep, fs in first.items()}
    second = plan_run(listing(), loaded, root=ROOT, now=NOW)
    assert all(fs == [] for fs in second.values())


def test_subset_takes_the_earliest_events_and_only_their_children():
    seen = []

    def cards(files):
        seen.extend(f.path for f in files)
        return {100, 101}, {1, 2, 3}

    plan = plan_run(listing(), {}, root=ROOT, now=NOW, max_events=1, card_ids_for=cards)
    assert [f.path.rsplit("/", 1)[-1] for f in plan["event"]] == ["10.json"]
    assert [f.path.rsplit("/", 1)[-1] for f in plan["event_odds"]] == ["10.json"]
    assert sorted(f.path.rsplit("/", 1)[-1] for f in plan["fight_rounds"]) == ["100.json", "101.json"]
    assert sorted(f.path.rsplit("/", 1)[-1] for f in plan["fighter"]) == ["1.json", "2.json", "3.json"]
    assert len(plan["events_list"]) == 1  # list pages are never partially loaded
    assert seen == [f"{ROOT}/event/ingest_date=2026-10-30/10.json"]


def test_subset_is_stable_when_earlier_events_are_already_loaded():
    lst = listing()
    loaded = {"event": {file_key(lst["event"][0])}}  # event 10 loaded already
    plan = plan_run(lst, loaded, root=ROOT, now=NOW, max_events=1, card_ids_for=lambda fs: (set(), set()))
    assert plan["event"] == []  # still event 10, not "the next unloaded one"


def test_max_files_caps_each_endpoint_in_path_order():
    plan = plan_run(listing(), {}, root=ROOT, now=NOW, max_files=2)
    assert len(plan["fighter"]) == 2 and len(plan["fight_rounds"]) == 2
    assert plan["fighter"][0].path < plan["fighter"][1].path


def test_endpoint_selection():
    plan = plan_run(listing(), {}, root=ROOT, now=NOW, endpoints=("fighter",))
    assert set(plan) == {"fighter"}


def test_subset_needs_a_card_reader():
    with pytest.raises(ValueError):
        plan_run(listing(), {}, root=ROOT, now=NOW, max_events=1)


def test_earliest_event_ids_orders_by_ingest_date_then_path_and_dedupes_ids():
    files = [lf("event/ingest_date=2026-11-04/5.json"), lf("event/ingest_date=2026-10-30/9.json"),
             lf("event/ingest_date=2026-11-04/9__101500Z.json")]
    assert earliest_event_ids(files, ROOT, 2) == [9, 5]
