"""Tests open_transaction_with_retries in isolation -- no real Synapse connection."""
import pytest

from harness.connector import TransientError, open_transaction_with_retries


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
