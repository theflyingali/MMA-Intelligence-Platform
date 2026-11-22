"""PySpark layer: list landing files, parse them with the pure parser, MERGE into Delta.

Kept thin on purpose. Parsing, selection and ordering rules live in the pure modules and are
unit-tested locally; this module only moves data. It needs Spark and Delta, so it is exercised on
Databricks (serverless) only.
"""

from __future__ import annotations

import logging
from typing import Any

from . import envelope as envelope_mod
from . import paths as paths_mod
from .envelope import card_ids, parse_envelope
from .paths import ENDPOINTS, name_id_from_filename, normalise
from .selection import ListedFile, from_epoch

log = logging.getLogger("ufcal_bronze")

LOG_TABLE = "ufcal_ingest_log"

_BRONZE_COLUMNS = """
    key BIGINT COMMENT 'natural key: event id, fight id or fighter id',
    fetched_at TIMESTAMP COMMENT 'when the API response was fetched (from the landing envelope)',
    http_status INT,
    request_url STRING,
    org STRING COMMENT 'from the payload where present (events and odds only)',
    slug STRING,
    starts_at STRING,
    payload STRING COMMENT 'the API response as raw JSON text',
    payload_fingerprint STRING COMMENT 'hash of the payload key paths, to spot schema drift',
    source_file STRING,
    source_modified_at TIMESTAMP,
    ingest_date DATE,
    ingested_at TIMESTAMP
"""

_LOG_COLUMNS = """
    endpoint STRING,
    source_file STRING,
    source_modified_at TIMESTAMP,
    status STRING COMMENT 'loaded or rejected',
    reject_reason STRING,
    row_count INT,
    run_id STRING,
    processed_at TIMESTAMP
"""

# Rule order must match dedupe.recency: fetched_at, then file modification time, then path.
_REPLACE_IF = ("struct(s.fetched_at, s.source_modified_at, s.source_file) "
               ">= struct(t.fetched_at, t.source_modified_at, t.source_file)")


def table_name(catalog: str, schema: str, endpoint: str) -> str:
    return f"{catalog}.{schema}.ufcal_{endpoint}"


def log_table_name(catalog: str, schema: str) -> str:
    return f"{catalog}.{schema}.{LOG_TABLE}"


def ensure_tables(spark: Any, catalog: str, schema: str) -> None:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema} COMMENT 'Bronze: raw UFCalendar payloads'")
    for ep in ENDPOINTS:
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {table_name(catalog, schema, ep)} ({_BRONZE_COLUMNS}) USING DELTA "
            f"COMMENT 'Bronze UFCalendar {ep}: latest fetch per key'"
        )
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {log_table_name(catalog, schema)} ({_LOG_COLUMNS}) USING DELTA "
        "COMMENT 'Landing files processed by the bronze load'"
    )


# ---- listing and log ---------------------------------------------------------------------------

def list_endpoint(spark: Any, root: str, endpoint: str) -> list[ListedFile]:
    """Data files under one endpoint folder, with size and modification time (content is not read)."""
    from pyspark.sql import functions as F

    df = (
        spark.read.format("binaryFile")
        .option("pathGlobFilter", "*.json")
        .option("recursiveFileLookup", "true")
        .load(f"{root.rstrip('/')}/{endpoint}")
        .select("path", "length", F.col("modificationTime").cast("double").alias("mtime"))
    )
    # mtime as epoch seconds: collecting timestamps would depend on the Python process time zone.
    return [ListedFile(normalise(r["path"]), int(r["length"]), from_epoch(r["mtime"])) for r in df.collect()]


def read_loaded(spark: Any, catalog: str, schema: str) -> dict[str, set[tuple[str, int]]]:
    """Files already loaded, per endpoint, as (path, mtime epoch ms) keys. Empty if no log yet."""
    from pyspark.sql import functions as F

    name = log_table_name(catalog, schema)
    if not spark.catalog.tableExists(name):
        return {}
    out: dict[str, set[tuple[str, int]]] = {}
    rows = (spark.table(name).where("status = 'loaded'")
            .select("endpoint", "source_file", F.col("source_modified_at").cast("double").alias("mtime")))
    for r in rows.collect():
        out.setdefault(r["endpoint"], set()).add((normalise(r["source_file"]), round(r["mtime"] * 1000)))
    return out


def read_cards(spark: Any, files: list[ListedFile]) -> tuple[set[int], set[int]]:
    """Fight and fighter ids on the cards in the given event files (subset mode; N is small)."""
    fights: set[int] = set()
    fighters: set[int] = set()
    if not files:
        return fights, fighters
    for r in spark.read.text([f.path for f in files], wholetext=True).collect():
        for row in parse_envelope("event", r["value"]).rows:
            f, p = card_ids(row.payload)
            fights |= f
            fighters |= p
    return fights, fighters


# ---- parse and load ----------------------------------------------------------------------------

def _parse_udf(endpoint: str) -> Any:
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    row_type = T.StructType([
        T.StructField("key", T.LongType()), T.StructField("fetched_at", T.StringType()),
        T.StructField("http_status", T.IntegerType()), T.StructField("request_url", T.StringType()),
        T.StructField("payload", T.StringType()), T.StructField("org", T.StringType()),
        T.StructField("slug", T.StringType()), T.StructField("starts_at", T.StringType()),
        T.StructField("fingerprint", T.StringType()),
    ])
    result_type = T.StructType([T.StructField("reject", T.StringType()),
                                T.StructField("rows", T.ArrayType(row_type))])

    # Ship the pure modules inside the UDF instead of importing them on the workers.
    try:
        import cloudpickle
        for module in (envelope_mod, paths_mod):
            cloudpickle.register_pickle_by_value(module)
    except Exception:  # pragma: no cover - worker import then has to work
        log.warning("could not register modules for pickling by value")

    def parse(text: str | None, path: str) -> tuple[str | None, list[tuple[Any, ...]]]:
        p = parse_envelope(endpoint, text, name_id_from_filename(path))
        return p.reject, [r.as_tuple() for r in p.rows]

    return F.udf(parse, result_type)


def parsed_frame(spark: Any, endpoint: str, paths: list[str]) -> Any:
    """One row per file with its parse result (`p.reject`, `p.rows`) and source metadata."""
    from pyspark.sql import functions as F

    raw = spark.read.text(paths, wholetext=True).select("value", "_metadata")
    return raw.select(
        F.regexp_replace(F.col("_metadata.file_path"), "^(dbfs|file):", "").alias("source_file"),
        F.col("_metadata.file_modification_time").alias("source_modified_at"),
        _parse_udf(endpoint)(F.col("value"), F.col("_metadata.file_path")).alias("p"),
    )


def latest_rows(parsed: Any) -> Any:
    """Bronze-shaped rows, one per key: the latest fetch in this batch (mirrors dedupe.latest_wins)."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    rows = (
        parsed.where(F.col("p.reject").isNull())
        .select("source_file", "source_modified_at", F.explode("p.rows").alias("r"))
        .select(
            F.col("r.key").alias("key"),
            F.to_timestamp("r.fetched_at").alias("fetched_at"),
            F.col("r.http_status").alias("http_status"),
            F.col("r.request_url").alias("request_url"),
            F.col("r.org").alias("org"),
            F.col("r.slug").alias("slug"),
            F.col("r.starts_at").alias("starts_at"),
            F.col("r.payload").alias("payload"),
            F.col("r.fingerprint").alias("payload_fingerprint"),
            "source_file", "source_modified_at",
            F.to_date(F.regexp_extract("source_file", r"ingest_date=(\d{4}-\d{2}-\d{2})", 1)).alias("ingest_date"),
            F.current_timestamp().alias("ingested_at"),
        )
    )
    w = Window.partitionBy("key").orderBy(
        F.col("fetched_at").desc(), F.col("source_modified_at").desc(), F.col("source_file").desc())
    return rows.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


def _merge(spark: Any, sql: str) -> dict[str, int]:
    """Run a MERGE INTO and return its affected-row counts (zeros if the engine does not report them)."""
    row = spark.sql(sql).collect()
    r = row[0].asDict() if row else {}
    return {"inserted": int(r.get("num_inserted_rows") or 0), "updated": int(r.get("num_updated_rows") or 0)}


def merge_bronze(spark: Any, target: str, source: Any) -> dict[str, int]:
    """Upsert one row per key; an incoming row replaces the stored one unless it is strictly older."""
    source.createOrReplaceTempView("_bronze_src")
    return _merge(spark, f"""
        MERGE INTO {target} t USING _bronze_src s ON t.key = s.key
        WHEN MATCHED AND {_REPLACE_IF} THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *""")


def merge_log(spark: Any, target: str, endpoint: str, parsed: Any, run_id: str) -> None:
    from pyspark.sql import functions as F

    src = parsed.select(
        F.lit(endpoint).alias("endpoint"), "source_file", "source_modified_at",
        F.when(F.col("p.reject").isNull(), "loaded").otherwise("rejected").alias("status"),
        F.col("p.reject").alias("reject_reason"),
        F.size("p.rows").alias("row_count"),
        F.lit(run_id).alias("run_id"),
        F.current_timestamp().alias("processed_at"),
    )
    src.createOrReplaceTempView("_log_src")
    _merge(spark, f"""
        MERGE INTO {target} t USING _log_src s
        ON t.source_file = s.source_file AND t.source_modified_at = s.source_modified_at
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *""")


def load_endpoint(spark: Any, catalog: str, schema: str, endpoint: str, files: list[ListedFile],
                  run_id: str, chunk_size: int) -> dict[str, Any]:
    """Load the selected files in chunks: MERGE into bronze first, then record them in the log.

    A crash between the two steps only means the chunk is read again next run; the MERGE rule
    makes that harmless. The parse runs twice per chunk (once per MERGE) because serverless
    compute does not support DataFrame caching; files are small, so this is cheap.
    """
    bronze, log_t = table_name(catalog, schema, endpoint), log_table_name(catalog, schema)
    merged = {"inserted": 0, "updated": 0}
    for i in range(0, len(files), chunk_size):
        chunk = [f.path for f in files[i:i + chunk_size]]
        parsed = parsed_frame(spark, endpoint, chunk)
        m = merge_bronze(spark, bronze, latest_rows(parsed))
        merge_log(spark, log_t, endpoint, parsed, run_id)
        for k in merged:
            merged[k] += m.get(k, 0)
        log.info("%s: chunk %d-%d done", endpoint, i, i + len(chunk))
    return merged


def run_summary(spark: Any, catalog: str, schema: str, run_id: str) -> dict[str, Any]:
    """Per endpoint: files loaded and rejected (by reason) in this run."""
    from pyspark.sql import functions as F

    rows = (spark.table(log_table_name(catalog, schema)).where(F.col("run_id") == run_id)
            .groupBy("endpoint", "status", "reject_reason")
            .agg(F.count("*").alias("files"), F.sum("row_count").alias("rows")).collect())
    out: dict[str, Any] = {}
    for r in rows:
        ep = out.setdefault(r["endpoint"], {"loaded_files": 0, "loaded_rows": 0, "rejected": {}})
        if r["status"] == "loaded":
            ep["loaded_files"] += r["files"]
            ep["loaded_rows"] += int(r["rows"] or 0)
        else:
            ep["rejected"][r["reject_reason"]] = r["files"]
    return out
