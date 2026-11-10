"""Connections to Azure Synapse SQL, for executing test queries and -- for the
evolve loop -- deploying/running a candidate stored procedure."""
import os
import re
import time

# Resource-exhaustion guard: a validation query is checking an aggregated
# business figure, never pulling a whole fact table into memory -- one that
# returns more than this many rows is almost certainly a bad check.sql
# (missing a GROUP BY) rather than a real need for more rows, so this fails
# loud instead of silently truncating a result set a check then compares
# against gold values as if it were complete.
MAX_QUERY_ROWS = 10_000

# ODBC-level SQLSTATEs worth retrying (deadlock, login timeout, network blip).
# pyodbc.Error's first arg is this generic ODBC state, e.g. '08S01' -- it is
# NOT where Azure SQL's own error numbers show up (see below).
TRANSIENT_SQLSTATES = {"08S01", "HYT00", "40001"}

# Azure SQL Database's own transient error numbers (not ODBC SQLSTATEs): a
# resuming serverless database, throttling, failover, resource-governor
# limits. pyodbc surfaces these only inside the message text, generically
# tagged SQLSTATE 'HY000' -- e.g. "...is not currently available... (40613)
# (SQLDriverConnect)" -- so args[0] alone (the old check) never catches this
# class of error; a real serverless-tier "database is paused" response hits
# exactly this path and was never actually retried before this fix.
TRANSIENT_AZURE_ERROR_NUMBERS = {
    "4060", "40197", "40501", "40613", "49918", "49919", "49920", "4221", "40143",
}
_AZURE_ERROR_NUMBER_RE = re.compile(r"\((\d+)\)")


def redact_secret(text: str, conn_str: str | None) -> str:
    """Strip a known connection string (and its PWD=/password= component) out
    of error text before it's ever printed or logged. CLI error handlers print
    exception text to stderr, which a public-repo CI run puts in a world-
    readable Actions log -- this exists because that print was previously
    trusting the ODBC driver to never echo the connection string (and
    therefore the password) back in an error message, which isn't guaranteed.
    """
    if not text or not conn_str:
        return text
    redacted = text.replace(conn_str, "***REDACTED-CONN-STR***")
    for part in conn_str.split(";"):
        key, sep, value = part.partition("=")
        if sep and value and key.strip().lower() in ("pwd", "password"):
            redacted = redacted.replace(value, "***REDACTED-PWD***")
    return redacted


class TransientError(Exception):
    """A connection/query error worth retrying (deadlock, timeout, throttling,
    a serverless database resuming from auto-pause)."""


class QueryTooLarge(Exception):
    """A query returned more than MAX_QUERY_ROWS rows."""


def _fetch_capped(cursor) -> list[dict]:
    if cursor.description is None:
        return []
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchmany(MAX_QUERY_ROWS)
    if cursor.fetchone() is not None:
        raise QueryTooLarge(
            f"query returned more than {MAX_QUERY_ROWS} rows -- aggregate in SQL "
            "(a GROUP BY, a SUM/COUNT) instead of comparing raw rows, or reconsider "
            "MAX_QUERY_ROWS in harness/connector.py if this check genuinely needs more"
        )
    return [dict(zip(columns, row)) for row in rows]


def _is_transient(exc: Exception) -> bool:
    sqlstate = exc.args[0] if exc.args else ""
    if sqlstate in TRANSIENT_SQLSTATES:
        return True
    return bool(_AZURE_ERROR_NUMBER_RE.search(str(exc)) and any(
        num in TRANSIENT_AZURE_ERROR_NUMBERS for num in _AZURE_ERROR_NUMBER_RE.findall(str(exc))
    ))


def open_transaction_with_retries(connector, retries: int = 6, max_backoff: int = 20) -> "SynapseTransaction":
    """Opens a transaction, retrying on TransientError (login timeout, deadlock,
    throttling, a serverless database waking up from auto-pause) with capped
    exponential backoff -- so a connection blip doesn't crash the caller with
    an unhandled exception the way a bare connector.transaction() call would.
    6 retries capped at 20s each (2+4+8+16+20+20 = 70s total) comfortably
    covers a cold serverless resume, which Azure documents as usually under
    30s but occasionally longer. Callers in promote.py/evolve.py use this
    instead of calling transaction() directly; a persistent failure still
    raises after retries are exhausted."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return connector.transaction()
        except TransientError as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt + 1), max_backoff))
    raise last_exc


class SynapseConnector:
    """Runs read-only queries against a Synapse SQL pool / serverless endpoint.

    Connection string comes from an environment variable (never hardcode
    credentials in a suite file). Point ``env_var`` at a per-environment
    variable, e.g. SYNAPSE_UAT_CONN_STR, SYNAPSE_PRD_CONN_STR.
    """

    def __init__(self, env_var: str = "SYNAPSE_CONN_STR", conn_str: str | None = None, query_timeout: int = 60):
        self.conn_str = conn_str or os.environ.get(env_var)
        if not self.conn_str:
            raise RuntimeError(f"connection string not found: set ${env_var}")
        self.query_timeout = query_timeout

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        # imported lazily so the harness (and its unit tests) don't need the
        # unixODBC runtime / driver installed unless a real query actually runs
        import pyodbc

        try:
            with pyodbc.connect(self.conn_str, timeout=self.query_timeout) as conn:
                conn.timeout = self.query_timeout
                cursor = conn.cursor()
                cursor.execute(sql, params or [])
                return _fetch_capped(cursor)
        except pyodbc.Error as exc:
            if _is_transient(exc):
                raise TransientError(str(exc)) from exc
            raise

    def execute(self, sql: str, params: list | None = None) -> None:
        """Runs a non-query statement (DDL like CREATE OR ALTER PROCEDURE, or EXEC).

        Callers (notably harness/evolve.py) are responsible for guardrail-checking
        the SQL before it reaches here -- this method does not re-validate it.
        """
        import pyodbc

        try:
            with pyodbc.connect(self.conn_str, timeout=self.query_timeout, autocommit=True) as conn:
                conn.timeout = self.query_timeout
                cursor = conn.cursor()
                cursor.execute(sql, params or [])
        except pyodbc.Error as exc:
            if _is_transient(exc):
                raise TransientError(str(exc)) from exc
            raise

    def transaction(self) -> "SynapseTransaction":
        """Opens one connection, held across deploy -> exec -> validate, so validation
        queries see the uncommitted changes and the whole attempt can be rolled back
        as a unit. SQL Server/Synapse DDL (CREATE OR ALTER PROCEDURE included) is
        transactional, so this also undoes a candidate's procedure definition, not
        just its data changes, when the caller rolls back."""
        import pyodbc

        try:
            conn = pyodbc.connect(self.conn_str, timeout=self.query_timeout, autocommit=False)
            conn.timeout = self.query_timeout
        except pyodbc.Error as exc:
            if _is_transient(exc):
                raise TransientError(str(exc)) from exc
            raise
        return SynapseTransaction(conn)


class SynapseTransaction:
    """A single open connection/transaction. execute()/query() behave like the ones on
    SynapseConnector but run on this one connection, so they see each other's
    uncommitted writes. Caller decides commit() vs rollback(); close() always runs."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: list | None = None) -> None:
        import pyodbc

        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params or [])
        except pyodbc.Error as exc:
            if _is_transient(exc):
                raise TransientError(str(exc)) from exc
            raise

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        import pyodbc

        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params or [])
            return _fetch_capped(cursor)
        except pyodbc.Error as exc:
            if _is_transient(exc):
                raise TransientError(str(exc)) from exc
            raise

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
