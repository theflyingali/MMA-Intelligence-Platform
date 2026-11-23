from bronze.ufcal_bronze.paths import name_id_from_filename, normalise, parse_landing_path

ROOT = "/Volumes/mma/raw/landing/ufcalendar"


def test_data_file_parses():
    lf = parse_landing_path(f"{ROOT}/fight_rounds/ingest_date=2026-10-30/83288.json", ROOT)
    assert (lf.endpoint, lf.ingest_date, lf.name_id) == ("fight_rounds", "2026-10-30", 83288)


def test_dbfs_prefix_is_normalised():
    assert normalise("dbfs:/Volumes/a/b.json") == "/Volumes/a/b.json"
    assert parse_landing_path(f"dbfs:{ROOT}/event/ingest_date=2026-11-04/10.json", ROOT) is not None


def test_same_day_suffix_keeps_the_id():
    assert name_id_from_filename("x/123__081502Z.json") == 123
    lf = parse_landing_path(f"{ROOT}/event/ingest_date=2026-11-04/123__081502Z.json", ROOT)
    assert lf.name_id == 123


def test_events_list_pages_have_no_id():
    lf = parse_landing_path(f"{ROOT}/events_list/ingest_date=2026-10-30/ufc_completed_081048Z_p1.json", ROOT)
    assert lf is not None and lf.name_id is None


def test_manifest_lock_runs_and_strays_are_never_data():
    for rel in ("_manifest.json", "_lock.json", "_runs/20261030T081044Z.json",
                "_runs/20261030T081044Z.log", "event/_manifest.json",
                "event/ingest_date=2026-10-30/10.json.tmp", "event/ingest_date=2026-10-30/_x.json",
                "event/2026-10-30/10.json", "other/ingest_date=2026-10-30/10.json",
                "event/ingest_date=2026-10-30/sub/10.json"):
        assert parse_landing_path(f"{ROOT}/{rel}", ROOT) is None, rel


def test_path_outside_root_is_ignored():
    assert parse_landing_path("/Volumes/other/event/ingest_date=2026-10-30/1.json", ROOT) is None
