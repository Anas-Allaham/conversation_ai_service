from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base


def normalize_database_url(url: str) -> str:
    value = url.strip()
    if value.startswith("postgres://"):
        value = "postgresql+asyncpg://" + value.removeprefix("postgres://")
    elif value.startswith("postgresql://"):
        value = "postgresql+asyncpg://" + value.removeprefix("postgresql://")

    if value.startswith("postgresql+asyncpg://"):
        parsed = make_url(value)
        query = dict(parsed.query)
        # Managed providers commonly emit libpq's `sslmode` and
        # `channel_binding`; asyncpg accepts `ssl` and has no channel-binding
        # keyword. Preserve the intended TLS requirement without passing
        # unsupported connection arguments.
        ssl_mode = query.pop("sslmode", None)
        if ssl_mode and "ssl" not in query:
            query["ssl"] = ssl_mode
        query.pop("channel_binding", None)
        value = parsed.set(query=query).render_as_string(hide_password=False)

    return value


class Database:
    def __init__(self, url: str) -> None:
        normalized = normalize_database_url(url)
        if not normalized:
            raise ValueError("DATABASE_URL is required")

        kwargs: dict[str, object] = {"pool_pre_ping": True}
        if normalized.startswith("postgresql+asyncpg://"):
            kwargs.update(pool_size=2, max_overflow=2, pool_recycle=300)

        self.url = normalized
        self.engine: AsyncEngine = create_async_engine(normalized, **kwargs)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        if normalized.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", self._enable_sqlite_foreign_keys)

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def ping(self) -> None:
        async with self.session() as session:
            await session.execute(text("SELECT 1"))

    async def create_schema_for_tests(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
