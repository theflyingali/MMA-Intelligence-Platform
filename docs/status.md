# Project Status

Single source of truth for what is done, in progress and next. Kept current by the tracker session (see "How to update" below). Last updated: 2026-11-22 (after the cloud access check).

Current phase: **1. Fighter stats foundation** (ingestion built, bronze to silver not started).

## Done
- 2026-10-27: Hybrid architecture agreed (`docs/decisions.md`).
- 2026-10-28: Git repo created, landing zone SQL added (volume `/Volumes/mma/raw/landing`), CLI upload fix logged.
- 2026-10-28: UFCStats scraping rejected on terms-of-use grounds; licensed UFCalendar API chosen instead.
- 2026-10-30: Ingestion design agreed (`docs/ingestion-design.md`) and backfill size estimated (about 19,500 requests, fits one Hobby month).
- 2026-10-30: Incremental UFCalendar ingestion built, with manifest, rate limiting, request budget, dry run and run lock. End-to-end test with a fake API passes 19/19.
- 2026-10-30: Ingestion moved to Databricks serverless jobs via an Asset Bundle (`ufcalendar-incremental`, `ufcalendar-backfill`); laptop kept as fallback.

## In progress
- **Historical UFC backfill: incomplete.** Verified from the cloud on 2026-11-22 (read-only check of the manifest and job runs). The `ufcalendar-backfill` run of 2026-11-04 (81.6 min) ended SUCCESS, but `listing.ufc.history_complete` is still `False`. Manifest as of 2026-11-07 05:03Z: 36 events, 36 odds, 372 bouts with round stats, 626 fighters, all HTTP 200. Why it stopped early is unconfirmed (free-quota limit or job parameters; logs not checked).
- **Scheduled ingestion has not run since 2026-11-07.** The incremental job runs every third day at 05:00 UTC; the runs expected on 10, 13, 16 and 19 November are missing. Cause unconfirmed: job paused, or the Free Edition fair-usage block seen on 4 November. Check the job's schedule and run history in the Jobs UI.
- **Cloud access works.** The Default cloud environment can reach Databricks with `DATABRICKS_HOST` and `DATABRICKS_TOKEN` (SCIM check returned 200 after the host was allowlisted and the token regenerated). `api.ufcalendar.com` is blocked in the cloud environment, which is fine because the jobs call it from Databricks.
- **Remote Control** is on for the tracker session (local, so the Mac must stay awake).

## Next
1. Find out why the schedule stopped after 2026-11-07 (job paused vs fair-usage block) and fix it.
2. Decide how to finish the UFC backfill: stay on the free plan in small chunks, or take the one Hobby month (about 19,500 requests for UFC, PFL, OKTAGON, RIZIN) and run the backfill job. Check why the 4 November run stopped with `history_complete` False.
3. Add alerting for missed scheduled runs (first raised on 2026-11-04, now confirmed to matter).
4. Move the tracker and ingestion work to cloud sessions; archive the finished "MMA Intelligence Platform repo" session.
5. Bronze Delta tables from the landing files (dedupe on natural key, latest `fetched_at` wins).
6. Silver tables: clean titles and sponsor prefixes, flag Contender Series bouts.
7. Phase 1 dashboard app, with the visible "Data by UFCalendar" link the terms require.

## Open questions
- Can Databricks Apps be opened by users outside the workspace on Free Edition?
- Which foundation models and how many serving endpoints are available?
- How to authenticate the external frontend securely (token or service principal options on Free Edition)?
- Which outbound domains are allowlisted, beyond `api.ufcalendar.com` (already tested)?
- Do Free Edition personal access tokens keep working long term? One is in use in the cloud environment now.

## Known risks
- Free Edition fair usage can block job runs for a day or more with no visible quota. The laptop fallback needs no Databricks compute.
- The free UFCalendar key allows 1,000 requests/month, 10/minute.

## How to update
The tracker session reads this file, `CLAUDE.md`, the docs, the git log and the other sessions' transcripts, then edits this file. Rules: check claims against files, commits or job results before marking anything done, and label anything unverified as unconfirmed.
