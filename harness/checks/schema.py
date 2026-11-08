"""Schema check: compares INFORMATION_SCHEMA.COLUMNS against an expected column list,
to catch a DEV change (renamed/retyped/dropped column) that never made it into UAT,
or that silently breaks the pivot table template downstream."""


def _split_table(table: str):
    if "." in table:
        schema_name, table_name = table.split(".", 1)
    else:
        schema_name, table_name = "dbo", table
    return schema_name, table_name


def run(connector, params: dict):
    table = params["table"]
    schema_name, table_name = _split_table(table)
    sql = (
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = '{schema_name}' AND TABLE_NAME = '{table_name}'"
    )
    rows = connector.query(sql)
    actual = {r["COLUMN_NAME"]: r["DATA_TYPE"] for r in rows}
    expected = {c["name"]: c["type"] for c in params["expected_columns"]}

    missing = [c for c in expected if c not in actual]
    type_mismatches = [
        c for c in expected if c in actual and actual[c].lower() != expected[c].lower()
    ]
    extra = [] if params.get("allow_extra", True) else [c for c in actual if c not in expected]

    details = {"missing": missing, "type_mismatches": type_mismatches, "extra": extra}
    if missing or type_mismatches or extra:
        return "fail", f"missing={missing} type_mismatches={type_mismatches} extra={extra}", details
    return "pass", "schema matches expected definition", details
