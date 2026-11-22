"""Event title rules. The regex strings are shared with the Spark layer, so Python and Spark agree.

Evidence (600 real UFC titles, 2026-11-22): sponsor prefixes are `Crypto.com`, `VeChain` and
`Polymarket`. Other leads before the brand are part of the event name (`Noche UFC`, `Road to UFC`),
so stripping "anything before the brand" would be wrong. Only listed sponsors are stripped; any other
lead is reported in `title_lead_unreviewed` for review on the full history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KNOWN_SPONSORS = ("Crypto.com", "VeChain", "Polymarket")
# Leads that are part of the event name, not sponsors: not reported for review.
KNOWN_NON_SPONSOR_LEADS = ("noche", "road to")
BRANDS = ("Dana White's", "UFC", "PFL", "OKTAGON", "RIZIN", "DWCS", "The Ultimate Fighter")

SPONSOR_PATTERN = r"(?i)^(" + "|".join(re.escape(s) for s in KNOWN_SPONSORS) + r")\s+"
LEAD_PATTERN = r"(?i)^(.+?)\s+(?:" + "|".join(re.escape(b) for b in BRANDS) + r")\b"
CONTENDER_PATTERN = r"(?i)dwcs|contender series"


@dataclass(frozen=True)
class TitleParts:
    clean: str
    sponsor: str | None  # stripped prefix
    lead_unreviewed: str | None  # a lead before the brand that is neither a known sponsor nor a known name part


def clean_title(title: str | None) -> TitleParts | None:
    if title is None:
        return None
    m = re.match(SPONSOR_PATTERN, title)
    if m:
        return TitleParts(clean=title[m.end():].strip(), sponsor=m.group(1), lead_unreviewed=None)
    lead = re.match(LEAD_PATTERN, title)
    lead_text = lead.group(1).strip() if lead else None
    if lead_text and lead_text.lower() not in KNOWN_NON_SPONSOR_LEADS:
        return TitleParts(clean=title.strip(), sponsor=None, lead_unreviewed=lead_text)
    return TitleParts(clean=title.strip(), sponsor=None, lead_unreviewed=None)


def is_contender_series(slug: str | None, title: str | None) -> bool:
    """Dana White's Contender Series (incl. the Tuesday Night and DWCS Brazil editions).

    Slug or title: on 600 real events they disagreed on 2 (DWCS Brazil), so either is enough.
    """
    return re.search(CONTENDER_PATTERN, f"{slug or ''} {title or ''}") is not None
