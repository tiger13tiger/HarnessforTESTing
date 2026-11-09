import pytest

from harness.guardrails import GuardrailViolation
from harness.mock_connector import MockConnector
from harness.promote import promote

CHECK_SQL = "SELECT revenue FROM dbo.fact_sales"
SQL_OK = "CREATE OR ALTER PROCEDURE dbo.sp_refresh\nAS\nBEGIN\n  SELECT 1;\nEND"
SUITE = {"checks": [{
    "id": "ok", "type": "aggregate", "category": "c", "description": "", "severity": "blocker",
    "params": {"sql": CHECK_SQL, "expected": {"revenue": 100.0}, "tolerance_abs": 1},
}]}


def test_promote_deploys_then_validates_and_commits_on_pass():
    conn = MockConnector({CHECK_SQL: [{"revenue": 100.0}]})
    results = promote(SQL_OK, "EXEC dbo.sp_refresh", SUITE, conn, allowed_schema="dbo")
    assert results[0].status == "pass"
    assert conn.executed == [SQL_OK, "EXEC dbo.sp_refresh"]
    assert conn.committed == 1
    assert conn.rolled_back == 0


def test_promote_rejects_wrong_schema_without_deploying():
    conn = MockConnector({})
    sql = "CREATE OR ALTER PROCEDURE other.sp_refresh\nAS\nBEGIN\n  SELECT 1;\nEND"
    with pytest.raises(GuardrailViolation):
        promote(sql, "EXEC other.sp_refresh", SUITE, conn, allowed_schema="dbo")
    assert conn.executed == []


def test_promote_rolls_back_instead_of_leaving_a_broken_proc_installed():
    conn = MockConnector({CHECK_SQL: [{"revenue": 50.0}]})  # planted: doesn't match UAT's golden figure
    results = promote(SQL_OK, "EXEC dbo.sp_refresh", SUITE, conn, allowed_schema="dbo")
    assert results[0].status == "fail"
    assert conn.rolled_back == 1
    assert conn.committed == 0


def test_promote_rolls_back_on_a_deploy_failure_too():
    normalized_sql_ok = " ".join(SQL_OK.split())
    conn = MockConnector(execute_errors={normalized_sql_ok: RuntimeError("incorrect syntax")})
    with pytest.raises(RuntimeError):
        promote(SQL_OK, "EXEC dbo.sp_refresh", SUITE, conn, allowed_schema="dbo")
    assert conn.rolled_back == 1
    assert conn.committed == 0
