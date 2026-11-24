"""When "corner A" is a real corner. Pure rule, shared by the Spark layer and the tests.

Evidence (share of decided bouts won by corner A, by year, full history 2026-11-24):
  UFC      100% up to 2009, 54 to 63% from 2010           -> reliable from 2010
  OKTAGON  76 to 100% for 2016 to 2018, 61 to 70% from 2019 -> reliable from 2019 (softer break, provisional)
  PFL      99 to 100% for 2017 to 2025, 79% in 2026       -> never reliable
  RIZIN    100% for 2015 to 2025, 79% in 2026             -> never reliable
Where it is about 100% the source lists the winner first, so corner A is the winner, not a corner.
Even where it is reliable, corner A wins about 55 to 65% (probably the favourite or higher-ranked
fighter), so a reliable corner is fine to display but is not a performance stat. Never a model feature.

An organisation missing from the map is unreliable until its history has been checked.
"""

from __future__ import annotations

CORNER_RELIABLE_FROM: dict[str, int] = {"ufc": 2010, "oktagon": 2019}


def corner_reliable(org: str | None, year: int | None) -> bool:
    if org is None or year is None:
        return False
    first_year = CORNER_RELIABLE_FROM.get(org)
    return first_year is not None and year >= first_year
