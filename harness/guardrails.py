"""Safety checks on a candidate stored procedure before it is ever deployed,
plus a check on what an LLM says about it before that's ever written down.

This is a text-level allow-list, not a security boundary on its own — the
connection used to run the evolve loop should also hold least-privilege
credentials scoped to the sandbox schema (document that as an infra control;
don't rely on this regex alone in production).
"""
import re
from pathlib import Path

import yaml

ALLOWED_DDL_PATTERN = re.compile(r"^\s*CREATE\s+OR\s+ALTER\s+PROCEDURE\b", re.IGNORECASE)
LEADING_COMMENT_PATTERN = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/)\s*", re.DOTALL)
PROCEDURE_NAME_PATTERN = re.compile(r"PROCEDURE\s+\[?(\w+)\]?\.\[?(\w+)\]?", re.IGNORECASE)
LINE_COMMENT_PATTERN = re.compile(r"--[^\n]*")
BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
STRING_LITERAL_PATTERN = re.compile(r"'(?:[^']|'')*'")
BEGIN_END_TOKEN_PATTERN = re.compile(r"\b(BEGIN|END)\b", re.IGNORECASE)

# A small, deliberately conservative set of shapes worth catching in LLM
# free text (a fix's rationale, which gets written verbatim into a public git
# commit message and PR comment) before it becomes permanently public. Not a
# general PII detector -- just the common, careless shapes an LLM might echo
# back from something it saw in a failing check's details.
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_PATTERN = re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
LEAK_PATTERNS = [EMAIL_PATTERN, SSN_PATTERN, PHONE_PATTERN]

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


def _scannable(sql: str) -> str:
    """Comments and string literals blanked out (same length-preserving trick
    as a leading-comment strip, just everywhere) so a keyword, semicolon, or
    BEGIN/END token *inside* a comment or a quoted value -- a legitimate
    product-name filter containing the word "END", say -- is never mistaken
    for real SQL structure."""
    sql = LINE_COMMENT_PATTERN.sub(" ", sql)
    sql = BLOCK_COMMENT_PATTERN.sub(" ", sql)
    return STRING_LITERAL_PATTERN.sub("''", sql)


def _end_of_outer_block(scannable: str) -> int | None:
    """Index just after the END that closes the procedure body's outer
    BEGIN...END, tracking nested BEGIN/END (IF blocks, TRY/CATCH, etc.) by
    depth. None if no balanced BEGIN...END is found at all."""
    depth = 0
    seen_begin = False
    for m in BEGIN_END_TOKEN_PATTERN.finditer(scannable):
        if m.group(1).upper() == "BEGIN":
            depth += 1
            seen_begin = True
        else:
            depth -= 1
            if depth < 0:
                return None
            if seen_begin and depth == 0:
                return m.end()
    return None


def _trailing_statement_after_body(sql: str) -> str | None:
    """A second statement smuggled in after the procedure's own closing END --
    e.g. "CREATE OR ALTER PROCEDURE ... END; DROP TABLE dbo.something;" -- is
    syntactically a single batch an LLM could generate and the "must start
    with CREATE OR ALTER PROCEDURE" check alone would never catch, since it
    only looks at the *start* of the text. Requires a balanced BEGIN...END to
    even attempt this check (every procedure in this repo has one); fails
    safe -- treated as a violation -- when the structure can't be confirmed,
    same policy as an unqualified TRUNCATE/DROP target below."""
    scannable = _scannable(sql)
    end_idx = _end_of_outer_block(scannable)
    if end_idx is None:
        return "candidate SQL has no balanced BEGIN...END block to confirm where the procedure body ends"
    remainder = scannable[end_idx:].strip().strip(";").strip()
    if remainder:
        return "candidate SQL has content after the procedure's closing END -- only the single CREATE OR ALTER PROCEDURE statement is allowed, nothing appended after it"
    return None


def load_blocked_tables(path: str = "infra/blocked_tables.yaml") -> set[str]:
    """Tables a candidate must never reference at all -- not just as a
    destructive-operation target (SCOPED_TABLE_OP_PATTERN below already
    covers that), but in any form: SELECT, JOIN, INSERT target, anything.
    Missing file -> empty set, same fail-open-on-absence convention as
    governance_check.py uses for a missing approval file (there the absence
    itself is the failure signal; here an empty list is the correct default
    for a repo with no PII-bearing tables yet)."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return set()
    return {str(t).lower() for t in (data.get("tables") or [])}


def _references_blocked_table(sql: str, blocked_tables: set[str]) -> str | None:
    if not blocked_tables:
        return None
    scannable = _scannable(sql)
    for table in blocked_tables:
        if re.search(rf"\b{re.escape(table)}\b", scannable, re.IGNORECASE):
            return table
    return None


def contains_likely_leak(text: str) -> str | None:
    """The matched substring if `text` looks like it contains an email, SSN,
    or phone number -- for scanning an LLM's free-text rationale before it's
    written into a commit message or PR comment. Same defense-in-depth idea
    as a chat agent's output PII scan, applied to a fix's explanation instead
    of a chat answer."""
    for pattern in LEAK_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return None


def check_candidate_sql(sql: str, allowed_schema: str, blocked_tables_path: str = "infra/blocked_tables.yaml") -> None:
    if not ALLOWED_DDL_PATTERN.match(_strip_leading_comments(sql)):
        raise GuardrailViolation(
            "candidate SQL must be a single CREATE OR ALTER PROCEDURE statement"
        )

    trailing_violation = _trailing_statement_after_body(sql)
    if trailing_violation:
        raise GuardrailViolation(trailing_violation)

    blocked_tables = load_blocked_tables(blocked_tables_path)
    blocked = _references_blocked_table(sql, blocked_tables)
    if blocked:
        raise GuardrailViolation(
            f"candidate SQL references '{blocked}', which is on the blocked-tables list "
            f"({blocked_tables_path}) and must never be touched by generated SQL"
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
