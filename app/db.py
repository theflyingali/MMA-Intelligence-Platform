"""Read-only client for the Databricks SQL Statement Execution API.

The public app runs outside Databricks and reads only `mma.silver`. Two ways to authenticate:

- OAuth M2M (production): a service principal's client id and secret are exchanged for a short-lived
  token at `{host}/oidc/v1/token`; the token is refreshed shortly before it expires.
- A static token (local development only): `DATABRICKS_TOKEN`.

Every query is parameterised (named `:params`, never string-built SQL), capped in rows and time, and
errors never include the credential.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import pandas as pd
import requests

STATEMENT_TIMEOUT_S = 30  # wait inline this long, then poll
MAX_WAIT_S = 90  # total budget per query, including a warehouse cold start; then cancel
POLL_INTERVAL_S = 1.5
DEFAULT_ROW_LIMIT = 10_000

log = logging.getLogger("mma_app.db")


class QueryError(RuntimeError):
    """A query failed. The message is safe to log: it never contains a credential."""


@dataclass(frozen=True)
class Settings:
    host: str
    warehouse_id: str
    client_id: str | None = None
    client_secret: str | None = None
    token: str | None = None
    catalog: str = "mma"
    schema: str = "silver"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "Settings":
        """Build settings from Streamlit secrets or the environment (same key names)."""
        host = str(values.get("DATABRICKS_HOST") or "").strip().strip('"').strip("'")
        if host and not host.startswith(("https://", "http://")):
            host = "https://" + host
        host = urlsplit(host)._replace(path="", query="", fragment="").geturl() if host else ""
        warehouse = str(values.get("DATABRICKS_WAREHOUSE_ID") or "").strip()
        settings = cls(
            host=host,
            warehouse_id=warehouse,
            client_id=values.get("DATABRICKS_CLIENT_ID") or None,
            client_secret=values.get("DATABRICKS_CLIENT_SECRET") or None,
            token=values.get("DATABRICKS_TOKEN") or None,
        )
        missing = [n for n, v in (("DATABRICKS_HOST", host), ("DATABRICKS_WAREHOUSE_ID", warehouse)) if not v]
        if not (settings.client_id and settings.client_secret) and not settings.token:
            missing.append("DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET (or DATABRICKS_TOKEN)")
        if missing:
            raise QueryError("Missing configuration: " + ", ".join(missing))
        return settings

    @property
    def uses_oauth(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass
class TokenProvider:
    """Returns a bearer token: the static one, or an OAuth M2M token refreshed before expiry."""

    settings: Settings
    session: requests.Session
    clock: Callable[[], float] = time.monotonic
    _token: str | None = field(default=None, init=False, repr=False)
    _expires_at: float = field(default=0.0, init=False)

    def get(self) -> str:
        if not self.settings.uses_oauth:
            assert self.settings.token
            return self.settings.token
        if self._token is None or self.clock() >= self._expires_at - 60:
            self._refresh()
        assert self._token
        return self._token

    def _refresh(self) -> None:
        try:
            resp = self.session.post(
                f"{self.settings.host}/oidc/v1/token",
                data={"grant_type": "client_credentials", "scope": "all-apis"},
                auth=(self.settings.client_id or "", self.settings.client_secret or ""),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise QueryError(f"Token request to {urlsplit(self.settings.host).hostname} failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            reason = ""
            try:  # e.g. {"error": "invalid_client", "error_description": "..."}; never contains the secret
                body = resp.json()
                reason = f": {body.get('error', '')} {body.get('error_description', '')}".rstrip()[:300]
            except ValueError:
                pass
            raise QueryError(f"Token request failed with HTTP {resp.status_code}{reason}")
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = self.clock() + float(body.get("expires_in", 3600))


def _param(name: str, value: Any) -> dict[str, Any]:
    """Statement API parameter with an explicit SQL type."""
    if value is None:
        return {"name": name, "value": None, "type": "STRING"}
    if isinstance(value, bool):
        return {"name": name, "value": str(value).lower(), "type": "BOOLEAN"}
    if isinstance(value, int):
        return {"name": name, "value": str(value), "type": "BIGINT"}
    if isinstance(value, float):
        return {"name": name, "value": repr(value), "type": "DOUBLE"}
    if isinstance(value, (date, datetime)):
        return {"name": name, "value": value.isoformat(), "type": "DATE" if not isinstance(value, datetime) else "TIMESTAMP"}
    return {"name": name, "value": str(value), "type": "STRING"}


_INT_TYPES = {"BYTE", "SHORT", "INT", "LONG"}
_FLOAT_TYPES = {"FLOAT", "DOUBLE", "DECIMAL"}


def to_frame(columns: list[dict[str, Any]], rows: list[list[Any]]) -> pd.DataFrame:
    """Turn a JSON_ARRAY result (every value a string or null) into typed pandas columns."""
    names = [c["name"] for c in columns]
    df = pd.DataFrame(rows, columns=names, dtype=object)
    for col in columns:
        name, kind = col["name"], str(col.get("type_name", "STRING")).upper()
        s = df[name]
        if kind in _INT_TYPES:
            df[name] = pd.to_numeric(s, errors="coerce").astype("Int64")
        elif kind in _FLOAT_TYPES:
            df[name] = pd.to_numeric(s, errors="coerce").astype("Float64")
        elif kind == "BOOLEAN":
            df[name] = s.map(lambda v: None if v is None else str(v).lower() == "true").astype("boolean")
        elif kind == "DATE":
            df[name] = pd.to_datetime(s, errors="coerce").dt.date
        elif kind == "TIMESTAMP":
            df[name] = pd.to_datetime(s, errors="coerce", utc=True)
    return df


class SqlClient:
    """Runs one parameterised, read-only statement at a time on the configured warehouse."""

    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.tokens = TokenProvider(settings, self.session, clock=clock)
        self._sleep = sleep
        self._clock = clock

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.get()}"}

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.settings.host}{path}"
        try:
            resp = self.session.request(method, url, headers=self._headers(), timeout=STATEMENT_TIMEOUT_S + 15, **kwargs)
        except requests.RequestException as exc:
            raise QueryError(f"Request to {urlsplit(url).hostname} failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            detail = ""
            try:
                detail = str(resp.json().get("message", ""))[:300]
            except ValueError:
                pass
            raise QueryError(f"SQL API returned HTTP {resp.status_code}: {detail}".rstrip(": "))
        return resp.json()

    def query(self, sql: str, params: Mapping[str, Any] | None = None, row_limit: int = DEFAULT_ROW_LIMIT) -> pd.DataFrame:
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if head not in {"SELECT", "WITH"}:
            raise QueryError("Only SELECT statements are allowed")
        body = {
            "warehouse_id": self.settings.warehouse_id,
            "catalog": self.settings.catalog,
            "schema": self.settings.schema,
            "statement": sql,
            "parameters": [_param(k, v) for k, v in (params or {}).items()],
            "wait_timeout": f"{STATEMENT_TIMEOUT_S}s",
            "on_wait_timeout": "CONTINUE",
            "disposition": "INLINE",
            "format": "JSON_ARRAY",
            "row_limit": row_limit,
        }
        started = self._clock()
        result = self._call("POST", "/api/2.0/sql/statements", json=body)
        statement_id = result.get("statement_id")
        while result.get("status", {}).get("state") in {"PENDING", "RUNNING"}:
            if self._clock() - started > MAX_WAIT_S:
                try:
                    self._call("POST", f"/api/2.0/sql/statements/{statement_id}/cancel")
                except QueryError:
                    pass  # best effort; the timeout below is the error that matters
                raise QueryError(f"Query timed out after {MAX_WAIT_S} s and was cancelled")
            self._sleep(POLL_INTERVAL_S)
            result = self._call("GET", f"/api/2.0/sql/statements/{statement_id}")
        status = result.get("status", {})
        if status.get("state") != "SUCCEEDED":
            message = str(status.get("error", {}).get("message", ""))[:300]
            raise QueryError(f"Query {status.get('state', 'failed').lower()}: {message}".rstrip(": "))
        columns = result.get("manifest", {}).get("schema", {}).get("columns", [])
        rows = result.get("result", {}).get("data_array") or []
        if result.get("manifest", {}).get("total_chunk_count", 1) > 1:
            raise QueryError("Result too large for one chunk; add a LIMIT")
        log.info("statement %s: %d rows in %.2f s", statement_id, len(rows), self._clock() - started)
        return to_frame(columns, rows)
