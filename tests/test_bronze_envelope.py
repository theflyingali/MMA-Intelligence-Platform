import json

import pytest

from bronze.ufcal_bronze.envelope import canonical_ts, card_ids, fingerprint, parse_envelope

from .bronze_fixtures import envelope, event_resp, fighter_resp, list_resp, odds_resp, rounds_resp


def test_event_row_keeps_raw_payload_and_fields():
    p = parse_envelope("event", envelope(event_resp(10, "pfl")), name_id=10)
    (r,) = p.rows
    assert (r.key, r.org, r.slug, r.fetched_at, r.http_status) == (10, "pfl", "ev-10", "2026-10-30T08:15:57Z", 200)
    assert json.loads(r.payload) == event_resp(10, "pfl")  # nothing dropped


def test_odds_org_and_key_come_from_the_nested_event():
    (r,) = parse_envelope("event_odds", envelope(odds_resp(7, "rizin"))).rows
    assert (r.key, r.org) == (7, "rizin")


def test_rounds_key_from_meta_then_filename():
    (r,) = parse_envelope("fight_rounds", envelope(rounds_resp(100))).rows
    assert r.key == 100
    resp = rounds_resp(100)
    del resp["meta"]
    assert parse_envelope("fight_rounds", envelope(resp), name_id=55).rows[0].key == 55


def test_empty_rounds_list_is_valid():
    resp = {"data": [], "meta": {"fight_id": 9}}
    p = parse_envelope("fight_rounds", envelope(resp))
    assert p.reject is None and p.rows[0].key == 9


def test_fighter_row():
    (r,) = parse_envelope("fighter", envelope(fighter_resp(5))).rows
    assert (r.key, r.slug, r.org) == (5, "f5", None)


def test_events_list_explodes_one_row_per_event():
    p = parse_envelope("events_list", envelope(list_resp((1, "ufc"), (2, "pfl"))))
    assert [(r.key, r.org) for r in p.rows] == [(1, "ufc"), (2, "pfl")]
    assert json.loads(p.rows[0].payload)["slug"] == "ev-1"


@pytest.mark.parametrize("text,reason", [
    ("", "empty"),
    ("   \n", "empty"),
    ('{"request_url": "x", "fetched_at": "2026-10-30T08:', "invalid_json"),  # truncated mid-write
    ("[1, 2]", "not_object"),
    ('{"response": {}}', "missing_envelope"),
    (envelope(event_resp(), fetched_at="yesterday"), "bad_fetched_at"),
    (envelope(event_resp(), status=404), "non_200"),
    (envelope({"data": "oops"}), "bad_data"),
])
def test_rejections(text, reason):
    assert parse_envelope("event", text, name_id=1).reject == reason


def test_missing_key_rejected_when_no_filename_id():
    assert parse_envelope("event", envelope({"data": {"slug": "x"}})).reject == "missing_key"
    assert parse_envelope("event", envelope({"data": {"slug": "x"}}), name_id=3).rows[0].key == 3


def test_string_id_is_accepted():
    resp = event_resp(10)
    resp["data"]["id"] = "10"
    assert parse_envelope("event", envelope(resp)).rows[0].key == 10


def test_drift_new_unknown_and_missing_fields_do_not_break_the_load():
    base = event_resp(10)
    drifted = event_resp(10)
    drifted["data"]["brand_new_field"] = {"nested": [1, 2]}
    del drifted["data"]["slug"]
    a = parse_envelope("event", envelope(base)).rows[0]
    b = parse_envelope("event", envelope(drifted)).rows[0]
    assert b.slug is None and "brand_new_field" in b.payload
    assert a.fingerprint != b.fingerprint  # drift is visible
    assert a.fingerprint == parse_envelope("event", envelope(base)).rows[0].fingerprint  # and stable


def test_fingerprint_ignores_values_and_list_length():
    one = {"card": [{"id": 1, "x": 1}]}
    many = {"card": [{"id": 2, "x": 9}, {"id": 3, "x": 8}]}
    assert fingerprint(one) == fingerprint(many)


def test_canonical_ts_handles_offsets_and_fractions():
    assert canonical_ts("2026-10-24T14:00:00.000Z") == "2026-10-24T14:00:00Z"
    assert canonical_ts("2026-10-24T16:00:00+02:00") == "2026-10-24T14:00:00Z"
    assert canonical_ts(None) is None


def test_card_ids_skip_cancelled_fighters_but_keep_all_fights():
    fights, fighters = card_ids(event_resp())
    assert fights == {100, 101}
    assert fighters == {1, 2}  # bout 101 is cancelled, so fighters 3 and 4 are not owed
    assert card_ids(json.dumps({"data": {}})) == (set(), set())


def test_unknown_endpoint_raises():
    with pytest.raises(ValueError):
        parse_envelope("scorecards", envelope({}))
