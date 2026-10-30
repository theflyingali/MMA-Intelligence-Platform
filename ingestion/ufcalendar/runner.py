"""Orchestration: events list -> event -> odds -> rounds -> fighters, with the manifest kept current."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .client import ApiError, ApiResponse, FatalApiError, StopRun
from .config import Settings
from .manifest import Manifest
from .planner import (
    Task,
    event_fetch_reason,
    event_task,
    events_newest_first,
    estimate_requests,
    in_refresh_window,
    iso,
    page_is_exhausted,
    parse_ts,
    pending_children,
    summarise_card,
)
from .storage import MANIFEST, Sink, envelope, landing_relpath

log = logging.getLogger("ufcalendar.run")

MAX_ERRORS_KEPT = 50


@dataclass
class Summary:
    run_id: str
    mode: str
    started_at: str
    finished_at: str | None = None
    stop_reason: str | None = None
    requests_used: int = 0
    budget: int = 0
    requests_by_endpoint: dict[str, int] = field(default_factory=dict)
    http_status_counts: dict[str, int] = field(default_factory=dict)
    files_written: int = 0
    files_by_endpoint: dict[str, int] = field(default_factory=dict)
    not_modified: int = 0
    not_found: int = 0
    errors: list[str] = field(default_factory=list)
    quota_remaining: int | None = None
    manifest_counts: dict[str, int] = field(default_factory=dict)
    estimate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Runner:
    def __init__(
        self,
        settings: Settings,
        client: Any,
        sink: Sink,
        manifest: Manifest,
        run_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.s = settings
        self.client = client
        self.sink = sink
        self.manifest = manifest
        self.now = now
        self.files: Counter[str] = Counter()
        self.not_modified = 0
        self.not_found = 0
        self.errors: list[str] = []
        self._saved_at_request = 0
        self.summary = Summary(
            run_id=run_id,
            mode="dry-run" if settings.dry_run else "ingest",
            started_at=iso(now()),
            budget=settings.budget,
        )

    # ---- entry point -------------------------------------------------------

    def run(self) -> Summary:
        try:
            if self.s.dry_run:
                self.summary.estimate = self._estimate()
            else:
                for org in self.s.orgs:
                    self._ingest_org(org)
                # Anything still owed for events not on this run's list pages (e.g. after a budget stop).
                for event_id in events_newest_first(self.manifest):
                    self._run_children(event_id)
            self.summary.stop_reason = "completed"
        except StopRun as exc:
            self.summary.stop_reason = f"stopped: {exc}"
            log.warning("stopping cleanly: %s", exc)
        except FatalApiError as exc:
            self.summary.stop_reason = f"fatal: {exc}"
            log.error("fatal API error, stopping: %s", exc)
        except ApiError as exc:  # events list failed after retries
            self.summary.stop_reason = f"error: {exc}"
            log.error("API error, stopping: %s", exc)
        except KeyboardInterrupt:
            self.summary.stop_reason = "interrupted"
            log.warning("interrupted, saving manifest")
        finally:
            if not self.s.dry_run:
                self.save_manifest()
            self._finish_summary()
        return self.summary

    # ---- ingest ------------------------------------------------------------

    def _ingest_org(self, org: str) -> None:
        listing = self.manifest.listing(org)
        cursor: str | None = None
        seen = 0
        page = 0
        while True:
            params: dict[str, Any] = {"org": org, "status": "completed", "limit": self.s.page_limit}
            if cursor:
                params["cursor"] = cursor
            resp = self.client.get("events_list", "/events", params=params)
            self._checkpoint()
            page += 1
            if resp.status != 200 or not isinstance(resp.body, dict):
                self._error(f"events_list {org} page {page}: HTTP {resp.status}")
                return
            stamp = resp.fetched_at[11:19].replace(":", "")
            self._land("events_list", resp, f"{org}_completed_{stamp}Z_p{page}")

            events = resp.body.get("data") or []
            if self.s.max_events:
                events = events[: self.s.max_events - seen]
            seen += len(events)
            for ev in events:
                reason = event_fetch_reason(ev, self.manifest, self.now(),
                                            self.s.refresh_days, self.s.min_refetch_hours)
                if reason:
                    log.info("event %s (%s) %s: %s", ev["id"], ev.get("slug"), ev.get("starts_at"), reason)
                    self._fetch_event(ev["id"])
                self._run_children(ev["id"])

            pagination = (resp.body.get("meta") or {}).get("pagination") or {}
            if self.s.max_events and seen >= self.s.max_events:
                break
            if not pagination.get("has_more"):
                listing["history_complete"] = True
                break
            if listing.get("history_complete") and page_is_exhausted(
                events, self.manifest, self.now(), self.s.refresh_days
            ):
                break
            cursor = pagination.get("next_cursor")
            if not cursor:
                break
        listing["listed_at"] = iso(self.now())

    def _fetch_event(self, event_id: int) -> None:
        task = event_task(event_id, self.manifest)
        resp = self._get(task)
        if resp is None:
            return
        if resp.status == 304:
            self.manifest.record("event", event_id, fetched_at=resp.fetched_at)
            return
        if resp.status != 200:
            self.manifest.record("event", event_id, fetched_at=resp.fetched_at, http_status=resp.status)
            return
        data = resp.body["data"]
        path = self._land("event", resp, event_id)
        fights, fighter_ids = summarise_card(data.get("card") or [])
        self.manifest.record(
            "event", event_id,
            fetched_at=resp.fetched_at, etag=resp.etag, path=path, http_status=200,
            org=data.get("org"), slug=data.get("slug"), starts_at=data.get("starts_at"),
            status=data.get("status"), fights=fights, fighter_ids=fighter_ids,
        )

    def _run_children(self, event_id: int | str) -> None:
        for task in pending_children(event_id, self.manifest):
            resp = self._get(task)
            if resp is None:
                continue
            fields: dict[str, Any] = {"fetched_at": resp.fetched_at, "http_status": resp.status}
            if resp.status == 200:
                fields["path"] = self._land(task.endpoint, resp, task.key)
                fields["etag"] = resp.etag
            if task.endpoint == "fight_rounds":
                fields["event_id"] = task.event_id
                fields["fight_state"] = task.fight_state
            self.manifest.record(task.endpoint, task.key, **fields)

    def _get(self, task: Task) -> ApiResponse | None:
        """One API call; non-fatal errors are recorded and return None."""
        try:
            resp = self.client.get(task.endpoint, task.path, etag=task.etag)
        except FatalApiError:
            raise
        except ApiError as exc:
            self._error(str(exc))
            return None
        finally:
            self._checkpoint()
        if resp.status == 304:
            self.not_modified += 1
        elif resp.status == 404:
            self.not_found += 1
            log.info("%s %s: not found (recorded, not retried until it changes)", task.endpoint, task.key)
        return resp

    def _land(self, endpoint: str, resp: ApiResponse, name: str | int) -> str:
        path = self.sink.write_new(landing_relpath(endpoint, resp.fetched_at, name), envelope(resp))
        self.files[endpoint] += 1
        return path

    # ---- dry run -----------------------------------------------------------

    def _estimate(self) -> dict[str, Any]:
        now = self.now()
        new_events = refresh_events = list_pages = 0
        notes: list[str] = []
        if self.s.discover:
            for org in self.s.orgs:
                pages, new, refresh = self._discover_org(org)
                list_pages += pages
                new_events += new
                refresh_events += refresh
        else:
            list_pages = len(self.s.orgs)
            known = self.manifest.entries("event")
            refresh_events = sum(
                1 for e in known.values()
                if e.get("starts_at")
                and in_refresh_window(e["starts_at"], now, self.s.refresh_days)
                and (now - parse_ts(e["fetched_at"])).total_seconds() >= self.s.min_refetch_hours * 3600
            )
            if not known and self.s.max_events:
                new_events = self.s.max_events * len(self.s.orgs)
                notes.append("empty manifest: assuming every listed event is new")
            else:
                notes.append("new events unknown without --discover; counted as 0")
        pending = [t for eid in events_newest_first(self.manifest) for t in pending_children(eid, self.manifest)]
        counts = estimate_requests(
            list_pages=list_pages, new_events=new_events, refresh_events=refresh_events,
            pending=pending, avg_fights=self.s.avg_fights,
        )
        total = sum(counts.values())
        if new_events:
            notes.append(f"rounds/fighters for new events assume {self.s.avg_fights} fights per card; "
                         "fighters are an upper bound")
        return {
            "new_events": new_events,
            "refresh_events": refresh_events,
            "pending_from_manifest": len(pending),
            "requests_by_endpoint": counts,
            "total_requests": total,
            "minutes_at_rpm": round(total / self.s.rpm, 1),
            "fits_budget": total <= self.s.budget,
            "notes": notes,
        }

    def _discover_org(self, org: str) -> tuple[int, int, int]:
        """List pages only: exact counts of new and refresh-due events."""
        listing = self.manifest.listing(org)
        cursor: str | None = None
        seen = pages = new = refresh = 0
        while True:
            params: dict[str, Any] = {"org": org, "status": "completed", "limit": self.s.page_limit}
            if cursor:
                params["cursor"] = cursor
            resp = self.client.get("events_list", "/events", params=params)
            pages += 1
            if resp.status != 200 or not isinstance(resp.body, dict):
                self._error(f"events_list {org} page {pages}: HTTP {resp.status}")
                break
            events = resp.body.get("data") or []
            if self.s.max_events:
                events = events[: self.s.max_events - seen]
            seen += len(events)
            for ev in events:
                reason = event_fetch_reason(ev, self.manifest, self.now(),
                                            self.s.refresh_days, self.s.min_refetch_hours)
                new += reason == "new"
                refresh += reason == "refresh"
            pagination = (resp.body.get("meta") or {}).get("pagination") or {}
            if self.s.max_events and seen >= self.s.max_events:
                break
            if not pagination.get("has_more") or not pagination.get("next_cursor"):
                break
            if listing.get("history_complete") and page_is_exhausted(
                events, self.manifest, self.now(), self.s.refresh_days
            ):
                break
            cursor = pagination["next_cursor"]
        return pages, new, refresh

    # ---- bookkeeping -------------------------------------------------------

    def _checkpoint(self) -> None:
        used = self.client.used if self.client else 0
        if used - self._saved_at_request >= self.s.checkpoint_every:
            self.save_manifest()

    def save_manifest(self) -> None:
        self.sink.write(MANIFEST, self.manifest.to_json(iso(self.now())).encode("utf-8"))
        self._saved_at_request = self.client.used if self.client else 0
        log.info("manifest saved (%s)", self.manifest.counts())

    def _error(self, message: str) -> None:
        log.warning("error: %s", message)
        if len(self.errors) < MAX_ERRORS_KEPT:
            self.errors.append(message)

    def _finish_summary(self) -> None:
        s = self.summary
        s.finished_at = iso(self.now())
        if self.client:
            s.requests_used = self.client.used
            s.requests_by_endpoint = dict(self.client.by_endpoint)
            s.http_status_counts = dict(getattr(self.client, "status_counts", {}))
            s.quota_remaining = getattr(self.client, "quota_remaining", None)
        s.files_by_endpoint = dict(self.files)
        s.files_written = sum(self.files.values())
        s.not_modified = self.not_modified
        s.not_found = self.not_found
        s.errors = self.errors
        s.manifest_counts = self.manifest.counts()
