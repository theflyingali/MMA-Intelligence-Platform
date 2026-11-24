import pytest

from silver.ufcal_silver.corner import CORNER_RELIABLE_FROM, corner_reliable


@pytest.mark.parametrize("org,year,expected", [
    ("ufc", 2009, False), ("ufc", 2010, True), ("ufc", 2026, True), ("ufc", 1993, False),
    ("oktagon", 2018, False), ("oktagon", 2019, True), ("oktagon", 2026, True),
    ("pfl", 2018, False), ("pfl", 2026, False),
    ("rizin", 2015, False), ("rizin", 2026, False),
    ("bkfc", 2026, False),          # unknown org: unreliable until its history is checked
    (None, 2026, False), ("ufc", None, False),
])
def test_corner_reliable(org, year, expected):
    assert corner_reliable(org, year) is expected


def test_only_orgs_with_a_checked_clean_history_are_listed():
    assert CORNER_RELIABLE_FROM == {"ufc": 2010, "oktagon": 2019}
