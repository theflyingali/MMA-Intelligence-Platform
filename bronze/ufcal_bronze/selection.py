"""Which landing files to load this run. Pure functions: listings in, selections out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from .paths import ENDPOINTS, parse_landing_path


@dataclass(frozen=True)
class ListedFile:
    path: str
    size: int
    modified_at: datetime  # timezone-aware, UTC


def epoch_ms(dt: datetime) -> int:
    return round(dt.timestamp() * 1000)


def from_epoch(seconds: float) -> datetime:
    """UTC datetime from epoch seconds, rounded to the millisecond (file systems report ms)."""
    return datetime.fromtimestamp(round(seconds * 1000) / 1000, tz=timezone.utc)


def file_key(f: ListedFile) -> tuple[str, int]:
    """Identity of one version of a file, as stored in the ingest log: path and mtime in epoch ms.

    Epoch milliseconds, not a datetime string, so no time zone handling can make the same file
    look new on the next run.
    """
    return (f.path, epoch_ms(f.modified_at))


def eligible(files: Iterable[ListedFile], root: str, now: datetime, quiet_minutes: int) -> list[ListedFile]:
    """Data files that are safe to read now.

    Drops non-data paths (manifest, lock, runs), empty files, and files modified within the quiet
    window (a writer may still be uploading them; they are picked up on a later run).
    """
    cutoff = now - timedelta(minutes=quiet_minutes)
    out = [
        f for f in files
        if parse_landing_path(f.path, root) is not None
        and f.size > 0
        and f.modified_at <= cutoff
    ]
    return sorted(out, key=lambda f: f.path)


def name_id(f: ListedFile, root: str) -> int | None:
    lf = parse_landing_path(f.path, root)
    return lf.name_id if lf else None


def earliest_event_ids(events: list[ListedFile], root: str, n: int) -> list[int]:
    """The n event ids whose first-landed file sorts earliest (ingest_date, then path).

    Independent of what has already been loaded, so a subset is stable across reruns.
    """
    ids: list[int] = []
    for f in sorted(events, key=lambda f: f.path):  # `ingest_date=` sorts before the name
        i = name_id(f, root)
        if i is not None and i not in ids:
            ids.append(i)
            if len(ids) == n:
                break
    return ids


def plan_run(
    listings: dict[str, list[ListedFile]],
    loaded: dict[str, set[tuple[str, int]]],
    *,
    root: str,
    now: datetime,
    quiet_minutes: int = 10,
    max_events: int = 0,
    max_files: int = 0,
    endpoints: tuple[str, ...] = ENDPOINTS,
    card_ids_for: Callable[[list[ListedFile]], tuple[set[int], set[int]]] | None = None,
) -> dict[str, list[ListedFile]]:
    """Files to load per endpoint: eligible, not yet loaded, and within the subset and file caps.

    `max_events` > 0 restricts events, odds, rounds and fighters to the cards of the N earliest
    landed events. `events_list` pages are never filtered (a page mixes many events, so loading
    part of one would wrongly mark the whole file as done). `max_files` caps each endpoint.
    `card_ids_for` reads event files and returns (fight ids, fighter ids); it is only called when
    `max_events` > 0.
    """
    ok = {ep: eligible(listings.get(ep, []), root, now, quiet_minutes) for ep in ENDPOINTS}
    wanted: dict[str, set[int] | None] = {ep: None for ep in ENDPOINTS}

    if max_events > 0:
        if card_ids_for is None:
            raise ValueError("card_ids_for is required when max_events > 0")
        event_ids = earliest_event_ids(ok["event"], root, max_events)
        chosen = [f for f in ok["event"] if name_id(f, root) in set(event_ids)]
        fight_ids, fighter_ids = card_ids_for(chosen)
        wanted.update(
            event=set(event_ids), event_odds=set(event_ids),
            fight_rounds=fight_ids, fighter=fighter_ids,
        )

    plan: dict[str, list[ListedFile]] = {}
    for ep in endpoints:
        ids = wanted[ep]
        files = [
            f for f in ok[ep]
            if (ids is None or name_id(f, root) in ids) and file_key(f) not in loaded.get(ep, set())
        ]
        plan[ep] = files[:max_files] if max_files > 0 else files
    return plan
