# Project Status

Single source of truth for what is done, in progress and next. Kept current by the tracker session (see "How to update" below). Last updated: 2026-11-22 (historical backfill complete).

Current phase: **1. Fighter stats foundation** (ingestion built, bronze to silver not started).

## Done
- 2026-10-27: Hybrid architecture agreed (`docs/decisions.md`).
- 2026-10-28: Git repo created, landing zone SQL added (volume `/Volumes/mma/raw/landing`), CLI upload fix logged.
- 2026-10-28: UFCStats scraping rejected on terms-of-use grounds; licensed UFCalendar API chosen instead.
- 2026-10-30: Ingestion design agreed (`docs/ingestion-design.md`) and backfill size estimated (about 19,500 requests, fits one Hobby month).
- 2026-10-30: Incremental UFCalendar ingestion built, with manifest, rate limiting, request budget, dry run and run lock. End-to-end test with a fake API passes 19/19.
- 2026-10-30: Ingestion moved to Databricks serverless jobs via an Asset Bundle (`ufcalendar-incremental`, `ufcalendar-backfill`); laptop kept as fallback.

## In progress
- **Jobs back on free-plan settings (deployed 2026-11-23).** Backfill schedule PAUSED; incremental back to UFC only, budget 100, 8/min (every third day, 06:00 Amsterdam, UNPAUSED). Other orgs are not kept current on the free plan; widen `incremental_orgs` if a renewed Hobby plan or spare free quota allows.
- **Historical backfill: complete (2026-11-22).** The long run (13:57Z to 18:10Z, 13,936 of 16,000 requests, stop reason `completed`, 0 errors, 0 404s) set `history_complete` True for UFC, PFL, OKTAGON and RIZIN. Manifest: 1,263 events with odds, 13,090 bouts with round stats, 5,322 fighters. The three runs on 22 November used 19,936 requests (estimate about 19,500); 10,064 Hobby quota left until 2026-12-22.
- **Earlier backfill stop (2026-11-04), cause found.** The `ufcalendar-backfill` run of 2026-11-04 was a manual run with overridden free-plan parameters (`--org=ufc --budget=650 --rpm=8 --quota-reserve=250`, no plan guard). It stopped cleanly on its 650-request budget after one list page, which exits 0 and shows SUCCESS; `history_complete` is only set after the last list page. Manifest as of 2026-11-07: 36 events, 372 bouts with round stats, 626 fighters. Details in `docs/learning-log.md`.
- **UFCalendar key on Hobby** (30,000/month, 60/min) until the quota resets on 2026-12-22 (owner confirmed; the backfill's 30,000 plan guard passed on 2026-11-22).
- **Backfill running.** Manual run 2026-11-22 12:01Z to 12:56Z used its 3,000-request budget with no errors: manifest now 215 events, 2,340 bouts with round stats, 1,252 fighters (UFC about 24% done; other orgs not started), 27,000 quota left. About 6 more runs. The first scheduled run started at 13:00Z the same day (`PERIODIC`), so the scheduler is triggering again. That run (13:00Z to 13:56Z) also used 3,000 requests: 410 events, 4,378 bouts, 1,793 fighters. At the owner's request, one long run started at 13:58Z with a 16,000-request budget (job timeout raised to 6 h in `databricks.yml` on `main`; whether that change is deployed is unconfirmed) to finish the rest in one go; it resumes from the manifest if stopped. Daily 14:00 Amsterdam schedule unpaused on 2026-11-22 at the owner's request. The long run's progress and outcome are unconfirmed until checked. Job changes for Hobby were **deployed on 2026-11-22** from branch `claude/blissful-hopper-mb8rz9` (both jobs updated, settings checked via the Jobs API): incremental widened to UFC, PFL, OKTAGON, RIZIN (budget 600, 55/min); backfill scope and budget as job parameters (UFC first); backfill daily 14:00 schedule (deployed PAUSED, unpaused later the same day, see above). See `docs/decisions.md` (2026-11-22).
- **Scheduled ingestion: schedule is live, but no runs since 2026-11-07.** Checked via the Jobs API on 2026-11-22: `ufcalendar-incremental` is bundle-deployed with `0 0 6 */3 * ?` Europe/Amsterdam, `UNPAUSED`. The 31 October, 1 and 7 November runs were `PERIODIC` (scheduler). Runs due on 4, 10, 13, 16, 19 and 22 November never appear. Audit log check on 2026-11-22: the schedule is unchanged since 30 October and the scheduler silently skipped every slot from 4 November (no `runTriggered`, no error). Manual triggering works again as of 2026-11-22. Cause unconfirmed; most likely the Free Edition block on triggering new runs seen on 4 November. Details in `docs/learning-log.md`.
- **Cloud access works.** The Default cloud environment can reach Databricks with `DATABRICKS_HOST` and `DATABRICKS_TOKEN` (SCIM check returned 200 after the host was allowlisted and the token regenerated). `api.ufcalendar.com` is blocked in the cloud environment, which is fine because the jobs call it from Databricks.
- **Tracker session runs in the cloud** (since 2026-11-22), so the Mac no longer needs to stay awake. The old local tracker and ingestion sessions are archived; whether a Remote Control process is still running on the Mac is unconfirmed.

## Next
1. Check the first scheduled incremental run after the deploy, due 2026-11-25 06:00 Amsterdam (UFC only, budget 100, 8/min): did it trigger, requests used, stop reason.
2. Decide by about 19 December whether to renew Hobby (see `docs/decisions.md`, 2026-11-22). On downgrade, revert the incremental variables and pause the backfill schedule first.
3. Add alerting for missed scheduled runs, or a backup trigger outside Databricks (e.g. a GitHub Actions cron calling `jobs run-now`).
4. Bronze Delta tables from the landing files (dedupe on natural key, latest `fetched_at` wins).
5. Silver tables: clean titles and sponsor prefixes, flag Contender Series bouts.
6. Phase 1 dashboard app, with the visible "Data by UFCalendar" link the terms require.

## Open questions
- Can Databricks Apps be opened by users outside the workspace on Free Edition?
- Which foundation models and how many serving endpoints are available?
- How to authenticate the external frontend securely (token or service principal options on Free Edition)?
- Which outbound domains are allowlisted, beyond `api.ufcalendar.com` (already tested)?
- Do Free Edition personal access tokens keep working long term? One is in use in the cloud environment now.

## Known risks
- Free Edition fair usage can block job runs for a day or more with no visible quota. The laptop fallback needs no Databricks compute.
- The UFCalendar key is on Hobby (30,000/month, 60/minute) for now; the free plan allows 1,000/month, 10/minute, and the incremental settings must be reverted before a downgrade.

## How to update
The tracker session reads this file, `CLAUDE.md`, the docs, the git log and the other sessions' transcripts, then edits this file. Rules: check claims against files, commits or job results before marking anything done, and label anything unverified as unconfirmed.
