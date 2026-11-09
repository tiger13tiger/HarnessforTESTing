"""Measures harness/evolve.py's own behavior across representative bug patterns --
not whether a particular LLM is good at SQL, but whether the loop converges, stops
cleanly, and reports correctly under each kind of failure it's built to handle.
This is the "verify the evaluator before trusting it" step from the AI-eval-harness
playbook this project borrowed from (build-eval-harness's Step 6), applied to the
fix loop itself: run it against known scenarios with a scripted LLM standing in for
the real one, and check it does what it's supposed to before trusting it on a real
procedure and a real API key.

No real Synapse connection or LLM API key is used here -- every case is built on
MockConnector + a scripted LLM client, the same tools harness/evolve.py's own unit
tests use. That proves the loop's *mechanics* (convergence, rollback, stage tagging,
guardrail enforcement, LLM fault tolerance); it does NOT measure how often a real
model actually proposes a correct fix for a real bug -- that number can only come
from running evolve_cli.py against real procedures and counting outcomes over time.
"""
from dataclasses import dataclass, field

from harness.evolve import evolve
from harness.llm_client import FixSuggestion, MockLLMClient
from harness.mock_connector import MockConnector

CHECK_SQL = "SELECT revenue FROM sandbox.fact_sales"
EXEC_STATEMENT = "EXEC sandbox.sp_refresh"
GOOD_SCHEMA = "sandbox"

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


def _proc(tag: str, schema: str = GOOD_SCHEMA) -> str:
    return f"CREATE OR ALTER PROCEDURE {schema}.sp_refresh\nAS\nBEGIN\n  -- {tag}\n  SELECT 1;\nEND"


def _tracking_fixture(correct_sql: str):
    """A query fixture that returns the golden revenue once `correct_sql` is the most
    recently deployed candidate, and a wrong value otherwise."""
    normalized_correct = " ".join(correct_sql.split())

    def fixture(connector):
        if connector.executed and normalized_correct in " ".join(connector.executed[-2].split()):
            return [{"revenue": 1000.0}]
        return [{"revenue": 2000.0}]

    return fixture


@dataclass
class CaseResult:
    name: str
    expected_success: bool
    actual_success: bool
    iterations: int
    final_stage: str
    matched_expectation: bool = field(init=False)

    def __post_init__(self):
        self.matched_expectation = self.actual_success == self.expected_success


@dataclass
class BenchmarkReport:
    cases: list[CaseResult]

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def matched_expectation_count(self) -> int:
        return sum(1 for c in self.cases if c.matched_expectation)

    @property
    def avg_iterations_to_success(self) -> float | None:
        successes = [c.iterations for c in self.cases if c.actual_success]
        return sum(successes) / len(successes) if successes else None


def _case_fixes_immediately():
    buggy = _proc("planted bug")
    fixed = _proc("fixed")
    connector = MockConnector({CHECK_SQL: _tracking_fixture(fixed)})
    llm = MockLLMClient([FixSuggestion(sql=fixed, rationale="fixed on first try")])
    return buggy, llm, connector, 5, True


def _case_fixes_after_three_tries():
    wrong1, wrong2, wrong3 = _proc("wrong 1"), _proc("wrong 2"), _proc("wrong 3")
    fixed = _proc("finally fixed")
    connector = MockConnector({CHECK_SQL: _tracking_fixture(fixed)})
    llm = MockLLMClient([
        FixSuggestion(sql=wrong2, rationale="attempt 1, still wrong"),
        FixSuggestion(sql=wrong3, rationale="attempt 2, still wrong"),
        FixSuggestion(sql=fixed, rationale="attempt 3, fixed"),
    ])
    return wrong1, llm, connector, 5, True


def _case_never_converges():
    buggy = _proc("never fixed")
    connector = MockConnector({CHECK_SQL: [{"revenue": 2000.0}]})  # always wrong, no fixture tracking needed
    llm = MockLLMClient([
        FixSuggestion(sql=buggy, rationale="attempt 1"),
        FixSuggestion(sql=buggy, rationale="attempt 2"),
    ])
    return buggy, llm, connector, 3, False


def _case_multi_stage_chain():
    """Syntax error -> fixed syntax but runtime EXEC error -> fixed that but wrong
    data -> fixed logic. Exercises all three failure stages in one run."""
    syntax_broken = _proc("syntax broken")
    exec_broken = _proc("exec broken")
    data_wrong = _proc("data wrong")
    fixed = _proc("fully fixed")

    normalized_syntax_broken = " ".join(syntax_broken.split())
    normalized_exec_broken = " ".join(exec_broken.split())

    connector = MockConnector(
        fixtures={CHECK_SQL: _tracking_fixture(fixed)},
        execute_errors={normalized_syntax_broken: RuntimeError("incorrect syntax near 'BEGIN'")},
    )

    original_execute = connector.execute

    def execute_with_exec_stage_bug(sql, params=None):
        normalized_sql = " ".join(sql.split())
        last_deployed = " ".join(connector.executed[-1].split()) if connector.executed else ""
        if normalized_sql == EXEC_STATEMENT and last_deployed == normalized_exec_broken:
            raise RuntimeError("Invalid object name 'dbo.raw_sales'")
        original_execute(sql, params)

    connector.execute = execute_with_exec_stage_bug

    llm = MockLLMClient([
        FixSuggestion(sql=exec_broken, rationale="fixed the syntax error"),
        FixSuggestion(sql=data_wrong, rationale="fixed the missing-table reference"),
        FixSuggestion(sql=fixed, rationale="fixed the double-counted revenue"),
    ])
    return syntax_broken, llm, connector, 5, True


def _case_llm_flake_then_recovers():
    buggy = _proc("needs a fix")
    fixed = _proc("recovered")
    connector = MockConnector({CHECK_SQL: _tracking_fixture(fixed)})

    class _FlakyLLM:
        def __init__(self):
            self.calls = 0

        def suggest_fix(self, original_sql, failing_checks, context, stage="validate"):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("simulated transient API error")
            return FixSuggestion(sql=fixed, rationale="recovered after the retry")

    return buggy, _FlakyLLM(), connector, 5, True


def _case_llm_proposes_wrong_schema():
    buggy = _proc("needs a fix")
    bad_schema_fix = _proc("wrong schema fix", schema="dbo")  # guardrail must reject this
    connector = MockConnector({CHECK_SQL: [{"revenue": 2000.0}]})
    llm = MockLLMClient([FixSuggestion(sql=bad_schema_fix, rationale="oops, wrong schema")])
    return buggy, llm, connector, 5, False


CASES = {
    "fixes_immediately": _case_fixes_immediately,
    "fixes_after_three_tries": _case_fixes_after_three_tries,
    "never_converges": _case_never_converges,
    "multi_stage_chain": _case_multi_stage_chain,
    "llm_flake_then_recovers": _case_llm_flake_then_recovers,
    "llm_proposes_wrong_schema": _case_llm_proposes_wrong_schema,
}


def run_benchmark() -> BenchmarkReport:
    results = []
    for name, build in CASES.items():
        initial_sql, llm_client, connector, max_iterations, expected_success = build()
        actual_success, history = evolve(
            initial_sql=initial_sql,
            exec_statement=EXEC_STATEMENT,
            validation_suite=SUITE,
            connector=connector,
            llm_client=llm_client,
            allowed_schema=GOOD_SCHEMA,
            max_iterations=max_iterations,
            llm_retries=1,
        )
        results.append(CaseResult(
            name=name,
            expected_success=expected_success,
            actual_success=actual_success,
            iterations=len(history),
            final_stage=history[-1].stage if history else "none",
        ))
    return BenchmarkReport(cases=results)
