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


def test_rejects_truncate_against_a_table_outside_the_allowed_schema():
    sql = (
        "CREATE OR ALTER PROCEDURE sandbox.sp_evil\nAS\nBEGIN\n"
        "  TRUNCATE TABLE dbo.fact_sales;\nEND"
    )
    with pytest.raises(GuardrailViolation):
        check_candidate_sql(sql, allowed_schema="sandbox")


def test_rejects_truncate_against_an_unqualified_table_name():
    # can't confirm the target is in-scope without a schema prefix -- fail safe
    sql = "CREATE OR ALTER PROCEDURE sandbox.sp_x\nAS\nBEGIN\n  TRUNCATE TABLE fact_sales;\nEND"
    with pytest.raises(GuardrailViolation):
        check_candidate_sql(sql, allowed_schema="sandbox")


def test_allows_truncate_against_its_own_allowed_schema():
    # caught by a real CI run: a full-refresh procedure (TRUNCATE + re-INSERT
    # into its own table) is completely normal and must not be blanket-banned
    sql = (
        "CREATE OR ALTER PROCEDURE dbo.sp_refresh_fact_sales\nAS\nBEGIN\n"
        "  TRUNCATE TABLE dbo.fact_sales;\n"
        "  INSERT INTO dbo.fact_sales (revenue) SELECT 1;\nEND"
    )
    check_candidate_sql(sql, allowed_schema="dbo")  # must not raise


def test_absolute_forbidden_keywords_are_rejected_regardless_of_schema():
    sql = "CREATE OR ALTER PROCEDURE dbo.sp_evil\nAS\nBEGIN\n  EXEC xp_cmdshell 'dir';\nEND"
    with pytest.raises(GuardrailViolation):
        check_candidate_sql(sql, allowed_schema="dbo")


def test_accepts_a_candidate_with_a_leading_header_comment():
    # caught by a real CI run: procs/sp_refresh_fact_sales.example.sql starts
    # with an explanatory header comment, which is completely normal SQL and
    # must not trip the "must start with CREATE OR ALTER PROCEDURE" check
    sql = (
        "-- This procedure refreshes the sales fact table.\n"
        "-- Deliberately contains a planted bug for the worked example.\n"
        "CREATE OR ALTER PROCEDURE sandbox.sp_refresh_fact_sales\nAS\nBEGIN\n  SELECT 1;\nEND"
    )
    check_candidate_sql(sql, allowed_schema="sandbox")  # must not raise


def test_accepts_a_candidate_with_a_leading_block_comment():
    sql = (
        "/* This procedure refreshes the sales fact table. */\n"
        "CREATE OR ALTER PROCEDURE sandbox.sp_refresh_fact_sales\nAS\nBEGIN\n  SELECT 1;\nEND"
    )
    check_candidate_sql(sql, allowed_schema="sandbox")  # must not raise
