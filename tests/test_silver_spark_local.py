"""End-to-end: fake landing files -> real bronze CLI -> real silver CLI, on local Spark + Delta.

Skipped unless pyspark and delta-spark are installed (see tests/test_bronze_spark_local.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("delta")

from bronze.ufcal_bronze.cli import main as bronze_main  # noqa: E402
from silver.ufcal_silver.build import TABLES  # noqa: E402
from silver.ufcal_silver.cli import main as silver_main  # noqa: E402

from .bronze_fixtures import envelope  # noqa: E402
from .silver_fixtures import bout, event, fighter, odds, rounds  # noqa: E402

CAT, BRZ, SLV = "spark_catalog", "s_bronze", "s_silver"
D1 = "ingest_date=2026-10-30"


def put(root: Path, rel: str, response: dict, fetched_at: str = "2026-10-30T08:00:00Z") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(envelope(response, fetched_at), encoding="utf-8")


@pytest.fixture(scope="module")
def landing(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("landing_silver") / "ufcalendar"
    put(root, f"event/{D1}/10.json", event(10, "ufc", "ufc-331-2026-01-01", "Crypto.com UFC 331", [
        bout(100, 1, 2, winner=1), bout(101, 3, 4, status="cancelled"),
        bout(102, 5, 6, winner=None, method_norm="draw", method="Draw (Majority)", rnd=3)]))
    put(root, f"event/{D1}/11.json", event(11, "ufc", "ufc-dwcs-95-2026-10-06", "Dana White's Contender Series 95",
                                          [bout(200, 7, 8, winner=8)]))
    put(root, f"event/{D1}/12.json", event(12, "rizin", "rizin-50-2026-10-10", "RIZIN 50", [bout(300, 9, 10, winner=9)]))
    put(root, f"event_odds/{D1}/10.json", odds(10, [(100, 1, 2), (102, 5, 6)]))
    put(root, f"event_odds/{D1}/11.json", odds(11, [(200, 7, 8), (999, 7, 8)]))  # 999 is not on any card
    for fid, a, b in ((100, 1, 2), (200, 7, 8), (300, 9, 10)):
        put(root, f"fight_rounds/{D1}/{fid}.json", rounds(fid, a, b))
    for i in (1, 2, 5, 6, 7, 8, 9, 10):
        put(root, f"fighter/{D1}/{i}.json", fighter(i, **({"dob": None, "height_inches": None} if i == 2 else {})))
    return root


def bronze(spark, root: Path) -> None:
    assert bronze_main(["--catalog", CAT, "--schema", BRZ, "--landing-root", str(root), "--quiet-minutes", "0",
                        "--endpoints", "event,event_odds,fight_rounds,fighter"], spark=spark) == 0


def silver(spark, capsys, *extra: str) -> dict:
    capsys.readouterr()
    assert silver_main(["--catalog", CAT, "--source-schema", BRZ, "--target-schema", SLV, *extra], spark=spark) == 0
    return json.loads(capsys.readouterr().out)


def rows(spark, table: str, where: str = "1=1", order: str = "1") -> list[dict]:
    return [r.asDict() for r in spark.sql(f"SELECT * FROM {CAT}.{SLV}.{table} WHERE {where} ORDER BY {order}").collect()]


def test_bronze_to_silver_incremental_refetch_and_full_refresh(spark, landing, capsys):
    bronze(spark, landing)
    first = silver(spark, capsys)
    assert first["changed_bronze_rows"] == {"events": 3, "fights": 3, "odds": 2, "fighters": 8}
    counts = first["data_quality"]["row_counts"]
    assert counts == {"event": 3, "bout": 5, "fighter_bout": 8, "round_stats": 12, "odds": 4, "fighter": 8,
                      "fighter_record": 24}

    # Events: sponsor stripped but kept, contender flag from the slug, official only for non-DWCS UFC.
    ev = {r["event_id"]: r for r in rows(spark, "event")}
    assert (ev[10]["title_raw"], ev[10]["title_clean"], ev[10]["title_sponsor"]) == (
        "Crypto.com UFC 331", "UFC 331", "Crypto.com")
    assert [ev[i]["is_contender_series"] for i in (10, 11, 12)] == [False, True, False]
    assert [ev[i]["is_official_ufc"] for i in (10, 11, 12)] == [True, False, False]
    assert ev[10]["venue_city"] == "Edmonton" and ev[10]["card_size"] == 3 and ev[10]["starts_at"] is not None

    # Bouts: outcome, winner and loser, draw has no winner, cancelled has no result.
    b = {r["bout_id"]: r for r in rows(spark, "bout")}
    assert {i: b[i]["outcome"] for i in b} == {100: "a_win", 101: "cancelled", 102: "draw", 200: "b_win", 300: "a_win"}
    assert (b[100]["winner_fighter_id"], b[100]["loser_fighter_id"]) == (1, 2)
    assert (b[200]["winner_fighter_id"], b[200]["loser_fighter_id"]) == (8, 7)
    assert b[102]["winner_fighter_id"] is None and b[102]["loser_fighter_id"] is None
    assert b[101]["method"] is None and b[101]["end_round"] is None
    assert b[200]["is_contender_series"] is True and b[100]["event_id"] == 10

    # Fighter-bout: two rows per fought bout, none for the cancelled one.
    fb = {(r["bout_id"], r["fighter_id"]): r["result"] for r in rows(spark, "fighter_bout")}
    assert fb[(100, 1)] == "win" and fb[(100, 2)] == "loss" and fb[(102, 5)] == "draw" == fb[(102, 6)]
    assert not any(k[0] == 101 for k in fb)

    # Fighters: typed, converted, nulls kept; long records table.
    f = {r["fighter_id"]: r for r in rows(spark, "fighter")}
    assert f[1]["height_cm"] == 177.8 and str(f[1]["dob"]) == "1990-05-17" and f[1]["ufc_wins"] == 2
    assert f[1]["slpm"] == 3.13 and f[1]["power_rating"] == 1691
    assert f[2]["dob"] is None and f[2]["height_cm"] is None
    rec = {r["record_type"]: r["record"] for r in rows(spark, "fighter_record", "fighter_id = 1")}
    assert rec == {"pro_mma": "6-1-0", "ufc": "2-1", "amateur_mma": "3-0"}

    # Odds and rounds.
    o = {r["fight_id"]: r for r in rows(spark, "odds")}
    assert set(o) == {100, 102, 200, 999}
    assert o[100]["consensus_a_american"] == 106 and o[100]["consensus_b_implied_probability"] == 0.5595
    assert o[100]["opening_a_american"] == 131 and o[100]["movement_direction"] == "a"
    assert len(rows(spark, "round_stats", "fight_id = 100")) == 4

    # Data quality reports what is wrong instead of hiding it.
    checks = first["data_quality"]["checks"]
    assert checks["odds_fights_without_bout"] == 1  # fight 999
    assert checks["played_bouts_without_round_stats"] == 1  # the draw, 102, has no rounds file
    assert checks["bouts_with_unknown_outcome"] == 0 and checks["events_without_bouts"] == 0
    assert checks["bout_fighters_without_fighter_row"] == 0
    assert first["data_quality"]["titles"]["sponsor_prefixes_stripped"] == [["Crypto.com", 1]]

    # Rerun: nothing changed, nothing rewritten.
    second = silver(spark, capsys)
    assert second["changed_bronze_rows"] == {"events": 0, "fights": 0, "odds": 0, "fighters": 0}
    assert second["data_quality"]["row_counts"] == counts

    # Re-fetch of event 10: bout 101 removed from the card, bout 100 result changed, new title.
    put(landing, "event/ingest_date=2026-11-22/10.json", event(10, "ufc", "ufc-331-2026-01-01", "Crypto.com UFC 331: Updated", [
        bout(100, 1, 2, winner=2), bout(102, 5, 6, winner=None, method_norm="draw", method="Draw (Majority)", rnd=3)]),
        "2026-11-22T12:00:00Z")
    bronze(spark, landing)
    third = silver(spark, capsys)
    assert third["changed_bronze_rows"] == {"events": 1, "fights": 0, "odds": 0, "fighters": 0}
    b = {r["bout_id"]: r for r in rows(spark, "bout")}
    assert 101 not in b and b[100]["outcome"] == "b_win" and b[100]["loser_fighter_id"] == 1
    assert rows(spark, "event", "event_id = 10")[0]["title_clean"] == "UFC 331: Updated"
    assert {r["result"] for r in rows(spark, "fighter_bout", "bout_id = 100")} == {"win", "loss"}
    assert [r["result"] for r in rows(spark, "fighter_bout", "bout_id = 100 AND fighter_id = 2")] == ["win"]
    assert third["data_quality"]["row_counts"]["bout"] == 4

    # Full refresh rebuilds the same tables from bronze alone.
    def snapshot() -> dict[str, list[dict]]:
        return {t: rows(spark, t, order=", ".join(TABLES[t][0])) for t in TABLES}

    before = snapshot()
    full = silver(spark, capsys, "--full-refresh")
    assert full["changed_bronze_rows"] == {"events": 3, "fights": 3, "odds": 2, "fighters": 8}
    after = snapshot()
    for t in before:
        assert [{k: v for k, v in r.items() if k != "_bronze_ingested_at"} for r in after[t]] == \
               [{k: v for k, v in r.items() if k != "_bronze_ingested_at"} for r in before[t]], t


def test_dry_run_changes_nothing(spark, landing, capsys):
    out = silver(spark, capsys, "--target-schema", "s_silver_never", "--dry-run")
    assert out["changed_bronze_rows"]["events"] == 3 and "merged" not in out
    assert not spark.catalog.databaseExists("s_silver_never")
