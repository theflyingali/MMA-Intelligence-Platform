"""SQL client for the dashboard: auth, parameters, polling, typing and safe errors (no network)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from app import db

SECRET = "dapi-super-secret"


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code, self._body = status, body

    def json(self) -> dict[str, Any]:
        return self._body


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)


def settings(**kw) -> db.Settings:
    values = {"DATABRICKS_HOST": "example.cloud.databricks.com", "DATABRICKS_WAREHOUSE_ID": "wh1",
              "DATABRICKS_TOKEN": SECRET}
    values.update(kw)
    return db.Settings.from_mapping(values)


def ok(rows, columns) -> FakeResponse:
    return FakeResponse(200, {"statement_id": "s1", "status": {"state": "SUCCEEDED"},
                              "manifest": {"schema": {"columns": columns}, "total_chunk_count": 1},
                              "result": {"data_array": rows}})


def test_settings_validation_and_host_normalisation():
    s = settings()
    assert s.host == "https://example.cloud.databricks.com" and not s.uses_oauth
    with pytest.raises(db.QueryError, match="DATABRICKS_WAREHOUSE_ID"):
        db.Settings.from_mapping({"DATABRICKS_HOST": "h", "DATABRICKS_TOKEN": "t"})
    with pytest.raises(db.QueryError, match="CLIENT_ID"):
        db.Settings.from_mapping({"DATABRICKS_HOST": "h", "DATABRICKS_WAREHOUSE_ID": "w"})
    assert settings(DATABRICKS_CLIENT_ID="id", DATABRICKS_CLIENT_SECRET="sec").uses_oauth


def test_query_sends_typed_parameters_and_types_result():
    cols = [{"name": "id", "type_name": "LONG"}, {"name": "ok", "type_name": "BOOLEAN"},
            {"name": "x", "type_name": "DOUBLE"}, {"name": "d", "type_name": "DATE"},
            {"name": "ts", "type_name": "TIMESTAMP"}, {"name": "s", "type_name": "STRING"}]
    session = FakeSession([ok([["7", "true", "1.5", "1991-10-27", "2026-11-14T22:00:00.000Z", "a"],
                               [None, None, None, None, None, None]], cols)])
    df = db.SqlClient(settings(), session=session).query("SELECT 1 WHERE id = :fighter_id", {"fighter_id": 397})
    method, url, kw = session.calls[0]
    assert url.endswith("/api/2.0/sql/statements")
    assert kw["json"]["parameters"] == [{"name": "fighter_id", "value": "397", "type": "BIGINT"}]
    assert kw["json"]["catalog"] == "mma" and kw["json"]["schema"] == "silver"
    assert kw["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert df["id"].iloc[0] == 7 and pd.isna(df["id"].iloc[1])
    assert bool(df["ok"].iloc[0]) is True and pd.isna(df["ok"].iloc[1])
    assert str(df["d"].iloc[0]) == "1991-10-27" and df["ts"].iloc[0].year == 2026


def test_only_select_is_allowed():
    client = db.SqlClient(settings(), session=FakeSession([]))
    for sql in ("DROP TABLE x", "  delete from x", "", "UPDATE x SET a=1"):
        with pytest.raises(db.QueryError, match="Only SELECT"):
            client.query(sql)


def test_polls_while_warehouse_starts_then_cancels_after_budget():
    now = [0.0]
    pending = FakeResponse(200, {"statement_id": "s1", "status": {"state": "PENDING"}})
    session = FakeSession([pending, pending, ok([["1"]], [{"name": "n", "type_name": "INT"}])])
    client = db.SqlClient(settings(), session=session, sleep=lambda s: None, clock=lambda: now[0])
    assert client.query("SELECT 1")["n"].iloc[0] == 1

    def tick(_):
        now[0] += 50
    session = FakeSession([pending, pending, pending, FakeResponse(200, {})])
    client = db.SqlClient(settings(), session=session, sleep=tick, clock=lambda: now[0])
    now[0] = 0
    with pytest.raises(db.QueryError, match="timed out"):
        client.query("SELECT 1")
    assert session.calls[-1][1].endswith("/statements/s1/cancel")


def test_errors_never_leak_the_credential():
    failed = FakeResponse(200, {"statement_id": "s1", "status": {"state": "FAILED", "error": {"message": "TABLE_OR_VIEW_NOT_FOUND"}}})
    client = db.SqlClient(settings(), session=FakeSession([failed]))
    with pytest.raises(db.QueryError) as exc:
        client.query("SELECT 1")
    assert "TABLE_OR_VIEW_NOT_FOUND" in str(exc.value) and SECRET not in str(exc.value)
    client = db.SqlClient(settings(), session=FakeSession([FakeResponse(403, {"message": "denied"})]))
    with pytest.raises(db.QueryError, match="403") as exc:
        client.query("SELECT 1")
    assert SECRET not in str(exc.value)


def test_oauth_token_is_fetched_once_and_refreshed_before_expiry():
    now = [0.0]
    token = lambda t: FakeResponse(200, {"access_token": t, "expires_in": 3600})  # noqa: E731
    col = [{"name": "n", "type_name": "INT"}]
    session = FakeSession([token("t1"), ok([["1"]], col), ok([["1"]], col), token("t2"), ok([["1"]], col)])
    client = db.SqlClient(settings(DATABRICKS_CLIENT_ID="id", DATABRICKS_CLIENT_SECRET="sec"),
                          session=session, clock=lambda: now[0])
    client.query("SELECT 1")
    now[0] = 3000
    client.query("SELECT 1")
    now[0] = 3550  # within 60 s of expiry
    client.query("SELECT 1")
    token_calls = [c for c in session.calls if c[1].endswith("/oidc/v1/token")]
    assert len(token_calls) == 2
    assert token_calls[0][2]["data"]["grant_type"] == "client_credentials"
    assert session.calls[-1][2]["headers"]["Authorization"] == "Bearer t2"


def test_oauth_failure_message_is_safe():
    session = FakeSession([FakeResponse(401, {"error": "invalid_client"})])
    client = db.SqlClient(settings(DATABRICKS_CLIENT_ID="id", DATABRICKS_CLIENT_SECRET=SECRET), session=session)
    with pytest.raises(db.QueryError, match="HTTP 401") as exc:
        client.query("SELECT 1")
    assert SECRET not in str(exc.value)


def test_host_is_cleaned_and_named_in_connection_errors():
    s = settings(DATABRICKS_HOST='"dbc-abc.cloud.databricks.com/?o=123#x"')
    assert s.host == "https://dbc-abc.cloud.databricks.com"

    class Down(FakeSession):
        def post(self, url, **kw):
            import requests
            raise requests.ConnectionError("boom")
    client = db.SqlClient(settings(DATABRICKS_CLIENT_ID="id", DATABRICKS_CLIENT_SECRET=SECRET), session=Down([]))
    with pytest.raises(db.QueryError, match="example.cloud.databricks.com failed: ConnectionError") as exc:
        client.query("SELECT 1")
    assert SECRET not in str(exc.value)
