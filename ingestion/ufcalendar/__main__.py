"""CLI entry point: python -m ingestion.ufcalendar [options]"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from .client import ApiClient
from .config import Settings, parse_args
from .manifest import Manifest
from .ratelimit import SlidingWindowLimiter
from .runner import Runner, Summary
from .storage import MANIFEST, LocalSink, RunLocked, VolumeSink, acquire_lock, release_lock

log = logging.getLogger("ufcalendar")


class RedactFilter(logging.Filter):
    """Belt and braces: scrub secret values from every log record."""

    def __init__(self, secrets: list[str | None]) -> None:
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 8]

    def _scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._scrub(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = self._scrub(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def read_databricks_secret(scope: str, key: str) -> str:
    from databricks.sdk.runtime import dbutils  # only available on Databricks compute

    return dbutils.secrets.get(scope=scope, key=key)


def load_api_key(env_file: Path, secret_scope: str | None = None, secret_key: str = "ufcal_key",
                 read_secret=read_databricks_secret) -> str:
    if secret_scope:
        key = (read_secret(secret_scope, secret_key) or "").strip()
        source = f"secret {secret_scope}/{secret_key}"
    else:
        # dotenv_values, not load_dotenv: keeps DATABRICKS_* in .env out of os.environ so they
        # cannot clash with the SDK's CLI-profile auth.
        key = (dotenv_values(env_file).get("UFCAL_KEY") or os.environ.get("UFCAL_KEY") or "").strip()
        source = f"{env_file} or the environment"
    if not key:
        raise SystemExit(f"UFCAL_KEY is not set (expected in {source})")
    return key


def setup_logging(log_dir: Path, run_id: str, secrets: list[str | None]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"ingest_{run_id}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    redact = RedactFilter(secrets)
    log.setLevel(logging.INFO)
    log.propagate = False
    for handler in (logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(fmt)
        handler.addFilter(redact)
        log.addHandler(handler)
    for noisy in ("databricks", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_path


def build_sink(settings: Settings) -> LocalSink | VolumeSink:
    if settings.output_dir:
        return LocalSink(settings.output_dir)
    mirror = LocalSink(settings.local_root)
    if settings.local_only:
        return mirror
    from databricks.sdk import WorkspaceClient

    return VolumeSink(settings.volume_root, WorkspaceClient(profile=settings.profile), mirror)


def print_summary(summary: Summary, log_path: Path) -> None:
    s = summary
    lines = [
        f"run {s.run_id} ({s.mode}): {s.stop_reason}",
        f"  requests used: {s.requests_used}/{s.budget}  by endpoint: {s.requests_by_endpoint}",
        f"  files written: {s.files_written}  by endpoint: {s.files_by_endpoint}",
        f"  not modified (304): {s.not_modified}  not found (404): {s.not_found}  errors: {len(s.errors)}",
        f"  monthly quota remaining: {s.quota_remaining if s.quota_remaining is not None else 'unknown'}",
        f"  manifest: {s.manifest_counts}",
    ]
    if s.estimate:
        e = s.estimate
        lines += [
            f"  estimate: {e['total_requests']} requests (~{e['minutes_at_rpm']} min), "
            f"fits budget: {e['fits_budget']}",
            f"    new events: {e['new_events']}  refresh due: {e['refresh_events']}  "
            f"pending from manifest: {e['pending_from_manifest']}",
            f"    by endpoint: {e['requests_by_endpoint']}",
        ] + [f"    note: {n}" for n in e["notes"]]
    lines.append(f"  log: {log_path}")
    log.info("summary\n%s", "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    settings = parse_args(argv)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    needs_api = not settings.dry_run or settings.discover
    api_key = load_api_key(settings.env_file, settings.secret_scope, settings.secret_key) if needs_api else None
    log_path = setup_logging(settings.log_dir, run_id, [api_key])
    log.info("run %s starting: %s", run_id, {
        "orgs": settings.orgs, "max_events": settings.max_events, "budget": settings.budget,
        "rpm": settings.rpm, "dry_run": settings.dry_run, "discover": settings.discover,
        "local_only": settings.local_only, "output_dir": str(settings.output_dir or ""),
    })

    sink = build_sink(settings)
    if not settings.dry_run:
        try:
            acquire_lock(sink, run_id, datetime.now(timezone.utc), settings.break_lock)
        except RunLocked as exc:
            log.error("not starting: %s", exc)
            return 2
    try:
        return _run(settings, sink, api_key, run_id, log_path)
    finally:
        if not settings.dry_run:
            release_lock(sink, run_id, datetime.now(timezone.utc))


def _run(settings: Settings, sink: LocalSink | VolumeSink, api_key: str | None, run_id: str,
         log_path: Path) -> int:
    manifest = Manifest.from_json(sink.read(MANIFEST))
    log.info("manifest loaded: %s", manifest.counts())

    client = None
    if api_key:
        client = ApiClient(
            api_key=api_key,
            base_url=settings.base_url,
            limiter=SlidingWindowLimiter(settings.rpm),
            budget=settings.budget,
            quota_reserve=settings.quota_reserve,
            min_plan_quota=settings.min_plan_quota,
        )
    summary = Runner(settings, client, sink, manifest, run_id).run()

    summary_json = json.dumps(summary.to_dict(), indent=1).encode("utf-8")
    (settings.log_dir / f"summary_{run_id}.json").write_bytes(summary_json)
    print_summary(summary, log_path)
    if not settings.dry_run:
        sink.write(f"_runs/{run_id}.json", summary_json)
        for handler in log.handlers:
            handler.flush()
        sink.write(f"_runs/{run_id}.log", log_path.read_bytes())
    return 1 if (summary.stop_reason or "").startswith(("fatal", "error")) else 0


if __name__ == "__main__":
    sys.exit(main())
