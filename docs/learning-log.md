# Learning Log

Failures found, how they were diagnosed, how they were fixed. Raw material for interview stories.

Format:
- **Date** | **Component** | **What went wrong** | **How I diagnosed it** | **Fix** | **Before/after (if measurable)**

---

- **2026-10-28** | Landing zone (CLI upload) | `databricks fs cp` failed with "no such directory" | Listed the volume root to confirm it existed, so the missing piece was the `_test` subfolder | Create folders with `databricks fs mkdir` before copying; the scraper's upload step must do the same | Upload failed → succeeded
- **2026-10-30** | Ingestion tests (end-to-end with fake API) | Two-run test failed: expected 4 round fetches and 10 fighter fetches, got 5 and 8 | Recounted the fake cards by hand: one played bout was missed, and fighters who appear on two events were counted twice | Code was correct; fixed the expectation and added a comment explaining the count. Lesson: dedupe across events is exactly what the test should pin down, so derive expected counts from the fixture, not from memory | 18/19 → 19/19 passing
