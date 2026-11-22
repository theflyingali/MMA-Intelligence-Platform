"""Entry point: bronze load of the UFCalendar landing files. Parameters are CLI arguments.

Subset run (build and test):  --schema bronze_dev --max-events 10
Full run (after the backfill): --schema bronze --max-events 0
Nothing is written with --dry-run.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from .paths import ENDPOINTS
from .selection import ListedFile, eligible, plan_run

DEFAULT_ROOT = "/Volumes/mma/raw/landing/ufcalendar"


def _flag(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    if value.strip().lower() in ("1", "true", "yes", "y"):
        return True
    if value.strip().lower() in ("0", "false", "no", "n", ""):
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--catalog", default="mma")
    p.add_argument("--schema", default="bronze", help="target schema; use bronze_dev for subset tests")
    p.add_argument("--landing-root", default=DEFAULT_ROOT)
    p.add_argument("--endpoints", default=",".join(ENDPOINTS), help="comma-separated subset of endpoints")
    p.add_argument("--max-events", type=int, default=0,
                   help="subset: only the N earliest landed events and their odds, rounds and fighters (0 = all)")
    p.add_argument("--max-files", type=int, default=0, help="cap on files per endpoint per run (0 = no cap)")
    p.add_argument("--quiet-minutes", type=int, default=10,
                   help="skip files modified more recently than this (a writer may still be uploading them)")
    p.add_argument("--chunk-size", type=int, default=2000, help="files per MERGE")
    p.add_argument("--dry-run", type=_flag, nargs="?", const=True, default=False,
                   help="report what would load; write nothing (accepts true/false so a job parameter can set it)")
    p.add_argument("--run-id", default=None)
    return p


def parse_endpoints(value: str) -> tuple[str, ...]:
    chosen = tuple(e.strip() for e in value.split(",") if e.strip())
    unknown = [e for e in chosen if e not in ENDPOINTS]
    if unknown or not chosen:
        raise SystemExit(f"unknown endpoints: {unknown or value!r}; choose from {', '.join(ENDPOINTS)}")
    return chosen


def main(argv: list[str], spark: Any = None) -> int:
    args = build_parser().parse_args(argv)
    endpoints = parse_endpoints(args.endpoints)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from pyspark.sql import SparkSession

    from . import spark_io as io

    spark = spark or SparkSession.builder.getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    now = datetime.now(timezone.utc)
    run_id = args.run_id or now.strftime("%Y%m%dT%H%M%SZ")
    root = args.landing_root.rstrip("/")

    # In subset mode the child endpoints are chosen from the event cards, so events are always listed.
    needed = set(endpoints) | ({"event", "event_odds", "fight_rounds", "fighter"} if args.max_events else set())
    listings: dict[str, list[ListedFile]] = {ep: io.list_endpoint(spark, root, ep) for ep in needed}
    loaded = io.read_loaded(spark, args.catalog, args.schema)
    plan = plan_run(
        listings, loaded, root=root, now=now, quiet_minutes=args.quiet_minutes,
        max_events=args.max_events, max_files=args.max_files, endpoints=endpoints,
        card_ids_for=lambda files: io.read_cards(spark, files),
    )

    report: dict[str, Any] = {
        "run_id": run_id, "dry_run": args.dry_run, "target": f"{args.catalog}.{args.schema}",
        "max_events": args.max_events, "max_files": args.max_files,
        "plan": {ep: {"listed": len(listings[ep]),
                      "eligible": len(eligible(listings[ep], root, now, args.quiet_minutes)),
                      "to_load": len(plan[ep])} for ep in endpoints},
    }
    if args.dry_run:
        print(json.dumps(report, indent=1))
        return 0

    io.ensure_tables(spark, args.catalog, args.schema)
    merged: dict[str, Any] = {}
    for ep in endpoints:
        if plan[ep]:
            merged[ep] = io.load_endpoint(spark, args.catalog, args.schema, ep, plan[ep], run_id, args.chunk_size)
    report["merged_rows"] = merged
    report["result"] = io.run_summary(spark, args.catalog, args.schema, run_id)
    report["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
