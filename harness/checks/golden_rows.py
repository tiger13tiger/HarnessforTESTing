"""Compares a query's result rows against a business-verified "golden" row set
(the numbers you already checked by hand in a pivot table), keyed by one or
more dimension columns, with a per-measure tolerance. This is the check type
the auto-fix loop in harness/evolve.py uses as its pass/fail judge."""


def run(connector, params: dict):
    rows = connector.query(params["sql"])
    key_columns = params["key_columns"]
    measures = params["measures"]
    expected_rows = params["expected"]
    strict = params.get("strict", False)

    def key_of(row):
        return tuple(row.get(k) for k in key_columns)

    actual_by_key = {key_of(r): r for r in rows}
    expected_by_key = {key_of(r): r for r in expected_rows}

    missing_keys = [k for k in expected_by_key if k not in actual_by_key]
    extra_keys = [k for k in actual_by_key if k not in expected_by_key]

    mismatches = []
    for key, expected_row in expected_by_key.items():
        if key not in actual_by_key:
            continue
        actual_row = actual_by_key[key]
        for measure, tolerance in measures.items():
            expected_val = expected_row.get(measure)
            actual_val = actual_row.get(measure)
            tolerance_abs = tolerance.get("tolerance_abs", 0)
            # actual_val can be a decimal.Decimal (SQL Server DECIMAL columns, via pyodbc);
            # expected_val is whatever YAML parsed (usually float) -- Decimal - float raises
            # TypeError, so compare as float (tolerance_abs is already a fuzzy comparison,
            # not an exact one, so the precision loss doesn't matter here)
            if expected_val is None or actual_val is None or abs(float(actual_val) - float(expected_val)) > tolerance_abs:
                mismatches.append({
                    "key": key, "measure": measure, "expected": expected_val, "actual": actual_val,
                })

    details = {
        "missing_keys": [list(k) for k in missing_keys],
        "extra_keys": [list(k) for k in extra_keys],
        "mismatches": mismatches,
    }

    failed = bool(missing_keys or mismatches) or (strict and bool(extra_keys))
    if failed:
        return "fail", f"missing_keys={len(missing_keys)} mismatches={len(mismatches)} extra_keys={len(extra_keys)}", details
    return "pass", f"all {len(expected_by_key)} golden rows matched", details
