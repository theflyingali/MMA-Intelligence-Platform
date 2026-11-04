# MMA Intelligence App

End-to-end AI system for MMA fans, built on Databricks Free Edition. Personal learning project: the goal is to design, build, deploy and operate a real AI system with real users, and be able to explain every decision.

Full background: @docs/MMA_Project_Context.md

## Phases
1. Fighter stats foundation (current)
2. News and interview intelligence (LLM enrichment)
3. "Ask the stats" Text2SQL / RAG agent
4. Fight prediction model with explanations
5. Real users, monitoring and iteration throughout

## Architecture (agreed)
- Scraping runs OUTSIDE Databricks (laptop or GitHub Actions) and lands raw files in a Unity Catalog volume.
- Exception: licensed API ingestion (UFCalendar) runs as Databricks serverless jobs, since serverless can reach the API (see `docs/decisions.md`, 2026-10-30).
- Databricks owns everything from the landing zone onwards: Delta tables, pipelines, LLM enrichment, retrieval, agents, ML model, evaluation, monitoring.
- Public frontend is hosted outside Databricks and calls Databricks APIs with a service credential.

## Hard constraints (Databricks Free Edition)
- Serverless compute only, one 2X-Small SQL warehouse, max 5 concurrent job tasks.
- Outbound internet from Databricks is restricted: do not scrape from inside Databricks.
- One Vector Search endpoint, no GPU serving, no batch inference, max 3 Databricks Apps.
- Exceeding fair usage shuts compute down for the day: keep jobs small and incremental.
- If a proposal breaks these limits, say so and offer a Free Edition alternative.

## Working rules
- Never commit secrets. Credentials live in `.env` (gitignored) locally and in Databricks secret scopes or GitHub Actions secrets remotely.
- Scraping: respect robots.txt and terms of use, rate-limit requests, cache responses, store summaries and links rather than full article text.
- Evaluation-driven: no LLM feature ships without an eval set and baseline score.
- Prefer small, reviewable changes. Explain the plan before large edits.
- Python 3.11+, type hints, pandas for local work, PySpark on Databricks.

## Documentation habits
- When a significant architecture decision is made, add an entry to `docs/decisions.md`.
- When a bug or failure is found and fixed, add an entry to `docs/learning-log.md`.
- Writing style: British English, concise, no em dashes.
