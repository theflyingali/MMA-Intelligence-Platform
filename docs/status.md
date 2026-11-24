# Project Status

Single source of truth for what is done, in progress and next. Kept current by the tracker session (see "How to update" below). Last updated: 2026-11-24 (bronze and silver built and loaded).

Current phase: **1. Fighter stats foundation** (ingestion, bronze and silver done; dashboard app not started).

## Done
- 2026-10-27: Hybrid architecture agreed (`docs/decisions.md`).
- 2026-10-28: Git repo created, landing zone SQL added (volume `/Volumes/mma/raw/landing`), CLI upload fix logged.
- 2026-10-28: UFCStats scraping rejected on terms-of-use grounds; licensed UFCalendar API chosen instead.
- 2026-10-30: Ingestion design agreed (`docs/ingestion-design.md`) and backfill size estimated (about 19,500 requests, fits one Hobby month).
- 2026-10-30: Incremental UFCalendar ingestion built, with manifest, rate limiting, request budget, dry run and run lock. End-to-end test with a fake API passes 19/19.
- 2026-10-30: Ingestion moved to Databricks serverless jobs via an Asset Bundle (`ufcalendar-incremental`, `ufcalendar-backfill`); laptop kept as fallback.
- 2026-11-22: Historical backfill complete for UFC, PFL, OKTAGON and RIZIN (details under "In progress").
- 2026-11-23: **Bronze built and loaded in full** (`bronze/`, `mma.bronze`): processed-files log, MERGE on natural key with latest `fetched_at` winning, raw JSON payload kept. 21,017 landing files loaded, 0 rejected; 1,263 events, 1,263 odds, 13,090 fights and 5,322 fighters, row counts equal to the manifest, no duplicate keys. About 13 minutes of serverless compute in two passes.
- 2026-11-23: **Silver built and loaded in full** (`silver/`, `mma.silver`): `event` 1,263, `bout` 13,239, `fighter_bout` 26,178, `round_stats` 57,321, `odds` 13,090, `fighter` 5,322, `fighter_record` 13,660. All keys unique; a `full_refresh` rebuilds identical tables from bronze (65 to 110 s). A data-quality report prints on every run. Docs: `bronze/README.md`, `silver/README.md`, diagrams in `docs/data-layers.html`.
- 2026-11-23: PR #3 (bronze, silver, diagrams) merged to `main`.
- 2026-11-24: Housekeeping: test schemas `mma.bronze_dev` and `mma.silver_dev` and the temporary workspace folders deleted. Title review closed: the full history has only three sponsor prefixes (Crypto.com, VeChain, Polymarket), the review list is empty, and `title_says_cancelled` was added for events the source lists as `completed` but whose title says cancelled or postponed (2 today).

## In progress
- **Bronze and silver are loaded but run by hand.** No bronze or silver job exists: both were run as one-off submits from the cloud session. Data fetched by the incremental job reaches silver only after a manual bronze run then silver run. Automation (deploy the two bundles, chain them as one job after the incremental job) is **deferred by the owner (2026-11-24)**, not needed yet.
- **Bronze and silver bundles are unvalidated.** `bronze/databricks.yml` and `silver/databricks.yml` have never been validated or deployed because the Databricks CLI cannot be installed in the cloud environment (GitHub downloads are blocked). Validate from the Mac before relying on them.
- **Jobs back on free-plan settings (deployed 2026-11-23).** Backfill schedule PAUSED; incremental on all four orgs (UFC, PFL, OKTAGON, RIZIN; 10 latest events each) with budget 100, 8/min (every third day, 06:00 Amsterdam, UNPAUSED). Watch monthly usage; fall back to `incremental_orgs=ufc` if the 1,000 free requests run short.
- **Offline backup of the raw data (2026-11-23).** The `landing-snapshot` job zipped the landing folder (21,038 files, 22.5 MB, about 34 min) and the zip is committed on the orphan branch `data-snapshots` (private repo; delete that branch before making the repo public). Re-run the job and commit a new zip there now and then.
- **Historical backfill: complete (2026-11-22).** The long run (13:57Z to 18:10Z, 13,936 of 16,000 requests, stop reason `completed`, 0 errors, 0 404s) set `history_complete` True for UFC, PFL, OKTAGON and RIZIN. Manifest: 1,263 events with odds, 13,090 bouts with round stats, 5,322 fighters. The three runs on 22 November used 19,936 requests (estimate about 19,500); 10,064 Hobby quota left until 2026-12-22.
- **Earlier backfill stop (2026-11-04), cause found.** The `ufcalendar-backfill` run of 2026-11-04 was a manual run with overridden free-plan parameters (`--org=ufc --budget=650 --rpm=8 --quota-reserve=250`, no plan guard). It stopped cleanly on its 650-request budget after one list page, which exits 0 and shows SUCCESS; `history_complete` is only set after the last list page. Manifest as of 2026-11-07: 36 events, 372 bouts with round stats, 626 fighters. Details in `docs/learning-log.md`.
- **UFCalendar key on Hobby** (30,000/month, 60/min) until the quota resets on 2026-12-22 (owner confirmed; the backfill's 30,000 plan guard passed on 2026-11-22).
- **Scheduled ingestion: schedule is live, but no runs since 2026-11-07.** Checked via the Jobs API on 2026-11-22: `ufcalendar-incremental` is bundle-deployed with `0 0 6 */3 * ?` Europe/Amsterdam, `UNPAUSED`. The 31 October, 1 and 7 November runs were `PERIODIC` (scheduler). Runs due on 4, 10, 13, 16, 19 and 22 November never appear. Audit log check on 2026-11-22: the schedule is unchanged since 30 October and the scheduler silently skipped every slot from 4 November (no `runTriggered`, no error). Manual triggering works again as of 2026-11-22. Cause unconfirmed; most likely the Free Edition block on triggering new runs seen on 4 November. Details in `docs/learning-log.md`.
- **Cloud access works.** The Default cloud environment can reach Databricks with `DATABRICKS_HOST` and `DATABRICKS_TOKEN` (SCIM check returned 200 after the host was allowlisted and the token regenerated). `api.ufcalendar.com` is blocked in the cloud environment, which is fine because the jobs call it from Databricks.
- **Tracker session runs in the cloud** (since 2026-11-22), so the Mac no longer needs to stay awake. The old local tracker and ingestion sessions are archived; whether a Remote Control process is still running on the Mac is unconfirmed.

## Next
1. Phase 1 dashboard app, first version, built from `mma.silver` (start in a new session). It needs the visible "Data by UFCalendar" link the terms require. Resolve the open questions below first (outside access, authentication).
2. Check the first scheduled incremental run after the deploy, due 2026-11-25 06:00 Amsterdam (four orgs, budget 100, 8/min): did it trigger, requests used, stop reason.
3. Decide by about 19 December whether to renew Hobby (see `docs/decisions.md`, 2026-11-22). Jobs are already on free-plan settings, so letting it lapse needs no change.
4. Add alerting for missed scheduled runs, or a backup trigger outside Databricks (e.g. a GitHub Actions cron calling `jobs run-now`).
5. Phase 3 preparation: a Text2SQL eval set and baseline over silver (`fighter_bout` is the main table) before any agent ships.
6. Phase 4 note: do not use `fighter_a`, `corner` or `a_win` as prediction features (see Known risks); use `odds` as the baseline.
7. Deferred (owner, 2026-11-24): automate bronze and silver as one scheduled job after the incremental job.

## Open questions
- Can Databricks Apps be opened by users outside the workspace on Free Edition?
- Which foundation models and how many serving endpoints are available?
- How to authenticate the external frontend securely (token or service principal options on Free Edition)?
- Which outbound domains are allowlisted, beyond `api.ufcalendar.com` (already tested)?
- Do Free Edition personal access tokens keep working long term? One is in use in the cloud environment now.

## Known risks
- Free Edition fair usage can block job runs for a day or more with no visible quota. The laptop fallback needs no Databricks compute.
- The UFCalendar key is on Hobby (30,000/month, 60/minute) until 2026-12-22; the free plan allows 1,000/month, 10/minute. Jobs already use free-plan settings, so a downgrade needs no change.
- **Corner A is not a real corner in parts of the data.** Share of decided bouts won from corner A: UFC 100% up to 2009 then 54 to 63%; PFL 99 to 100% for 2017 to 2025 (79% in 2026); RIZIN 100% for 2015 to 2025 (79% in 2026); OKTAGON 76 to 100% for 2016 to 2018 then 61 to 70%. Where it is about 100% the source lists the winner first. Silver now carries `corner_reliable` on `bout` and `fighter_bout` (UFC from 2010, OKTAGON from 2019, never PFL or RIZIN): show corner only where it is true, and never use `fighter_a`, `corner` or `a_win` as prediction features. The report checks each reliable org-year (`corner_reliable_org_years_skewed`, 0 today). Details in `silver/README.md`.
- **Silver data gaps (reported, not hidden):** about 6% of played bouts have no round stats (UFC 1994 to 98, early PFL, OKTAGON and RIZIN years); 5 events have empty cards, 2 of them cancelled or postponed but listed as `completed` (`title_says_cancelled`); one UFC bout (83820) has no winner upstream, so its outcome is `unknown`; 521 fighters have no date of birth.
- The dev copies of bronze and silver are gone. Real tables are `mma.bronze` and `mma.silver`; a rerun after a cleaning-rule change is a silver `full_refresh`.

## How to update
The tracker session reads this file, `CLAUDE.md`, the docs, the git log and the other sessions' transcripts, then edits this file. Rules: check claims against files, commits or job results before marking anything done, and label anything unverified as unconfirmed.
