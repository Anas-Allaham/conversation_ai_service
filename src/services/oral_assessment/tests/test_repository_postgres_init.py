from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

from services.oral_assessment.repository import SQLRepository


class ClosingConnection:
    """Model psycopg's connection context, which closes on context exit."""

    def __init__(self) -> None:
        self.closed = False
        self.context_entries = 0
        self.statements: list[str] = []

    def __enter__(self):
        self.context_entries += 1
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.closed = True

    def execute(self, statement: str) -> None:
        if self.closed:
            raise RuntimeError("the connection is closed")
        self.statements.append(statement)


def test_postgres_initialization_uses_one_connection_context() -> None:
    repository = SQLRepository("postgresql://database.example/conversation_ai")
    connection = ClosingConnection()

    with patch.object(repository, "_connection", return_value=nullcontext(connection)):
        repository.initialize()

    assert connection.context_entries == 1
    assert connection.closed
    assert len(connection.statements) > 1
