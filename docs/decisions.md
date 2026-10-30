# Architecture Decision Log

One entry per significant decision. Newest at the bottom.

Format:
- **Date** | **Decision** | **Options considered** | **Why** | **What I'd change at scale**

---

- **2026-10-27** | Hybrid architecture: scraping outside Databricks, lakehouse on Databricks, frontend outside | All on Databricks; all outside; hybrid | Free Edition blocks most outbound internet and Apps stop after 24h; hybrid mirrors enterprise landing-zone pattern | Run ingestion on managed compute with a service principal; host the frontend as a Databricks App on a paid workspace
- **2026-10-28** | Claude Code as primary dev tool, context in version-controlled CLAUDE.md plus docs/ | Cursor; Claude Code; both | Terminal-first fits scraping, CLI and Git work; context is reproducible and reviewable | Same, plus shared team conventions in CLAUDE.md
- **2026-10-28**: Rejected scraping UFCStats after the UFC terms of use were found to prohibit automated access and database building; fighter stats to come from a licensed MMA API instead. At scale, negotiate a commercial data licence.
- **2026-10-30** | UFCalendar ingestion: incremental rules | Re-fetch recent events every run; refresh on a fixed interval; webhooks | Every-run refresh would spend ~14 requests per recent event per run and exhaust the free quota. Chosen: fetch by numeric id (slugs can 308-redirect); events from the last 14 days re-fetched at most every 72 hours; round stats re-fetched only when a bout's result changes; fighters re-fetched after they fight again; ETags sent on re-fetch. Estimated steady state for UFC on a free key: about 190 requests/month of 1,000 | Use UFCalendar webhooks (deliveries do not count against quota) from a hosted endpoint instead of polling
