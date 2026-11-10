import pytest

from harness.guardrails import (
    GuardrailViolation,
    check_candidate_sql,
    contains_likely_leak,
    load_blocked_tables,
)

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


def test_rejects_a_second_statement_smuggled_in_after_the_closing_end():
    # Modeled on bank-data-agent-eval's "smuggled_statement" attack: a
    # syntactically valid first statement followed by a second, malicious one
    # in the same batch. The "must start with CREATE OR ALTER PROCEDURE"
    # check alone never catches this -- it only looks at the start.
    sql = VALID_SQL + "; DROP TABLE sandbox.fact_sales;"
    with pytest.raises(GuardrailViolation, match="content after the procedure's closing END"):
        check_candidate_sql(sql, allowed_schema="sandbox")


def test_rejects_a_second_statement_with_no_separating_semicolon():
    sql = VALID_SQL + "\nEXEC sandbox.sp_other"
    with pytest.raises(GuardrailViolation, match="content after the procedure's closing END"):
        check_candidate_sql(sql, allowed_schema="sandbox")


def test_accepts_nested_begin_end_blocks_as_long_as_nothing_follows_the_outer_end():
    # IF/ELSE and TRY/CATCH both introduce their own BEGIN...END -- the check
    # must track nesting depth, not just stop at the first END it sees.
    sql = (
        "CREATE OR ALTER PROCEDURE sandbox.sp_x\nAS\nBEGIN\n"
        "  IF 1 = 1\n  BEGIN\n    SELECT 1;\n  END\n"
        "  ELSE\n  BEGIN\n    SELECT 2;\n  END\n"
        "END"
    )
    check_candidate_sql(sql, allowed_schema="sandbox")  # must not raise


def test_a_begin_or_end_keyword_inside_a_string_literal_does_not_confuse_the_check():
    # A filter value that happens to contain the word "END" (e.g. a product
    # name) must not be mistaken for the procedure body's real closing END.
    sql = (
        "CREATE OR ALTER PROCEDURE sandbox.sp_x\nAS\nBEGIN\n"
        "  SELECT 1 WHERE name = 'Weekend BEGIN Sale END';\n"
        "END"
    )
    check_candidate_sql(sql, allowed_schema="sandbox")  # must not raise


def test_a_begin_or_end_keyword_inside_a_comment_does_not_confuse_the_check():
    sql = (
        "CREATE OR ALTER PROCEDURE sandbox.sp_x\nAS\nBEGIN\n"
        "  -- note: this used to BEGIN differently before the END of Q3\n"
        "  SELECT 1;\n"
        "END"
    )
    check_candidate_sql(sql, allowed_schema="sandbox")  # must not raise


def test_rejects_a_candidate_with_no_balanced_begin_end_block():
    # Fail safe: can't confirm where the procedure body actually ends, so
    # a trailing-statement attack can't be ruled out either.
    sql = "CREATE OR ALTER PROCEDURE sandbox.sp_x\nAS\n  SELECT 1"
    with pytest.raises(GuardrailViolation, match="no balanced BEGIN...END"):
        check_candidate_sql(sql, allowed_schema="sandbox")


def test_load_blocked_tables_returns_empty_set_for_a_missing_file(tmp_path):
    assert load_blocked_tables(str(tmp_path / "does_not_exist.yaml")) == set()


def test_load_blocked_tables_reads_the_configured_list(tmp_path):
    path = tmp_path / "blocked_tables.yaml"
    path.write_text("tables: [customer_pii, account_numbers]\n", encoding="utf-8")
    assert load_blocked_tables(str(path)) == {"customer_pii", "account_numbers"}


def test_rejects_a_candidate_that_references_a_blocked_table(tmp_path):
    path = tmp_path / "blocked_tables.yaml"
    path.write_text("tables: [customer_pii]\n", encoding="utf-8")
    sql = (
        "CREATE OR ALTER PROCEDURE sandbox.sp_x\nAS\nBEGIN\n"
        "  SELECT c.full_name FROM sandbox.customer_pii c;\nEND"
    )
    with pytest.raises(GuardrailViolation, match="blocked-tables list"):
        check_candidate_sql(sql, allowed_schema="sandbox", blocked_tables_path=str(path))


def test_accepts_a_candidate_that_does_not_touch_any_blocked_table(tmp_path):
    path = tmp_path / "blocked_tables.yaml"
    path.write_text("tables: [customer_pii]\n", encoding="utf-8")
    check_candidate_sql(VALID_SQL, allowed_schema="sandbox", blocked_tables_path=str(path))  # must not raise


def test_an_empty_blocklist_blocks_nothing():
    # The repo's real infra/blocked_tables.yaml ships empty by default.
    check_candidate_sql(VALID_SQL, allowed_schema="sandbox", blocked_tables_path="infra/blocked_tables.yaml")


def test_contains_likely_leak_catches_an_email():
    assert contains_likely_leak("contact jane.doe@example.com for details") == "jane.doe@example.com"


def test_contains_likely_leak_catches_an_ssn_shape():
    assert contains_likely_leak("ssn on file: 123-45-6789") == "123-45-6789"


def test_contains_likely_leak_catches_a_phone_shape():
    assert contains_likely_leak("call 415-555-0199 to confirm") == "415-555-0199"


def test_contains_likely_leak_returns_none_for_ordinary_rationale():
    assert contains_likely_leak("removed the fan-out join against store_promotions") is None
