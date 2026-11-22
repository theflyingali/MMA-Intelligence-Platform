# Silver build: bronze to typed, cleaned tables

Reads only the bronze tables (`mma.bronze`, or `mma.bronze_dev` for tests) and writes `mma.silver`
(or `mma.silver_dev`). It never reads the landing volume or calls the API. Bronze keeps the raw
payload, so silver can always be rebuilt (`--full-refresh`).

## Tables
| Table | Grain | Notes |
|---|---|---|
| `event` | event | `title_raw`, `title_clean`, `title_sponsor`, `title_lead_unreviewed`, `is_contender_series`, `is_official_ufc`, typed times, venue columns, `card_size` |
| `bout` | bout | Exploded from the card. `outcome` is `a_win`, `b_win`, `draw`, `no_contest`, `cancelled` or `unknown`; winner and loser ids; method, end round and seconds |
| `fighter_bout` | fighter and bout | Two rows per fought bout (win, loss, draw, no contest); cancelled bouts excluded. Best table for "ask the stats" |
| `round_stats` | fight, round, fighter | Typed. The detailed strike and time columns are mostly null today (about 80% in the sample) |
| `odds` | fight | Consensus, opening and closing prices for both sides, fair probability, movement. Props stay in bronze |
| `fighter` | fighter | Inches to cm, `dob` as a date, numeric career stats, power index, UFC and pro MMA records |
| `fighter_record` | fighter and record type | Long format from `records`, which is keyed by type (`pro_mma`, `ufc`, `amateur_mma`, ...) |

Every row carries `fetched_at` and `_bronze_ingested_at`.

## Cleaning rules
- **Sponsor prefixes:** only `Crypto.com`, `VeChain` and `Polymarket` are stripped (`title_raw` is kept,
  the prefix goes to `title_sponsor`). Other leads before a brand are kept and listed in
  `title_lead_unreviewed`, except known event-name leads (`Noche UFC`, `Road to UFC`). Extend
  `KNOWN_SPONSORS` in `ufcal_silver/titles.py` after reviewing the report on the full history.
- **Contender Series:** the slug or the title matches `dwcs` or `contender series` (the two disagree
  on some DWCS Brazil events). `is_official_ufc` is UFC and not Contender Series.
- **Unexpected values** are never guessed: an unrecognised bout status gives `outcome = 'unknown'`,
  counted in the data-quality report.

## How it stays incremental
A bronze row is processed when silver has nothing built from that key, or bronze's `ingested_at` is
newer than the `_bronze_ingested_at` on the silver rows built from it. A re-fetched event reloads its
bouts, a re-fetched fight its rounds, a re-fetched fighter its records, so rows removed upstream
disappear. Child tables are written first and each parent table last, so a run that stops half way
is simply picked up again. Run silver after bronze has finished.

## Run
Test run (job defaults): `source_schema=bronze_dev`, `target_schema=silver_dev`.

```bash
cd silver
databricks bundle deploy
databricks bundle run silver_ufcalendar --params dry_run=true     # counts only
databricks bundle run silver_ufcalendar                           # builds silver_dev
```

## Rerun on the full dataset
After the full bronze load (`schema=bronze`), parameters only:

```bash
databricks bundle run silver_ufcalendar --params source_schema=bronze,target_schema=silver,dry_run=true
databricks bundle run silver_ufcalendar --params source_schema=bronze,target_schema=silver
```

Later updates: run bronze, then silver; silver reloads only what changed. Use `full_refresh=true`
after changing a cleaning rule.

## Data-quality report (printed every run, nothing is enforced)
Row counts per table, events without bouts, unknown outcomes, played bouts without round stats,
round or odds rows without a bout, card fighters missing from `fighter`, fighters without a date of
birth, sponsor prefixes stripped, and leads for review. Missing round stats are expected for old
events and for files still inside bronze's quiet window.

## Tests
`python -m pytest tests -q` runs the title rules. `tests/test_silver_spark_local.py` runs bronze and
silver end to end on local Spark and Delta (skips without `pyspark` and `delta-spark`; about 4 minutes).
