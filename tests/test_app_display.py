"""Display rules for the dashboard: corners, results, nulls, escaping and search."""

from datetime import date

import pandas as pd
import pytest

from app import display as d


def bout(**kw):
    base = dict(fighter_a_id=1, fighter_a_name="Alpha", fighter_b_id=2, fighter_b_name="Bravo",
                outcome="a_win", winner_fighter_id=1, corner_reliable=True)
    base.update(kw)
    return base


@pytest.mark.parametrize("reliable", [True, False, None])
def test_decided_bout_lists_winner_first_and_never_claims_corner_order(reliable):
    h = d.bout_headline(bout(outcome="b_win", winner_fighter_id=2, corner_reliable=reliable))
    assert (h.first_name, h.connector, h.second_name) == ("Bravo", "def.", "Alpha")
    assert h.corner_order is False
    assert d.order_note(h, reliable) == "Winner listed first."


def test_undecided_bout_shows_corner_order_only_when_reliable():
    reliable = d.bout_headline(bout(outcome="draw", winner_fighter_id=None, corner_reliable=True))
    unreliable = d.bout_headline(bout(outcome="draw", winner_fighter_id=None, corner_reliable=False))
    missing = d.bout_headline(bout(outcome="no_contest", winner_fighter_id=None, corner_reliable=pd.NA))
    assert reliable.corner_order and reliable.note == "Draw"
    assert not unreliable.corner_order and not missing.corner_order
    assert "corner A" in d.order_note(reliable, True)
    assert "not a real corner" in d.order_note(unreliable, False)
    assert "corner A" not in d.order_note(unreliable, False)


def test_unknown_outcome_has_no_winner():
    h = d.bout_headline(bout(outcome="unknown", winner_fighter_id=None))
    assert h.connector == "vs" and h.note == "Result unknown"
    assert d.fighter_result("unknown", None, 1) == "Unknown"
    assert d.fighter_result("a_win", None, 1) == "Unknown"  # decided but winner missing upstream


@pytest.mark.parametrize("outcome,winner,fighter,expected", [
    ("a_win", 1, 1, "Win"), ("a_win", 1, 2, "Loss"), ("b_win", 2, 1, "Loss"),
    ("draw", None, 1, "Draw"), ("no_contest", None, 2, "No contest"), (None, None, 1, "Unknown"),
])
def test_fighter_result_ignores_corner(outcome, winner, fighter, expected):
    assert d.fighter_result(outcome, winner, fighter) == expected


def test_opponent():
    assert d.opponent(bout(), 1) == (2, "Bravo")
    assert d.opponent(bout(), 2) == (1, "Alpha")


@pytest.mark.parametrize("args,expected", [
    (("ko_tko", "Punches"), "KO/TKO (Punches)"),
    (("decision_unanimous", "Unanimous"), "Decision (unanimous)"),
    (("decision", "Split"), "Decision (split)"),
    (("draw", "Majority"), "Draw (majority)"),
    (("submission", "Submission"), "Submission"),
    ((None, None, "Overturned"), "Overturned"),
    ((None, None, None), d.DASH),
])
def test_method_label(args, expected):
    assert d.method_label(*args) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Light heavyweight", "Light Heavyweight"), ("108lb Catchweight", "108lb Catchweight"),
    ("Women's Strawweight", "Women's Strawweight"), (None, d.DASH),
])
def test_tidy_weight_class(raw, expected):
    assert d.tidy_weight_class(raw) == expected


def test_null_formatting():
    for v in (None, pd.NA, float("nan"), pd.NaT, ""):
        assert d.missing(v)
    assert d.fmt_record(None, None, None) == d.DASH
    assert d.fmt_record(29, 1, 0, 0) == "29-1-0"
    assert d.fmt_record(5, 2, None, 1) == "5-2-0 (1 NC)"
    assert d.fmt_pct(pd.NA) == d.DASH and d.fmt_pct(0.584) == "58%"
    assert d.fmt_cm(None) == d.DASH and d.fmt_cm(177.8) == "178 cm"
    assert d.round_time(None, None) == d.DASH and d.round_time(2, "3:15") == "R2 3:15"
    assert d.fmt_seconds(125) == "2:05" and d.fmt_date(None) == d.DASH
    assert d.landed_of(5, None) == "5" and d.landed_of(5, 9) == "5 of 9"


def test_age():
    assert d.age_years(date(1991, 10, 27), date(2026, 11, 24)) == 35
    assert d.age_years(date(1991, 12, 1), date(2026, 11, 24)) == 34
    assert d.age_years(None, date(2026, 11, 24)) is None
    assert d.age_years(pd.NA, date(2026, 11, 24)) is None


def test_contender_series_is_its_own_org():
    assert d.org_key("ufc", True) == "dwcs"
    assert d.org_key("ufc", False) == "ufc"
    assert d.org_key("pfl", None) == "pfl"
    assert d.org_label("dwcs") == "Contender Series"


def test_parse_orgs_and_links():
    assert d.parse_orgs(None) == list(d.ORG_KEYS)
    assert d.parse_orgs("pfl,nonsense, RIZIN") == ["pfl", "rizin"]
    assert d.parse_orgs("nonsense") == list(d.ORG_KEYS)
    assert d.href("fighter", list(d.ORG_KEYS), id=7) == "?view=fighter&id=7"
    assert d.href("fighter", ["pfl"], id=7) == "?view=fighter&id=7&orgs=pfl"


def test_source_text_is_escaped():
    evil = '<script>alert(1)</script>'
    assert "<script>" not in d.esc(evil)
    assert "<script>" not in d.link(evil, '?view=x&"onmouseover=1')
    assert '"onmouseover' not in d.link("x", '?view=x&"onmouseover=1')
    table = d.html_table(["<b>"], [["cell"]])
    assert "<th>&lt;b&gt;</th>" in table
    assert "<thead>" not in d.html_table(None, [["a"]])


def test_dataset_summary_counts_methods():
    history = pd.DataFrame([
        dict(outcome="a_win", winner_fighter_id=1, method_normalized="ko_tko"),
        dict(outcome="b_win", winner_fighter_id=1, method_normalized="technical_submission"),
        dict(outcome="a_win", winner_fighter_id=9, method_normalized="decision_split"),
        dict(outcome="draw", winner_fighter_id=None, method_normalized="draw"),
        dict(outcome="unknown", winner_fighter_id=None, method_normalized="decision_split"),
        dict(outcome="a_win", winner_fighter_id=1, method_normalized=None),
    ])
    s = d.dataset_summary(history, 1)
    assert s["counts"] == {"Win": 3, "Loss": 1, "Draw": 1, "No contest": 0, "Unknown": 1}
    assert s["win_methods"] == {"KO/TKO": 1, "Submission": 1, "Decision": 0, "Other": 1}
    assert s["loss_methods"]["Decision"] == 1


def test_search_is_accent_insensitive_and_respects_orgs():
    index = pd.DataFrame([
        dict(fighter_id=1, name="Juan Díaz", nickname="Pegajoso", orgs="dwcs,ufc", bouts=3),
        dict(fighter_id=2, name="Nate Diaz", nickname=None, orgs="ufc", bouts=27),
        dict(fighter_id=3, name="Hassan Shaaban", nickname="Diaz", orgs="oktagon,pfl", bouts=9),
        dict(fighter_id=4, name="Unknown Orgs", nickname=None, orgs=None, bouts=0),
    ])
    assert list(d.search_fighters(index, "diaz", list(d.ORG_KEYS))["fighter_id"]) == [2, 3, 1]
    assert list(d.search_fighters(index, "DÍAZ", ["pfl"])["fighter_id"]) == [3]
    assert list(d.search_fighters(index, "juan diaz", ["dwcs"])["fighter_id"]) == [1]
    assert d.search_fighters(index, "   ", list(d.ORG_KEYS)).empty
    assert d.search_fighters(index, "orgs", list(d.ORG_KEYS)).empty
