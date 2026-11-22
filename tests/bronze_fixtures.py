"""Synthetic landing files shaped like the real UFCalendar envelopes (no real API data is committed)."""

from __future__ import annotations

import json
from typing import Any


def envelope(response: dict[str, Any], fetched_at: str = "2026-10-30T08:15:57Z",
             status: int = 200, url: str = "https://api.ufcalendar.com/v1/x") -> str:
    return json.dumps({"request_url": url, "fetched_at": fetched_at, "http_status": status, "response": response})


def bout(fight_id: int, a: int, b: int, status: str = "completed") -> dict[str, Any]:
    return {"id": fight_id, "status": status, "fighter_a": {"id": a, "slug": f"f{a}"},
            "fighter_b": {"id": b, "slug": f"f{b}"}, "result": {"winner_fighter_id": a, "method": "KO/TKO"}}


def event_resp(event_id: int = 10, org: str = "ufc", card: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"data": {"id": event_id, "slug": f"ev-{event_id}", "org": org, "title": "T",
                     "starts_at": "2026-10-17T21:00:00.000Z", "status": "completed",
                     "card": card if card is not None else [bout(100, 1, 2), bout(101, 3, 4, "cancelled")]},
            "meta": {}}


def odds_resp(event_id: int = 10, org: str = "rizin") -> dict[str, Any]:
    return {"data": {"event": {"id": event_id, "slug": f"ev-{event_id}", "org": org,
                               "starts_at": "2026-10-17T21:00:00.000Z"},
                     "fights": [{"fight_id": 100, "consensus": {}}]},
            "meta": {"priced": 1}}


def rounds_resp(fight_id: int = 100) -> dict[str, Any]:
    return {"data": [{"round_number": 1, "fighter_id": 1, "knockdowns": 0},
                     {"round_number": 1, "fighter_id": 2, "knockdowns": 1}],
            "meta": {"fight_id": fight_id}}


def fighter_resp(fighter_id: int = 1) -> dict[str, Any]:
    return {"data": {"id": fighter_id, "slug": f"f{fighter_id}", "name": "N", "stats": {"slpm": "3.1"}}, "meta": {}}


def list_resp(*events: tuple[int, str]) -> dict[str, Any]:
    return {"data": [{"id": i, "slug": f"ev-{i}", "org": org, "starts_at": "2026-10-17T21:00:00.000Z"}
                     for i, org in events],
            "meta": {"pagination": {"has_more": False, "next_cursor": None, "limit": 10}}}
