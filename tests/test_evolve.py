"""Proves the auto-fix loop itself, with a mock connector and a scripted mock LLM --
no real Synapse connection or API key needed."""
from harness.evolve import evolve
from harness.llm_client import FixSuggestion, MockLLMClient
from harness.mock_connector import MockConnector

CHECK_SQL = "SELECT revenue FROM sandbox.fact_sales"

BUGGY_SQL = "CREATE OR ALTER PROCEDURE sandbox.sp_refresh\nAS\nBEGIN\n  -- planted bug: double counts\n  SELECT 1;\nEND"
FIXED_SQL = "CREATE OR ALTER PROCEDURE sandbox.sp_refresh\nAS\nBEGIN\n  -- fixed\n  SELECT 1;\nEND"

SUITE = {
    "checks": [{
        "id": "revenue_matches_golden",
        "type": "aggregate",
        "category": "business_logic",
        "description": "",
        "severity": "blocker",
        "params": {"sql": CHECK_SQL, "expected": {"revenue": 1000.0}, "tolerance_abs": 1},
    }]
}


def _fixture_tracking_last_deploy(connector):
    # the "database" returns the buggy total until the fixed SQL has been deployed
    if connector.executed and FIXED_SQL in connector.executed[-2]:
        return [{"revenue": 1000.0}]
    return [{"revenue": 2000.0}]  # planted bug: doubled


def test_evolve_succeeds_once_the_llm_fix_lands():
    connector = MockConnector({CHECK_SQL: _fixture_tracking_last_deploy})
    llm = MockLLMClient([FixSuggestion(sql=FIXED_SQL, rationale="removed the fan-out join")])

    success, history = evolve(
        initial_sql=BUGGY_SQL,
        exec_statement="EXEC sandbox.sp_refresh",
        validation_suite=SUITE,
        connector=connector,
        llm_client=llm,
        allowed_schema="sandbox",
        max_iterations=5,
    )

    assert success is True
    assert len(history) == 2
    assert history[0].stage == "validate"
    assert history[0].gate_failed is True
    assert history[1].gate_failed is False
    assert history[0].rationale == "removed the fan-out join"
    # the failing attempt rolled back, the passing one committed
    assert connector.rolled_back == 1
    assert connector.committed == 1


def test_evolve_fails_cleanly_when_the_llm_never_fixes_it():
    connector = MockConnector({CHECK_SQL: [{"revenue": 2000.0}]})  # always wrong
    llm = MockLLMClient([
        FixSuggestion(sql=BUGGY_SQL, rationale="attempt 1"),
        FixSuggestion(sql=BUGGY_SQL, rationale="attempt 2"),
    ])

    success, history = evolve(
        initial_sql=BUGGY_SQL,
        exec_statement="EXEC sandbox.sp_refresh",
        validation_suite=SUITE,
        connector=connector,
        llm_client=llm,
        allowed_schema="sandbox",
        max_iterations=3,
    )

    assert success is False
    assert len(history) == 3
    assert all(it.gate_failed for it in history)
    assert connector.rolled_back == 3
    assert connector.committed == 0


def test_evolve_rejects_a_candidate_outside_the_sandbox_schema_without_deploying_it():
    connector = MockConnector({})
    llm = MockLLMClient([])  # must never be called

    success, history = evolve(
        initial_sql="CREATE OR ALTER PROCEDURE dbo.sp_refresh\nAS\nBEGIN\n  SELECT 1;\nEND",
        exec_statement="EXEC dbo.sp_refresh",
        validation_suite=SUITE,
        connector=connector,
        llm_client=llm,
        allowed_schema="sandbox",
        max_iterations=3,
    )

    assert success is False
    assert len(history) == 1
    assert history[0].stage == "guardrail"
    assert "sandbox" in history[0].error
    assert connector.executed == []  # never deployed
    assert llm.calls == []  # never asked for a fix


def test_evolve_rolls_back_and_reports_a_deploy_failure_distinctly_from_a_check_failure():
    # planted: the candidate's CREATE OR ALTER PROCEDURE itself fails (e.g. a syntax error)
    # (MockConnector normalizes whitespace before matching, so the key must be pre-normalized too)
    normalized_buggy_sql = " ".join(BUGGY_SQL.split())
    connector = MockConnector(execute_errors={normalized_buggy_sql: RuntimeError("incorrect syntax near 'BEGIN'")})
    llm = MockLLMClient([FixSuggestion(sql=FIXED_SQL, rationale="fixed the syntax error")])
    # second attempt deploys fine and the check passes
    connector.fixtures[CHECK_SQL] = [{"revenue": 1000.0}]

    success, history = evolve(
        initial_sql=BUGGY_SQL,
        exec_statement="EXEC sandbox.sp_refresh",
        validation_suite=SUITE,
        connector=connector,
        llm_client=llm,
        allowed_schema="sandbox",
        max_iterations=5,
    )

    assert success is True
    assert history[0].stage == "deploy"
    assert "syntax" in history[0].error
    assert history[0].results == []  # distinct from a check-level failure, which would have results
    assert connector.rolled_back == 1  # the failed deploy attempt was rolled back (a no-op, but explicit)


def test_evolve_fails_cleanly_instead_of_crashing_when_the_llm_keeps_erroring(monkeypatch):
    monkeypatch.setattr("harness.evolve.time.sleep", lambda _seconds: None)  # skip the real backoff delay
    connector = MockConnector({CHECK_SQL: [{"revenue": 2000.0}]})  # always wrong, so a fix is always requested

    class _AlwaysBrokenLLM:
        def suggest_fix(self, *args, **kwargs):
            raise ConnectionError("simulated API outage")

    success, history = evolve(
        initial_sql=BUGGY_SQL,
        exec_statement="EXEC sandbox.sp_refresh",
        validation_suite=SUITE,
        connector=connector,
        llm_client=_AlwaysBrokenLLM(),
        allowed_schema="sandbox",
        max_iterations=5,
        llm_retries=1,
    )

    assert success is False
    assert history[-1].stage == "llm"
    assert "simulated API outage" in history[-1].error
    # stopped after the first validate attempt + the exhausted LLM retry, not all 5 iterations
    assert len(history) == 2
