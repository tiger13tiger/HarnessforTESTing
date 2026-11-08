"""Business-logic / regression check: run an aggregate query and compare each
named value either to a fixed expected value (e.g. a finance-reconciled figure)
or to the same query run against a baseline environment (dev/last-prd)."""


def run(connector, params: dict):
    row = connector.query(params["sql"])
    row = row[0] if row else {}

    results = {}
    failures = []

    if "baseline_sql" in params:
        baseline_row = connector.query(params["baseline_sql"])[0]
        tolerance_pct = params.get("tolerance_pct", 0)
        for key, val in row.items():
            base_val = baseline_row.get(key)
            if not base_val:
                diff_pct = 100 if val else 0
            else:
                diff_pct = abs((val - base_val) / base_val) * 100
            results[key] = {"actual": val, "baseline": base_val, "diff_pct": round(diff_pct, 2)}
            if diff_pct > tolerance_pct:
                failures.append(key)
    else:
        expected = params["expected"]
        tolerance_abs = params.get("tolerance_abs", 0)
        for key, expected_val in expected.items():
            actual_val = row.get(key)
            results[key] = {"actual": actual_val, "expected": expected_val}
            if actual_val is None or abs(actual_val - expected_val) > tolerance_abs:
                failures.append(key)

    if failures:
        return "fail", f"mismatched fields: {failures}", results
    return "pass", "all aggregate values within tolerance", results
