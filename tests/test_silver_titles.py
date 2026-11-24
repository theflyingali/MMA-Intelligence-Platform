import pytest

from silver.ufcal_silver.titles import clean_title, is_contender_series, title_says_cancelled


@pytest.mark.parametrize("title,clean,sponsor", [
    ("Crypto.com UFC 331", "UFC 331", "Crypto.com"),
    ("VeChain UFC 322: Della Maddalena vs Makhachev", "UFC 322: Della Maddalena vs Makhachev", "VeChain"),
    ("Polymarket UFC 334: Gane vs Hokit", "UFC 334: Gane vs Hokit", "Polymarket"),
    ("polymarket UFC 1", "UFC 1", "polymarket"),
    ("UFC 333: Volkanovski vs Evloev", "UFC 333: Volkanovski vs Evloev", None),
    ("UFC Fight Night: Buckley vs Malott", "UFC Fight Night: Buckley vs Malott", None),
])
def test_known_sponsors_are_stripped_and_kept_as_a_column(title, clean, sponsor):
    p = clean_title(title)
    assert (p.clean, p.sponsor, p.lead_unreviewed) == (clean, sponsor, None)


@pytest.mark.parametrize("title", ["Super RIZIN 2", "Super RIZIN / RIZIN 38", "East PRO Fight - Powered by OKTAGON MMA"])
def test_reviewed_event_names_are_not_reported(title):
    assert clean_title(title).lead_unreviewed is None


@pytest.mark.parametrize("title,expected", [
    ("PFL MENA 8: Khobar (cancelled)", True),
    ("UFC 99 (Canceled)", True),
    ("PFL 4 postponed", True),
    ("OKTAGON PRIME 4 - SE PŘESOUVÁ", True),
    ("oktagon prime 4 - se přesouvá", True),
    ("OKTAGON TIME", False),
    ("OKTAGON SUMMER FEST", False),
    ("UFC 333: Volkanovski vs Evloev", False),
    (None, False),
])
def test_title_says_cancelled(title, expected):
    assert title_says_cancelled(title) is expected


@pytest.mark.parametrize("title", ["Noche UFC: Lopes vs Silva", "Road to UFC Season 4 Semifinals", "Road To UFC: Maheshate vs Flowers"])
def test_event_name_leads_are_not_stripped_nor_reported(title):
    p = clean_title(title)
    assert p.clean == title and p.sponsor is None and p.lead_unreviewed is None


def test_unknown_lead_is_kept_and_reported_for_review():
    p = clean_title("Bud Light UFC 400")
    assert p.clean == "Bud Light UFC 400" and p.sponsor is None and p.lead_unreviewed == "Bud Light"


@pytest.mark.parametrize("title", ["The Ultimate Fighter Finale: A Champion Will Be Crowned", "DWCS Brazil 1.2",
                                   "Dana White's Tuesday Night Contender Series 12", "PFL 1", "OKTAGON 60", "RIZIN 40",
                                   "Rizin 1 - Rizin Fighting Grand Prix", "Professional Fighters League - 2019 Season",
                                   "PFL 10: 2023 Playoffs - PFL Championship", "Oktagon MMA - Oktagon 5"])
def test_titles_with_brand_first_or_no_brand_have_no_lead(title):
    assert clean_title(title).lead_unreviewed is None and clean_title(title).clean == title


def test_lead_before_a_brand_in_another_org_is_reported():
    assert clean_title("Acme Fight Night - Powered by Oktagon").lead_unreviewed == "Acme Fight Night - Powered by"


def test_none_title():
    assert clean_title(None) is None


@pytest.mark.parametrize("slug,title,expected", [
    ("ufc-dwcs-95-2026-10-06", "Dana White's Contender Series 95", True),
    ("ufc-dwcs-brazil-1-2-2022-01-01", "DWCS Brazil 1.2", True),
    ("ufc-tnc-1-2017-07-11", "Dana White's Tuesday Night Contender Series 1", True),   # title only
    ("ufc-dwcs-9-2025-01-01", "Something else", True),                                # slug only
    ("ufc-333-2026-10-24", "UFC 333: Volkanovski vs Evloev", False),
    ("ufc-fight-night-2026-10-17", "UFC Fight Night: Buckley vs Malott", False),
    (None, None, False),
])
def test_contender_series(slug, title, expected):
    assert is_contender_series(slug, title) is expected
