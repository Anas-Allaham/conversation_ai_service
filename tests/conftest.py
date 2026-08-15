from __future__ import annotations

import pytest_asyncio

from conversation_ai.persistence import Database


@pytest_asyncio.fixture
async def database(tmp_path):
    path = (tmp_path / "sessions.db").as_posix()
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()

