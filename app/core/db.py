from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import asyncpg

logger = logging.getLogger(__name__)

DB_SCHEMA: Final[str] = "bot_core"
MIGRATIONS_TABLE: Final[str] = f"{DB_SCHEMA}.schema_migrations"


class Database:
    """Small explicit asyncpg wrapper.

    Business repositories receive this object and acquire their own connection.
    Future financial services must own transaction boundaries explicitly rather
    than hiding them in handlers.
    """

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 2,
        max_size: int = 20,
        command_timeout: float = 15.0,
    ) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._command_timeout = command_timeout
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pool is not None:
            return
        self.pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=self._command_timeout,
            max_inactive_connection_lifetime=300.0,
        )
        logger.info("PostgreSQL pool ready: min=%s max=%s", self._min_size, self._max_size)

    async def close(self) -> None:
        if self.pool is None:
            return
        await self.pool.close()
        self.pool = None
        logger.info("PostgreSQL pool closed")

    def require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("Database pool is not connected")
        return self.pool

    async def ping(self) -> bool:
        pool = self.require_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1

    async def apply_migrations(self, migrations_dir: Path) -> None:
        pool = self.require_pool()
        files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())

        async with pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}")
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            applied = {
                row["version"]
                for row in await conn.fetch(f"SELECT version FROM {MIGRATIONS_TABLE}")
            }

            for path in files:
                version = path.name
                if version in applied:
                    continue
                sql = path.read_text(encoding="utf-8")
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        f"INSERT INTO {MIGRATIONS_TABLE}(version) VALUES($1)",
                        version,
                    )
                logger.info("Applied database migration: %s", version)
