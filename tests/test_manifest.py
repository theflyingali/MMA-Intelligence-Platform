import json

import pytest

from ingestion.ufcalendar.manifest import ENDPOINTS, Manifest
from ingestion.ufcalendar.runner import Runner
from ingestion.ufcalendar.storage import MANIFEST, LocalSink

from .conftest import FakeClient


def test_empty_manifest_has_every_endpoint():
    m = Manifest.from_json(None)
    assert m.counts() == {ep: 0 for ep in ENDPOINTS}
    assert m.listing("ufc") == {"history_complete": False}


def test_record_merges_and_keys_are_strings():
    m = Manifest()
    m.record("fighter", 42, fetched_at="2026-10-30T08:00:00Z", etag="a")
    m.record("fighter", "42", etag="b")
    assert m.get("fighter", 42) == {"fetched_at": "2026-10-30T08:00:00Z", "etag": "b"}
    assert list(m.entries("fighter")) == ["42"]


def test_json_round_trip():
    m = Manifest()
    m.record("event", 1, fetched_at="2026-10-30T08:00:00Z", fights={"101": {"status": "completed"}})
    text = m.to_json("2026-10-30T09:00:00Z")
    again = Manifest.from_json(text)
    assert again.data == m.data
    assert json.loads(text)["updated_at"] == "2026-10-30T09:00:00Z"


def test_unknown_version_is_rejected():
    with pytest.raises(ValueError):
        Manifest.from_json('{"version": 99}')


def test_budget_stop_saves_manifest_and_next_run_resumes(api, clock, settings):
    sink = LocalSink(settings.local_root)

    # Full run for reference.
    full = FakeClient(api, clock)
    Runner(settings, full, LocalSink(settings.local_root.parent / "ref"), Manifest(), "ref", now=clock).run()

    # Same work split by a tiny budget.
    first = FakeClient(api, clock, budget=5)
    summary = Runner(settings, first, sink, Manifest(), "r1", now=clock).run()
    assert summary.stop_reason.startswith("stopped: request budget")
    saved = Manifest.from_json(sink.read(MANIFEST))
    assert saved.get("event", 1) is not None  # progress made before the stop is kept

    second = FakeClient(api, clock)
    summary = Runner(settings, second, sink, saved, "r2", now=clock).run()
    assert summary.stop_reason == "completed"
    # Nothing fetched twice apart from the events list page.
    assert first.used + second.used == full.used + 1
    final = Manifest.from_json(sink.read(MANIFEST))
    assert final.counts() == Manifest.from_json(
        LocalSink(settings.local_root.parent / "ref").read(MANIFEST)).counts()
