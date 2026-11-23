"""Entry point: build silver from bronze. Parameters are CLI arguments.

Test run (default job parameters):  --source-schema bronze_dev --target-schema silver_dev
Full run (after bronze is complete): --source-schema bronze --target-schema silver
--full-refresh rebuilds silver from bronze; --dry-run counts what would change and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


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
    p.add_argument("--source-schema", default="bronze")
    p.add_argument("--target-schema", default="silver")
    for name, help_ in (("--full-refresh", "delete and rebuild every silver table from bronze"),
                        ("--dry-run", "count changed bronze rows; write nothing")):
        p.add_argument(name, type=_flag, nargs="?", const=True, default=False, help=help_)
    p.add_argument("--run-id", default=None)
    return p


def main(argv: list[str], spark: Any = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from pyspark.sql import SparkSession

    from . import build

    spark = spark or SparkSession.builder.getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "run_id": args.run_id or started.strftime("%Y%m%dT%H%M%SZ"),
        "source": f"{args.catalog}.{args.source_schema}", "target": f"{args.catalog}.{args.target_schema}",
        "full_refresh": args.full_refresh, "dry_run": args.dry_run,
    }
    report.update(build.run_build(spark, args.catalog, args.source_schema, args.target_schema,
                                  args.full_refresh, args.dry_run))
    if not args.dry_run:
        report["data_quality"] = build.dq_report(spark, args.catalog, args.target_schema)
    report["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
