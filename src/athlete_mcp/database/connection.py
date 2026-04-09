"""Database connection layer.

Wraps libsql_client to expose the same API surface that the routers were
written against (aiosqlite-style: db.execute() → cursor with fetchone/fetchall,
db.commit(), db.executemany()). This lets us swap drivers without touching
any router code.

Supports two backends:
- Local file SQLite (via libsql_client local mode)
- Remote Turso database (via libsql_client over HTTPS)

The choice is driven by config.settings.using_turso.
"""

import logging
import os
from collections.abc import AsyncGenerator
from typing import Any, Sequence

import certifi
import libsql_client

from athlete_mcp.config import settings

logger = logging.getLogger(__name__)

# Ensure aiohttp / libsql_client uses certifi's CA bundle on macOS
# (system Python.framework installs ship without one).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

_db: "Database | None" = None


class _Cursor:
    """aiosqlite-style cursor wrapping a libsql ResultSet."""

    __slots__ = ("_result", "_index")

    def __init__(self, result: libsql_client.ResultSet):
        self._result = result
        self._index = 0

    @property
    def lastrowid(self) -> int | None:
        return self._result.last_insert_rowid

    @property
    def rowcount(self) -> int:
        return self._result.rows_affected or 0

    async def fetchone(self) -> libsql_client.Row | None:
        rows = self._result.rows
        if self._index >= len(rows):
            return None
        row = rows[self._index]
        self._index += 1
        return row

    async def fetchall(self) -> list[libsql_client.Row]:
        rows = list(self._result.rows[self._index:])
        self._index = len(self._result.rows)
        return rows


class Database:
    """Thin async wrapper exposing aiosqlite-like methods on top of libsql_client."""

    def __init__(self, client: libsql_client.Client):
        self._client = client

    async def execute(
        self, sql: str, parameters: Sequence[Any] | None = None
    ) -> _Cursor:
        # libsql_client expects a list (not tuple) for positional params, and
        # raises if you pass an empty sequence — pass None in that case.
        params: list[Any] | None
        if parameters is None or len(parameters) == 0:
            params = None
        else:
            params = list(parameters)

        if params is None:
            result = await self._client.execute(sql)
        else:
            result = await self._client.execute(sql, params)
        return _Cursor(result)

    async def executemany(
        self, sql: str, seq_of_parameters: Sequence[Sequence[Any]]
    ) -> None:
        # libsql_client supports batched statements via batch()
        statements = [
            libsql_client.Statement(sql, list(p)) for p in seq_of_parameters
        ]
        if statements:
            await self._client.batch(statements)

    async def executescript(self, script: str) -> None:
        """Execute multiple SQL statements separated by ';'.

        libsql_client doesn't have executescript() — we split and run each.
        Comments and empty statements are skipped.
        """
        statements = []
        for stmt in script.split(";"):
            cleaned = stmt.strip()
            if not cleaned:
                continue
            # strip line comments
            lines = [
                line for line in cleaned.split("\n") if not line.strip().startswith("--")
            ]
            cleaned = "\n".join(lines).strip()
            if cleaned:
                statements.append(cleaned)

        for stmt in statements:
            await self._client.execute(stmt)

    async def commit(self) -> None:
        # libsql_client auto-commits each execute() — this is a no-op kept for
        # API compatibility with aiosqlite-based router code.
        return None

    async def close(self) -> None:
        await self._client.close()


def _normalize_turso_url(url: str) -> str:
    """libsql_client v0.3 uses websocket transport for libsql:// URLs which
    modern Turso endpoints reject (HTTP 505). Force HTTPS instead.
    """
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://") :]
    if url.startswith("wss://"):
        return "https://" + url[len("wss://") :]
    return url


def _create_client() -> libsql_client.Client:
    if settings.using_turso:
        url = _normalize_turso_url(settings.TURSO_DATABASE_URL)
        token = settings.TURSO_AUTH_TOKEN
        logger.info("Connecting to Turso at %s", url)
        return libsql_client.create_client(url=url, auth_token=token)

    # Local file mode
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_url = f"file:{settings.DB_PATH}"
    logger.info("Connecting to local SQLite at %s", settings.DB_PATH)
    return libsql_client.create_client(url=file_url)


async def init_db() -> None:
    global _db
    # Import here to avoid circular import (migrations imports nothing from us
    # at module level, but the runtime call needs Database).
    from athlete_mcp.database.migrations import run_migrations

    client = _create_client()
    _db = Database(client)

    # Foreign keys: only meaningful on local SQLite. Turso enforces them
    # at the storage layer regardless. Wrap in try/except for safety.
    if not settings.using_turso:
        try:
            await _db.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass

    await run_migrations(_db)
    logger.info("Database initialized")


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")


async def get_db() -> AsyncGenerator[Database, None]:
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    yield _db
