"""Null-rate check on a column: either pass a raw SQL returning (total, nulls),
or table/column and the check builds the query itself."""


def run(connector, params: dict):
    threshold = params.get("threshold_pct", 0)

    if "sql" in params:
        row = connector.query(params["sql"])[0]
        total, nulls = row["total"], row["nulls"]
    else:
        table, column = params["table"], params["column"]
        sql = (
            f"SELECT COUNT(*) AS total, "
            f"SUM(CASE WHEN [{column}] IS NULL THEN 1 ELSE 0 END) AS nulls "
            f"FROM {table}"
        )
        row = connector.query(sql)[0]
        total, nulls = row["total"], row["nulls"]

    pct = (nulls / total * 100) if total else 0
    details = {"total": total, "nulls": nulls, "pct": round(pct, 2)}
    if pct > threshold:
        return "fail", f"null rate {pct:.2f}% > threshold {threshold}%", details
    return "pass", f"null rate {pct:.2f}% within threshold {threshold}%", details
