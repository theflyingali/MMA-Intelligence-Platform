# Learning Log

Failures found, how they were diagnosed, how they were fixed. Raw material for interview stories.

Format:
- **Date** | **Component** | **What went wrong** | **How I diagnosed it** | **Fix** | **Before/after (if measurable)**

---

- **2026-10-28** | Landing zone (CLI upload) | `databricks fs cp` failed with "no such directory" | Listed the volume root to confirm it existed, so the missing piece was the `_test` subfolder | Create folders with `databricks fs mkdir` before copying; the scraper's upload step must do the same | Upload failed → succeeded