"""Bronze to silver with PySpark: parse payloads, clean, MERGE. Needs Spark and Delta.

Incremental without a watermark: a bronze row is processed when its key is missing from silver or its
`ingested_at` is newer than the `_bronze_ingested_at` stored on the silver rows built from it. Silver
tables are written child first and the parent that defines "changed" last, so a crash only means the
same rows are picked up again next run (every MERGE is idempotent). A re-fetched event replaces its
bouts, a re-fetched fight its rounds, and so on, so removed rows do not linger.
"""

from __future__ import annotations

import logging
from typing import Any

from . import schemas
from .titles import CONTENDER_PATTERN, KNOWN_NON_SPONSOR_LEADS, LEAD_PATTERN, SPONSOR_PATTERN

log = logging.getLogger("ufcal_silver")

# table -> (merge keys, scope column for reloading a parent's rows, scope view of changed parents)
TABLES: dict[str, tuple[tuple[str, ...], str | None, str | None]] = {
    "event": (("event_id",), None, None),
    "bout": (("bout_id",), "event_id", "_chg_events"),
    "fighter_bout": (("bout_id", "fighter_id"), "event_id", "_chg_events"),
    "round_stats": (("fight_id", "round_number", "fighter_id"), "fight_id", "_chg_fights"),
    "odds": (("fight_id",), "event_id", "_chg_odds"),
    "fighter": (("fighter_id",), None, None),
    "fighter_record": (("fighter_id", "record_type"), "fighter_id", "_chg_fighters"),
}
# Bronze table behind each "changed" set, and the silver table + column that records what was built.
SOURCES = {
    "events": ("ufcal_event", "event", "event_id"),
    "fights": ("ufcal_fight_rounds", "round_stats", "fight_id"),
    "odds": ("ufcal_event_odds", "odds", "event_id"),
    "fighters": ("ufcal_fighter", "fighter", "fighter_id"),
}


def tname(catalog: str, schema: str, table: str) -> str:
    return f"{catalog}.{schema}.{table}"


# ---- changed rows ----------------------------------------------------------------------------

def changed_rows(spark: Any, catalog: str, src: str, tgt: str, which: str, schema_ddl: str) -> Any:
    """Bronze rows of one kind that silver has not built yet (or built from an older fetch), parsed."""
    from pyspark.sql import functions as F

    bronze_t, silver_t, silver_key = SOURCES[which]
    b = spark.table(tname(catalog, src, bronze_t))
    target = tname(catalog, tgt, silver_t)
    if spark.catalog.tableExists(target):
        built = (spark.table(target).groupBy(silver_key)
                 .agg(F.max("_bronze_ingested_at").alias("_built_at")))
        b = (b.join(built, b["key"] == built[silver_key], "left")
             .where(F.col("_built_at").isNull() | (F.col("ingested_at") > F.col("_built_at"))))
    return b.select(
        F.col("key"), F.col("fetched_at"), F.col("ingested_at"),
        F.from_json(F.col("payload"), schema_ddl).alias("p"),
    )


# ---- transforms (changed bronze rows -> silver-shaped rows) ------------------------------------

def event_rows(ev: Any) -> Any:
    from pyspark.sql import functions as F

    d = F.col("p.data")
    raw = d["title"]
    sponsor = F.nullif(F.regexp_extract(raw, SPONSOR_PATTERN, 1), F.lit(""))
    lead = F.regexp_extract(raw, LEAD_PATTERN, 1)
    unreviewed = F.when(
        sponsor.isNull() & (lead != "") & ~F.lower(F.trim(lead)).isin(*KNOWN_NON_SPONSOR_LEADS),
        F.trim(lead))
    contender = F.concat_ws(" ", d["slug"], raw).rlike(CONTENDER_PATTERN)
    return ev.where(d.isNotNull()).select(
        F.col("key").alias("event_id"), d["org"].alias("org"), d["slug"].alias("slug"),
        raw.alias("title_raw"),
        F.trim(F.regexp_replace(raw, SPONSOR_PATTERN, "")).alias("title_clean"),
        sponsor.alias("title_sponsor"), unreviewed.alias("title_lead_unreviewed"),
        d["short_title"].alias("short_title"), d["numbering"].alias("numbering"),
        contender.alias("is_contender_series"),
        ((d["org"] == "ufc") & ~contender).alias("is_official_ufc"),
        d["sport"].alias("sport"), F.to_timestamp(d["starts_at"]).alias("starts_at"),
        F.to_timestamp(d["main_card_at"]).alias("main_card_at"),
        F.to_timestamp(d["prelims_at"]).alias("prelims_at"),
        F.to_timestamp(d["early_prelims_at"]).alias("early_prelims_at"),
        d["tz"].alias("tz"), d["status"].alias("status"),
        d["is_ppv"].alias("is_ppv"), d["is_title_card"].alias("is_title_card"),
        d["venue"]["id"].alias("venue_id"), d["venue"]["name"].alias("venue_name"),
        d["venue"]["city"].alias("venue_city"), d["venue"]["region"].alias("venue_region"),
        d["venue"]["country"].alias("venue_country"), d["venue"]["country_code"].alias("venue_country_code"),
        F.size(d["card"]).alias("card_size"),
        F.col("fetched_at"), F.col("ingested_at").alias("_bronze_ingested_at"),
    )


def bout_rows(ev: Any) -> Any:
    from pyspark.sql import functions as F

    d = F.col("p.data")
    contender = F.concat_ws(" ", d["slug"], d["title"]).rlike(CONTENDER_PATTERN)
    b = F.col("bout")
    r = b["result"]
    a_id, b_id, win = b["fighter_a"]["id"], b["fighter_b"]["id"], r["winner_fighter_id"]
    mn = r["method_normalized"]
    # Statuses seen so far: completed, cancelled. Anything unexpected becomes 'unknown' and is counted
    # in the data-quality report rather than guessed.
    outcome = (
        F.when(b["status"] == "cancelled", "cancelled")
        .when((b["status"] == "no_contest") | (mn == "no_contest"), "no_contest")
        .when((b["status"] == "completed") & (win == a_id), "a_win")
        .when((b["status"] == "completed") & (win == b_id), "b_win")
        .when((b["status"] == "completed") & win.isNull() & mn.startswith("draw"), "draw")
        .otherwise("unknown")
    )
    exploded = ev.where(d.isNotNull()).select(
        F.col("key").alias("event_id"), d["org"].alias("org"),
        F.to_timestamp(d["starts_at"]).alias("event_starts_at"), contender.alias("is_contender_series"),
        F.col("fetched_at"), F.col("ingested_at").alias("_bronze_ingested_at"),
        F.explode(d["card"]).alias("bout"),
    )
    out = exploded.select(
        b["id"].alias("bout_id"), "event_id", "org", "event_starts_at",
        b["ordering"].alias("ordering"), b["card_section"].alias("card_section"),
        b["sport"].alias("sport"), b["weight_class"].alias("weight_class"),
        b["division_slug"].alias("division_slug"), b["is_title"].alias("is_title"),
        b["is_main"].alias("is_main"), b["scheduled_rounds"].alias("scheduled_rounds"),
        b["status"].alias("status"), outcome.alias("outcome"),
        a_id.alias("fighter_a_id"), b["fighter_a"]["name"].alias("fighter_a_name"),
        b_id.alias("fighter_b_id"), b["fighter_b"]["name"].alias("fighter_b_name"),
        win.alias("winner_fighter_id"),
        F.when(outcome == "a_win", b_id).when(outcome == "b_win", a_id).alias("loser_fighter_id"),
        r["method"].alias("method"), mn.alias("method_normalized"), r["finish_detail"].alias("finish_detail"),
        r["round"].alias("end_round"), r["time"].alias("end_time"), r["time_seconds"].alias("end_time_seconds"),
        b["referee"].alias("referee"), b["bonus"].alias("bonus"), "is_contender_series",
        "fetched_at", "_bronze_ingested_at",
    )
    return dedupe(out, ("bout_id",))


def fighter_bout_rows(bouts: Any) -> Any:
    """Two rows per bout that was fought (win, loss, draw or no contest), one per fighter."""
    from pyspark.sql import functions as F

    played = bouts.where(F.col("outcome").isin("a_win", "b_win", "draw", "no_contest"))

    def side(me: str, opp: str, corner: str, win: str, loss: str) -> Any:
        return played.select(
            "bout_id", F.col(f"{me}_id").alias("fighter_id"), F.col(f"{opp}_id").alias("opponent_id"),
            F.lit(corner).alias("corner"),
            F.when(F.col("outcome") == win, "win").when(F.col("outcome") == loss, "loss")
            .when(F.col("outcome") == "draw", "draw").otherwise("no_contest").alias("result"),
            "event_id", "org", "event_starts_at", "weight_class", "is_title", "is_main",
            "scheduled_rounds", "method_normalized", "end_round", "end_time_seconds",
            "is_contender_series", "_bronze_ingested_at",
        )

    return side("fighter_a", "fighter_b", "a", "a_win", "b_win").unionByName(
        side("fighter_b", "fighter_a", "b", "b_win", "a_win"))


def round_rows(rd: Any) -> Any:
    from pyspark.sql import functions as F

    exploded = rd.where(F.col("p.data").isNotNull()).select(
        F.col("key").alias("fight_id"), F.col("fetched_at"),
        F.col("ingested_at").alias("_bronze_ingested_at"), F.explode("p.data").alias("r"))
    cols = [F.col(f"r.{c}").alias(c) for c in schemas.ROUND_COLUMNS]
    out = exploded.select("fight_id", *cols, "fetched_at", "_bronze_ingested_at")
    return dedupe(out, ("fight_id", "round_number", "fighter_id"))


def odds_rows(od: Any) -> Any:
    from pyspark.sql import functions as F

    def line(prefix: str, c: Any) -> list[Any]:
        out = []
        for side in ("a", "b"):
            out += [c[side]["american"].alias(f"{prefix}_{side}_american"),
                    c[side]["decimal"].alias(f"{prefix}_{side}_decimal"),
                    c[side]["implied_probability"].alias(f"{prefix}_{side}_implied_probability")]
        return out + [c["favourite"].alias(f"{prefix}_favourite"),
                      c["fair_probability_a"].alias(f"{prefix}_fair_probability_a"),
                      c["sources"].alias(f"{prefix}_sources"),
                      F.to_timestamp(c["recorded_at"]).alias(f"{prefix}_recorded_at")]

    f = F.col("fight")
    exploded = od.where(F.col("p.data").isNotNull()).select(
        F.col("key").alias("event_id"), F.col("fetched_at"),
        F.col("ingested_at").alias("_bronze_ingested_at"), F.explode("p.data.fights").alias("fight"))
    out = exploded.select(
        f["fight_id"].alias("fight_id"), "event_id", f["status"].alias("status"),
        f["fighter_a"]["id"].alias("fighter_a_id"), f["fighter_b"]["id"].alias("fighter_b_id"),
        *line("consensus", f["consensus"]), *line("opening", f["opening"]), *line("closing", f["closing"]),
        f["movement"]["delta_points_a"].alias("movement_delta_points_a"),
        f["movement"]["direction"].alias("movement_direction"),
        f["points"].alias("points"), F.to_timestamp(f["updated_at"]).alias("odds_updated_at"),
        "fetched_at", "_bronze_ingested_at",
    )
    return dedupe(out, ("fight_id",))


def fighter_rows(fi: Any) -> Any:
    from pyspark.sql import functions as F

    d = F.col("p.data")
    rec = d["records"]
    s = d["stats"]["values"]
    pi = d["power_index"]

    def inches_to_cm(c: Any) -> Any:
        return F.round(c * 2.54, 1)

    return dedupe(fi.where(d.isNotNull()).select(
        F.col("key").alias("fighter_id"), d["slug"].alias("slug"), d["name"].alias("name"),
        d["nickname"].alias("nickname"), d["nationality"].alias("nationality"),
        d["country_code"].alias("country_code"), d["second_nationality"].alias("second_nationality"),
        d["height_inches"].alias("height_in"), inches_to_cm(d["height_inches"]).alias("height_cm"),
        d["reach_inches"].alias("reach_in"), inches_to_cm(d["reach_inches"]).alias("reach_cm"),
        d["weight_lbs"].alias("weight_lbs"), d["stance"].alias("stance"),
        F.to_date(d["dob"]).alias("dob"), d["team"].alias("team"), d["birthplace"].alias("birthplace"),
        rec["pro_mma"]["wins"].alias("pro_mma_wins"), rec["pro_mma"]["losses"].alias("pro_mma_losses"),
        rec["pro_mma"]["draws"].alias("pro_mma_draws"), rec["pro_mma"]["no_contests"].alias("pro_mma_no_contests"),
        rec["ufc"]["wins"].alias("ufc_wins"), rec["ufc"]["losses"].alias("ufc_losses"),
        rec["ufc"]["draws"].alias("ufc_draws"), rec["ufc"]["no_contests"].alias("ufc_no_contests"),
        s["slpm"].alias("slpm"), s["str_acc"].alias("str_acc"), s["sapm"].alias("sapm"),
        s["str_def"].alias("str_def"), s["td_avg"].alias("td_avg"), s["td_acc"].alias("td_acc"),
        s["td_def"].alias("td_def"), s["sub_avg"].alias("sub_avg"),
        d["stats"]["basis"]["bouts"].alias("stats_bouts"),
        pi["rating"].alias("power_rating"), pi["peak"].alias("power_peak"),
        F.to_date(pi["peak_date"]).alias("power_peak_date"), pi["fights_rated"].alias("power_fights_rated"),
        F.to_date(pi["last_fought_date"]).alias("last_fought_date"),
        d["last_fight"]["fight_id"].alias("last_fight_id"), d["last_fight"]["event_id"].alias("last_fight_event_id"),
        F.col("fetched_at"), F.col("ingested_at").alias("_bronze_ingested_at"),
    ), ("fighter_id",))


def fighter_record_rows(fi: Any) -> Any:
    """One row per fighter and record type; `records` is keyed by type (pro_mma, ufc, amateur_mma, ...)."""
    from pyspark.sql import functions as F

    exploded = fi.where(F.col("p.data").isNotNull()).select(
        F.col("key").alias("fighter_id"), F.col("fetched_at"),
        F.col("ingested_at").alias("_bronze_ingested_at"),
        F.explode(F.col("p.data.records")).alias("record_type", "r"))
    return dedupe(exploded.select(
        "fighter_id", "record_type", F.col("r.value").alias("record"),
        F.col("r.wins").alias("wins"), F.col("r.losses").alias("losses"), F.col("r.draws").alias("draws"),
        F.col("r.no_contests").alias("no_contests"), F.col("r.source").alias("source"),
        F.col("r.scope").alias("scope"), "fetched_at", "_bronze_ingested_at"),
        ("fighter_id", "record_type"))


def dedupe(df: Any, keys: tuple[str, ...]) -> Any:
    """One row per key (the latest fetch), so a drifted payload cannot make MERGE see duplicate sources."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    w = Window.partitionBy(*keys).orderBy(F.col("_bronze_ingested_at").desc(), F.col("fetched_at").desc())
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


# ---- merge -------------------------------------------------------------------------------------

def ensure_table(spark: Any, name: str, df: Any) -> list[str]:
    """Create the silver table from the transform's schema (so the code is the one place columns live).

    If the table exists and the transform now produces extra columns, add them with ALTER TABLE.
    (Serverless compute does not allow the `autoMerge` setting, so schema evolution is explicit.)
    Returns the names of added columns.
    """
    if not spark.catalog.tableExists(name):
        df.limit(0).writeTo(name).using("delta").create()
        return []
    existing = {c.lower() for c in spark.table(name).columns}
    new = [f for f in df.schema.fields if f.name.lower() not in existing]
    if new:
        cols = ", ".join(f"`{f.name}` {f.dataType.simpleString()}" for f in new)
        spark.sql(f"ALTER TABLE {name} ADD COLUMNS ({cols})")
        log.info("added columns to %s: %s", name, [f.name for f in new])
    return [f.name for f in new]


def merge_table(spark: Any, catalog: str, tgt: str, table: str, df: Any) -> dict[str, int]:
    """Reload one table's changed rows.

    Tables derived from a parent row (bouts of an event, rounds of a fight, ...) first delete that
    parent's rows, then upsert, so rows that disappeared from the source do not linger. The delete
    is a join-based MERGE ... THEN DELETE: neither a subquery in DELETE nor in the condition of
    NOT MATCHED BY SOURCE is accepted by every Delta version. If a run stops between the two steps, the parent is still marked changed
    and the next run reloads it.
    """
    keys, scope_col, scope_view = TABLES[table]
    target = tname(catalog, tgt, table)
    ensure_table(spark, target, df)
    deleted = 0
    if scope_col:
        res = spark.sql(f"""
            MERGE INTO {target} t USING (SELECT DISTINCT {scope_col} FROM {scope_view}) s
            ON t.{scope_col} = s.{scope_col} WHEN MATCHED THEN DELETE""").collect()
        deleted = int(res[0]["num_deleted_rows"]) if res else 0
    df.createOrReplaceTempView(f"_src_{table}")
    on = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    row = spark.sql(f"""
        MERGE INTO {target} t USING _src_{table} s ON {on}
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *""").collect()
    r = row[0].asDict() if row else {}
    return {"inserted": int(r.get("num_inserted_rows") or 0), "updated": int(r.get("num_updated_rows") or 0),
            "deleted_before_reload": deleted}


def run_build(spark: Any, catalog: str, src: str, tgt: str, full_refresh: bool, dry_run: bool) -> dict[str, Any]:
    """Build every silver table from bronze. Children first; each parent table last."""
    from pyspark.sql import functions as F

    if not dry_run:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{tgt} COMMENT 'Silver: typed and cleaned UFCalendar tables'")
    if full_refresh and not dry_run:
        for table in TABLES:
            if spark.catalog.tableExists(tname(catalog, tgt, table)):
                spark.sql(f"DELETE FROM {tname(catalog, tgt, table)}")

    ev = changed_rows(spark, catalog, src, tgt, "events", schemas.EVENT)
    rd = changed_rows(spark, catalog, src, tgt, "fights", schemas.ROUNDS)
    od = changed_rows(spark, catalog, src, tgt, "odds", schemas.ODDS)
    fi = changed_rows(spark, catalog, src, tgt, "fighters", schemas.FIGHTER)
    # Scope views are lazy over silver, which is why the parent table is merged last (see module doc).
    ev.select(F.col("key").alias("event_id")).createOrReplaceTempView("_chg_events")
    rd.select(F.col("key").alias("fight_id")).createOrReplaceTempView("_chg_fights")
    od.select(F.col("key").alias("event_id")).createOrReplaceTempView("_chg_odds")
    fi.select(F.col("key").alias("fighter_id")).createOrReplaceTempView("_chg_fighters")

    report: dict[str, Any] = {"changed_bronze_rows": {
        "events": ev.count(), "fights": rd.count(), "odds": od.count(), "fighters": fi.count()}}
    if dry_run:
        return report

    merged: dict[str, Any] = {}
    merged["round_stats"] = merge_table(spark, catalog, tgt, "round_stats", round_rows(rd))
    merged["odds"] = merge_table(spark, catalog, tgt, "odds", odds_rows(od))
    merged["fighter_record"] = merge_table(spark, catalog, tgt, "fighter_record", fighter_record_rows(fi))
    merged["fighter"] = merge_table(spark, catalog, tgt, "fighter", fighter_rows(fi))
    bouts = bout_rows(ev)
    merged["bout"] = merge_table(spark, catalog, tgt, "bout", bouts)
    merged["fighter_bout"] = merge_table(spark, catalog, tgt, "fighter_bout", fighter_bout_rows(bouts))
    merged["event"] = merge_table(spark, catalog, tgt, "event", event_rows(ev))
    report["merged"] = merged
    return report


# ---- data quality (reported, not enforced) -----------------------------------------------------

def dq_report(spark: Any, catalog: str, tgt: str) -> dict[str, Any]:
    t = {k: tname(catalog, tgt, k) for k in TABLES}

    def one(sql: str) -> int:
        return int(spark.sql(sql).collect()[0][0])

    played = "('a_win','b_win','draw','no_contest')"
    counts = {k: one(f"SELECT count(*) FROM {v}") for k, v in t.items()}
    checks = {
        "events_without_bouts": one(f"SELECT count(*) FROM {t['event']} e WHERE NOT EXISTS "
                                    f"(SELECT 1 FROM {t['bout']} b WHERE b.event_id = e.event_id)"),
        "bouts_with_unknown_outcome": one(f"SELECT count(*) FROM {t['bout']} WHERE outcome = 'unknown'"),
        "played_bouts_without_round_stats": one(
            f"SELECT count(*) FROM {t['bout']} b WHERE b.outcome IN {played} AND NOT EXISTS "
            f"(SELECT 1 FROM {t['round_stats']} r WHERE r.fight_id = b.bout_id)"),
        "round_stats_fights_without_bout": one(
            f"SELECT count(DISTINCT fight_id) FROM {t['round_stats']} r WHERE NOT EXISTS "
            f"(SELECT 1 FROM {t['bout']} b WHERE b.bout_id = r.fight_id)"),
        "odds_fights_without_bout": one(f"SELECT count(*) FROM {t['odds']} o WHERE NOT EXISTS "
                                        f"(SELECT 1 FROM {t['bout']} b WHERE b.bout_id = o.fight_id)"),
        "bout_fighters_without_fighter_row": one(
            f"SELECT count(DISTINCT fighter_id) FROM {t['fighter_bout']} fb WHERE NOT EXISTS "
            f"(SELECT 1 FROM {t['fighter']} f WHERE f.fighter_id = fb.fighter_id)"),
        "fighters_without_dob": one(f"SELECT count(*) FROM {t['fighter']} WHERE dob IS NULL"),
    }
    titles = {
        "sponsor_prefixes_stripped": [list(r) for r in spark.sql(
            f"SELECT title_sponsor, count(*) FROM {t['event']} WHERE title_sponsor IS NOT NULL GROUP BY 1").collect()],
        "leads_for_review": [r[0] for r in spark.sql(
            f"SELECT DISTINCT title_lead_unreviewed FROM {t['event']} WHERE title_lead_unreviewed IS NOT NULL "
            "ORDER BY 1 LIMIT 50").collect()],
    }
    # Share of decided bouts won from corner A. Near 50% means a neutral side; near 100% means the source
    # lists the winner first for that org, so corner / fighter_a must not be used as a model feature.
    a_share = [[r[0], float(r[1]), int(r[2])] for r in spark.sql(
        f"SELECT org, round(avg(CASE WHEN outcome = 'a_win' THEN 1.0 ELSE 0.0 END), 3), count(*) "
        f"FROM {t['bout']} WHERE outcome IN ('a_win','b_win') GROUP BY org ORDER BY org").collect()]
    return {"row_counts": counts, "checks": checks, "a_win_share_by_org": a_share, "titles": titles}
