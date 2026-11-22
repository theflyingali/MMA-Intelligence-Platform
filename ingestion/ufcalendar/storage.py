"""Where landed files go: the Unity Catalog volume, mirrored to data/ locally."""

from __future__ import annotations

import io
import json
import configparser
import logging
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .client import ApiResponse

log = logging.getLogger("ufcalendar.storage")

MANIFEST = "_manifest.json"


def workspace_client(profile: str):
    """Databricks client: the CLI profile if it exists here (laptop), else DATABRICKS_HOST/TOKEN (cloud)."""
    from databricks.sdk import WorkspaceClient

    cfg = configparser.ConfigParser()
    cfg.read(Path(os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg")).expanduser())
    if cfg.has_section(profile):
        return WorkspaceClient(profile=profile)
    if os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"):
        return WorkspaceClient()
    raise RuntimeError(
        f"No Databricks CLI profile '{profile}' and DATABRICKS_HOST/DATABRICKS_TOKEN are not both set."
    )


def envelope(resp: ApiResponse) -> bytes:
    return json.dumps(
        {
            "request_url": resp.url,
            "fetched_at": resp.fetched_at,
            "http_status": resp.status,
            "response": resp.body,
        },
        ensure_ascii=False,
    ).encode("utf-8")


def landing_relpath(endpoint: str, fetched_at: str, name: str | int) -> str:
    return f"{endpoint}/ingest_date={fetched_at[:10]}/{name}.json"


def suffixed(relpath: str, now: datetime | None = None) -> str:
    """`a/b/123.json` -> `a/b/123__081502Z.json`, used when a same-day file already exists."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%H%M%SZ")
    p = PurePosixPath(relpath)
    return str(p.with_name(f"{p.stem}__{stamp}{p.suffix}"))


LOCK = "_lock.json"
LOCK_STALE_HOURS = 12


class RunLocked(Exception):
    pass


def acquire_lock(sink: Sink, run_id: str, now: datetime, break_lock: bool = False) -> None:
    """Stop two runs (laptop and job, or two jobs) from writing the manifest at once.

    A lock is held while it has no `released_at` and is younger than LOCK_STALE_HOURS,
    so a crashed run blocks others for at most that long.
    """
    raw = sink.read(LOCK)
    if raw and not break_lock:
        held = json.loads(raw)
        acquired = datetime.fromisoformat(held["acquired_at"].replace("Z", "+00:00"))
        age_h = (now - acquired).total_seconds() / 3600
        if not held.get("released_at") and age_h < LOCK_STALE_HOURS:
            raise RunLocked(
                f"run {held['run_id']} has held the lock since {held['acquired_at']}; "
                f"wait for it to finish, or pass --break-lock if it crashed"
            )
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    sink.write(LOCK, json.dumps({"run_id": run_id, "acquired_at": stamp}).encode("utf-8"))


def release_lock(sink: Sink, run_id: str, now: datetime) -> None:
    raw = sink.read(LOCK)
    held = json.loads(raw) if raw else {}
    if held.get("run_id") == run_id:
        held["released_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sink.write(LOCK, json.dumps(held).encode("utf-8"))


class Sink(Protocol):
    def write_new(self, relpath: str, content: bytes) -> str: ...
    def write(self, relpath: str, content: bytes) -> str: ...
    def read(self, relpath: str) -> bytes | None: ...


class LocalSink:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write_new(self, relpath: str, content: bytes) -> str:
        if (self.root / relpath).exists():
            relpath = suffixed(relpath)
        return self.write(relpath, content)

    def write(self, relpath: str, content: bytes) -> str:
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    def read(self, relpath: str) -> bytes | None:
        target = self.root / relpath
        return target.read_bytes() if target.exists() else None


class VolumeSink:
    """Uploads to the volume with the Databricks SDK; keeps a local mirror of every file."""

    def __init__(self, root: str, workspace: Any, mirror: LocalSink) -> None:
        self.root = root.rstrip("/")
        self.w = workspace
        self.mirror = mirror
        self._dirs: set[str] = set()

    def _full(self, relpath: str) -> str:
        return f"{self.root}/{relpath}"

    def _ensure_dir(self, relpath: str) -> None:
        # Uploads fail when the parent folder is missing (see docs/learning-log.md).
        parent = str(PurePosixPath(self._full(relpath)).parent)
        if parent not in self._dirs:
            self.w.files.create_directory(parent)
            self._dirs.add(parent)

    def write_new(self, relpath: str, content: bytes) -> str:
        from databricks.sdk.errors import AlreadyExists, ResourceAlreadyExists, ResourceConflict

        self._ensure_dir(relpath)
        try:
            self.w.files.upload(self._full(relpath), io.BytesIO(content), overwrite=False)
        except (AlreadyExists, ResourceAlreadyExists, ResourceConflict):
            relpath = suffixed(relpath)
            log.info("file exists, writing %s instead", relpath)
            self.w.files.upload(self._full(relpath), io.BytesIO(content), overwrite=False)
        self.mirror.write(relpath, content)
        return self._full(relpath)

    def write(self, relpath: str, content: bytes) -> str:
        self.mirror.write(relpath, content)
        self._ensure_dir(relpath)
        self.w.files.upload(self._full(relpath), io.BytesIO(content), overwrite=True)
        return self._full(relpath)

    def read(self, relpath: str) -> bytes | None:
        from databricks.sdk.errors import NotFound

        try:
            return self.w.files.download(self._full(relpath)).contents.read()
        except NotFound:
            return None
