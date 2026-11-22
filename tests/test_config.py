import pytest

from ingestion.ufcalendar.config import DEFAULT_ORGS, parse_args


def test_org_default():
    assert parse_args([]).orgs == DEFAULT_ORGS


def test_org_repeated_and_comma_separated_keep_order():
    s = parse_args(["--org=ufc,pfl", "--org=OKTAGON", "--org= rizin ,ufc"])
    assert s.orgs == ["ufc", "pfl", "oktagon", "rizin"]


def test_org_empty_list_rejected():
    with pytest.raises(SystemExit):
        parse_args(["--org=,"])
