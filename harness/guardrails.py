"""Safety checks on a candidate stored procedure before it is ever deployed.

This is a text-level allow-list, not a security boundary on its own — the
connection used to run the evolve loop should also hold least-privilege
credentials scoped to the sandbox schema (document that as an infra control;
don't rely on this regex alone in production).
"""
import re

ALLOWED_DDL_PATTERN = re.compile(r"^\s*CREATE\s+OR\s+ALTER\s+PROCEDURE\b", re.IGNORECASE)
PROCEDURE_NAME_PATTERN = re.compile(r"PROCEDURE\s+\[?(\w+)\]?\.\[?(\w+)\]?", re.IGNORECASE)
FORBIDDEN_KEYWORDS = [
    "DROP DATABASE", "DROP SCHEMA", "TRUNCATE TABLE", "DROP TABLE",
    "sp_configure", "xp_cmdshell", "OPENROWSET", "OPENDATASOURCE",
]


class GuardrailViolation(Exception):
    pass


def check_candidate_sql(sql: str, allowed_schema: str) -> None:
    if not ALLOWED_DDL_PATTERN.match(sql.strip()):
        raise GuardrailViolation(
            "candidate SQL must be a single CREATE OR ALTER PROCEDURE statement"
        )

    upper = sql.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword.upper() in upper:
            raise GuardrailViolation(f"candidate SQL contains forbidden keyword: {keyword}")

    match = PROCEDURE_NAME_PATTERN.search(sql)
    if not match:
        raise GuardrailViolation("could not determine the procedure's schema from the CREATE statement")

    schema_name = match.group(1)
    if schema_name.lower() != allowed_schema.lower():
        raise GuardrailViolation(
            f"candidate procedure must live in schema '{allowed_schema}', got '{schema_name}' "
            "(the evolve loop only ever deploys into the sandbox schema, never dbo/uat/prd directly)"
        )
