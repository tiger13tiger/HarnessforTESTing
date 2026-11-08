"""Uniqueness check on key columns: pass raw SQL returning dup_count,
or table + key_columns and the check builds the GROUP BY ... HAVING COUNT(*) > 1 query."""


def run(connector, params: dict):
    if "sql" in params:
        sql = params["sql"]
    else:
        table = params["table"]
        key_list = ", ".join(f"[{k}]" for k in params["key_columns"])
        sql = (
            f"SELECT COUNT(*) AS dup_count FROM ("
            f"SELECT {key_list}, COUNT(*) AS c FROM {table} "
            f"GROUP BY {key_list} HAVING COUNT(*) > 1"
            f") t"
        )

    dup_count = connector.query(sql)[0]["dup_count"]
    allowed = params.get("allowed", 0)
    details = {"dup_count": dup_count, "allowed": allowed}
    if dup_count > allowed:
        return "fail", f"{dup_count} duplicate key groups found (allowed {allowed})", details
    return "pass", f"no unexpected duplicate keys ({dup_count} <= {allowed})", details
