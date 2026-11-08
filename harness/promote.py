"""Deploys an already-finalized stored procedure (no LLM involved) and runs a
validation suite against it. This is the dev -> uat promotion step: by the
time code reaches here it already converged in harness/evolve.py, so this
only re-checks the guardrail and validates -- it never asks for a fix."""
from harness.guardrails import check_candidate_sql
from harness.runner import run_suite


def promote(sql: str, exec_statement: str, validation_suite: dict, connector, allowed_schema: str):
    check_candidate_sql(sql, allowed_schema)  # raises GuardrailViolation; caller decides what to do with it
    connector.execute(sql)
    connector.execute(exec_statement)
    return run_suite(validation_suite, connector)
