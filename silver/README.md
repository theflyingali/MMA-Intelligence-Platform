# Silver build: bronze to typed, cleaned tables

Reads only the bronze tables (`mma.bronze`, or `mma.bronze_dev` for tests) and writes `mma.silver`
(or `mma.silver_dev`). It never reads the landing volume or calls the API. Bronze keeps the raw
payload, so silver can always be rebuilt (`--full-refresh`).

## Tables
| Table | Grain | Notes |
|---|---|---|
| `event` | event | `title_raw`, `title_clean`, `title_sponsor`, `title_lead_unreviewed`, `is_contender_series`, `is_official_ufc`, `title_says_cancelled`, typed times, venue columns, `card_size` |
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
  `title_lead_unreviewed`, except known event-name leads (`Noche UFC`, `Road to UFC`, `Super RIZIN`,
  `East PRO Fight - Powered by OKTAGON MMA`). The full history (1,263 titles) was reviewed on
  2026-11-24: only the three sponsors above exist and the report is empty. A new lead appearing in
  the report after a later load means a new sponsor or event name to decide on; add it to
  `KNOWN_SPONSORS` or `KNOWN_NON_SPONSOR_LEADS` in `ufcal_silver/titles.py`.
- **Cancelled events:** the source lists some cancelled or postponed events as `completed` with an
  empty card. `title_says_cancelled` is true when the title says so (English, plus the Czech
  `SE PŘESOUVÁ`): 2 events today (`PFL MENA 8: Khobar (cancelled)`, `OKTAGON PRIME 4`). Filter on it
  when showing event lists.
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

## Known data caveats (found on the full history, 2026-11-23)
- **Corner A is not a real corner in parts of the data.** Share of decided bouts won from corner A,
  by period (checked by year on 2026-11-24): UFC 100% up to 2009 and 54 to 63% from 2010; PFL 99 to 100%
  for 2017 to 2025 and 79% in 2026; RIZIN 100% for 2015 to 2025 and 79% in 2026; OKTAGON 76 to 100% for
  2016 to 2018 and 61 to 70% from 2019. A real corner would sit near 50% (or somewhat higher if corner A
  goes to the favourite), so where it is about 100% the source simply lists the winner first. Rules:
  never use `fighter_a`, `corner` or `a_win` as model features (label leakage); do not show corner labels
  or corner-based stats for UFC before 2010, for PFL, for RIZIN (2026 is 79%, unexplained) or for OKTAGON
  before 2019, show winner and loser only. For UFC from 2010 and OKTAGON from 2019 the corner looks real,
  but corner A still wins about 55 to 65% (probably the favourite or higher-ranked fighter; unverified),
  so never present corner win rate as a performance stat. The report prints `a_win_share_by_org` every
  run, but that is an average per org and hides period breaks like UFC 2009 to 2010: check by year.
- Some events have empty cards at the source (5 of 1,263). Two are cancelled or postponed
  (`title_says_cancelled`); the other three (`OKTAGON TIME` x2, `OKTAGON SUMMER FEST`) are simply empty.
- About 6% of played bouts have no round stats (UFC 1994 to 98, early PFL, OKTAGON and RIZIN years).
- One UFC bout (83820) is a completed split decision with no winner upstream; its outcome is `unknown`.

## Tests
`python -m pytest tests -q` runs the title rules. `tests/test_silver_spark_local.py` runs bronze and
silver end to end on local Spark and Delta (skips without `pyspark` and `delta-spark`; about 4 minutes).
