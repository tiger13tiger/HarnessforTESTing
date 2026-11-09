from decimal import Decimal

from harness.checks import golden_rows
from harness.mock_connector import MockConnector

SQL = "SELECT product_category, revenue, txn_count FROM t"
PARAMS = {
    "sql": SQL,
    "key_columns": ["product_category"],
    "measures": {"revenue": {"tolerance_abs": 50}, "txn_count": {"tolerance_abs": 0}},
    "expected": [
        {"product_category": "Electronics", "revenue": 582340.12, "txn_count": 1820},
        {"product_category": "Groceries", "revenue": 128900.55, "txn_count": 940},
    ],
}


def test_passes_when_rows_match_within_tolerance():
    conn = MockConnector({SQL: [
        {"product_category": "Electronics", "revenue": 582360.00, "txn_count": 1820},
        {"product_category": "Groceries", "revenue": 128900.55, "txn_count": 940},
    ]})
    status, _, _ = golden_rows.run(conn, PARAMS)
    assert status == "pass"


def test_fails_on_planted_double_count():
    # planted: a fan-out join roughly doubled Electronics revenue
    conn = MockConnector({SQL: [
        {"product_category": "Electronics", "revenue": 1164680.24, "txn_count": 3640},
        {"product_category": "Groceries", "revenue": 128900.55, "txn_count": 940},
    ]})
    status, _, details = golden_rows.run(conn, PARAMS)
    assert status == "fail"
    assert any(m["key"] == ("Electronics",) for m in details["mismatches"])


def test_fails_when_a_golden_category_is_missing():
    conn = MockConnector({SQL: [{"product_category": "Electronics", "revenue": 582340.12, "txn_count": 1820}]})
    status, _, details = golden_rows.run(conn, PARAMS)
    assert status == "fail"
    assert details["missing_keys"] == [["Groceries"]]


def test_handles_decimal_values_from_a_real_sql_server_decimal_column():
    # caught by a real CI run: pyodbc returns decimal.Decimal for DECIMAL columns,
    # and Decimal - float raises TypeError -- this must not crash the check
    conn = MockConnector({SQL: [
        {"product_category": "Electronics", "revenue": Decimal("582360.00"), "txn_count": 1820},
        {"product_category": "Groceries", "revenue": Decimal("128900.55"), "txn_count": 940},
    ]})
    status, _, _ = golden_rows.run(conn, PARAMS)
    assert status == "pass"


def test_fails_cleanly_not_with_a_typeerror_on_a_decimal_mismatch():
    conn = MockConnector({SQL: [
        {"product_category": "Electronics", "revenue": Decimal("1164680.24"), "txn_count": 3640},
        {"product_category": "Groceries", "revenue": Decimal("128900.55"), "txn_count": 940},
    ]})
    status, _, details = golden_rows.run(conn, PARAMS)
    assert status == "fail"
    assert any(m["key"] == ("Electronics",) for m in details["mismatches"])
