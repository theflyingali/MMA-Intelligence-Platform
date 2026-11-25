"""Pure display rules for the dashboard: no Streamlit, no I/O, so they are unit tested.

Corner rules (silver/README.md):
1. Where `corner_reliable` is false, corner A is often just the listed winner: never show corner labels or
   corner order; show winner and loser only.
2. Where it is true, corner order may be shown, but corner win rate is never presented as a stat.
Null handling: every formatter accepts None, pandas NA or NaN and returns a readable placeholder.
"""

from __future__ import annotations

import html
import math
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode

import pandas as pd

DASH = "–"  # en dash, used as the empty-cell placeholder
UFCALENDAR_URL = "https://www.ufcalendar.com"

ORG_LABELS: dict[str, str] = {
    "ufc": "UFC",
    "dwcs": "Contender Series",
    "pfl": "PFL",
    "oktagon": "OKTAGON",
    "rizin": "RIZIN",
}
ORG_KEYS: tuple[str, ...] = tuple(ORG_LABELS)

METHOD_LABELS: dict[str, str] = {
    "ko_tko": "KO/TKO",
    "submission": "Submission",
    "technical_submission": "Technical submission",
    "decision_unanimous": "Decision (unanimous)",
    "decision_split": "Decision (split)",
    "decision_majority": "Decision (majority)",
    "decision": "Decision",
    "dq": "Disqualification",
    "no_contest": "No contest",
    "draw": "Draw",
}
METHOD_GROUPS: dict[str, str] = {
    "ko_tko": "KO/TKO",
    "submission": "Submission",
    "technical_submission": "Submission",
    "decision_unanimous": "Decision",
    "decision_split": "Decision",
    "decision_majority": "Decision",
    "decision": "Decision",
}
_DECISION_DETAILS = {"unanimous", "split", "majority"}


def missing(value: Any) -> bool:
    """True for None, pandas NA/NaT, NaN and empty strings."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def truthy(value: Any) -> bool:
    """True only for a real true value; null counts as false."""
    return not missing(value) and bool(value)


def esc(value: Any, placeholder: str = DASH) -> str:
    """HTML-escape a value for display; source text is untrusted."""
    return placeholder if missing(value) else html.escape(str(value))


def href(view: str, orgs: Sequence[str] | None = None, **params: Any) -> str:
    """Relative link inside the app. Selected organisations travel with every link."""
    query: dict[str, Any] = {"view": view}
    query.update({k: v for k, v in params.items() if not missing(v)})
    if orgs is not None and tuple(orgs) != ORG_KEYS:
        query["orgs"] = ",".join(orgs)
    return "?" + urlencode(query)


def link(text: Any, url: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}" target="_self">{esc(text)}</a>'


def html_table(headers: Sequence[str] | None, rows: Iterable[Sequence[str]], css_class: str = "t") -> str:
    """Static table (no download or copy toolbar). Cells must already be escaped HTML. No headers, no thead."""
    head = "<thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr></thead>" if headers else ""
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="tw"><table class="{css_class}">{head}<tbody>{body}</tbody></table></div>'


def parse_orgs(raw: str | None) -> list[str]:
    """Organisations from the URL; unknown keys dropped; empty or absent means all."""
    if not raw:
        return list(ORG_KEYS)
    keys = [k for k in (p.strip().lower() for p in raw.split(",")) if k in ORG_LABELS]
    return keys or list(ORG_KEYS)


def org_key(org: Any, is_contender_series: Any) -> str:
    """Contender Series is shown apart from official UFC events."""
    if truthy(is_contender_series):
        return "dwcs"
    return "" if missing(org) else str(org).lower()


def org_label(key: str) -> str:
    return ORG_LABELS.get(key, key.upper() if key else DASH)


def tidy_weight_class(value: Any) -> str:
    """'Light heavyweight' -> 'Light Heavyweight'; words with digits ('108lb', '80kg') unchanged."""
    if missing(value):
        return DASH
    words = str(value).split()
    return " ".join(w[:1].upper() + w[1:] if w[:1].isalpha() and w[:1].islower() else w for w in words)


def method_label(method_normalized: Any, finish_detail: Any = None, method: Any = None) -> str:
    """'KO/TKO (Punches)', 'Decision (split)', 'Submission (Rear-Naked Choke)'."""
    if missing(method_normalized):
        return DASH if missing(method) else str(method)
    key = str(method_normalized)
    label = METHOD_LABELS.get(key, key.replace("_", " ").capitalize())
    if missing(finish_detail):
        return label
    detail = str(finish_detail).strip()
    if key in {"decision", "draw"}:
        # Plain 'decision' and 'draw' gain the kind; the other decision labels already carry it.
        return f"{label} ({detail.lower()})" if detail.lower() in _DECISION_DETAILS else label
    if key.startswith("decision") or detail.lower() == label.lower():
        return label
    return f"{label} ({detail})"


def round_time(end_round: Any, end_time: Any) -> str:
    if missing(end_round):
        return DASH
    return f"R{int(end_round)} {end_time}" if not missing(end_time) else f"R{int(end_round)}"


def fighter_result(outcome: Any, winner_id: Any, fighter_id: int) -> str:
    """Result from one fighter's side, without using corners."""
    o = "" if missing(outcome) else str(outcome)
    if o in {"a_win", "b_win"}:
        if missing(winner_id):
            return "Unknown"
        return "Win" if int(winner_id) == int(fighter_id) else "Loss"
    return {"draw": "Draw", "no_contest": "No contest", "cancelled": "Cancelled"}.get(o, "Unknown")


def opponent(row: Mapping[str, Any], fighter_id: int) -> tuple[Any, Any]:
    if not missing(row.get("fighter_a_id")) and int(row["fighter_a_id"]) == int(fighter_id):
        return row.get("fighter_b_id"), row.get("fighter_b_name")
    return row.get("fighter_a_id"), row.get("fighter_a_name")


@dataclass(frozen=True)
class Headline:
    """How to show the two fighters of a bout. `connector` is 'def.' or 'vs'."""

    first_id: Any
    first_name: Any
    connector: str
    second_id: Any
    second_name: Any
    note: str  # '', 'Draw', 'No contest', 'Result unknown', 'Cancelled'
    corner_order: bool  # True only when the order shown is the real corner order


def bout_headline(row: Mapping[str, Any]) -> Headline:
    """Winner first for decided bouts. Otherwise the listed order, flagged as corner order only when reliable."""
    a = (row.get("fighter_a_id"), row.get("fighter_a_name"))
    b = (row.get("fighter_b_id"), row.get("fighter_b_name"))
    outcome = "" if missing(row.get("outcome")) else str(row["outcome"])
    winner = row.get("winner_fighter_id")
    reliable = truthy(row.get("corner_reliable"))
    if outcome in {"a_win", "b_win"} and not missing(winner):
        if not missing(b[0]) and int(winner) == int(b[0]):
            a, b = b, a
        return Headline(a[0], a[1], "def.", b[0], b[1], "", False)
    note = {"draw": "Draw", "no_contest": "No contest", "cancelled": "Cancelled"}.get(outcome, "Result unknown")
    return Headline(a[0], a[1], "vs", b[0], b[1], note, reliable)


def order_note(headline: Headline, corner_reliable: Any) -> str:
    """Explain the order the two fighters are shown in, without ever labelling an unreliable corner."""
    if headline.connector == "def.":
        return "Winner listed first."
    if headline.corner_order:
        return ("Listed in corner order (corner A first). Corner A is often the favourite or higher-ranked fighter, "
                "so it says nothing about performance.")
    return ("Listed in the source's order. Corners are not shown: in this part of the data the source lists the "
            "winner first, so the corner is not a real corner.")


def fmt_record(wins: Any, losses: Any, draws: Any = None, no_contests: Any = None) -> str:
    """'29-1-0', plus ' (2 NC)' when there are no contests."""
    if all(missing(v) for v in (wins, losses, draws)):
        return DASH
    w, l, d = (0 if missing(v) else int(v) for v in (wins, losses, draws))
    text = f"{w}-{l}-{d}"
    if not missing(no_contests) and int(no_contests) > 0:
        text += f" ({int(no_contests)} NC)"
    return text


def age_years(dob: Any, today: date) -> int | None:
    if missing(dob):
        return None
    if isinstance(dob, datetime):
        dob = dob.date()
    if not isinstance(dob, date):
        try:
            dob = pd.to_datetime(dob).date()
        except (TypeError, ValueError):
            return None
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years if 0 < years < 100 else None


def fmt_number(value: Any, digits: int = 2, suffix: str = "") -> str:
    return DASH if missing(value) else f"{float(value):.{digits}f}{suffix}"


def fmt_pct(fraction: Any) -> str:
    """Source stores accuracy and defence as fractions (0.58)."""
    return DASH if missing(fraction) else f"{float(fraction) * 100:.0f}%"


def fmt_cm(value: Any) -> str:
    return DASH if missing(value) else f"{float(value):.0f} cm"


def fmt_date(value: Any) -> str:
    if missing(value):
        return DASH
    ts = pd.Timestamp(value)
    return f"{ts.day} {ts.strftime('%b %Y')}"


def fmt_seconds(value: Any) -> str:
    if missing(value):
        return DASH
    s = int(value)
    return f"{s // 60}:{s % 60:02d}"


def landed_of(landed: Any, attempted: Any) -> str:
    if missing(landed):
        return DASH
    return f"{int(landed)} of {int(attempted)}" if not missing(attempted) else str(int(landed))


def dataset_summary(history: pd.DataFrame, fighter_id: int) -> dict[str, Any]:
    """Record and win/loss methods across the bouts in `history` (one fighter's rows from `bout`)."""
    results = [fighter_result(r["outcome"], r["winner_fighter_id"], fighter_id) for _, r in history.iterrows()]
    counts = {k: results.count(k) for k in ("Win", "Loss", "Draw", "No contest", "Unknown")}
    win_methods: dict[str, int] = {"KO/TKO": 0, "Submission": 0, "Decision": 0, "Other": 0}
    loss_methods: dict[str, int] = dict.fromkeys(win_methods, 0)
    for result, (_, row) in zip(results, history.iterrows()):
        if result not in {"Win", "Loss"}:
            continue
        mn = row.get("method_normalized")
        group = METHOD_GROUPS.get("" if missing(mn) else str(mn), "Other")
        (win_methods if result == "Win" else loss_methods)[group] += 1
    return {"counts": counts, "win_methods": win_methods, "loss_methods": loss_methods}


def normalise(text: Any) -> str:
    """Lower case without accents, for search ('Díaz' matches 'diaz')."""
    if missing(text):
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def search_fighters(index: pd.DataFrame, query: str, orgs: Sequence[str], limit: int = 50) -> pd.DataFrame:
    """Every query word must appear in the name or nickname. Fighters who fought in a selected org only."""
    words = normalise(query).split()
    if not words:
        return index.iloc[0:0]
    haystack = (index["name"].map(normalise) + " " + index["nickname"].map(normalise))
    mask = pd.Series(True, index=index.index)
    for w in words:
        mask &= haystack.str.contains(w, regex=False)
    selected = set(orgs)
    in_orgs = index["orgs"].map(lambda v: bool(selected & set(str(v).split(","))) if not missing(v) else False)
    found = index[mask & in_orgs].copy()
    # Exact name matches first, then the most active fighters.
    found["_exact"] = found["name"].map(normalise) == " ".join(words)
    found = found.sort_values(["_exact", "bouts"], ascending=[False, False])
    return found.drop(columns="_exact").head(limit)
