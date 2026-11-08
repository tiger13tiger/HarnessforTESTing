"""Unit tests for check logic, using MockConnector fixtures instead of a real Synapse connection.

Each check has a 'clean' case that must pass, and a 'planted defect' case that must fail —
proving the check actually catches the problem it's meant to catch, not just that it runs.
"""
from harness.checks import aggregate, duplicates, null_rate, pivot_readiness, row_count, schema
from harness.mock_connector import MockConnector


def test_row_count_pass_within_tolerance():
    conn = MockConnector({
        "SELECT COUNT(*) AS cnt FROM t": [{"cnt": 100}],
        "SELECT COUNT(*) AS cnt FROM dev_t": [{"cnt": 98}],
    })
    status, _, _ = row_count.run(conn, {
        "sql": "SELECT COUNT(*) AS cnt FROM t",
        "baseline_sql": "SELECT COUNT(*) AS cnt FROM dev_t",
        "tolerance_pct": 5,
    })
    assert status == "pass"


def test_row_count_fails_on_planted_drift():
    conn = MockConnector({
        "SELECT COUNT(*) AS cnt FROM t": [{"cnt": 100}],
        "SELECT COUNT(*) AS cnt FROM dev_t": [{"cnt": 50}],  # planted: UAT lost half its rows
    })
    status, _, _ = row_count.run(conn, {
        "sql": "SELECT COUNT(*) AS cnt FROM t",
        "baseline_sql": "SELECT COUNT(*) AS cnt FROM dev_t",
        "tolerance_pct": 5,
    })
    assert status == "fail"


def test_null_rate_pass_when_clean():
    conn = MockConnector({"SELECT COUNT(*) AS total, SUM(CASE WHEN [store_id] IS NULL THEN 1 ELSE 0 END) AS nulls FROM t":
                          [{"total": 1000, "nulls": 0}]})
    status, _, _ = null_rate.run(conn, {"table": "t", "column": "store_id", "threshold_pct": 0})
    assert status == "pass"


def test_null_rate_fails_on_planted_nulls():
    conn = MockConnector({"SELECT COUNT(*) AS total, SUM(CASE WHEN [store_id] IS NULL THEN 1 ELSE 0 END) AS nulls FROM t":
                          [{"total": 1000, "nulls": 50}]})  # planted: 5% of store_id is NULL
    status, _, _ = null_rate.run(conn, {"table": "t", "column": "store_id", "threshold_pct": 0})
    assert status == "fail"


def test_duplicates_pass_when_unique():
    conn = MockConnector({
        "SELECT COUNT(*) AS dup_count FROM (SELECT [sale_id], COUNT(*) AS c FROM t GROUP BY [sale_id] HAVING COUNT(*) > 1) t":
            [{"dup_count": 0}],
    })
    status, _, _ = duplicates.run(conn, {"table": "t", "key_columns": ["sale_id"]})
    assert status == "pass"


def test_duplicates_fails_on_planted_dupes():
    conn = MockConnector({
        "SELECT COUNT(*) AS dup_count FROM (SELECT [sale_id], COUNT(*) AS c FROM t GROUP BY [sale_id] HAVING COUNT(*) > 1) t":
            [{"dup_count": 3}],  # planted: 3 sale_id values repeated
    })
    status, _, _ = duplicates.run(conn, {"table": "t", "key_columns": ["sale_id"]})
    assert status == "fail"


def test_schema_pass_when_matching():
    conn = MockConnector({
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'fact_sales'":
            [{"COLUMN_NAME": "sale_id", "DATA_TYPE": "bigint"}, {"COLUMN_NAME": "revenue", "DATA_TYPE": "decimal"}],
    })
    status, _, _ = schema.run(conn, {
        "table": "dbo.fact_sales",
        "expected_columns": [{"name": "sale_id", "type": "bigint"}, {"name": "revenue", "type": "decimal"}],
    })
    assert status == "pass"


def test_schema_fails_on_planted_type_change():
    conn = MockConnector({
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'fact_sales'":
            [{"COLUMN_NAME": "sale_id", "DATA_TYPE": "bigint"}, {"COLUMN_NAME": "revenue", "DATA_TYPE": "varchar"}],
            # planted: revenue silently became varchar in dev, which would break SUM() in the pivot table
    })
    status, _, details = schema.run(conn, {
        "table": "dbo.fact_sales",
        "expected_columns": [{"name": "sale_id", "type": "bigint"}, {"name": "revenue", "type": "decimal"}],
    })
    assert status == "fail"
    assert "revenue" in details["type_mismatches"]


def test_aggregate_pass_within_tolerance():
    conn = MockConnector({"SELECT SUM(revenue) AS total_revenue FROM t": [{"total_revenue": 100050.0}]})
    status, _, _ = aggregate.run(conn, {
        "sql": "SELECT SUM(revenue) AS total_revenue FROM t",
        "expected": {"total_revenue": 100000.0},
        "tolerance_abs": 100,
    })
    assert status == "pass"


def test_aggregate_fails_on_planted_calc_error():
    conn = MockConnector({"SELECT SUM(revenue) AS total_revenue FROM t": [{"total_revenue": 85000.0}]})
    # planted: a join fan-out or double-count dropped total revenue by 15%
    status, _, _ = aggregate.run(conn, {
        "sql": "SELECT SUM(revenue) AS total_revenue FROM t",
        "expected": {"total_revenue": 100000.0},
        "tolerance_abs": 100,
    })
    assert status == "fail"


def test_pivot_readiness_pass_when_clean():
    conn = MockConnector({
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'fact_sales'":
            [
                {"COLUMN_NAME": "store_id", "DATA_TYPE": "int"},
                {"COLUMN_NAME": "revenue", "DATA_TYPE": "decimal"},
                {"COLUMN_NAME": "product_category", "DATA_TYPE": "varchar"},
            ],
        "SELECT COUNT(*) AS total, SUM(CASE WHEN [product_category] IS NULL THEN 1 ELSE 0 END) AS nulls, COUNT(DISTINCT [product_category]) AS distinct_count FROM dbo.fact_sales":
            [{"total": 1000, "nulls": 0, "distinct_count": 20}],
    })
    status, _, _ = pivot_readiness.run(conn, {
        "table": "dbo.fact_sales",
        "required_columns": ["store_id", "revenue", "product_category"],
        "measure_columns": ["revenue"],
        "dimension_columns": {"product_category": {"max_cardinality": 500, "null_threshold_pct": 0}},
    })
    assert status == "pass"


def test_pivot_readiness_fails_on_planted_cardinality_blowup():
    conn = MockConnector({
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'fact_sales'":
            [
                {"COLUMN_NAME": "store_id", "DATA_TYPE": "int"},
                {"COLUMN_NAME": "revenue", "DATA_TYPE": "decimal"},
                {"COLUMN_NAME": "product_category", "DATA_TYPE": "varchar"},
            ],
        "SELECT COUNT(*) AS total, SUM(CASE WHEN [product_category] IS NULL THEN 1 ELSE 0 END) AS nulls, COUNT(DISTINCT [product_category]) AS distinct_count FROM dbo.fact_sales":
            # planted: a join fan-out exploded product_category cardinality from ~20 to ~5000
            [{"total": 1000, "nulls": 0, "distinct_count": 5000}],
    })
    status, _, details = pivot_readiness.run(conn, {
        "table": "dbo.fact_sales",
        "required_columns": ["store_id", "revenue", "product_category"],
        "measure_columns": ["revenue"],
        "dimension_columns": {"product_category": {"max_cardinality": 500, "null_threshold_pct": 0}},
    })
    assert status == "fail"
    assert details["dimension_issues"]
