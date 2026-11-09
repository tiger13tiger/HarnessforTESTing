"""Deploys an already-finalized stored procedure (no LLM involved) and runs a
validation suite against it. This is the dev -> uat promotion step: by the
time code reaches here it already converged in harness/evolve.py, so this
only re-checks the guardrail and validates -- it never asks for a fix.

Runs inside one transaction (harness/connector.py's SynapseTransaction) so a
failed promotion rolls back: a broken procedure never stays installed in UAT
just because this step wasn't reviewed by a human. This matters more here
than in evolve.py's sandbox, since promote.py is the one step in the whole
pipeline that runs fully unattended.
"""
from harness.guardrails import check_candidate_sql
from harness.report import gate_failed
from harness.runner import run_suite


def promote(sql: str, exec_statement: str, validation_suite: dict, connector, allowed_schema: str):
    check_candidate_sql(sql, allowed_schema)  # raises GuardrailViolation; caller decides what to do with it

    txn = connector.transaction()
    try:
        try:
            txn.execute(sql)
            txn.execute(exec_statement)
        except Exception:
            txn.rollback()  # don't rely on close()'s implicit behavior for a deploy/exec failure
            raise
        results = run_suite(validation_suite, txn)
        txn.commit() if not gate_failed(results) else txn.rollback()
        return results
    finally:
        txn.close()
