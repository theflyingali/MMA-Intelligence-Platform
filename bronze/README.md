# Bronze load: UFCalendar landing files to Delta

Turns the raw files in `/Volumes/mma/raw/landing/ufcalendar` into bronze Delta tables. It only
reads the landing volume; it never calls the UFCalendar API.

## Tables (schema `mma.bronze`, or `mma.bronze_dev` for tests)
| Table | One row per | Natural key |
|---|---|---|
| `ufcal_events_list` | event in a list page | `data[].id` |
| `ufcal_event` | event fetch (the card holds the bouts) | `data.id` |
| `ufcal_event_odds` | event's odds | `data.event.id` |
| `ufcal_fight_rounds` | fight's round stats | `meta.fight_id` |
| `ufcal_fighter` | fighter | `data.id` |
| `ufcal_ingest_log` | landing file version (loaded or rejected, with reason) | path + modification time |

Each bronze row keeps the raw API response in `payload` (JSON text), plus `key`, `fetched_at`,
`org` and `slug` where the payload has them, `source_file`, `source_modified_at`, `ingest_date`,
`ingested_at` and `payload_fingerprint` (hash of the payload's key paths, to spot schema drift).
Silver can be rebuilt from `payload` alone. There is no bouts table: bouts are `event.card[]`, and
silver explodes them.

## Rules
- **Idempotent:** `MERGE` on `key`; the latest `fetched_at` wins (ties: file modification time, then
  path). An incoming row never replaces a newer stored one, and reprocessing a file changes nothing.
- **Incremental:** the log table remembers which file versions were loaded. A rewritten file (new
  modification time) is loaded again.
- **Safe with files still arriving:** only `*.json` under the five endpoint folders is read (so
  `_manifest.json`, `_lock.json` and `_runs/` are never data). Empty files and files modified in
  the last `--quiet-minutes` (default 10) are skipped and picked up on a later run. Truncated JSON,
  non-200 envelopes and malformed payloads are logged as `rejected` and never reach bronze.
- **Schema drift:** the payload is stored whole; missing optional fields become null; the
  fingerprint changes when key paths change.

## Run
Subset test (the job defaults): `schema=bronze_dev`, `max_events=10`. This takes the 10 earliest
landed events, plus only their odds, rounds and fighters. `events_list` pages are always loaded
whole.

```bash
cd bronze
databricks bundle deploy
databricks bundle run bronze_ufcalendar                                   # subset into bronze_dev
databricks bundle run bronze_ufcalendar --params dry_run=true             # list only, write nothing
```

## Rerun on the full dataset (after `history_complete` is true for all four orgs)
No code change, only parameters: `schema=bronze`, `max_events=0`.

```bash
databricks bundle run bronze_ufcalendar --params schema=bronze,max_events=0,dry_run=true   # check the plan
databricks bundle run bronze_ufcalendar --params schema=bronze,max_events=0
```

To keep a first full load small, add `max_files=5000` (per endpoint per run) and repeat until the
dry run reports `to_load: 0`. Later runs load only what landed since.

Checks after a run: per table `count(*) = count(distinct key)`, and
`select reject_reason, count(*) from ufcal_ingest_log where status = 'rejected' group by 1`.

## Tests
```bash
python -m pytest tests -q      # pure logic: paths, parsing, ordering, file selection
```
`tests/test_bronze_spark_local.py` runs the real CLI against local Spark and Delta on a fake landing
tree. It skips unless `pyspark` and `delta-spark` are installed (e.g. `uv pip install pyspark==3.5.3
delta-spark==3.2.1` in a Python 3.11 venv); it takes about two minutes.
