"""Safety checks on a candidate stored procedure before it is ever deployed.

This is a text-level allow-list, not a security boundary on its own — the
connection used to run the evolve loop should also hold least-privilege
credentials scoped to the sandbox schema (document that as an infra control;
don't rely on this regex alone in production).
"""
import re

ALLOWED_DDL_PATTERN = re.compile(r"^\s*CREATE\s+OR\s+ALTER\s+PROCEDURE\b", re.IGNORECASE)
LEADING_COMMENT_PATTERN = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/)\s*", re.DOTALL)
PROCEDURE_NAME_PATTERN = re.compile(r"PROCEDURE\s+\[?(\w+)\]?\.\[?(\w+)\]?", re.IGNORECASE)

# Always forbidden, anywhere in the SQL: nothing a normal data-refresh procedure
# would ever need, and no legitimate reason to allow an exception by schema.
ABSOLUTE_FORBIDDEN_KEYWORDS = [
    "DROP DATABASE", "DROP SCHEMA", "sp_configure", "xp_cmdshell", "OPENROWSET", "OPENDATASOURCE",
]

# TRUNCATE/DROP TABLE are NOT banned outright -- a full-refresh procedure
# (TRUNCATE + re-INSERT) is completely normal and is exactly what our own
# example does. They're only a problem if the target is outside the schema
# this candidate is allowed to touch. Schema-unqualified targets are treated
# as a violation too: if we can't confirm the target is in-scope, fail safe.
SCOPED_TABLE_OP_PATTERN = re.compile(
    r"\b(TRUNCATE\s+TABLE|DROP\s+TABLE)\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?", re.IGNORECASE
)


class GuardrailViolation(Exception):
    pass


def _strip_leading_comments(sql: str) -> str:
    """Strips leading `--` line comments and `/* */` block comments (a header
    explaining what the procedure does is completely normal SQL and must not
    trip the "must start with CREATE OR ALTER PROCEDURE" check)."""
    stripped = sql.strip()
    while True:
        match = LEADING_COMMENT_PATTERN.match(stripped)
        if not match:
            return stripped
        stripped = stripped[match.end():]


def check_candidate_sql(sql: str, allowed_schema: str) -> None:
    if not ALLOWED_DDL_PATTERN.match(_strip_leading_comments(sql)):
        raise GuardrailViolation(
            "candidate SQL must be a single CREATE OR ALTER PROCEDURE statement"
        )

    upper = sql.upper()
    for keyword in ABSOLUTE_FORBIDDEN_KEYWORDS:
        if keyword.upper() in upper:
            raise GuardrailViolation(f"candidate SQL contains forbidden keyword: {keyword}")

    for op_match in SCOPED_TABLE_OP_PATTERN.finditer(sql):
        op, target_schema, target_table = op_match.group(1), op_match.group(2), op_match.group(3)
        if target_schema is None or target_schema.lower() != allowed_schema.lower():
            target = f"{target_schema}.{target_table}" if target_schema else target_table
            raise GuardrailViolation(
                f"candidate SQL runs '{' '.join(op.split()).upper()}' against '{target}', "
                f"not confirmed to be inside the allowed schema '{allowed_schema}' "
                "(schema-qualify the target to allow it)"
            )

    match = PROCEDURE_NAME_PATTERN.search(sql)
    if not match:
        raise GuardrailViolation("could not determine the procedure's schema from the CREATE statement")

    schema_name = match.group(1)
    if schema_name.lower() != allowed_schema.lower():
        raise GuardrailViolation(
            f"candidate procedure must live in schema '{allowed_schema}', got '{schema_name}' "
            "(the evolve loop only ever deploys into the sandbox schema, never dbo/uat/prd directly)"
        )
