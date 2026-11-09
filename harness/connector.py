"""Connections to Azure Synapse SQL, for executing test queries and -- for the
evolve loop -- deploying/running a candidate stored procedure."""
import os

TRANSIENT_SQLSTATES = {"08S01", "HYT00", "40001", "40613"}


class TransientError(Exception):
    """A connection/query error worth retrying (deadlock, timeout, throttling)."""


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
                if cursor.description is None:
                    return []
                columns = [c[0] for c in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as exc:
            sqlstate = exc.args[0] if exc.args else ""
            if sqlstate in TRANSIENT_SQLSTATES:
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
            sqlstate = exc.args[0] if exc.args else ""
            if sqlstate in TRANSIENT_SQLSTATES:
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
            sqlstate = exc.args[0] if exc.args else ""
            if sqlstate in TRANSIENT_SQLSTATES:
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
            sqlstate = exc.args[0] if exc.args else ""
            if sqlstate in TRANSIENT_SQLSTATES:
                raise TransientError(str(exc)) from exc
            raise

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        import pyodbc

        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params or [])
            if cursor.description is None:
                return []
            columns = [c[0] for c in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as exc:
            sqlstate = exc.args[0] if exc.args else ""
            if sqlstate in TRANSIENT_SQLSTATES:
                raise TransientError(str(exc)) from exc
            raise

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
