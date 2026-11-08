"""Checks that a table is actually safe to hand to end users as a pivot-table source:
required columns present, dimension columns not full of NULLs (NULL dimension values
collapse into a useless pivot group), dimension cardinality within a sane bound
(a blown-up cardinality usually means a join fan-out or a dirty key), and measure
columns are numeric (a measure stored as text silently breaks SUM/AVG in Excel)."""

from .schema import _split_table


def run(connector, params: dict):
    table = params["table"]
    schema_name, table_name = _split_table(table)

    sql = (
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = '{schema_name}' AND TABLE_NAME = '{table_name}'"
    )
    columns = {r["COLUMN_NAME"]: r["DATA_TYPE"] for r in connector.query(sql)}

    required = params.get("required_columns", [])
    missing = [c for c in required if c not in columns]

    numeric_types = {"int", "bigint", "smallint", "tinyint", "decimal", "numeric", "float", "real", "money"}
    measure_columns = params.get("measure_columns", [])
    non_numeric_measures = [c for c in measure_columns if c in columns and columns[c].lower() not in numeric_types]

    dimension_issues = []
    for dim_col, dim_params in params.get("dimension_columns", {}).items():
        if dim_col not in columns:
            continue
        max_cardinality = dim_params.get("max_cardinality")
        null_threshold_pct = dim_params.get("null_threshold_pct", 0)

        stats_sql = (
            f"SELECT COUNT(*) AS total, "
            f"SUM(CASE WHEN [{dim_col}] IS NULL THEN 1 ELSE 0 END) AS nulls, "
            f"COUNT(DISTINCT [{dim_col}]) AS distinct_count "
            f"FROM {table}"
        )
        stats = connector.query(stats_sql)[0]
        total, nulls, distinct_count = stats["total"], stats["nulls"], stats["distinct_count"]
        null_pct = (nulls / total * 100) if total else 0

        if null_pct > null_threshold_pct:
            dimension_issues.append(f"{dim_col}: null rate {null_pct:.2f}% > {null_threshold_pct}%")
        if max_cardinality is not None and distinct_count > max_cardinality:
            dimension_issues.append(f"{dim_col}: cardinality {distinct_count} > max {max_cardinality}")

    details = {
        "missing_required": missing,
        "non_numeric_measures": non_numeric_measures,
        "dimension_issues": dimension_issues,
    }
    if missing or non_numeric_measures or dimension_issues:
        return "fail", (
            f"missing={missing} non_numeric_measures={non_numeric_measures} "
            f"dimension_issues={dimension_issues}"
        ), details
    return "pass", "table is pivot-table ready", details
