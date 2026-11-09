"""A fixed-answer connector for testing check logic without a real Synapse connection.

A fixture value can be a static list of rows, or a callable ``(connector) -> list[dict]``
that inspects ``connector.executed`` -- the DDL/EXEC statements run so far -- so a test
can simulate a deployed candidate changing what a later query returns (needed to test
the evolve loop across iterations without a real database).
"""


class MockConnector:
    def __init__(
        self,
        fixtures: dict[str, list[dict]] | None = None,
        execute_errors: dict[str, Exception] | None = None,
    ):
        self.fixtures = fixtures or {}
        self.execute_errors = execute_errors or {}  # normalized sql -> exception to raise, for testing deploy/exec failures
        self.executed: list[str] = []
        self.committed = 0
        self.rolled_back = 0

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        key = " ".join(sql.split())
        if key not in self.fixtures:
            raise KeyError(f"MockConnector has no fixture for query: {key!r}")
        value = self.fixtures[key]
        return value(self) if callable(value) else value

    def execute(self, sql: str, params: list | None = None) -> None:
        key = " ".join(sql.split())
        if key in self.execute_errors:
            raise self.execute_errors[key]
        self.executed.append(sql)

    def transaction(self) -> "MockTransaction":
        return MockTransaction(self)


class MockTransaction:
    """Mirrors SynapseTransaction's interface, delegating query()/execute() to the
    same MockConnector so fixtures keep working, while commit()/rollback() just
    tally on the parent for tests to assert against."""

    def __init__(self, parent: MockConnector):
        self._parent = parent

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        return self._parent.query(sql, params)

    def execute(self, sql: str, params: list | None = None) -> None:
        self._parent.execute(sql, params)

    def commit(self) -> None:
        self._parent.committed += 1

    def rollback(self) -> None:
        self._parent.rolled_back += 1

    def close(self) -> None:
        pass
