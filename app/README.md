# Phase 1 dashboard (Streamlit)

Fighter search and profiles, an event browser with full results, fight stats, and an organisation filter.
Reads only `mma.silver` through the Databricks SQL Statement Execution API, hosted outside Databricks
(Streamlit Community Cloud) so viewers need no workspace account. Data by [UFCalendar](https://www.ufcalendar.com).

| File | What it does |
|---|---|
| `streamlit_app.py` | Pages and layout. Navigation is in the URL (`?view=fighter&id=397&orgs=ufc,pfl`) |
| `db.py` | Read-only SQL client: OAuth M2M or a dev token, named parameters, row and time caps, safe errors |
| `queries.py` | All SQL. Each query is a key lookup or a capped scan of a small table |
| `display.py` | Pure display rules (corners, results, nulls, escaping, search); tested in `tests/test_app_display.py` |

## Rules the app enforces
- **Corners:** winners are listed first everywhere; corner colours are never shown. Corner order is shown
  only for undecided bouts where `corner_reliable` is true, with a note that corner A is not a performance stat.
- **Photos:** only UFCalendar's Wikimedia Commons / CC photos, each shown with its photographer, licence and
  source link (a licence requirement); a photo without that credit is not shown, and fighters without one get
  their initials. Never photos from ESPN, Tapology, UFC or other sites (copyrighted).
- **UFCalendar terms:** "Data by UFCalendar" on every page; tables are static HTML, so there is no CSV
  download; no bulk export; bronze and raw payloads are never read.
- **Data caveats:** cancelled events and bouts are hidden; Contender Series is its own organisation in the
  filter; nulls show as a dash or "Unknown"; the one bout with outcome `unknown` shows as "Result unknown".
- **Warehouse load:** every result is cached for 6 hours; the fighter list (about 5,300 rows) and event list
  (about 1,260) are loaded once and filtered in the session, so typing never queries; queries are capped by
  `LIMIT` and cancelled after 90 s. A page view costs at most 3 small statements when nothing is cached.

## Run locally
```bash
pip install -r app/requirements.txt
export DATABRICKS_WAREHOUSE_ID=<warehouse id>   # DATABRICKS_HOST and DATABRICKS_TOKEN from .env
streamlit run app/streamlit_app.py              # run from the repo root so .streamlit/config.toml applies
```
A local `.streamlit/secrets.toml` (gitignored) works too; see `secrets.toml.example`. Locally the app may use
your own token; the deployed app must use the read-only service principal.

Tests: `python -m pytest tests/test_app_display.py tests/test_app_db.py -q`.

## Deploy to Streamlit Community Cloud
1. **Service principal** (once): `mma-dashboard-reader`, with only `USE CATALOG mma`, `USE SCHEMA mma.silver`,
   `SELECT ON SCHEMA mma.silver`, the Databricks SQL access entitlement, and Can use on the warehouse.
   Create an OAuth secret for it. Check it cannot read `mma.bronze` before going further.
2. **Repository access:** Community Cloud needs GitHub access to the repo. The repo is private; keep it so
   until the `data-snapshots` branch is deleted (UFCalendar terms).
3. **New app:** repository `theflyingali/MMA-Intelligence-Platform`, branch `main` (after merge), main file
   `app/streamlit_app.py`, Python 3.11 or later. Dependencies come from `app/requirements.txt`.
4. **Secrets** (app settings, never in Git): `DATABRICKS_HOST`, `DATABRICKS_WAREHOUSE_ID`,
   `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`. Do not set `DATABRICKS_TOKEN` there.
5. **Smoke test:** events page, an event card, a fighter (`?view=fighter&id=397`), a fight with and without
   round stats (`?view=fight&id=93886`, `?view=fight&id=67800`), and the UFCalendar link in the footer.
6. **Access:** the app is public by default. Start by inviting viewers only (Community Cloud sharing settings),
   then open it up.
7. **After go-live:** watch the logs (`mma_app.db` prints one line per statement with rows and seconds) and
   the warehouse query history for unexpected load; rotate the OAuth secret before it expires.
