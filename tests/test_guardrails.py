import pytest

from harness.guardrails import GuardrailViolation, check_candidate_sql

VALID_SQL = "CREATE OR ALTER PROCEDURE sandbox.sp_refresh_fact_sales\nAS\nBEGIN\n  SELECT 1;\nEND"


def test_accepts_a_well_formed_candidate_in_the_allowed_schema():
    check_candidate_sql(VALID_SQL, allowed_schema="sandbox")  # must not raise


def test_rejects_wrong_target_schema():
    sql = "CREATE OR ALTER PROCEDURE dbo.sp_refresh_fact_sales\nAS\nBEGIN\n  SELECT 1;\nEND"
    with pytest.raises(GuardrailViolation):
        check_candidate_sql(sql, allowed_schema="sandbox")


def test_rejects_non_create_or_alter_procedure_statements():
    with pytest.raises(GuardrailViolation):
        check_candidate_sql("DROP TABLE sandbox.fact_sales;", allowed_schema="sandbox")


def test_rejects_forbidden_keyword_even_inside_the_right_schema():
    sql = (
        "CREATE OR ALTER PROCEDURE sandbox.sp_evil\nAS\nBEGIN\n"
        "  TRUNCATE TABLE dbo.fact_sales;\nEND"
    )
    with pytest.raises(GuardrailViolation):
        check_candidate_sql(sql, allowed_schema="sandbox")
