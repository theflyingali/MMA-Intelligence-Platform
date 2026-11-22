"""workspace_client: CLI profile on the laptop, DATABRICKS_HOST/TOKEN in the cloud."""

import pytest

from ingestion.ufcalendar import storage


class _Fake:
    def __init__(self, **kw):
        self.kw = kw


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    import databricks.sdk as sdk

    monkeypatch.setattr(sdk, "WorkspaceClient", _Fake)


def test_uses_profile_when_present(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.write_text("[mma]\nhost = https://x\n")
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
    assert storage.workspace_client("mma").kw == {"profile": "mma"}


def test_falls_back_to_env_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(tmp_path / "missing"))
    monkeypatch.setenv("DATABRICKS_HOST", "https://x")
    monkeypatch.setenv("DATABRICKS_TOKEN", "t")
    assert storage.workspace_client("mma").kw == {}


def test_errors_when_neither(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(tmp_path / "missing"))
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        storage.workspace_client("mma")
