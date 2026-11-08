"""Row count checks: absolute bounds, exact expected value, or drift vs. a baseline query
(e.g. compare UAT row count against DEV, or against last PRD run)."""


def run(connector, params: dict):
    count_column = params.get("count_column", "cnt")
    rows = connector.query(params["sql"])
    count = rows[0][count_column] if rows else 0

    if "baseline_sql" in params:
        baseline_rows = connector.query(params["baseline_sql"])
        baseline = baseline_rows[0][count_column] if baseline_rows else 0
        tolerance_pct = params.get("tolerance_pct", 0)
        diff_pct = (abs(count - baseline) / baseline * 100) if baseline else (100 if count else 0)
        details = {"count": count, "baseline": baseline, "diff_pct": round(diff_pct, 2)}
        if diff_pct > tolerance_pct:
            return "fail", f"row count {count} vs baseline {baseline} (diff {diff_pct:.2f}% > {tolerance_pct}%)", details
        return "pass", f"row count {count} within {tolerance_pct}% of baseline {baseline}", details

    expected = params.get("expected")
    if expected is not None:
        details = {"count": count, "expected": expected}
        if count != expected:
            return "fail", f"row count {count} != expected {expected}", details
        return "pass", f"row count {count} == expected {expected}", details

    min_v, max_v = params.get("min"), params.get("max")
    details = {"count": count, "min": min_v, "max": max_v}
    if min_v is not None and count < min_v:
        return "fail", f"row count {count} < min {min_v}", details
    if max_v is not None and count > max_v:
        return "fail", f"row count {count} > max {max_v}", details
    return "pass", f"row count {count} within [{min_v}, {max_v}]", details
