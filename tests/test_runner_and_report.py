"""Tests the orchestration layer: a bad check must not abort the run, and the
pass/fail gate must only trip on blocker-severity failures or errors."""
from harness.mock_connector import MockConnector
from harness.report import gate_failed
from harness.runner import run_suite


def test_one_broken_check_does_not_abort_the_run():
    conn = MockConnector({"SELECT COUNT(*) AS cnt FROM t": [{"cnt": 10}]})
    suite = {
        "checks": [
            {"id": "ok", "type": "row_count", "category": "c", "description": "", "severity": "blocker",
             "params": {"sql": "SELECT COUNT(*) AS cnt FROM t", "expected": 10}},
            {"id": "broken", "type": "row_count", "category": "c", "description": "", "severity": "blocker",
             "params": {"sql": "SELECT COUNT(*) AS cnt FROM missing_fixture"}},
        ]
    }
    results = run_suite(suite, conn, retries=0)
    assert len(results) == 2
    assert results[0].status == "pass"
    assert results[1].status == "error"


def test_gate_fails_on_blocker_failure_but_not_on_warning_failure():
    conn = MockConnector({})

    def result(status, severity):
        from harness.runner import CheckResult
        return CheckResult("x", "c", "", severity, status, "", {}, 0.0)

    assert gate_failed([result("fail", "blocker")]) is True
    assert gate_failed([result("fail", "warning")]) is False
    assert gate_failed([result("pass", "blocker")]) is False
    assert gate_failed([result("error", "warning")]) is True
