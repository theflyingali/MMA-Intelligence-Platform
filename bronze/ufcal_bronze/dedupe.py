"""Latest-fetch-wins ordering. Pure functions; the Spark layer mirrors the same ordering.

Order: `fetched_at`, then the file's modification time, then the file path. The last two break
ties between same-second re-fetches (e.g. `123.json` and `123__081502Z.json`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class Versioned:
    key: int
    fetched_at: datetime
    modified_at: datetime
    source_file: str
    value: Any = None


def recency(v: Versioned) -> tuple[datetime, datetime, str]:
    return (v.fetched_at, v.modified_at, v.source_file)


def latest_wins(items: Iterable[Versioned]) -> dict[int, Versioned]:
    """One item per key: the most recent version."""
    best: dict[int, Versioned] = {}
    for item in items:
        current = best.get(item.key)
        if current is None or recency(item) > recency(current):
            best[item.key] = item
    return best


def replaces(source: Versioned, target: Versioned) -> bool:
    """MERGE rule: the incoming row replaces the stored one unless it is strictly older.

    `>=` makes reprocessing the same file a no-op update rather than a conflict.
    """
    return recency(source) >= recency(target)
