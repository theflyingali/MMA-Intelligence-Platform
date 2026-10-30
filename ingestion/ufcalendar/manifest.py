"""The ingestion manifest: what has been fetched, when, and with which ETag.

Shape (keys are string ids):
    {"version": 1, "updated_at": "...",
     "event":        {"<id>": {"fetched_at", "etag", "path", "org", "slug", "starts_at", "status",
                               "fights": {"<fight_id>": <fight_state>}, "fighter_ids": [...]}},
     "event_odds":   {"<event_id>": {"fetched_at", "etag", "path", "http_status"}},
     "fight_rounds": {"<fight_id>": {"fetched_at", "etag", "path", "http_status", "event_id", "fight_state"}},
     "fighter":      {"<id>": {"fetched_at", "etag", "path", "http_status"}},
     "listing":      {"<org>": {"history_complete": bool, "listed_at"}}}

`history_complete` is set once paging has reached the oldest event for an org; until then a
run never stops paging early, so an interrupted backfill resumes where it left off.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

VERSION = 1
ENDPOINTS = ("event", "event_odds", "fight_rounds", "fighter")


@dataclass
class Manifest:
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data.setdefault("version", VERSION)
        self.data.setdefault("updated_at", None)
        for ep in ENDPOINTS:
            self.data.setdefault(ep, {})
        self.data.setdefault("listing", {})

    @classmethod
    def from_json(cls, text: str | bytes | None) -> Manifest:
        if not text:
            return cls()
        data = json.loads(text)
        if data.get("version") != VERSION:
            raise ValueError(f"Unsupported manifest version: {data.get('version')!r}")
        return cls(data)

    def to_json(self, updated_at: str) -> str:
        self.data["updated_at"] = updated_at
        return json.dumps(self.data, indent=1, sort_keys=True)

    def get(self, endpoint: str, key: int | str) -> dict[str, Any] | None:
        return self.data[endpoint].get(str(key))

    def record(self, endpoint: str, key: int | str, **fields: Any) -> dict[str, Any]:
        """Create or update an entry, merging the given fields."""
        entry = self.data[endpoint].setdefault(str(key), {})
        entry.update(fields)
        return entry

    def entries(self, endpoint: str) -> dict[str, dict[str, Any]]:
        return self.data[endpoint]

    def listing(self, org: str) -> dict[str, Any]:
        return self.data["listing"].setdefault(org, {"history_complete": False})

    def counts(self) -> dict[str, int]:
        return {ep: len(self.data[ep]) for ep in ENDPOINTS}
