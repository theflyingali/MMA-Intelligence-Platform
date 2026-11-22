# Learning Log

Failures found, how they were diagnosed, how they were fixed. Raw material for interview stories.

Format:
- **Date** | **Component** | **What went wrong** | **How I diagnosed it** | **Fix** | **Before/after (if measurable)**

---

- **2026-10-28** | Landing zone (CLI upload) | `databricks fs cp` failed with "no such directory" | Listed the volume root to confirm it existed, so the missing piece was the `_test` subfolder | Create folders with `databricks fs mkdir` before copying; the scraper's upload step must do the same | Upload failed → succeeded
- **2026-10-30** | Ingestion tests (end-to-end with fake API) | Two-run test failed: expected 4 round fetches and 10 fighter fetches, got 5 and 8 | Recounted the fake cards by hand: one played bout was missed, and fighters who appear on two events were counted twice | Code was correct; fixed the expectation and added a comment explaining the count. Lesson: dedupe across events is exactly what the test should pin down, so derive expected counts from the fixture, not from memory | 18/19 → 19/19 passing
- **2026-11-04** | Scheduled ingestion job (Databricks Free Edition) | The every-third-day run on 4 November never started, and a manual run failed with "Triggering new runs for organization ... is currently disabled temporarily" | Job settings were unchanged and unpaused, and the run history showed nothing since 1 November, so the scheduler had been blocked rather than failing. The Free Edition docs say exceeding fair usage shuts compute down for the day (or month); the exact message is undocumented and remaining quota is not visible | Ran the same chunk from the laptop fallback, which uploads through the Files API and needs no Databricks compute. Lesson: keep a non-compute fallback path, and alert on missed scheduled runs rather than only on failed ones | Job blocked → laptop run fetched 2 new events and resumes on request
