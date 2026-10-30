# Ingestion Design: UFCalendar Fight API

Status: agreed 2026-10-30. Phase 1 (fighter stats foundation).

## Source
- UFCalendar Fight API, `https://api.ufcalendar.com/v1`, bearer key in `.env` as `UFCAL_KEY`.
- Spec: `docs/ufcalendar-openapi.json`. Terms: https://www.ufcalendar.com/developers/terms
- Usage rules: display and analysis only, no redistribution of the raw dataset, keep a visible "Data by UFCalendar" link in the app.
- Plans: Free = 1,000 requests/month, 10 requests/minute. Hobby = 30,000/month, 60/minute (one paid month planned for the backfill).

## Scope
- Organisations are a config list. Start with `ufc`, then add `pfl`, `oktagon`, `rizin` (and `bkfc` only if wanted; it is bare-knuckle boxing, not MMA).
- Include Dana White's Contender Series (comes under `org=ufc`). Ingest raw; flag in silver later (e.g. `is_official_ufc`).

## What to pull
Per organisation:
1. `GET /events?org={org}&status=completed` (cursor pagination via `meta.pagination.next_cursor` / `has_more`)
2. `GET /events/{slug}` per event: card, fight IDs, results
3. `GET /events/{slug}/odds` per event: consensus odds for every fight on the card (1 call per event)
4. `GET /fights/{id}/rounds` per fight: fight totals plus round-by-round stats (so `/stats` is not needed)
5. `GET /fighters/{slug}` per unique fighter

Not now: scorecards, rankings, predictions.

## Landing layout
One JSON file per API response in the Unity Catalog volume:

```
/Volumes/mma/raw/landing/ufcalendar/{endpoint}/ingest_date=YYYY-MM-DD/{id}.json
```

`{endpoint}` is one of `events_list`, `event`, `event_odds`, `fight_rounds`, `fighter`. Each file wraps the response:

```json
{
  "request_url": "...",
  "fetched_at": "2026-10-30T08:00:00Z",
  "http_status": 200,
  "response": { ... }
}
```

Raw files are never modified. Cleaning (title typos, sponsor prefixes, nulls) happens downstream in silver.

## Incremental logic
- A manifest JSON in the volume (`/Volumes/mma/raw/landing/ufcalendar/_manifest.json`) records fetched IDs per endpoint with `fetched_at`.
- Each run: fetch anything not in the manifest, plus re-fetch events and their fights/odds from the last 14 days (results can change on official review).
- Downstream deduplicates on the natural key, latest `fetched_at` wins.
- Create volume folders before uploading (`fs cp` / SDK uploads fail if the parent folder is missing).

## Guardrails
- Client-side rate limit below the plan's per-minute limit; retries with exponential backoff on 429 and 5xx.
- Request budget cap per run (configurable); stop cleanly and save the manifest before hitting it.
- Dry-run mode that reports how many requests a run would make without calling the API.
- Log every request (endpoint, status, latency) to a local log file and a run summary (requests used, files written, errors).
- Never print or log the API key or Databricks credentials.

## Where it runs
- For now: manually from the laptop, authenticating to Databricks with the CLI profile `mma` (OAuth U2M).
- Later (undecided): scheduled runner such as GitHub Actions, which needs unattended Databricks auth.

## Build order
1. Build and test on the free plan against ~10 recent UFC events.
2. Validate files land correctly and the manifest works across two runs (second run should fetch almost nothing).
3. Dry-run the full backfill to get a request count.
4. Upgrade to Hobby for one month, run the backfill, then downgrade.
