# MMA-Intelligence-Platform

End-to-end AI system for MMA fans on Databricks Free Edition. See `CLAUDE.md` and `docs/`.

## Ingestion: UFCalendar API to the landing volume

Design: `docs/ingestion-design.md`. Code: `ingestion/ufcalendar/`. Runs from the laptop and uploads raw JSON to
`/Volumes/mma/raw/landing/ufcalendar/` with the Databricks SDK. Data by [UFCalendar](https://www.ufcalendar.com).

### Setup (once)
- Python 3.11+, then install dependencies:

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

- `UFCAL_KEY=...` in `.env` (gitignored).
- Databricks CLI profile `mma` authenticated (OAuth U2M):

```bash
databricks auth login --profile mma
```

- Landing volume exists (`infra/sql/001_create_landing.sql`).

### Run
Estimate first (no API calls, no uploads):

```bash
python -m ingestion.ufcalendar --org ufc --max-events 10 --dry-run
```

Exact count of new events (spends list-page calls only):

```bash
python -m ingestion.ufcalendar --org ufc --max-events 10 --dry-run --discover --budget 5
```

Ingest (milestone 1: the 10 most recent completed UFC events):

```bash
python -m ingestion.ufcalendar --org ufc --max-events 10 --budget 400
```

Re-running the same command is safe and incremental: it fetches the events list, anything not yet in the
manifest, and events from the last 14 days at most once every 72 hours.

Useful options: `--rpm` (default 8, free plan allows 10), `--budget` (default 50 requests per run),
`--quota-reserve` (stop when the monthly quota remaining falls to this, default 100),
`--min-refetch-hours`, `--refresh-days`, `--local-only` (write to `data/` only). See `--help`.

### On Databricks (scheduled)
The same code runs as serverless jobs defined in `databricks.yml`:

```bash
databricks bundle deploy
```

```bash
databricks bundle run ufcalendar_incremental
```

The API key is read from secret scope `mma` (key `ufcal_key`). `ufcalendar_backfill` is for the Hobby month only
and refuses to run on a smaller plan. Run it repeatedly until it fetches almost nothing.

### Outputs
- Volume: `{endpoint}/ingest_date=YYYY-MM-DD/{id}.json`, `_manifest.json`, `_runs/{run_id}.json`.
- Local: mirror of every file under `data/ufcalendar/`, request log and run summary under `logs/`.

### Tests

```bash
python -m pytest -q
```
