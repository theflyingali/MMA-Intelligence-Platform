"""MMA Intelligence: Phase 1 dashboard (fighters and events), hosted outside Databricks.

Reads `mma.silver` through the SQL Statement Execution API (see `db.py`). Navigation lives in the URL
(`?view=fighter&id=397&orgs=ufc,pfl`) so every page can be linked to. All results are cached for six hours;
search filters a cached fighter list in the browser session, so typing never queries the warehouse.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

import db
import display as d
import queries as q

CACHE_TTL_S = 6 * 60 * 60  # silver refreshes every few days at most
log = logging.getLogger("mma_app")
if not log.handlers:  # one line per warehouse statement, for latency and cost monitoring
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)

st.set_page_config(page_title="MMA Intelligence", page_icon="🥊", layout="wide")

CSS = """
<style>
.block-container { padding-top: 2rem; max-width: 1200px; }
.tw { overflow-x: auto; margin: 0.25rem 0 1rem; }
table.t { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
table.t th { text-align: left; font-weight: 600; padding: 6px 10px; border-bottom: 2px solid rgba(128,128,128,.35);
  white-space: nowrap; }
table.t td { padding: 6px 10px; border-bottom: 1px solid rgba(128,128,128,.18); vertical-align: top; }
table.t tr:hover td { background: rgba(128,128,128,.06); }
table.t a { text-decoration: none; }
table.t td:first-child { min-width: 8.5rem; }
table.t a:hover { text-decoration: underline; }
.nowrap { white-space: nowrap; }
.muted { opacity: .7; }
.badge { display: inline-block; font-size: .72rem; padding: 1px 7px; margin: 0 4px 2px 0; border-radius: 10px;
  border: 1px solid rgba(128,128,128,.45); white-space: nowrap; }
.res-win { font-weight: 600; color: #2e7d32; } .res-loss { font-weight: 600; color: #c62828; }
@media (prefers-color-scheme: dark) { .res-win { color: #81c784; } .res-loss { color: #ef9a9a; } }
.footer { margin-top: 2.5rem; padding-top: .75rem; border-top: 1px solid rgba(128,128,128,.25); font-size: .85rem; }
.headline { font-size: 1.35rem; line-height: 1.4; margin: .25rem 0 .5rem; }
.headline a { text-decoration: none; }
[data-testid="stMetricValue"] { font-size: 1.5rem; }
</style>
"""

# --------------------------------------------------------------------------------------------- data


def _config_values() -> dict[str, Any]:
    """Streamlit secrets win over environment variables (local development uses the environment)."""
    values: dict[str, Any] = dict(os.environ)
    try:
        values.update({k: v for k, v in st.secrets.items() if isinstance(v, str)})
    except Exception:  # no secrets file: fine locally
        pass
    return values


@st.cache_resource(show_spinner=False)
def _client() -> db.SqlClient:
    return db.SqlClient(db.Settings.from_mapping(_config_values()))


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False, max_entries=2000)
def _fetch(name: str, **params: Any) -> pd.DataFrame:
    return _client().query(getattr(q, name), params)


def load(name: str, **params: Any) -> pd.DataFrame:
    """Cached query; on failure show a friendly message and stop the page (details go to the log)."""
    try:
        with st.spinner("Loading… the database can take a few seconds to wake up."):
            return _fetch(name, **params)
    except db.QueryError as exc:
        log.error("query %s failed: %s", name, exc)
        st.error("The data service is not available right now. Please try again in a minute.")
        footer(with_freshness=False)
        st.stop()
    raise AssertionError("unreachable")


def events_frame() -> pd.DataFrame:
    events = load("EVENTS").copy()
    events["org_key"] = [d.org_key(o, c) for o, c in zip(events["org"], events["is_contender_series"])]
    return events


# --------------------------------------------------------------------------------------------- layout


def _freshness() -> str:
    """Best effort: a failed lookup drops the note instead of stopping the page."""
    try:
        frame = _fetch("FRESHNESS")
    except db.QueryError as exc:
        log.warning("freshness lookup failed: %s", exc)
        return ""
    return d.freshness_note(frame["fetched_at"].iloc[0]) if len(frame) else ""


def footer(with_freshness: bool = True) -> None:
    note = _freshness() if with_freshness else ""
    st.markdown(
        f'<div class="footer">Data by <a href="{d.UFCALENDAR_URL}" target="_blank" rel="noopener">UFCalendar</a>. '
        f"{d.esc(note) + ' ' if note else ''}"
        "For display and analysis only. Not affiliated with any organisation.</div>",
        unsafe_allow_html=True,
    )


def badge(text: str) -> str:
    return f'<span class="badge">{d.esc(text)}</span>'


def sidebar(orgs: list[str]) -> list[str]:
    with st.sidebar:
        st.markdown("### MMA Intelligence")
        nav = [("Events", "events"), ("Fighters", "fighters"), ("About the data", "about")]
        st.markdown(" · ".join(d.link(label, d.href(view, orgs)) for label, view in nav), unsafe_allow_html=True)
        chosen = st.multiselect(
            "Organisations", options=list(d.ORG_KEYS), default=orgs, format_func=d.org_label,
            help="Contender Series is listed apart from official UFC events.",
        )
        if not chosen:
            st.caption("No organisation selected, so all are shown.")
        chosen = chosen or list(d.ORG_KEYS)
        if sorted(chosen) != sorted(orgs):
            if tuple(chosen) == d.ORG_KEYS or sorted(chosen) == sorted(d.ORG_KEYS):
                st.query_params.pop("orgs", None)
            else:
                st.query_params["orgs"] = ",".join(chosen)
        st.markdown(
            f'<div class="footer">Data by <a href="{d.UFCALENDAR_URL}" target="_blank" rel="noopener">UFCalendar</a></div>',
            unsafe_allow_html=True,
        )
    return chosen


def _int_param(name: str) -> int | None:
    raw = st.query_params.get(name)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------- pages


def page_events(orgs: list[str]) -> None:
    st.title("Events")
    events = events_frame()
    events = events[events["org_key"].isin(orgs)]
    if events.empty:
        st.info("No events for the selected organisations.")
        return
    years = sorted({ts.year for ts in events["starts_at"].dropna()}, reverse=True)
    wanted = _int_param("year")
    c1, c2 = st.columns([1, 3])
    year = c1.selectbox("Year", years, index=years.index(wanted) if wanted in years else 0)
    if year != wanted:
        st.query_params["year"] = str(year)
    text = c2.text_input("Filter by title or place", placeholder="e.g. Las Vegas, UFC 300, Prague")
    shown = events[events["starts_at"].dt.year == year]
    if text.strip():
        needle = d.normalise(text)
        blob = (shown["title_clean"].map(d.normalise) + " " + shown["venue_city"].map(d.normalise) + " "
                + shown["venue_country"].map(d.normalise))
        shown = shown[blob.str.contains(needle, regex=False)]
    st.caption(f"{len(shown)} events in {year}. Cancelled or postponed events are not listed.")
    rows = []
    for _, e in shown.iterrows():
        place = ", ".join(str(x) for x in (e["venue_city"], e["venue_country"]) if not d.missing(x)) or d.DASH
        title = d.link(e["title_clean"], d.href("event", orgs, id=int(e["event_id"])))
        if e["played_bouts"] == 0:
            title += " " + badge("no bouts listed")
        rows.append([f'<span class="nowrap">{d.fmt_date(e["starts_at"])}</span>', d.esc(d.org_label(e["org_key"])),
                     title, d.esc(place), str(int(e["played_bouts"]))])
    st.markdown(d.html_table(["Date", "Organisation", "Event", "Location", "Bouts"], rows), unsafe_allow_html=True)


SECTION_LABELS = {"main": "Main card", "prelims": "Prelims", "early_prelims": "Early prelims"}


def bout_cell(row: pd.Series, orgs: list[str]) -> str:
    h = d.bout_headline(row)
    first = d.link(h.first_name, d.href("fighter", orgs, id=h.first_id)) if not d.missing(h.first_id) else d.esc(h.first_name)
    second = d.link(h.second_name, d.href("fighter", orgs, id=h.second_id)) if not d.missing(h.second_id) else d.esc(h.second_name)
    if h.connector == "def.":
        return f"<strong>{first}</strong> def. {second}"
    return f"{first} vs {second} " + badge(h.note)


def bout_notes(row: pd.Series) -> str:
    notes = []
    if d.truthy(row.get("is_title")):
        notes.append(badge("Title fight"))
    if not d.missing(row.get("sport")) and str(row["sport"]) != "mma":
        notes.append(badge(str(row["sport"]).replace("-", " ").capitalize()))
    if not d.missing(row.get("bonus")):
        notes.append(badge(str(row["bonus"])))
    return "".join(notes)


def page_event(orgs: list[str]) -> None:
    event_id = _int_param("id")
    events = events_frame()
    match = events[events["event_id"] == event_id] if event_id is not None else events.iloc[0:0]
    if match.empty:
        st.title("Event not found")
        st.write("This event does not exist or is not listed (cancelled and postponed events are hidden).")
        return
    e = match.iloc[0]
    st.title(str(e["title_clean"]))
    place = ", ".join(str(x) for x in (e["venue_name"], e["venue_city"], e["venue_country"]) if not d.missing(x))
    meta = [d.org_label(e["org_key"]), d.fmt_date(e["starts_at"]), place]
    st.markdown(" · ".join(d.esc(m) for m in meta if m) + (" " + badge("PPV") if d.truthy(e["is_ppv"]) else ""),
                unsafe_allow_html=True)
    bouts = load("EVENT_BOUTS", event_id=int(event_id))
    played = bouts[bouts["outcome"] != "cancelled"]
    if played.empty:
        st.info("The source lists no bouts for this event.")
        return
    for section in ["main", "prelims", "early_prelims"] + sorted(set(played["card_section"].dropna()) - set(SECTION_LABELS)):
        part = played[played["card_section"] == section]
        if part.empty:
            continue
        st.subheader(SECTION_LABELS.get(section, str(section).replace("_", " ").capitalize()))
        rows = []
        for _, b in part.iterrows():
            details = d.link("Details", d.href("fight", orgs, id=int(b["bout_id"])))
            if not d.truthy(b["has_round_stats"]):
                details += ' <span class="muted">(no round stats)</span>'
            rows.append([bout_cell(b, orgs), d.esc(d.tidy_weight_class(b["weight_class"])),
                         d.esc(d.method_label(b["method_normalized"], b["finish_detail"], b["method"])),
                         f'<span class="nowrap">{d.esc(d.round_time(b["end_round"], b["end_time"]))}</span>',
                         bout_notes(b), details])
        st.markdown(d.html_table(["Bout", "Weight class", "Method", "Round", "Notes", ""], rows), unsafe_allow_html=True)
    cancelled = len(bouts) - len(played)
    if cancelled:
        st.caption(f"{cancelled} cancelled bout{'s' if cancelled > 1 else ''} not shown.")
    st.caption("Winners are listed first. Corner colours are not shown on cards.")


def page_fighters(orgs: list[str]) -> None:
    st.title("Fighters")
    index = load("FIGHTER_INDEX")
    query = st.text_input("Search by name or nickname", value=st.query_params.get("q", ""),
                          placeholder="e.g. Makhachev, Jiri Prochazka, The Eagle")
    if query != st.query_params.get("q", ""):
        if query:
            st.query_params["q"] = query
        else:
            st.query_params.pop("q", None)
    if not query.strip():
        st.caption(f"{len(index):,} fighters from UFC, Contender Series, PFL, OKTAGON and RIZIN. Type a name and press Enter.")
        return
    found = d.search_fighters(index, query, orgs, limit=50)
    if found.empty:
        st.info("No fighters match that search in the selected organisations.")
        return
    st.caption(f"{len(found)} match{'es' if len(found) != 1 else ''}" + (" (first 50 shown)" if len(found) == 50 else ""))
    rows = [[d.link(f["name"], d.href("fighter", orgs, id=int(f["fighter_id"]))), d.esc(f["nickname"]),
             d.esc(f["country_code"]),
             d.esc(", ".join(d.org_label(k) for k in str(f["orgs"]).split(",") if k) if not d.missing(f["orgs"]) else None),
             str(int(f["bouts"])), d.fmt_date(f["last_bout_at"])] for _, f in found.iterrows()]
    st.markdown(d.html_table(["Name", "Nickname", "Country", "Organisations", "Bouts", "Last bout"], rows),
                unsafe_allow_html=True)


def _result_html(result: str) -> str:
    css = {"Win": "res-win", "Loss": "res-loss"}.get(result, "")
    return f'<span class="{css}">{d.esc(result)}</span>'


def page_fighter(orgs: list[str]) -> None:
    fighter_id = _int_param("id")
    profile = load("FIGHTER", fighter_id=fighter_id) if fighter_id is not None else pd.DataFrame()
    if profile.empty:
        st.title("Fighter not found")
        return
    f = profile.iloc[0]
    st.title(str(f["name"]))
    if not d.missing(f["nickname"]):
        st.markdown(f'<div class="muted">“{d.esc(f["nickname"])}”</div>', unsafe_allow_html=True)

    history = load("FIGHTER_HISTORY", fighter_id=int(fighter_id)).copy()
    history["org_key"] = [d.org_key(o, c) for o, c in zip(history["org"], history["is_contender_series"])]
    shown = history[history["org_key"].isin(orgs)]
    summary = d.dataset_summary(shown, int(fighter_id))
    c = summary["counts"]

    age = d.age_years(f["dob"], date.today())
    bio = st.columns(5)
    bio[0].metric("Age", age if age is not None else "Unknown")
    bio[1].metric("Height", d.fmt_cm(f["height_cm"]))
    bio[2].metric("Reach", d.fmt_cm(f["reach_cm"]))
    bio[3].metric("Stance", f["stance"] if not d.missing(f["stance"]) else d.DASH)
    bio[4].metric("Country", f["country_code"] if not d.missing(f["country_code"]) else d.DASH)
    facts = [("Team", f["team"]), ("Born", f["birthplace"])]
    st.markdown(" · ".join(f"{k}: {d.esc(v)}" for k, v in facts if not d.missing(v)) or "", unsafe_allow_html=True)

    st.subheader("Record")
    rec = st.columns(3)
    rec[0].metric("Pro MMA (all promotions)", d.fmt_record(f["pro_mma_wins"], f["pro_mma_losses"], f["pro_mma_draws"], f["pro_mma_no_contests"]))
    rec[1].metric("UFC", d.fmt_record(f["ufc_wins"], f["ufc_losses"], f["ufc_draws"], f["ufc_no_contests"]))
    rec[2].metric("In this app's data", d.fmt_record(c["Win"], c["Loss"], c["Draw"], c["No contest"]))
    st.caption("Pro MMA and UFC records come from the source's fighter profile and can include fights outside "
               "this app. The last figure counts only the fights listed below (selected organisations).")
    others = load("FIGHTER_RECORDS", fighter_id=int(fighter_id))
    others = others[~others["record_type"].isin(["pro_mma", "ufc"])]
    if not others.empty:
        with st.expander("Other records (amateur, kickboxing, grappling …)"):
            rows = [[d.esc(str(r["record_type"]).replace("_", " ").capitalize()),
                     d.fmt_record(r["wins"], r["losses"], r["draws"], r["no_contests"])] for _, r in others.iterrows()]
            st.markdown(d.html_table(["Record type", "W-L-D"], rows), unsafe_allow_html=True)

    wins, losses = summary["win_methods"], summary["loss_methods"]
    if c["Win"] or c["Loss"]:
        line = lambda m: ", ".join(f"{k} {v}" for k, v in m.items() if v) or "none"  # noqa: E731
        st.markdown(f"**Wins by method:** {line(wins)}  \n**Losses by method:** {line(losses)}")

    st.subheader("Career averages")
    stats = [("Significant strikes landed per minute", d.fmt_number(f["slpm"])),
             ("Significant striking accuracy", d.fmt_pct(f["str_acc"])),
             ("Significant strikes absorbed per minute", d.fmt_number(f["sapm"])),
             ("Significant strike defence", d.fmt_pct(f["str_def"])),
             ("Takedowns per 15 minutes", d.fmt_number(f["td_avg"])),
             ("Takedown accuracy", d.fmt_pct(f["td_acc"])),
             ("Takedown defence", d.fmt_pct(f["td_def"])),
             ("Submission attempts per 15 minutes", d.fmt_number(f["sub_avg"]))]
    if all(v == d.DASH for _, v in stats):
        st.caption("No career averages available for this fighter.")
    else:
        half = (len(stats) + 1) // 2
        cols = st.columns(2)
        for col, chunk in zip(cols, (stats[:half], stats[half:])):
            col.markdown(d.html_table(["Statistic", "Value"], [[d.esc(k), v] for k, v in chunk]), unsafe_allow_html=True)
        basis = f"based on {int(f['stats_bouts'])} bouts" if not d.missing(f["stats_bouts"]) else "basis not stated"
        st.caption(f"Averages as published by the source ({basis}).")

    st.subheader("Fight history")
    hidden = len(history) - len(shown)
    if hidden:
        st.caption(f"{hidden} fight{'s' if hidden > 1 else ''} in organisations you have not selected {'are' if hidden > 1 else 'is'} hidden.")
    if shown.empty:
        st.info("No fights in the selected organisations.")
    else:
        rows = []
        for _, b in shown.iterrows():
            result = d.fighter_result(b["outcome"], b["winner_fighter_id"], int(fighter_id))
            opp_id, opp_name = d.opponent(b, int(fighter_id))
            opp = d.link(opp_name, d.href("fighter", orgs, id=opp_id)) if not d.missing(opp_id) else d.esc(opp_name)
            if d.truthy(b["is_title"]):
                opp += " " + badge("Title fight")
            rows.append([f'<span class="nowrap">{d.fmt_date(b["event_starts_at"])}</span>', _result_html(result), opp,
                         d.esc(d.method_label(b["method_normalized"], b["finish_detail"], b["method"])),
                         f'<span class="nowrap">{d.esc(d.round_time(b["end_round"], b["end_time"]))}</span>',
                         d.link(b["event_title"], d.href("event", orgs, id=int(b["event_id"]))),
                         d.esc(d.org_label(b["org_key"])), d.esc(d.tidy_weight_class(b["weight_class"])),
                         d.link("Details", d.href("fight", orgs, id=int(b["bout_id"])))])
        st.markdown(d.html_table(["Date", "Result", "Opponent", "Method", "Round", "Event", "Organisation",
                                  "Weight class", ""], rows), unsafe_allow_html=True)


STAT_ROWS: list[tuple[str, str, str | None]] = [
    ("Knockdowns", "knockdowns", None),
    ("Significant strikes", "sig_strikes_landed", "sig_strikes_attempted"),
    ("Total strikes", "total_strikes_landed", "total_strikes_attempted"),
    ("Head", "head_landed", "head_attempted"),
    ("Body", "body_landed", "body_attempted"),
    ("Leg", "leg_landed", "leg_attempted"),
    ("Takedowns", "takedowns_landed", "takedowns_attempted"),
    ("Submission attempts", "submission_attempts", None),
    ("Reversals", "reversals", None),
    ("Control time", "control_time_sec", None),
]


def _stat_value(frame: pd.DataFrame, landed: str, attempted: str | None) -> str:
    if frame.empty or frame[landed].isna().all():
        return d.DASH
    total_landed = int(frame[landed].sum())
    if landed == "control_time_sec":
        return d.fmt_seconds(total_landed)
    if attempted is None:
        return str(total_landed)
    return d.landed_of(total_landed, None if frame[attempted].isna().all() else int(frame[attempted].sum()))


def page_fight(orgs: list[str]) -> None:
    bout_id = _int_param("id")
    fight = load("FIGHT", bout_id=bout_id) if bout_id is not None else pd.DataFrame()
    if fight.empty:
        st.title("Fight not found")
        return
    b = fight.iloc[0]
    h = d.bout_headline(b)
    names = {h.first_id: h.first_name, h.second_id: h.second_name}
    fl = lambda i, n: d.link(n, d.href("fighter", orgs, id=i)) if not d.missing(i) else d.esc(n)  # noqa: E731
    head = f"<strong>{fl(h.first_id, h.first_name)}</strong> def. {fl(h.second_id, h.second_name)}" if h.connector == "def." \
        else f"{fl(h.first_id, h.first_name)} vs {fl(h.second_id, h.second_name)} {badge(h.note)}"
    st.markdown(f'<div class="headline">{head}</div>', unsafe_allow_html=True)
    st.caption(d.order_note(h, b["corner_reliable"]))

    org = d.org_label(d.org_key(b["org"], b["is_contender_series"]))
    facts = [("Event", d.link(b["event_title"], d.href("event", orgs, id=int(b["event_id"])))),
             ("Date", d.fmt_date(b["event_starts_at"])), ("Organisation", d.esc(org)),
             ("Weight class", d.esc(d.tidy_weight_class(b["weight_class"])) + (" " + badge("Title fight") if d.truthy(b["is_title"]) else "")),
             ("Method", d.esc(d.method_label(b["method_normalized"], b["finish_detail"], b["method"]))),
             ("Ended", d.esc(d.round_time(b["end_round"], b["end_time"]))
              + (f' <span class="muted">of {int(b["scheduled_rounds"])} scheduled</span>' if not d.missing(b["scheduled_rounds"]) else "")),
             ("Referee", d.esc(b["referee"])), ("Bonus", d.esc(b["bonus"]))]
    if not d.missing(b["sport"]) and str(b["sport"]) != "mma":
        facts.append(("Sport", d.esc(str(b["sport"]).replace("-", " ").capitalize())))
    st.markdown(d.html_table(None, [[f"<strong>{k}</strong>", v] for k, v in facts]), unsafe_allow_html=True)

    st.subheader("Fight stats")
    rounds = load("ROUND_STATS", bout_id=int(bout_id))
    if rounds.empty:
        st.info("No round-by-round stats for this fight. They are missing for about 6% of fights, mostly older "
                "events and early years of the smaller organisations.")
        return
    order = [i for i in (h.first_id, h.second_id) if not d.missing(i)]
    per_fighter = {i: rounds[rounds["fighter_id"] == i] for i in order}
    headers = ["Totals"] + [str(names.get(i, i)) for i in order]
    rows = [[d.esc(label)] + [_stat_value(per_fighter[i], landed, att) for i in order] for label, landed, att in STAT_ROWS]
    st.markdown(d.html_table(headers, rows), unsafe_allow_html=True)
    st.caption("Strikes are shown as landed of attempted.")
    with st.expander("Round by round"):
        for rnd in sorted(rounds["round_number"].dropna().unique()):
            per_round = {i: rounds[(rounds["fighter_id"] == i) & (rounds["round_number"] == rnd)] for i in order}
            rows = [[d.esc(label)] + [_stat_value(per_round[i], landed, att) for i in order]
                    for label, landed, att in STAT_ROWS]
            st.markdown(d.html_table([f"Round {int(rnd)}"] + headers[1:], rows), unsafe_allow_html=True)


def page_about() -> None:
    st.title("About the data")
    st.markdown(f"""
Fighter profiles, events, results and round statistics for **UFC** (with Dana White's Contender Series listed
separately), **PFL**, **OKTAGON** and **RIZIN**, from the
<a href="{d.UFCALENDAR_URL}" target="_blank" rel="noopener">UFCalendar</a> fight API. The data is refreshed every
few days and is shown here for display and analysis only.

**Things to know**
- **Corners.** In parts of the source data the first-listed fighter is simply the winner (UFC before 2010,
  PFL and RIZIN throughout, OKTAGON before 2019), so the app lists winners first and does not show corner colours.
- **Round statistics** are missing for about 6% of fights, mostly early UFC events and the first years of the
  smaller organisations.
- **Records.** A fighter's pro MMA and UFC records come from the source's profile and can include fights outside
  this app. The "in this app's data" record counts only the fights listed on the fighter's page.
- **Missing details.** Some fighters have no date of birth, reach or stance; these show as a dash or "Unknown".
- **Cancelled events** are not listed, and cancelled bouts are left off fight cards.
- One fight (a split decision) has no winner recorded at the source and is shown as "Unknown".

This is a personal, non-commercial learning project and is not affiliated with any organisation.
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------------------------- main


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    orgs = sidebar(d.parse_orgs(st.query_params.get("orgs")))
    view = st.query_params.get("view", "events")
    pages = {"events": page_events, "event": page_event, "fighters": page_fighters, "fighter": page_fighter,
             "fight": page_fight}
    if view == "about":
        page_about()
    else:
        pages.get(view, page_events)(orgs)
    footer()


main()
