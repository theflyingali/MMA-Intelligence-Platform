"""Incremental logic: decide what needs fetching. Pure functions, no I/O."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .manifest import Manifest

# Bout statuses that have stats; cancelled/announced/confirmed bouts do not.
PLAYED = {"completed", "no_contest"}


@dataclass
class Task:
    endpoint: str
    key: int
    path: str
    etag: str | None = None
    event_id: int | None = None
    fight_state: dict[str, Any] | None = field(default=None)


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def in_refresh_window(starts_at: str, now: datetime, refresh_days: int) -> bool:
    return parse_ts(starts_at) >= now - timedelta(days=refresh_days)


def event_fetch_reason(
    event: dict[str, Any],
    manifest: Manifest,
    now: datetime,
    refresh_days: int,
    min_refetch_hours: float,
) -> str | None:
    """'new', 'refresh' or None for one event from the list endpoint."""
    entry = manifest.get("event", event["id"])
    if entry is None:
        return "new"
    if not in_refresh_window(event["starts_at"], now, refresh_days):
        return None
    if now - parse_ts(entry["fetched_at"]) >= timedelta(hours=min_refetch_hours):
        return "refresh"
    return None


def event_task(event_id: int, manifest: Manifest) -> Task:
    entry = manifest.get("event", event_id) or {}
    return Task("event", event_id, f"/events/{event_id}", etag=entry.get("etag"), event_id=event_id)


def fight_state(fight: dict[str, Any]) -> dict[str, Any]:
    """The parts of a bout that, when they change, mean its round stats may have changed."""
    result = fight.get("result") or {}
    return {
        "status": fight.get("status"),
        "winner_fighter_id": result.get("winner_fighter_id"),
        "method": result.get("method"),
        "round": result.get("round"),
        "time": result.get("time"),
    }


def summarise_card(card: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[int]]:
    """Per-fight state and the ordered unique fighter ids on non-cancelled bouts."""
    fights = {str(f["id"]): fight_state(f) for f in card}
    fighter_ids: list[int] = []
    for f in card:
        if f.get("status") == "cancelled":
            continue
        for corner in ("fighter_a", "fighter_b"):
            fid = (f.get(corner) or {}).get("id")
            if fid is not None and fid not in fighter_ids:
                fighter_ids.append(fid)
    return fights, fighter_ids


def pending_children(event_id: int | str, manifest: Manifest) -> list[Task]:
    """Odds, rounds and fighter fetches still owed for an event already in the manifest.

    Works from the manifest alone, so a run that stopped mid-event resumes without
    re-fetching the event itself.
    """
    event = manifest.get("event", event_id)
    if event is None or event.get("http_status", 200) != 200:
        return []
    eid = int(event_id)
    event_fetched = parse_ts(event["fetched_at"])
    tasks: list[Task] = []

    odds = manifest.get("event_odds", eid)
    if odds is None or parse_ts(odds["fetched_at"]) < event_fetched:
        tasks.append(Task("event_odds", eid, f"/events/{eid}/odds",
                          etag=(odds or {}).get("etag"), event_id=eid))

    for fight_id, state in event.get("fights", {}).items():
        if state.get("status") not in PLAYED:
            continue
        rounds = manifest.get("fight_rounds", fight_id)
        if rounds is None or rounds.get("fight_state") != state:
            tasks.append(Task("fight_rounds", int(fight_id), f"/fights/{fight_id}/rounds",
                              etag=(rounds or {}).get("etag"), event_id=eid, fight_state=state))

    starts_at = parse_ts(event["starts_at"])
    completed = event.get("status") == "completed"
    for fighter_id in event.get("fighter_ids", []):
        fighter = manifest.get("fighter", fighter_id)
        stale = fighter is not None and completed and parse_ts(fighter["fetched_at"]) < starts_at
        if fighter is None or stale:
            tasks.append(Task("fighter", int(fighter_id), f"/fighters/{fighter_id}",
                              etag=(fighter or {}).get("etag"), event_id=eid))
    return tasks


def events_newest_first(manifest: Manifest) -> list[str]:
    entries = manifest.entries("event")
    return sorted(entries, key=lambda k: entries[k].get("starts_at") or "", reverse=True)


def page_is_exhausted(
    events: list[dict[str, Any]], manifest: Manifest, now: datetime, refresh_days: int
) -> bool:
    """True when every event on a list page is known and outside the refresh window.

    Only safe to act on once the org's full history has been listed at least once;
    otherwise older pages may still hold events never fetched.
    """
    return all(
        manifest.get("event", e["id"]) is not None
        and not in_refresh_window(e["starts_at"], now, refresh_days)
        for e in events
    )


def estimate_requests(
    *,
    list_pages: int,
    new_events: int,
    refresh_events: int,
    pending: list[Task],
    avg_fights: int,
) -> dict[str, int]:
    """Request count per endpoint. New-event rounds and fighters are estimates (fighters an upper bound)."""
    counts: Counter[str] = Counter(t.endpoint for t in pending)
    counts["events_list"] += list_pages
    counts["event"] += new_events + refresh_events
    counts["event_odds"] += new_events + refresh_events
    counts["fight_rounds"] += new_events * avg_fights
    counts["fighter"] += new_events * avg_fights * 2
    return {k: v for k, v in counts.items() if v}
