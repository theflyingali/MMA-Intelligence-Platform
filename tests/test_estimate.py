from ingestion.ufcalendar.estimate_backfill import compute_estimate, known_counts
from ingestion.ufcalendar.manifest import Manifest


def test_counts_subtract_known_and_respect_capabilities():
    per_org_year = {
        "ufc": {2025: {"events": 150, "bouts": 1500}, 2026: {"events": 50, "bouts": 500}},
        "rizin": {2026: {"events": 10, "bouts": 100}},
    }
    caps = {"ufc": {"rounds": True, "odds": True}, "rizin": {"rounds": False, "odds": True}}
    known = {"ufc": {"events": 10, "bouts": 96}}
    e = compute_estimate(per_org_year, caps, known, fighters_cap=4500, known_fighters=192, rpm=60)

    ufc, rizin = e["orgs"]["ufc"], e["orgs"]["rizin"]
    assert (ufc["events_list"], ufc["event"], ufc["event_odds"], ufc["fight_rounds"]) == (2, 190, 190, 1904)
    assert (rizin["events_list"], rizin["event"], rizin["event_odds"], rizin["fight_rounds"]) == (1, 10, 10, 0)
    # 2 x 2,100 bouts = 4,200 is below the 4,500 cap, so the per-bout bound applies
    assert e["requests_by_endpoint"]["fighter"] == 4200 - 192
    assert e["total_requests"] == sum(e["requests_by_endpoint"].values())


def test_fighters_bounded_by_two_per_bout_for_small_scopes():
    e = compute_estimate({"pfl": {2026: {"events": 2, "bouts": 20}}}, {}, {}, fighters_cap=4500)
    assert e["requests_by_endpoint"]["fighter"] == 40


def test_known_counts_from_manifest():
    m = Manifest()
    m.record("event", 1, org="ufc", fights={"1": {"status": "completed"}, "2": {"status": "cancelled"}})
    m.record("fighter", 7, fetched_at="x")
    assert known_counts(m) == ({"ufc": {"events": 1, "bouts": 1}}, 1)
