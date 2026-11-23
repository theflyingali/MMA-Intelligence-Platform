"""End-to-end bronze load against local Spark + Delta on a fake landing tree.

Skipped unless pyspark and delta-spark are installed (they are not in requirements.txt; the load
itself runs on Databricks serverless). Run with e.g. `uv pip install pyspark==3.5.3 delta-spark==3.2.1`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("delta")

from bronze.ufcal_bronze.cli import main  # noqa: E402

from .bronze_fixtures import bout, envelope, event_resp, fighter_resp, list_resp, odds_resp, rounds_resp  # noqa: E402

CATALOG, SCHEMA = "spark_catalog", "bronze_dev"


def put(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def landing(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("landing") / "ufcalendar"
    d1, d2 = "ingest_date=2026-10-30", "ingest_date=2026-11-04"
    # Event 10 (ufc): two real bouts and one cancelled. Event 11 (rizin): one bout.
    put(root, f"event/{d1}/10.json", envelope(event_resp(10, "ufc", [bout(100, 1, 2), bout(101, 3, 4, "cancelled")])))
    put(root, f"event/{d2}/11.json", envelope(event_resp(11, "rizin", [bout(200, 5, 6)]), "2026-11-04T09:00:00Z"))
    put(root, f"event_odds/{d1}/10.json", envelope(odds_resp(10, "ufc")))
    put(root, f"event_odds/{d2}/11.json", envelope(odds_resp(11, "rizin"), "2026-11-04T09:00:00Z"))
    put(root, f"fight_rounds/{d1}/100.json", envelope(rounds_resp(100)))
    put(root, f"fight_rounds/{d2}/200.json", envelope(rounds_resp(200), "2026-11-04T09:00:00Z"))
    for i in (1, 2, 5):
        put(root, f"fighter/{d1}/{i}.json", envelope(fighter_resp(i)))
    put(root, f"fighter/{d2}/6.json", envelope(fighter_resp(6), "2026-11-04T09:00:00Z"))
    put(root, f"events_list/{d1}/ufc_completed_081048Z_p1.json", envelope(list_resp((10, "ufc"), (11, "rizin"))))
    # Bad files: truncated mid-write, an error envelope, and an empty file.
    put(root, f"fighter/{d2}/7.json", envelope(fighter_resp(7))[:40])
    put(root, f"fighter/{d2}/8.json", envelope({"error": "x"}, status=404))
    put(root, f"fighter/{d2}/9.json", "")
    # Never data: the manifest, the lock and run logs sit beside the endpoint folders.
    put(root, "_manifest.json", json.dumps({"version": 1, "event": {"10": {}}}))
    put(root, "_lock.json", json.dumps({"run_id": "x", "acquired_at": "2026-11-22T13:57:22Z"}))
    put(root, "_runs/20261030T081044Z.json", json.dumps({"run_id": "x"}))
    return root


def run(spark, root: Path, *extra: str) -> None:
    rc = main(["--catalog", CATALOG, "--schema", SCHEMA, "--landing-root", str(root),
               "--quiet-minutes", "0", *extra], spark=spark)
    assert rc == 0


def counts(spark) -> dict[str, tuple[int, int]]:
    """(rows, distinct keys) per bronze table: equal means no duplicates."""
    out = {}
    for ep in ("events_list", "event", "event_odds", "fight_rounds", "fighter"):
        df = spark.table(f"{CATALOG}.{SCHEMA}.ufcal_{ep}")
        out[ep] = (df.count(), df.select("key").distinct().count())
    return out


def test_subset_then_rerun_then_full_then_refetch(spark, landing):
    # 1. Subset of one event: that event, its odds, its played bout, its non-cancelled fighters.
    run(spark, landing, "--max-events", "1")
    assert counts(spark) == {"events_list": (2, 2), "event": (1, 1), "event_odds": (1, 1),
                             "fight_rounds": (1, 1), "fighter": (2, 2)}

    # 2. Rerun: nothing new, nothing changes.
    run(spark, landing, "--max-events", "1")
    assert counts(spark)["event"] == (1, 1)
    again = spark.table(f"{CATALOG}.{SCHEMA}.ufcal_ingest_log").where("run_id IS NOT NULL").count()

    # 3. Full run: the rest arrives, no duplicates, bad files rejected with reasons.
    run(spark, landing)
    assert counts(spark) == {"events_list": (2, 2), "event": (2, 2), "event_odds": (2, 2),
                             "fight_rounds": (2, 2), "fighter": (4, 4)}
    log = spark.table(f"{CATALOG}.{SCHEMA}.ufcal_ingest_log")
    rejected = {r["reject_reason"] for r in log.where("status = 'rejected'").collect()}
    assert rejected == {"invalid_json", "non_200"}
    # An empty file is treated as still being uploaded: skipped and retried, not rejected or logged.
    assert log.where("source_file LIKE '%/fighter/%/9.json'").count() == 0
    assert log.where("source_file LIKE '%_manifest%' OR source_file LIKE '%_lock%' "
                     "OR source_file LIKE '%_runs%'").count() == 0
    assert log.count() > again

    # 4. Org comes from the payload, for any org.
    orgs = {r["key"]: r["org"] for r in spark.table(f"{CATALOG}.{SCHEMA}.ufcal_event").collect()}
    assert orgs == {10: "ufc", 11: "rizin"}

    # 5. Re-fetch: a newer fetch of event 10 wins; an older fetch landed later does not.
    newer = event_resp(10, "ufc")
    newer["data"]["title"] = "UPDATED"
    put(landing, "event/ingest_date=2026-11-22/10.json", envelope(newer, "2026-11-22T12:00:00Z"))
    stale = event_resp(10, "ufc")
    stale["data"]["title"] = "STALE"
    put(landing, "event/ingest_date=2026-11-23/10.json", envelope(stale, "2026-11-01T00:00:00Z"))
    run(spark, landing)
    ev = spark.table(f"{CATALOG}.{SCHEMA}.ufcal_event").where("key = 10").collect()
    assert len(ev) == 1 and json.loads(ev[0]["payload"])["data"]["title"] == "UPDATED"
    assert counts(spark)["event"] == (2, 2)

    # 6. Rerunning once more is a no-op.
    before = {r["key"]: r["ingested_at"] for r in spark.table(f"{CATALOG}.{SCHEMA}.ufcal_event").collect()}
    run(spark, landing)
    after = {r["key"]: r["ingested_at"] for r in spark.table(f"{CATALOG}.{SCHEMA}.ufcal_event").collect()}
    assert before == after and counts(spark)["event"] == (2, 2)


def test_dry_run_writes_nothing(spark, landing, capsys):
    rc = main(["--catalog", CATALOG, "--schema", "bronze_never_created", "--landing-root", str(landing),
               "--quiet-minutes", "0", "--dry-run"], spark=spark)
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["plan"]["event"]["to_load"] == 4  # event 10 in three versions, plus event 11
    assert not spark.catalog.databaseExists("bronze_never_created")
