"""Backfill estimate: how many requests a full history ingest would take.

    python -m ingestion.ufcalendar.estimate_backfill [--org ufc --org pfl ...] [--budget 80]

Uses aggregate endpoints instead of guessing card sizes:
- /stats/years/{year} (one call per year, all orgs): exact completed events and bouts per org.
- /orgs: coverage flags (rounds, odds) per org.
- A few probe events per org (list, event, rounds, odds) to see whether old cards have
  round stats and priced odds.
Fighters are capped by the API's own figure (~4.5k with a launch-org fight, all orgs together).
Responses are cached under data/ so re-running costs nothing except the current year and /usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .__main__ import load_api_key, setup_logging
from .client import ApiClient, StopRun
from .config import BASE_URL, DEFAULT_ORGS, VOLUME_ROOT
from .manifest import Manifest
from .planner import PLAYED
from .ratelimit import SlidingWindowLimiter
from .storage import MANIFEST, LocalSink, VolumeSink

log = logging.getLogger("ufcalendar.estimate")

FIRST_YEAR = 1993
FIGHTERS_ALL_ORGS = 4500  # "Fighters with at least one launch-org fight (~4.5k)", /v1/fighters
PROBE_YEARS = (2005, 2015)  # probed in addition to each org's first year, where they apply
HOBBY = {"monthly": 30_000, "rpm": 60}
CACHE_DIR = Path("data/ufcalendar_cache")


def compute_estimate(
    per_org_year: dict[str, dict[int, dict[str, int]]],
    capabilities: dict[str, dict[str, bool]],
    known: dict[str, dict[str, int]],
    fighters_cap: int = FIGHTERS_ALL_ORGS,
    known_fighters: int = 0,
    rpm: int = 55,
) -> dict[str, Any]:
    """Requests per org and endpoint for a full backfill, minus what the manifest already holds.

    per_org_year: {org: {year: {"events": n, "bouts": n}}}
    known:        {org: {"events": n, "bouts": n}} already ingested
    """
    orgs: dict[str, dict[str, int]] = {}
    total_bouts = 0
    for org, years in per_org_year.items():
        events = sum(y["events"] for y in years.values())
        bouts = sum(y["bouts"] for y in years.values())
        total_bouts += bouts
        caps = capabilities.get(org, {})
        k = known.get(org, {})
        new_events = max(0, events - k.get("events", 0))
        new_bouts = max(0, bouts - k.get("bouts", 0))
        orgs[org] = {
            "events": events,
            "bouts": bouts,
            "events_list": math.ceil(events / 100) if events else 0,
            "event": new_events,
            "event_odds": new_events if caps.get("odds", True) else 0,
            "fight_rounds": new_bouts if caps.get("rounds", True) else 0,
        }
    fighters = max(0, min(fighters_cap, 2 * total_bouts) - known_fighters)
    by_endpoint = {
        ep: sum(o[ep] for o in orgs.values())
        for ep in ("events_list", "event", "event_odds", "fight_rounds")
    }
    by_endpoint["fighter"] = fighters
    total = sum(by_endpoint.values())
    return {
        "orgs": orgs,
        "requests_by_endpoint": by_endpoint,
        "total_requests": total,
        "fighters_note": f"upper bound: min({fighters_cap} across all launch orgs, 2 x bouts) minus known",
        "hours_at_rpm": round(total / rpm / 60, 1),
        "rpm": rpm,
        "fits_hobby_month": total <= HOBBY["monthly"],
    }


class CachedApi:
    def __init__(self, client: ApiClient, cache_dir: Path = CACHE_DIR) -> None:
        self.client = client
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0

    def get(self, endpoint: str, path: str, params: dict[str, Any] | None = None, cache: bool = True) -> Any:
        key = hashlib.sha1(json.dumps([path, sorted((params or {}).items())]).encode()).hexdigest()[:16]
        f = self.cache_dir / f"{endpoint}_{key}.json"
        if cache and f.exists():
            self.hits += 1
            return json.loads(f.read_text())
        resp = self.client.get(endpoint, path, params=params)
        body = resp.body if resp.status == 200 else None
        if cache and body is not None:
            f.write_text(json.dumps(body))
        return body


def fetch_year_counts(api: CachedApi, orgs: list[str], this_year: int) -> dict[str, dict[int, dict[str, int]]]:
    per_org_year: dict[str, dict[int, dict[str, int]]] = {o: {} for o in orgs}
    for year in range(FIRST_YEAR, this_year + 1):
        body = api.get("year_stats", f"/stats/years/{year}", cache=year < this_year)
        for row in ((body or {}).get("data") or {}).get("orgs") or []:
            if row["slug"] in per_org_year and (row["events"] or row["fights"]):
                per_org_year[row["slug"]][year] = {"events": row["events"], "bouts": row["fights"]}
    return per_org_year


def probe(api: CachedApi, org: str, year: int) -> dict[str, Any] | None:
    """Oldest completed event of `org` in `year`: does it have round stats and priced odds?"""
    listing = api.get("events_list", "/events", {
        "org": org, "status": "completed", "from": f"{year}-01-01", "to": f"{year}-12-31",
        "order": "asc", "limit": 1,
    })
    rows = (listing or {}).get("data") or []
    if not rows:
        return None
    event_id = rows[0]["id"]
    detail = api.get("event", f"/events/{event_id}")
    card = ((detail or {}).get("data") or {}).get("card") or []
    played = [f for f in card if f.get("status") in PLAYED]
    rounds_lines = None
    if played:
        rounds = api.get("fight_rounds", f"/fights/{played[0]['id']}/rounds")
        rounds_lines = len((rounds or {}).get("data") or [])
    odds = api.get("event_odds", f"/events/{event_id}/odds")
    meta = (odds or {}).get("meta") or {}
    return {
        "org": org, "year": year, "event": rows[0].get("slug"), "played_bouts": len(played),
        "main_bout_round_lines": rounds_lines,
        "odds_priced": meta.get("priced"), "odds_unpriced": meta.get("unpriced"),
    }


def known_counts(manifest: Manifest) -> tuple[dict[str, dict[str, int]], int]:
    known: dict[str, dict[str, int]] = {}
    events = manifest.entries("event")
    for entry in events.values():
        org = entry.get("org") or "?"
        k = known.setdefault(org, {"events": 0, "bouts": 0})
        k["events"] += 1
        k["bouts"] += sum(1 for s in entry.get("fights", {}).values() if s.get("status") in PLAYED)
    return known, len(manifest.entries("fighter"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ingestion.ufcalendar.estimate_backfill")
    p.add_argument("--org", dest="orgs", action="append", help="Org slug; repeat (default: ufc pfl oktagon rizin)")
    p.add_argument("--budget", type=int, default=80)
    p.add_argument("--rpm", type=int, default=8, help="Client-side rate for this estimate (free plan)")
    p.add_argument("--backfill-rpm", type=int, default=55, help="Rate assumed for the backfill on Hobby")
    p.add_argument("--profile", default="mma")
    p.add_argument("--local-only", action="store_true", help="Read the manifest from data/ instead of the volume")
    a = p.parse_args(argv)
    orgs = a.orgs or ["ufc", "pfl", "oktagon", "rizin"]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = load_api_key(Path(".env"))
    setup_logging(Path("logs"), f"estimate_{run_id}", [key])

    mirror = LocalSink(Path("data/ufcalendar"))
    if a.local_only:
        sink: LocalSink | VolumeSink = mirror
    else:
        from databricks.sdk import WorkspaceClient
        sink = VolumeSink(VOLUME_ROOT, WorkspaceClient(profile=a.profile), mirror)
    manifest = Manifest.from_json(sink.read(MANIFEST))
    known, known_fighters = known_counts(manifest)

    client = ApiClient(key, BASE_URL, SlidingWindowLimiter(a.rpm), budget=a.budget, quota_reserve=0)
    api = CachedApi(client)
    report: dict[str, Any] = {"run_id": run_id, "orgs_in_scope": orgs, "known": known,
                              "known_fighters": known_fighters}
    try:
        usage = api.get("usage", "/usage", cache=False)
        report["usage"] = (usage or {}).get("data")
        caps_body = api.get("orgs", "/orgs")
        caps = {o["slug"]: o["capabilities"] for o in (caps_body or {}).get("data") or []}
        report["capabilities"] = {o: caps.get(o) for o in orgs}

        this_year = datetime.now(timezone.utc).year
        per_org_year = fetch_year_counts(api, orgs, this_year)
        report["per_org_year"] = per_org_year

        probes = []
        for org in orgs:
            years = sorted(per_org_year[org])
            if not years:
                continue
            for year in sorted({years[0], *(y for y in PROBE_YEARS if y > years[0])}):
                result = probe(api, org, year)
                if result:
                    probes.append(result)
        report["probes"] = probes
        report["estimate"] = compute_estimate(per_org_year, caps, known, known_fighters=known_fighters,
                                              rpm=a.backfill_rpm)
        report["stop_reason"] = "completed"
    except StopRun as exc:
        report["stop_reason"] = f"stopped: {exc}"
    report["requests_used"] = client.used
    report["cache_hits"] = api.hits
    report["quota_remaining"] = client.quota_remaining

    out = Path("logs") / f"backfill_estimate_{run_id}.json"
    out.write_text(json.dumps(report, indent=1))
    print_report(report, out)
    return 0 if report["stop_reason"] == "completed" else 1


def print_report(r: dict[str, Any], out: Path) -> None:
    lines = [f"backfill estimate {r['run_id']}: {r['stop_reason']}",
             f"  requests used: {r['requests_used']} (cache hits {r['cache_hits']}), "
             f"quota remaining: {r['quota_remaining']}"]
    if r.get("usage"):
        u = r["usage"]
        lines.append(f"  plan: {u.get('tier')}, {u.get('requests_used')}/{u.get('requests_limit')} used, "
                     f"{u.get('rpm_limit')} rpm, resets {u.get('reset_at')}")
    for org, c in (r.get("capabilities") or {}).items():
        lines.append(f"  {org} coverage: {c}")
    for pr in r.get("probes", []):
        lines.append(f"  probe {pr['org']} {pr['year']} {pr['event']}: {pr['played_bouts']} bouts, "
                     f"main-bout round lines {pr['main_bout_round_lines']}, "
                     f"odds priced {pr['odds_priced']} / unpriced {pr['odds_unpriced']}")
    e = r.get("estimate")
    if e:
        lines.append("  org        events   bouts   list  event   odds  rounds")
        for org, o in e["orgs"].items():
            lines.append(f"  {org:<9}{o['events']:>8}{o['bouts']:>8}{o['events_list']:>7}{o['event']:>7}"
                         f"{o['event_odds']:>7}{o['fight_rounds']:>8}")
        lines += [
            f"  fighters: {e['requests_by_endpoint']['fighter']} ({e['fighters_note']})",
            f"  TOTAL: {e['total_requests']} requests, ~{e['hours_at_rpm']} h at {e['rpm']} rpm, "
            f"fits one Hobby month (30,000): {e['fits_hobby_month']}",
        ]
    lines.append(f"  report: {out}")
    log.info("summary\n%s", "\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
