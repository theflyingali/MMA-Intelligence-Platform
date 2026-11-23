"""Landing-path rules: which files are data, and what a file name says about its content.

Pure functions, no I/O. Layout (see docs/ingestion-design.md):
    {root}/{endpoint}/ingest_date=YYYY-MM-DD/{id}.json
    {root}/{endpoint}/ingest_date=YYYY-MM-DD/{id}__HHMMSSZ.json   (same-day re-fetch)
Anything else under the root (`_manifest.json`, `_lock.json`, `_runs/`) is never data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ENDPOINTS = ("events_list", "event", "event_odds", "fight_rounds", "fighter")

_PARTITION = re.compile(r"^ingest_date=(\d{4}-\d{2}-\d{2})$")
_NAME = re.compile(r"^(?P<stem>[^/]+?)(?:__\d{6}Z)?\.json$")


@dataclass(frozen=True)
class LandingFile:
    path: str
    endpoint: str
    ingest_date: str
    name_id: int | None  # numeric id from the file name; None for events_list pages


def normalise(path: str) -> str:
    """Spark reports `dbfs:/Volumes/...` (Databricks) or `file:/...` (local); the code uses plain paths."""
    for scheme in ("dbfs:", "file:"):
        if path.startswith(scheme):
            return path[len(scheme):]
    return path


def name_id_from_filename(path: str) -> int | None:
    m = _NAME.match(path.rsplit("/", 1)[-1])
    if not m:
        return None
    stem = m.group("stem")
    return int(stem) if stem.isdigit() else None


def parse_landing_path(path: str, root: str) -> LandingFile | None:
    """A LandingFile when `path` is a data file under `root`, else None (manifest, lock, runs, strays)."""
    path = normalise(path)
    prefix = root.rstrip("/") + "/"
    if not path.startswith(prefix):
        return None
    parts = path[len(prefix):].split("/")
    if len(parts) != 3:
        return None
    endpoint, partition, filename = parts
    if endpoint not in ENDPOINTS:
        return None
    pm = _PARTITION.match(partition)
    nm = _NAME.match(filename)
    if not pm or not nm or nm.group("stem").startswith("_"):
        return None
    return LandingFile(path, endpoint, pm.group(1), name_id_from_filename(filename))
