"""Parse one landed file into bronze rows. Pure functions, no I/O.

A file is either parsed into rows or rejected with a reason; rejected files are logged and never
reach bronze, so a truncated or error file cannot overwrite a good row.

Schema drift: the payload is kept as raw JSON text. Only the natural key and a few convenience
fields are read, and missing optional fields become None. A fingerprint of the payload's key
paths makes drift visible without breaking the load.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

FIELDS = ("key", "fetched_at", "http_status", "request_url", "payload",
          "org", "slug", "starts_at", "fingerprint")


@dataclass(frozen=True)
class BronzeRow:
    key: int
    fetched_at: str  # canonical YYYY-MM-DDTHH:MM:SSZ
    http_status: int
    request_url: str | None
    payload: str  # the API response, as JSON text
    org: str | None
    slug: str | None
    starts_at: str | None
    fingerprint: str

    def as_tuple(self) -> tuple[Any, ...]:
        return tuple(getattr(self, f) for f in FIELDS)


@dataclass(frozen=True)
class Parsed:
    rows: tuple[BronzeRow, ...] = ()
    reject: str | None = None


def canonical_ts(value: Any) -> str | None:
    """ISO timestamp (with Z, offset or fractional seconds) as YYYY-MM-DDTHH:MM:SSZ in UTC."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key_paths(obj: Any, prefix: str, depth: int, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            if depth > 1:
                _key_paths(v, p, depth - 1, out)
    elif isinstance(obj, list):
        for item in obj[:200]:
            _key_paths(item, prefix + "[]", depth, out)


# Key paths are compared this many levels down. Fighters are depth 1 because `records` is keyed by
# record type (amateur_mma, pro_mma, ufc, ...): those keys are data, and at depth 2 they gave 39
# fingerprints across 192 fighters, which would drown any real drift signal.
FINGERPRINT_DEPTH = {"fighter": 1}


def fingerprint(data: Any, depth: int = 2) -> str:
    """Short hash of the key paths in `data` down to `depth` levels (lists are merged)."""
    paths: set[str] = set()
    _key_paths(data, "", depth, paths)
    return hashlib.md5("|".join(sorted(paths)).encode("utf-8")).hexdigest()[:12]


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _get(obj: Any, *path: str) -> Any:
    for p in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def parse_envelope(endpoint: str, text: str | None, name_id: int | None = None) -> Parsed:
    """Rows for one landed file, or a rejection reason.

    `name_id` is the numeric id from the file name, used only when the payload lacks its own id.
    """
    if text is None or not text.strip():
        return Parsed(reject="empty")
    try:
        env = json.loads(text)
    except ValueError:
        return Parsed(reject="invalid_json")  # typically a partially written file
    if not isinstance(env, dict):
        return Parsed(reject="not_object")
    if "response" not in env or "fetched_at" not in env:
        return Parsed(reject="missing_envelope")
    fetched_at = canonical_ts(env.get("fetched_at"))
    if fetched_at is None:
        return Parsed(reject="bad_fetched_at")
    status = env.get("http_status")
    if status != 200:
        return Parsed(reject="non_200")
    resp = env["response"]
    if not isinstance(resp, dict):
        return Parsed(reject="bad_response")
    url = env.get("request_url") if isinstance(env.get("request_url"), str) else None

    def row(key: int, payload: Any, fp_source: Any, org: Any = None, slug: Any = None,
            starts_at: Any = None) -> BronzeRow:
        return BronzeRow(
            key=key, fetched_at=fetched_at, http_status=200, request_url=url,
            payload=_dumps(payload), org=org if isinstance(org, str) else None,
            slug=slug if isinstance(slug, str) else None,
            starts_at=starts_at if isinstance(starts_at, str) else None,
            fingerprint=fingerprint(fp_source, FINGERPRINT_DEPTH.get(endpoint, 2)),
        )

    data = resp.get("data")

    if endpoint == "events_list":
        if not isinstance(data, list):
            return Parsed(reject="bad_data")
        rows = []
        for item in data:
            key = _as_int(item.get("id")) if isinstance(item, dict) else None
            if key is None:
                return Parsed(reject="missing_key")
            rows.append(row(key, item, item, item.get("org"), item.get("slug"), item.get("starts_at")))
        return Parsed(rows=tuple(rows))

    if endpoint == "event":
        if not isinstance(data, dict):
            return Parsed(reject="bad_data")
        key = _as_int(data.get("id"))
        key = name_id if key is None else key
        if key is None:
            return Parsed(reject="missing_key")
        return Parsed(rows=(row(key, resp, data, data.get("org"), data.get("slug"), data.get("starts_at")),))

    if endpoint == "event_odds":
        if not isinstance(data, dict):
            return Parsed(reject="bad_data")
        ev = data.get("event")
        key = _as_int(_get(ev, "id"))
        key = name_id if key is None else key
        if key is None:
            return Parsed(reject="missing_key")
        return Parsed(rows=(row(key, resp, data, _get(ev, "org"), _get(ev, "slug"), _get(ev, "starts_at")),))

    if endpoint == "fight_rounds":
        if not isinstance(data, list):
            return Parsed(reject="bad_data")
        key = _as_int(_get(resp, "meta", "fight_id"))
        key = name_id if key is None else key
        if key is None:
            return Parsed(reject="missing_key")
        return Parsed(rows=(row(key, resp, data),))

    if endpoint == "fighter":
        if not isinstance(data, dict):
            return Parsed(reject="bad_data")
        key = _as_int(data.get("id"))
        key = name_id if key is None else key
        if key is None:
            return Parsed(reject="missing_key")
        return Parsed(rows=(row(key, resp, data, None, data.get("slug")),))

    raise ValueError(f"unknown endpoint: {endpoint!r}")


def card_ids(event_payload: str | dict[str, Any]) -> tuple[set[int], set[int]]:
    """(fight ids, fighter ids) on an event's card, for choosing a coherent subset.

    Fight ids cover every bout (odds exist for all); fighter ids skip cancelled bouts, as the
    ingestion does.
    """
    resp = json.loads(event_payload) if isinstance(event_payload, str) else event_payload
    card = _get(resp, "data", "card")
    fights: set[int] = set()
    fighters: set[int] = set()
    for bout in card if isinstance(card, list) else []:
        if not isinstance(bout, dict):
            continue
        fid = _as_int(bout.get("id"))
        if fid is not None:
            fights.add(fid)
        if bout.get("status") == "cancelled":
            continue
        for corner in ("fighter_a", "fighter_b"):
            pid = _as_int(_get(bout, corner, "id"))
            if pid is not None:
                fighters.add(pid)
    return fights, fighters
