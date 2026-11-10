"""Tests harness/secrets_check.py's pass/fail logic with the network and the
database mocked out -- no real credentials needed to run these."""
from harness import secrets_check
from harness.connector import TransientError


class _FakeConnector:
    def __init__(self, env_var):
        self.env_var = env_var

    def query(self, sql, params=None):
        return [{"ok": 1}]


class _MissingEnvVarConnector:
    def __init__(self, env_var):
        raise RuntimeError(f"connection string not found: set ${env_var}")


class _FailingQueryConnector:
    def __init__(self, env_var):
        pass

    def query(self, sql, params=None):
        raise RuntimeError("login failed")


class _ResumingThenHealthyConnector:
    """Fails with the exact shape of a serverless database waking up from
    auto-pause on its first two attempts, then succeeds -- the real-world
    case this retry exists for."""

    def __init__(self, env_var):
        self.calls = 0

    def query(self, sql, params=None):
        self.calls += 1
        if self.calls <= 2:
            raise TransientError("database is not currently available (40613)")
        return [{"ok": 1}]


class _AlwaysResumingConnector:
    def __init__(self, env_var):
        self.calls = 0

    def query(self, sql, params=None):
        self.calls += 1
        raise TransientError("database is not currently available (40613)")


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json


def test_check_synapse_passes_when_query_succeeds(monkeypatch):
    monkeypatch.setattr(secrets_check, "SynapseConnector", _FakeConnector)
    ok, message = secrets_check.check_synapse("SYNAPSE_DEV_CONN_STR")
    assert ok
    assert "success" in message.lower()


def test_check_synapse_fails_when_env_var_missing(monkeypatch):
    monkeypatch.setattr(secrets_check, "SynapseConnector", _MissingEnvVarConnector)
    ok, message = secrets_check.check_synapse("SYNAPSE_DEV_CONN_STR")
    assert not ok
    assert "not found" in message


def test_check_synapse_fails_when_query_raises(monkeypatch):
    monkeypatch.setattr(secrets_check, "SynapseConnector", _FailingQueryConnector)
    ok, message = secrets_check.check_synapse("SYNAPSE_DEV_CONN_STR")
    assert not ok
    assert "login failed" in message


def test_check_synapse_retries_a_transient_error_and_then_succeeds(monkeypatch):
    # caught by a real nightly run: a serverless database resuming from
    # auto-pause failed the first two attempts, then came up fine
    monkeypatch.setattr(secrets_check, "SynapseConnector", _ResumingThenHealthyConnector)
    monkeypatch.setattr(secrets_check.time, "sleep", lambda _seconds: None)
    ok, message = secrets_check.check_synapse("SYNAPSE_DEV_CONN_STR")
    assert ok
    assert "success" in message.lower()


def test_check_synapse_gives_up_and_reports_failure_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(secrets_check, "SynapseConnector", _AlwaysResumingConnector)
    monkeypatch.setattr(secrets_check.time, "sleep", lambda _seconds: None)
    ok, message = secrets_check.check_synapse("SYNAPSE_DEV_CONN_STR")
    assert not ok
    assert "gave up after" in message
    assert "40613" in message


def test_check_deepseek_fails_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    ok, message = secrets_check.check_deepseek()
    assert not ok
    assert "not set" in message


def test_check_deepseek_passes_on_200(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(secrets_check.requests, "get", lambda *a, **k: _FakeResponse(200))
    ok, message = secrets_check.check_deepseek()
    assert ok


def test_check_deepseek_fails_on_401(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-bad")
    monkeypatch.setattr(secrets_check.requests, "get", lambda *a, **k: _FakeResponse(401, text="Unauthorized"))
    ok, message = secrets_check.check_deepseek()
    assert not ok
    assert "401" in message


def test_check_gh_pat_fails_without_token(monkeypatch):
    monkeypatch.delenv("GH_PAT", raising=False)
    ok, message = secrets_check.check_gh_pat()
    assert not ok
    assert "not set" in message


def test_check_gh_pat_passes_with_repo_scope(monkeypatch):
    monkeypatch.setenv("GH_PAT", "ghp_test")
    monkeypatch.setattr(
        secrets_check.requests, "get",
        lambda *a, **k: _FakeResponse(200, json_data={"login": "tiger13tiger"}, headers={"X-OAuth-Scopes": "repo, workflow"}),
    )
    ok, message = secrets_check.check_gh_pat()
    assert ok
    assert "tiger13tiger" in message


def test_check_gh_pat_passes_for_fine_grained_token_with_no_scope_header(monkeypatch):
    monkeypatch.setenv("GH_PAT", "github_pat_test")
    monkeypatch.setattr(
        secrets_check.requests, "get",
        lambda *a, **k: _FakeResponse(200, json_data={"login": "tiger13tiger"}, headers={}),
    )
    ok, message = secrets_check.check_gh_pat()
    assert ok


def test_check_gh_pat_fails_without_repo_scope(monkeypatch):
    monkeypatch.setenv("GH_PAT", "ghp_test")
    monkeypatch.setattr(
        secrets_check.requests, "get",
        lambda *a, **k: _FakeResponse(200, json_data={"login": "tiger13tiger"}, headers={"X-OAuth-Scopes": "read:user"}),
    )
    ok, message = secrets_check.check_gh_pat()
    assert not ok
    assert "repo" in message


def test_check_gh_pat_fails_on_bad_token(monkeypatch):
    monkeypatch.setenv("GH_PAT", "ghp_bad")
    monkeypatch.setattr(secrets_check.requests, "get", lambda *a, **k: _FakeResponse(401))
    ok, message = secrets_check.check_gh_pat()
    assert not ok


def test_main_returns_0_when_everything_passes(monkeypatch, capsys):
    monkeypatch.setattr(secrets_check, "SynapseConnector", _FakeConnector)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("GH_PAT", "ghp_test")
    monkeypatch.setattr(
        secrets_check.requests, "get",
        lambda url, **k: _FakeResponse(200, json_data={"login": "x"}, headers={"X-OAuth-Scopes": "repo"}),
    )
    assert secrets_check.main() == 0
    assert "All secrets check out" in capsys.readouterr().out


def test_main_returns_1_when_one_secret_fails(monkeypatch, capsys):
    monkeypatch.setattr(secrets_check, "SynapseConnector", _FakeConnector)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("GH_PAT", "ghp_test")
    monkeypatch.setattr(
        secrets_check.requests, "get",
        lambda url, **k: _FakeResponse(200, json_data={"login": "x"}, headers={"X-OAuth-Scopes": "repo"}),
    )
    assert secrets_check.main() == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "DEEPSEEK_API_KEY" in out
