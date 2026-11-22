from datetime import datetime, timedelta, timezone

from bronze.ufcal_bronze.dedupe import Versioned, latest_wins, replaces

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def v(key, fetched_min, mod_min=0, file="a", value=None):
    return Versioned(key, T0 + timedelta(minutes=fetched_min), T0 + timedelta(minutes=mod_min), file, value)


def test_latest_fetched_at_wins_regardless_of_input_order():
    items = [v(1, 5, value="new"), v(1, 1, value="old"), v(2, 3, value="only")]
    for order in (items, items[::-1]):
        best = latest_wins(order)
        assert best[1].value == "new" and best[2].value == "only"
        assert len(best) == 2


def test_ties_break_on_modification_time_then_path():
    assert latest_wins([v(1, 5, 1, "a"), v(1, 5, 2, "b")])[1].source_file == "b"
    assert latest_wins([v(1, 5, 1, "z"), v(1, 5, 1, "a")])[1].source_file == "z"


def test_rerunning_the_same_data_is_a_stable_noop():
    items = [v(1, 1), v(1, 2), v(2, 1)]
    once = latest_wins(items)
    twice = latest_wins(list(once.values()) + items)
    assert once == twice


def test_merge_rule_never_lets_an_older_row_replace_a_newer_one():
    new, old = v(1, 5), v(1, 1)
    assert replaces(new, old) and not replaces(old, new)
    assert replaces(new, new)  # same file reprocessed: harmless update
