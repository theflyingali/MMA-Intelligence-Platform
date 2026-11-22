# Project Status

Single source of truth for what is done, in progress and next. Kept current by the tracker session (see "How to update" below). Last updated: 2026-11-22.

Current phase: **1. Fighter stats foundation** (ingestion built, bronze to silver not started).

## Done
- 2026-10-27: Hybrid architecture agreed (`docs/decisions.md`).
- 2026-10-28: Git repo created, landing zone SQL added (volume `/Volumes/mma/raw/landing`), CLI upload fix logged.
- 2026-10-28: UFCStats scraping rejected on terms-of-use grounds; licensed UFCalendar API chosen instead.
- 2026-10-30: Ingestion design agreed (`docs/ingestion-design.md`) and backfill size estimated (about 19,500 requests, fits one Hobby month).
- 2026-10-30: Incremental UFCalendar ingestion built, with manifest, rate limiting, request budget, dry run and run lock. End-to-end test with a fake API passes 19/19.
- 2026-10-30: Ingestion moved to Databricks serverless jobs via an Asset Bundle (`ufcalendar-incremental`, `ufcalendar-backfill`); laptop kept as fallback.

## In progress
- **Historical backfill (UFC), partial.** After the 4 November job block, a free-quota chunk ran from the laptop and was paused. At that point the manifest held 13 events, 126 bouts with round stats and 244 fighters, with 905 free requests left that month.
- **Databricks backfill run, result unconfirmed.** The ingestion session reported job runs working again and started a run on Databricks (expected about 80 minutes), but its watcher was stopped when the session closed. Check the run history in the Jobs UI and the manifest before treating this as done. Note the backfill job is designed to refuse below a 30,000/month plan, so confirm which job actually ran.
- **Uncommitted:** the 4 November entry in `docs/learning-log.md` (reworded from "completed" to "paused").

## Next
1. Confirm the state of the Databricks run and the manifest (counts per endpoint).
2. Commit the learning-log change.
3. Decide when to take the one Hobby month for the full backfill (UFC, PFL, OKTAGON, RIZIN).
4. Bronze Delta tables from the landing files (dedupe on natural key, latest `fetched_at` wins).
5. Silver tables: clean titles and sponsor prefixes, flag Contender Series bouts.
6. Phase 1 dashboard app, with the visible "Data by UFCalendar" link the terms require.

## Open questions
- Can Databricks Apps be opened by users outside the workspace on Free Edition?
- Which foundation models and how many serving endpoints are available?
- How to authenticate the external frontend securely (token or service principal options on Free Edition)?
- Which outbound domains are allowlisted, beyond `api.ufcalendar.com` (already tested)?
- Alerting for missed scheduled runs (raised in the 2026-11-04 learning-log entry; not built).

## Known risks
- Free Edition fair usage can block job runs for a day or more with no visible quota. The laptop fallback needs no Databricks compute.
- The free UFCalendar key allows 1,000 requests/month, 10/minute.

## How to update
The tracker session reads this file, `CLAUDE.md`, the docs, the git log and the other sessions' transcripts, then edits this file. Rules: check claims against files, commits or job results before marking anything done, and label anything unverified as unconfirmed.
