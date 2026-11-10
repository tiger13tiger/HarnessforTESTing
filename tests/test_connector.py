"""Tests open_transaction_with_retries in isolation -- no real Synapse connection."""
import pytest

from harness.connector import (
    MAX_QUERY_ROWS,
    QueryTooLarge,
    TransientError,
    _fetch_capped,
    _is_transient,
    open_transaction_with_retries,
    redact_secret,
)


class _FakeCursor:
    """Enough of a DB-API cursor for _fetch_capped: description + fetchmany + fetchone."""

    def __init__(self, columns, rows):
        self.description = [(c,) for c in columns] if columns else None
        self._rows = list(rows)

    def fetchmany(self, n):
        batch, self._rows = self._rows[:n], self._rows[n:]
        return batch

    def fetchone(self):
        return self._rows[0] if self._rows else None


def test_fetch_capped_returns_rows_as_dicts_under_the_cap():
    cursor = _FakeCursor(["a", "b"], [(1, 2), (3, 4)])
    assert _fetch_capped(cursor) == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]


def test_fetch_capped_returns_empty_list_for_a_non_query_statement():
    cursor = _FakeCursor(None, [])
    assert _fetch_capped(cursor) == []


def test_fetch_capped_raises_when_more_rows_remain_past_the_cap():
    cursor = _FakeCursor(["a"], [(i,) for i in range(MAX_QUERY_ROWS + 1)])
    with pytest.raises(QueryTooLarge, match=str(MAX_QUERY_ROWS)):
        _fetch_capped(cursor)


def test_fetch_capped_does_not_raise_exactly_at_the_cap():
    cursor = _FakeCursor(["a"], [(i,) for i in range(MAX_QUERY_ROWS)])
    rows = _fetch_capped(cursor)
    assert len(rows) == MAX_QUERY_ROWS


def test_redact_secret_strips_the_whole_connection_string():
    conn_str = "Driver={ODBC Driver 18};Server=x;Database=y;UID=u;PWD=hunter2"
    text = f"login failed, conn={conn_str}"
    assert conn_str not in redact_secret(text, conn_str)
    assert "***REDACTED-CONN-STR***" in redact_secret(text, conn_str)


def test_redact_secret_strips_just_the_password_if_echoed_alone():
    conn_str = "Driver={ODBC Driver 18};Server=x;Database=y;UID=u;PWD=hunter2"
    text = "authentication failed for password hunter2"
    redacted = redact_secret(text, conn_str)
    assert "hunter2" not in redacted
    assert "***REDACTED-PWD***" in redacted


def test_redact_secret_is_a_no_op_with_no_secrets_present():
    text = "some unrelated error"
    assert redact_secret(text, None) == text


def test_redact_secret_handles_empty_text():
    assert redact_secret("", "Driver=x;PWD=hunter2") == ""


def test_classifies_azure_serverless_resume_error_as_transient():
    # Caught by a real CI run: a serverless Azure SQL database waking up from
    # auto-pause raises pyodbc.Error with SQLSTATE 'HY000' (the generic ODBC
    # state) and the real Azure error number (40613) only inside the message
    # text -- checking args[0] alone (the old logic) never matched this, so
    # it propagated as a raw, uncaught error instead of retrying.
    exc = Exception(
        "HY000",
        "[HY000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
        "Database 'dev' on server '...' is not currently available. "
        "Please retry the connection later. (40613) (SQLDriverConnect)",
    )
    assert _is_transient(exc)


def test_does_not_classify_an_ordinary_error_as_transient():
    exc = Exception("42S02", "[42S02] Invalid object name 'dbo.fact_sales'.")
    assert not _is_transient(exc)


class _FlakyThenOk:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def transaction(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TransientError(f"login timeout on call {self.calls}")
        return "a transaction object"


def test_retries_and_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr("harness.connector.time.sleep", lambda _s: None)
    connector = _FlakyThenOk(fail_times=2)
    result = open_transaction_with_retries(connector, retries=2)
    assert result == "a transaction object"
    assert connector.calls == 3


def test_raises_once_retries_are_exhausted(monkeypatch):
    monkeypatch.setattr("harness.connector.time.sleep", lambda _s: None)
    connector = _FlakyThenOk(fail_times=5)  # never succeeds within the retry budget
    with pytest.raises(TransientError):
        open_transaction_with_retries(connector, retries=2)
    assert connector.calls == 3  # 1 initial + 2 retries, not more
