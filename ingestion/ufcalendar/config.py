"""Run settings and command-line parsing for the UFCalendar ingestion."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://api.ufcalendar.com/v1"
VOLUME_ROOT = "/Volumes/mma/raw/landing/ufcalendar"
DEFAULT_ORGS = ["ufc"]  # later: pfl, oktagon, rizin (bkfc only if wanted)


@dataclass
class Settings:
    orgs: list[str] = field(default_factory=lambda: list(DEFAULT_ORGS))
    max_events: int | None = None
    budget: int = 50
    rpm: int = 8  # free plan allows 10/min; stay below it
    quota_reserve: int = 100
    refresh_days: int = 14
    min_refetch_hours: float = 72.0
    avg_fights: int = 12
    dry_run: bool = False
    discover: bool = False
    local_only: bool = False
    profile: str = "mma"
    base_url: str = BASE_URL
    volume_root: str = VOLUME_ROOT
    local_root: Path = Path("data/ufcalendar")
    log_dir: Path = Path("logs")
    env_file: Path = Path(".env")
    checkpoint_every: int = 25

    @property
    def page_limit(self) -> int:
        if self.max_events:
            return max(1, min(self.max_events, 100))
        return 100


def parse_args(argv: list[str] | None = None) -> Settings:
    p = argparse.ArgumentParser(
        prog="python -m ingestion.ufcalendar",
        description="Incremental UFCalendar ingestion into the Unity Catalog landing volume.",
    )
    p.add_argument("--org", dest="orgs", action="append", help="Org slug; repeat for several (default: ufc)")
    p.add_argument("--max-events", type=int, help="Only consider the N most recent completed events per org")
    p.add_argument("--budget", type=int, default=Settings.budget, help="Max API requests this run (default: %(default)s)")
    p.add_argument("--rpm", type=int, default=Settings.rpm, help="Client-side requests per minute (default: %(default)s)")
    p.add_argument("--quota-reserve", type=int, default=Settings.quota_reserve,
                   help="Stop when the monthly quota remaining falls to this (default: %(default)s)")
    p.add_argument("--refresh-days", type=int, default=Settings.refresh_days,
                   help="Re-fetch events that started within this many days (default: %(default)s)")
    p.add_argument("--min-refetch-hours", type=float, default=Settings.min_refetch_hours,
                   help="Minimum hours between re-fetches of a recent event (default: %(default)s)")
    p.add_argument("--avg-fights", type=int, default=Settings.avg_fights,
                   help="Fights per event assumed by the dry-run estimate (default: %(default)s)")
    p.add_argument("--dry-run", action="store_true", help="Estimate requests; no API calls, no uploads")
    p.add_argument("--discover", action="store_true",
                   help="With --dry-run: spend list-page calls only, for an exact count of new events")
    p.add_argument("--local-only", action="store_true", help="Write to data/ instead of the Databricks volume")
    p.add_argument("--profile", default=Settings.profile, help="Databricks CLI profile (default: %(default)s)")
    a = p.parse_args(argv)
    if a.discover and not a.dry_run:
        p.error("--discover only makes sense with --dry-run")
    if a.budget < 0 or a.rpm < 1:
        p.error("--budget must be >= 0 and --rpm >= 1")
    return Settings(
        orgs=a.orgs or list(DEFAULT_ORGS),
        max_events=a.max_events,
        budget=a.budget,
        rpm=a.rpm,
        quota_reserve=a.quota_reserve,
        refresh_days=a.refresh_days,
        min_refetch_hours=a.min_refetch_hours,
        avg_fights=a.avg_fights,
        dry_run=a.dry_run,
        discover=a.discover,
        local_only=a.local_only,
        profile=a.profile,
    )
